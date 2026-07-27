"""Link migrated legacy stock to exact existing PLM model variants.

Dry-run is the default. The mapping contains only exact normalized
model-number + variant matches. It also reverses the earlier non-canonical
547-row reconciliation so those rows return to their original internal legacy
identities instead of appearing as PLM duplicates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models import (
    FinishedGoodsStock,
    LegacyStockReceipt,
    Model,
    Package,
    PackageItem,
    ShipmentPackage,
    StockReservation,
)
from app.services.audit import log_action


EXPECTED_MAPPING_SHA256 = "b03d7b4263a0db142d67f23438fcf39a71b159377647a5a876faaa6b0d1e43dc"
EXPECTED_CANONICAL_ROWS = 8009
EXPECTED_CANONICAL_QTY = 100074
EXPECTED_RESTORE_ROWS = 547


def clean(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def is_import_created(model: Model) -> bool:
    details = model.details_json if isinstance(model.details_json, dict) else {}
    return details.get("legacy_import") is True


def load_mapping(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    sha256 = hashlib.sha256(raw).hexdigest()
    if sha256 != EXPECTED_MAPPING_SHA256:
        raise ValueError("mapping checksum does not match the reviewed canonical mapping")
    payload = json.loads(raw.decode("utf-8"))
    summary = payload.get("summary") or {}
    canonical_rows = payload.get("canonical_rows")
    restore_rows = payload.get("restore_rows")
    if not isinstance(canonical_rows, list) or not isinstance(restore_rows, list):
        raise ValueError("mapping row lists are missing")
    if len(canonical_rows) != EXPECTED_CANONICAL_ROWS:
        raise ValueError("canonical row count does not match reviewed mapping")
    if len(restore_rows) != EXPECTED_RESTORE_ROWS:
        raise ValueError("restore row count does not match reviewed mapping")
    if int(summary.get("canonical_available_quantity") or 0) != EXPECTED_CANONICAL_QTY:
        raise ValueError("canonical quantity does not match reviewed mapping")
    all_rows = canonical_rows + restore_rows
    source_ids = [clean(row.get("source_record_id")) for row in all_rows]
    if not all(source_ids) or len(source_ids) != len(set(source_ids)):
        raise ValueError("mapping source record ids must be unique")
    return payload, sha256


def reconcile(
    db: Session,
    payload: dict[str, Any],
    *,
    mapping_sha256: str,
    apply: bool,
    mapping_reference: str,
) -> dict[str, Any]:
    canonical_rows = payload["canonical_rows"]
    restore_rows = payload["restore_rows"]
    all_rows = canonical_rows + restore_rows
    mapping_by_source = {
        clean(row["source_record_id"]): row for row in all_rows
    }
    source_ids = list(mapping_by_source)

    receipts = (
        db.query(LegacyStockReceipt)
        .filter(
            LegacyStockReceipt.source_system == "UZERP",
            LegacyStockReceipt.source_warehouse_id == "18",
            LegacyStockReceipt.source_record_id.in_(source_ids),
        )
        .all()
    )
    receipts_by_source = {row.source_record_id: row for row in receipts}
    if set(receipts_by_source) != set(source_ids):
        missing = sorted(set(source_ids) - set(receipts_by_source))
        raise ValueError(f"mapped legacy receipts are missing: {missing[:20]}")

    packages = (
        db.query(Package)
        .filter(Package.legacy_receipt_id.in_([row.id for row in receipts]))
        .all()
    )
    packages_by_receipt = {row.legacy_receipt_id: row for row in packages}
    if len(packages_by_receipt) != len(receipts):
        raise ValueError("expected exactly one package for each mapped receipt")

    package_ids = [row.id for row in packages]
    items = db.query(PackageItem).filter(PackageItem.package_id.in_(package_ids)).all()
    stocks = (
        db.query(FinishedGoodsStock)
        .filter(FinishedGoodsStock.package_id.in_(package_ids))
        .all()
    )
    items_by_package: dict[int, list[PackageItem]] = {}
    stocks_by_package: dict[int, list[FinishedGoodsStock]] = {}
    for row in items:
        items_by_package.setdefault(row.package_id, []).append(row)
    for row in stocks:
        stocks_by_package.setdefault(row.package_id, []).append(row)
    invalid_cardinality = [
        package_id
        for package_id in package_ids
        if len(items_by_package.get(package_id, [])) != 1
        or len(stocks_by_package.get(package_id, [])) != 1
    ]
    if invalid_cardinality:
        raise ValueError(f"package/item/stock cardinality mismatch: {invalid_cardinality[:20]}")

    if db.query(ShipmentPackage.id).filter(ShipmentPackage.package_id.in_(package_ids)).first():
        raise ValueError("a mapped package is linked to a shipment")
    stock_ids = [row.id for row in stocks]
    if (
        db.query(StockReservation.id)
        .filter(StockReservation.finished_goods_stock_id.in_(stock_ids))
        .first()
    ):
        raise ValueError("mapped finished-goods stock is reserved")

    target_ids = {int(row["target_model_id"]) for row in all_rows}
    target_models = {
        row.id: row for row in db.query(Model).filter(Model.id.in_(target_ids)).all()
    }
    if set(target_models) != target_ids:
        raise ValueError("one or more target models are missing")

    canonical_sources = {clean(row["source_record_id"]) for row in canonical_rows}
    for row in canonical_rows:
        target = target_models[int(row["target_model_id"])]
        if is_import_created(target):
            raise ValueError(f"canonical target is import-created: {target.code}")
        if clean(target.code) != clean(row["target_model_code"]):
            raise ValueError(f"canonical target code changed for model {target.id}")
    for row in restore_rows:
        target = target_models[int(row["target_model_id"])]
        if not is_import_created(target) or not target.code.startswith("LEGACY-"):
            raise ValueError(f"restore target is not the original internal legacy model: {target.code}")

    before_totals = {
        "package_quantity": sum(int(row.total_quantity or 0) for row in packages),
        "stock_quantity": sum(int(row.quantity or 0) for row in stocks),
        "available_quantity": sum(int(row.available_qty or 0) for row in stocks),
        "reserved_quantity": sum(int(row.reserved_qty or 0) for row in stocks),
        "sold_quantity": sum(int(row.sold_qty or 0) for row in stocks),
    }
    changed: list[dict[str, Any]] = []
    skipped_existing = 0

    for source_id in source_ids:
        mapping = mapping_by_source[source_id]
        receipt = receipts_by_source[source_id]
        package = packages_by_receipt[receipt.id]
        item = items_by_package[package.id][0]
        stock = stocks_by_package[package.id][0]
        target = target_models[int(mapping["target_model_id"])]

        if package.id != int(mapping["package_id"]):
            raise ValueError(f"package id changed for source {source_id}")
        if package.status != "received_in_storage" or package.sales_order_id is not None:
            raise ValueError(f"package {package.id} is no longer untouched storage stock")
        if int(stock.reserved_qty or 0) or int(stock.sold_qty or 0):
            raise ValueError(f"stock {stock.id} has reserved or sold quantity")
        if item.model_id != package.model_id or stock.model_id != package.model_id:
            raise ValueError(f"model identity mismatch inside package {package.id}")
        expected_current_id = int(mapping["expected_current_model_id"])
        if package.model_id not in {expected_current_id, target.id}:
            raise ValueError(
                f"package {package.id} model changed after review: "
                f"{package.model_id} not in {{{expected_current_id}, {target.id}}}"
            )
        expected_qty = mapping.get("available_quantity")
        if expected_qty is not None and int(stock.available_qty or 0) != int(expected_qty):
            raise ValueError(f"available quantity changed for package {package.id}")

        already_target = (
            package.model_id == target.id
            and item.model_id == target.id
            and stock.model_id == target.id
            and package.brand_id == target.brand_id
            and package.collection_id == target.collection_id
            and stock.brand_id == target.brand_id
            and stock.collection_id == target.collection_id
        )
        if already_target:
            skipped_existing += 1
            continue

        current = db.get(Model, package.model_id)
        old = {
            "model_id": current.id,
            "model_code": current.code,
            "brand_id": package.brand_id,
            "collection_id": package.collection_id,
        }
        package.model_id = target.id
        package.brand_id = target.brand_id
        package.collection_id = target.collection_id
        item.model_id = target.id
        stock.model_id = target.id
        stock.brand_id = target.brand_id
        stock.collection_id = target.collection_id
        changed.append(
            {
                "source_record_id": source_id,
                "package_id": package.id,
                "stock_id": stock.id,
                "action": "canonical_link" if source_id in canonical_sources else "restore_internal_legacy",
                "old": old,
                "new": {
                    "model_id": target.id,
                    "model_code": target.code,
                    "brand_id": target.brand_id,
                    "collection_id": target.collection_id,
                },
            }
        )

    db.flush()
    after_totals = {
        "package_quantity": sum(int(row.total_quantity or 0) for row in packages),
        "stock_quantity": sum(int(row.quantity or 0) for row in stocks),
        "available_quantity": sum(int(row.available_qty or 0) for row in stocks),
        "reserved_quantity": sum(int(row.reserved_qty or 0) for row in stocks),
        "sold_quantity": sum(int(row.sold_qty or 0) for row in stocks),
    }
    if before_totals != after_totals:
        raise AssertionError("canonical linking changed finished-goods quantities")
    if len(changed) + skipped_existing != len(all_rows):
        raise AssertionError("mapping rows did not reconcile")

    result = {
        "mode": "apply" if apply else "dry_run",
        "mapping_sha256": mapping_sha256,
        "mapping_reference": mapping_reference,
        "expected_rows": len(all_rows),
        "canonical_rows": len(canonical_rows),
        "restore_rows": len(restore_rows),
        "changed_rows": len(changed),
        "skipped_existing": skipped_existing,
        "before_totals": before_totals,
        "after_totals": after_totals,
        "changed": changed,
    }
    if apply:
        log_action(
            db,
            None,
            "legacy_stock_canonical_model_link",
            "LegacyStockCanonicalization",
            old_value={
                "reviewed_rows": len(all_rows),
                **before_totals,
            },
            new_value={
                "canonical_rows": len(canonical_rows),
                "restored_noncanonical_rows": len(restore_rows),
                "changed_rows": len(changed),
                "skipped_existing": skipped_existing,
                "mapping_sha256": mapping_sha256,
                **after_totals,
            },
        )
        db.commit()
    else:
        db.rollback()
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--audit-output", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    payload, mapping_sha256 = load_mapping(args.mapping)
    with SessionLocal() as db:
        result = reconcile(
            db,
            payload,
            mapping_sha256=mapping_sha256,
            apply=args.apply,
            mapping_reference=str(args.mapping),
        )
    args.audit_output.parent.mkdir(parents=True, exist_ok=True)
    args.audit_output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {key: value for key, value in result.items() if key != "changed"},
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )


if __name__ == "__main__":
    main()
