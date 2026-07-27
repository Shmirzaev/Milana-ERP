"""Import the reviewed astatka.xlsx balances into finished-goods stock.

The prepared JSON contains only positive net balances. Exact catalog matches
keep their model_id; old products without an exact match remain model-less and
retain their identity in the immutable LegacyStockReceipt source payload.

Dry-run is the default. Pass --apply only after a verified production backup.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func

from app.db.session import SessionLocal
from app.models import (
    FinishedGoodsStock,
    LegacyStockReceipt,
    Model,
    Package,
    PackageItem,
    PackageScanLog,
    Warehouse,
)
from app.services.audit import log_action


SOURCE_SYSTEM = "ASTATKA_XLSX"
SOURCE_WAREHOUSE_ID = "READY_PRODUCTS_BALANCE"
SOURCE_WAREHOUSE_NAME = "Ready products balance workbook"
EXPECTED_WAREHOUSE_TYPE = "finished_goods"


def clean(value: Any, *, limit: int | None = None) -> str:
    text = " ".join(str(value or "").strip().split())
    return text[:limit] if limit else text


def checksum(row: dict[str, Any]) -> str:
    encoded = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def positive_int(value: Any, field: str, source_record_id: str) -> int:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{source_record_id}: {field} is not numeric") from None
    rounded = int(round(number))
    if number <= 0 or abs(number - rounded) > 0.000001:
        raise ValueError(f"{source_record_id}: {field} must be a positive whole number")
    return rounded


def load_plan(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("rows"), list):
        raise ValueError("Import plan must be an object with a rows list")
    return payload


def profile_rows(rows: list[dict[str, Any]]) -> dict[str, int]:
    source_ids: set[str] = set()
    package_nos: set[str] = set()
    barcodes: set[str] = set()
    quantity = 0
    mapped = 0
    model_less = 0
    for row in rows:
        record_id = clean(row.get("source_record_id"), limit=128)
        package_no = clean(row.get("package_no"), limit=64)
        barcode = clean(row.get("barcode"), limit=64)
        if not record_id or not package_no or not barcode:
            raise ValueError("Every row requires source_record_id, package_no, and barcode")
        if record_id in source_ids:
            raise ValueError(f"Duplicate source_record_id: {record_id}")
        if package_no in package_nos:
            raise ValueError(f"Duplicate package_no: {package_no}")
        if barcode in barcodes:
            raise ValueError(f"Duplicate barcode: {barcode}")
        source_ids.add(record_id)
        package_nos.add(package_no)
        barcodes.add(barcode)
        quantity += positive_int(row.get("quantity"), "quantity", record_id)
        if row.get("target_model_id") is None:
            model_less += 1
        else:
            mapped += 1
    return {
        "rows": len(rows),
        "quantity": quantity,
        "mapped_rows": mapped,
        "model_less_rows": model_less,
    }


def stock_totals(db) -> dict[str, int]:
    return {
        "stock_rows": int(db.query(func.count(FinishedGoodsStock.id)).scalar() or 0),
        "stock_quantity": int(
            db.query(func.coalesce(func.sum(FinishedGoodsStock.quantity), 0)).scalar() or 0
        ),
        "available_quantity": int(
            db.query(func.coalesce(func.sum(FinishedGoodsStock.available_qty), 0)).scalar() or 0
        ),
        "packages": int(db.query(func.count(Package.id)).scalar() or 0),
        "legacy_receipts": int(db.query(func.count(LegacyStockReceipt.id)).scalar() or 0),
        "models": int(db.query(func.count(Model.id)).scalar() or 0),
    }


def run_import(
    db,
    plan: dict[str, Any],
    *,
    warehouse_id: int,
    imported_by: int | None,
    apply: bool,
) -> dict[str, Any]:
    rows = list(plan["rows"])
    profile = profile_rows(rows)
    expectations = dict(plan.get("expectations") or {})
    for key in ("rows", "quantity", "mapped_rows", "model_less_rows"):
        if key in expectations and int(expectations[key]) != int(profile[key]):
            raise ValueError(
                f"Plan expectation {key}={expectations[key]} does not match {profile[key]}"
            )

    warehouse = db.get(Warehouse, warehouse_id)
    if not warehouse or warehouse.type != EXPECTED_WAREHOUSE_TYPE:
        raise ValueError(
            f"Warehouse {warehouse_id} must exist with type {EXPECTED_WAREHOUSE_TYPE}"
        )

    model_ids = {
        int(row["target_model_id"])
        for row in rows
        if row.get("target_model_id") is not None
    }
    models = {
        int(model.id): model
        for model in db.query(Model).filter(Model.id.in_(model_ids)).all()
    } if model_ids else {}
    if set(models) != model_ids:
        missing = sorted(model_ids - set(models))
        raise ValueError(f"Mapped production models are missing: {missing[:20]}")

    for row in rows:
        model_id = row.get("target_model_id")
        expected_code = clean(row.get("target_model_code"))
        if model_id is not None and expected_code and models[int(model_id)].code != expected_code:
            raise ValueError(
                f"{row['source_record_id']}: model {model_id} code changed from "
                f"{expected_code!r} to {models[int(model_id)].code!r}"
            )

    source_ids = [clean(row["source_record_id"], limit=128) for row in rows]
    existing_receipts = {
        receipt.source_record_id: receipt
        for receipt in db.query(LegacyStockReceipt).filter(
            LegacyStockReceipt.source_system == SOURCE_SYSTEM,
            LegacyStockReceipt.source_warehouse_id == SOURCE_WAREHOUSE_ID,
            LegacyStockReceipt.source_record_id.in_(source_ids),
        )
    }
    existing_package_nos = {
        value
        for (value,) in db.query(Package.package_no).filter(
            Package.package_no.in_([clean(row["package_no"], limit=64) for row in rows])
        )
    }
    existing_barcodes = {
        value
        for (value,) in db.query(Package.barcode).filter(
            Package.barcode.in_([clean(row["barcode"], limit=64) for row in rows])
        )
    }

    before = stock_totals(db)
    created = {
        "receipts": 0,
        "packages": 0,
        "package_items": 0,
        "stock_rows": 0,
        "scan_logs": 0,
        "quantity": 0,
        "mapped_rows": 0,
        "model_less_rows": 0,
        "skipped_existing": 0,
    }

    for row in rows:
        record_id = clean(row["source_record_id"], limit=128)
        source_payload = dict(row.get("source_payload") or {})
        row_checksum = checksum(source_payload)
        existing = existing_receipts.get(record_id)
        if existing:
            if existing.source_checksum != row_checksum:
                raise ValueError(f"{record_id}: existing receipt checksum differs")
            created["skipped_existing"] += 1
            continue

        package_no = clean(row["package_no"], limit=64)
        barcode = clean(row["barcode"], limit=64)
        if package_no in existing_package_nos:
            raise ValueError(f"{record_id}: package number already exists: {package_no}")
        if barcode in existing_barcodes:
            raise ValueError(f"{record_id}: barcode already exists: {barcode}")

        quantity = positive_int(row["quantity"], "quantity", record_id)
        model_id = int(row["target_model_id"]) if row.get("target_model_id") is not None else None
        model = models.get(model_id) if model_id is not None else None
        product = clean(source_payload.get("product") or source_payload.get("model_name"), limit=64)
        color = product or clean(source_payload.get("model_code"), limit=64) or "Old ready product"
        size = clean(source_payload.get("size"), limit=32) or "UNSPECIFIED"

        receipt = LegacyStockReceipt(
            source_system=SOURCE_SYSTEM,
            source_warehouse_id=SOURCE_WAREHOUSE_ID,
            source_warehouse_name=SOURCE_WAREHOUSE_NAME,
            source_record_id=record_id,
            source_checksum=row_checksum,
            source_payload=source_payload,
            imported_by=imported_by,
        )
        db.add(receipt)
        db.flush()
        created["receipts"] += 1

        package = Package(
            package_no=package_no,
            barcode=barcode,
            production_order_id=None,
            legacy_receipt_id=receipt.id,
            brand_id=model.brand_id if model else None,
            collection_id=model.collection_id if model else None,
            model_id=model_id,
            color=color,
            package_type="legacy_stock",
            total_quantity=quantity,
            capacity=max(60, quantity),
            warehouse_id=warehouse.id,
            status="received_in_storage",
            received_by=imported_by,
            received_at=datetime.now(timezone.utc),
            notes=f"Imported from astatka.xlsx source {record_id}.",
        )
        db.add(package)
        db.flush()
        created["packages"] += 1

        db.add(
            PackageItem(
                package_id=package.id,
                model_id=model_id,
                color=color,
                size=size,
                quantity=quantity,
            )
        )
        created["package_items"] += 1
        db.add(
            FinishedGoodsStock(
                production_order_id=None,
                package_id=package.id,
                model_id=model_id,
                brand_id=package.brand_id,
                collection_id=package.collection_id,
                color=color,
                size=size,
                quantity=quantity,
                available_qty=quantity,
                reserved_qty=0,
                sold_qty=0,
                cost_per_piece=0,
                selling_price=0,
                warehouse_id=warehouse.id,
                status="available",
            )
        )
        created["stock_rows"] += 1
        db.add(
            PackageScanLog(
                package_id=package.id,
                scanned_by=imported_by,
                scan_type="legacy_import",
                location=SOURCE_WAREHOUSE_NAME,
            )
        )
        created["scan_logs"] += 1
        created["quantity"] += quantity
        if model_id is None:
            created["model_less_rows"] += 1
        else:
            created["mapped_rows"] += 1

    db.flush()
    after = stock_totals(db)
    expected_after = {
        "stock_rows": before["stock_rows"] + created["stock_rows"],
        "stock_quantity": before["stock_quantity"] + created["quantity"],
        "available_quantity": before["available_quantity"] + created["quantity"],
        "packages": before["packages"] + created["packages"],
        "legacy_receipts": before["legacy_receipts"] + created["receipts"],
        "models": before["models"],
    }
    if after != expected_after:
        raise AssertionError(
            f"Projected totals do not reconcile: expected {expected_after}, got {after}"
        )

    result = {
        "mode": "apply" if apply else "dry_run",
        "source_system": SOURCE_SYSTEM,
        "source_file_sha256": plan.get("source_file_sha256"),
        "profile": profile,
        "before": before,
        "created": created,
        "after": after,
        "models_created": after["models"] - before["models"],
    }
    if apply:
        log_action(
            db,
            None,
            "astatka_ready_stock_import",
            "LegacyReadyStockImport",
            new_value=result,
        )
        db.commit()
    else:
        db.rollback()
    db.expunge_all()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("--warehouse-id", type=int, required=True)
    parser.add_argument("--imported-by", type=int)
    parser.add_argument("--audit-output", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    plan = load_plan(args.plan)
    with SessionLocal() as db:
        result = run_import(
            db,
            plan,
            warehouse_id=args.warehouse_id,
            imported_by=args.imported_by,
            apply=args.apply,
        )
    args.audit_output.parent.mkdir(parents=True, exist_ok=True)
    args.audit_output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
