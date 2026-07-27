"""Reassign high-confidence legacy finished-goods stock to known model identities.

The immutable ``LegacyStockReceipt.source_payload`` remains untouched. The
mapping file is generated from the frozen UZERP inventory snapshot and must
carry the validated source digest. Dry-run is the default; pass ``--apply``
only after a production backup and review of the audit output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from sqlalchemy import func
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
from scripts.import_legacy_ready_stock import display_color


EXPECTED_SOURCE_DIGEST = "7cd78fc79226079fa018cd1a3066ff174d8a6ea6b47e06a696c41c4fce3bb525"
EXPECTED_IMPORT_SHA256 = "8f1182fec7b849fcbf71acab3e103f29f45997f6f82c9be0d6b1eb67d2cded0a"


def clean(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def load_mapping(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    summary = payload.get("summary") or {}
    rows = payload.get("auto_matches")
    if not isinstance(rows, list) or not rows:
        raise ValueError("mapping must contain a non-empty auto_matches list")
    if summary.get("source_digest_sha256") != EXPECTED_SOURCE_DIGEST:
        raise ValueError("mapping source digest does not match the frozen UZERP snapshot")
    if summary.get("import_file_sha256") != EXPECTED_IMPORT_SHA256:
        raise ValueError("mapping import-file checksum does not match the validated import")
    if int(summary.get("automatic_high_confidence_rows") or 0) != len(rows):
        raise ValueError("mapping summary row count does not match auto_matches")

    source_ids = [clean(row.get("source_record_id")) for row in rows]
    if not all(source_ids) or len(set(source_ids)) != len(source_ids):
        raise ValueError("mapping source_record_id values must be non-empty and unique")
    for row in rows:
        if not clean(row.get("target_model_code")) or not clean(row.get("target_variant")):
            raise ValueError(f"incomplete target identity for {row.get('source_record_id')}")
        if not row.get("evidence_methods"):
            raise ValueError(f"missing evidence methods for {row.get('source_record_id')}")
        if clean(row.get("confidence")) != "High":
            raise ValueError(f"non-high-confidence row in automatic mapping: {row.get('source_record_id')}")
    return payload, hashlib.sha256(raw).hexdigest()


def _model_map(db: Session, codes: set[str]) -> dict[str, Model]:
    rows = db.query(Model).filter(func.lower(Model.code).in_({code.casefold() for code in codes})).all()
    result = {row.code.casefold(): row for row in rows}
    missing = sorted(code for code in codes if code.casefold() not in result)
    if missing:
        raise ValueError(f"target models missing from ERP: {missing}")
    return result


def reconcile(
    db: Session,
    payload: dict[str, Any],
    *,
    mapping_sha256: str,
    apply: bool,
    mapping_reference: str,
) -> dict[str, Any]:
    rows = payload["auto_matches"]
    source_ids = [clean(row["source_record_id"]) for row in rows]
    mapping_by_source = {clean(row["source_record_id"]): row for row in rows}
    target_models = _model_map(db, {clean(row["target_model_code"]) for row in rows})

    receipts = (
        db.query(LegacyStockReceipt)
        .filter(
            LegacyStockReceipt.source_system == "UZERP",
            LegacyStockReceipt.source_warehouse_id == "18",
            LegacyStockReceipt.source_record_id.in_(source_ids),
        )
        .all()
    )
    receipt_by_source = {row.source_record_id: row for row in receipts}
    missing_receipts = sorted(set(source_ids) - set(receipt_by_source))
    if missing_receipts:
        raise ValueError(f"legacy receipts missing from ERP: {missing_receipts[:20]}")

    packages = (
        db.query(Package)
        .filter(Package.legacy_receipt_id.in_([row.id for row in receipts]))
        .all()
    )
    package_by_receipt = {row.legacy_receipt_id: row for row in packages}
    if len(package_by_receipt) != len(receipts):
        raise ValueError("expected exactly one package per mapped legacy receipt")

    package_ids = [row.id for row in packages]
    item_rows = db.query(PackageItem).filter(PackageItem.package_id.in_(package_ids)).all()
    stock_rows = (
        db.query(FinishedGoodsStock)
        .filter(FinishedGoodsStock.package_id.in_(package_ids))
        .all()
    )
    items_by_package: dict[int, list[PackageItem]] = {}
    stock_by_package: dict[int, list[FinishedGoodsStock]] = {}
    for row in item_rows:
        items_by_package.setdefault(row.package_id, []).append(row)
    for row in stock_rows:
        stock_by_package.setdefault(row.package_id, []).append(row)
    bad_cardinality = [
        package_id
        for package_id in package_ids
        if len(items_by_package.get(package_id, [])) != 1
        or len(stock_by_package.get(package_id, [])) != 1
    ]
    if bad_cardinality:
        raise ValueError(f"package/item/stock cardinality mismatch: {bad_cardinality[:20]}")

    if db.query(ShipmentPackage.id).filter(ShipmentPackage.package_id.in_(package_ids)).first():
        raise ValueError("mapped package is already linked to a shipment")
    if (
        db.query(StockReservation.id)
        .filter(
            StockReservation.finished_goods_stock_id.in_(
                [row.id for row in stock_rows]
            )
        )
        .first()
    ):
        raise ValueError("mapped stock is already reserved")

    before_totals = {
        "package_quantity": sum(int(row.total_quantity or 0) for row in packages),
        "stock_quantity": sum(int(row.quantity or 0) for row in stock_rows),
        "available_quantity": sum(int(row.available_qty or 0) for row in stock_rows),
        "reserved_quantity": sum(int(row.reserved_qty or 0) for row in stock_rows),
        "sold_quantity": sum(int(row.sold_qty or 0) for row in stock_rows),
    }
    changed: list[dict[str, Any]] = []
    skipped_existing = 0

    for source_id in source_ids:
        mapping = mapping_by_source[source_id]
        receipt = receipt_by_source[source_id]
        package = package_by_receipt[receipt.id]
        item = items_by_package[package.id][0]
        stock = stock_by_package[package.id][0]
        target_model = target_models[clean(mapping["target_model_code"]).casefold()]
        current_model = db.get(Model, package.model_id)
        if not current_model:
            raise ValueError(f"current model missing for package {package.id}")
        if item.model_id != package.model_id or stock.model_id != package.model_id:
            raise ValueError(f"model identity mismatch inside package {package.id}")
        if package.sales_order_id is not None or package.status != "received_in_storage":
            raise ValueError(f"package {package.id} is no longer untouched storage stock")
        if int(stock.reserved_qty or 0) or int(stock.sold_qty or 0):
            raise ValueError(f"stock {stock.id} has reserved or sold quantity")

        target_color = display_color(
            {
                "color": (receipt.source_payload or {}).get("color"),
                "variant": clean(mapping["target_variant"]),
            }
        )
        already_target = (
            package.model_id == target_model.id
            and item.model_id == target_model.id
            and stock.model_id == target_model.id
            and package.color == target_color
            and item.color == target_color
            and stock.color == target_color
        )
        if already_target:
            skipped_existing += 1
            continue
        if not current_model.code.startswith("LEGACY-"):
            raise ValueError(
                f"package {package.id} has non-legacy model {current_model.code}, "
                f"expected {target_model.code}"
            )

        old_value = {
            "model_id": current_model.id,
            "model_code": current_model.code,
            "package_color": package.color,
            "item_color": item.color,
            "stock_color": stock.color,
        }
        package.model_id = target_model.id
        item.model_id = target_model.id
        stock.model_id = target_model.id
        package.color = target_color
        item.color = target_color
        stock.color = target_color
        changed.append(
            {
                "source_record_id": source_id,
                "package_id": package.id,
                "stock_id": stock.id,
                "old": old_value,
                "new": {
                    "model_id": target_model.id,
                    "model_code": target_model.code,
                    "variant": clean(mapping["target_variant"]),
                    "color": target_color,
                },
                "evidence_methods": mapping["evidence_methods"],
            }
        )

    db.flush()
    after_totals = {
        "package_quantity": sum(int(row.total_quantity or 0) for row in packages),
        "stock_quantity": sum(int(row.quantity or 0) for row in stock_rows),
        "available_quantity": sum(int(row.available_qty or 0) for row in stock_rows),
        "reserved_quantity": sum(int(row.reserved_qty or 0) for row in stock_rows),
        "sold_quantity": sum(int(row.sold_qty or 0) for row in stock_rows),
    }
    if after_totals != before_totals:
        raise AssertionError("model reconciliation changed finished-goods quantities")

    result = {
        "mode": "apply" if apply else "dry_run",
        "mapping_sha256": mapping_sha256,
        "mapping_reference": mapping_reference,
        "expected_rows": len(rows),
        "changed_rows": len(changed),
        "skipped_existing": skipped_existing,
        "before_totals": before_totals,
        "after_totals": after_totals,
        "changed": changed,
    }
    if len(changed) + skipped_existing != len(rows):
        raise AssertionError("mapping rows did not reconcile")

    if apply:
        log_action(
            db,
            None,
            "legacy_stock_model_reconciliation",
            "LegacyStockReconciliation",
            old_value={
                "legacy_fallback_rows": len(changed),
                **before_totals,
            },
            new_value={
                "resolved_rows": len(changed),
                "skipped_existing": skipped_existing,
                "mapping_sha256": mapping_sha256,
                "mapping_reference": mapping_reference,
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
