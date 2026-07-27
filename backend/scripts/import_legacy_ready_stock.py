"""Idempotent import of ready-product stock from the legacy UZERP report.

The input is a JSON object with a ``rows`` list. Each row must already contain
the model/variant mapping produced by the extraction/reconciliation step.

Dry-run is the default. Pass ``--apply`` only after the audit summary matches
the source report and a production database backup has completed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func

from app.db.session import SessionLocal
from app.models import (
    Brand,
    FinishedGoodsStock,
    LegacyStockReceipt,
    Model,
    ModelColor,
    ModelSize,
    Package,
    PackageBarcodeAlias,
    PackageItem,
    PackageScanLog,
    Warehouse,
)


SOURCE_SYSTEM = "UZERP"
SOURCE_WAREHOUSE_ID = "18"
SOURCE_WAREHOUSE_NAME = "TAYYOR MAHSULOT OMBORI"
EMPTY_TOKENS = {"", "-", "—", "null", "none", "n/a"}


def clean(value: Any, *, limit: int | None = None) -> str:
    text = " ".join(str(value or "").strip().split())
    if text.lower() in EMPTY_TOKENS:
        return ""
    return text[:limit] if limit else text


def positive_int(value: Any, field: str, record_id: str) -> int:
    raw = clean(value).replace(",", ".")
    try:
        number = float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"{record_id}: {field} is not numeric: {value!r}") from None
    rounded = int(round(number))
    if number <= 0 or abs(number - rounded) > 0.000001:
        raise ValueError(f"{record_id}: {field} must be a positive whole-piece quantity: {value!r}")
    return rounded


def optional_number(value: Any) -> float | None:
    raw = clean(value).replace(",", ".")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def current_piece_quantity(row: dict[str, Any], record_id: str) -> int:
    original_qty = positive_int(row.get("quantity"), "quantity", record_id)
    if optional_number(row.get("available")) is None:
        return original_qty
    current_qty = positive_int(row.get("available"), "available", record_id)
    if current_qty > original_qty:
        raise ValueError(
            f"{record_id}: available quantity {current_qty} exceeds original quantity {original_qty}"
        )
    return current_qty


def canonical_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {str(key): row[key] for key in sorted(row)}


def payload_checksum(row: dict[str, Any]) -> str:
    payload = json.dumps(canonical_payload(row), ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def fallback_model_code(row: dict[str, Any]) -> str:
    seed = clean(row.get("finished_name")) or clean(row.get("product")) or clean(row.get("product_article"))
    if not seed:
        seed = f"source-record-{clean(row.get('source_record_id'))}"
    suffix = hashlib.sha1(seed.casefold().encode("utf-8")).hexdigest()[:12].upper()
    return f"LEGACY-{suffix}"


def normalized_model_code(row: dict[str, Any]) -> str:
    code = clean(row.get("model_code"), limit=64)
    return code or fallback_model_code(row)


def display_color(row: dict[str, Any]) -> str:
    color = clean(row.get("color")) or "UNSPECIFIED"
    variant = clean(row.get("variant"))
    if variant and variant.casefold() not in color.casefold():
        color = f"{color} · {variant}"
    return color[:64]


def model_name(row: dict[str, Any]) -> str:
    return (
        clean(row.get("finished_name"), limit=255)
        or clean(row.get("product"), limit=255)
        or normalized_model_code(row)
    )


def source_aliases(row: dict[str, Any]) -> list[tuple[str, str]]:
    candidates = [
        ("system_no", row.get("source_record_id")),
        ("product_barcode", row.get("product_barcode")),
        ("item_barcode", row.get("item_barcode")),
        ("external_barcode", row.get("external_barcode")),
        ("sewing_barcode", row.get("sewing_barcode")),
        ("legacy_package_no", row.get("package_no")),
    ]
    aliases: list[tuple[str, str]] = []
    seen: set[str] = set()
    for code_type, value in candidates:
        code = clean(value, limit=128)
        if code and code not in seen:
            seen.add(code)
            aliases.append((code_type, code))
    return aliases


def read_input(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return {}, payload
    if not isinstance(payload, dict) or not isinstance(payload.get("rows"), list):
        raise ValueError("Input must be a JSON list or an object with a rows list")
    return dict(payload.get("source") or {}), list(payload["rows"])


def profile_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ids = [clean(row.get("source_record_id")) for row in rows]
    if any(not record_id for record_id in ids):
        raise ValueError("Every source row must have source_record_id")
    duplicates = [record_id for record_id, count in Counter(ids).items() if count > 1]
    if duplicates:
        raise ValueError(f"Duplicate source_record_id values: {duplicates[:10]}")

    quantities: list[int] = []
    available_quantities: list[int] = []
    unmapped = 0
    units: Counter[str] = Counter()
    available_mismatches = 0
    for row, record_id in zip(rows, ids):
        qty = positive_int(row.get("quantity"), "quantity", record_id)
        available_qty = current_piece_quantity(row, record_id)
        quantities.append(qty)
        available_quantities.append(available_qty)
        if not clean(row.get("model_code")):
            unmapped += 1
        unit = clean(row.get("unit")) or "(blank)"
        units[unit] += 1
        if available_qty != qty:
            available_mismatches += 1

    return {
        "row_count": len(rows),
        "piece_quantity": sum(quantities),
        "available_piece_quantity": sum(available_quantities),
        "depleted_piece_quantity": sum(quantities) - sum(available_quantities),
        "distinct_source_records": len(set(ids)),
        "unmapped_model_rows": unmapped,
        "available_quantity_mismatch_rows": available_mismatches,
        "units": dict(units.most_common()),
        "distinct_model_codes": len({normalized_model_code(row).casefold() for row in rows}),
        "distinct_alias_codes": len({code for row in rows for _, code in source_aliases(row)}),
    }


def ensure_expectations(source: dict[str, Any], profile: dict[str, Any], args: argparse.Namespace) -> None:
    expected_rows = args.expected_rows or source.get("expected_rows")
    expected_qty = args.expected_quantity or source.get("expected_quantity")
    expected_available_qty = args.expected_available_quantity or source.get("expected_available_quantity")
    if expected_rows is not None and int(expected_rows) != int(profile["row_count"]):
        raise ValueError(f"Expected {expected_rows} rows, found {profile['row_count']}")
    if expected_qty is not None and int(expected_qty) != int(profile["piece_quantity"]):
        raise ValueError(f"Expected quantity {expected_qty}, found {profile['piece_quantity']}")
    if expected_available_qty is not None and int(expected_available_qty) != int(
        profile["available_piece_quantity"]
    ):
        raise ValueError(
            f"Expected available quantity {expected_available_qty}, "
            f"found {profile['available_piece_quantity']}"
        )


def find_or_create_brand(db, name: str, *, apply: bool) -> Brand | None:
    brand = db.query(Brand).filter(func.lower(Brand.name) == name.casefold()).first()
    if brand or not apply:
        return brand
    brand = Brand(
        name=name,
        description="Models created only to preserve finished-goods stock migrated from the legacy UZERP.",
        is_active=True,
    )
    db.add(brand)
    db.flush()
    return brand


def package_identity(record_id: str) -> tuple[str, str]:
    normalized = re.sub(r"[^0-9A-Za-z._-]+", "-", record_id).strip("-") or hashlib.sha1(
        record_id.encode("utf-8")
    ).hexdigest()[:16]
    normalized = normalized[:50]
    return f"LEG-{normalized}", f"LEGACY:{normalized}"


def run_import(args: argparse.Namespace) -> dict[str, Any]:
    source, rows = read_input(args.input)
    profile = profile_rows(rows)
    ensure_expectations(source, profile, args)

    source_warehouse_id = clean(source.get("warehouse_id")) or SOURCE_WAREHOUSE_ID
    source_warehouse_name = clean(source.get("warehouse_name")) or SOURCE_WAREHOUSE_NAME
    if source_warehouse_id != SOURCE_WAREHOUSE_ID:
        raise ValueError(f"Expected legacy warehouse {SOURCE_WAREHOUSE_ID}, got {source_warehouse_id}")

    summary: dict[str, Any] = {
        "mode": "apply" if args.apply else "dry-run",
        "source_system": SOURCE_SYSTEM,
        "source_warehouse_id": source_warehouse_id,
        "source_warehouse_name": source_warehouse_name,
        **profile,
        "created_receipts": 0,
        "created_packages": 0,
        "created_stock_rows": 0,
        "created_models": 0,
        "created_aliases": 0,
        "skipped_existing": 0,
        "conflicts": [],
        "started_at": datetime.now(timezone.utc).isoformat(),
    }

    db = SessionLocal()
    try:
        warehouse = db.get(Warehouse, args.warehouse_id)
        if not warehouse:
            raise ValueError(f"Destination warehouse {args.warehouse_id} does not exist")

        brand = find_or_create_brand(db, args.legacy_brand, apply=args.apply)
        if not brand and args.apply:
            raise ValueError(f"Could not create or find brand {args.legacy_brand!r}")

        existing_models = {
            clean(model.code).casefold(): model
            for model in db.query(Model).all()
            if clean(model.code)
        }
        model_sizes = {
            (int(model_id), clean(size).casefold())
            for model_id, size in db.query(ModelSize.model_id, ModelSize.size).all()
        }
        model_colors = {
            (int(model_id), clean(color).casefold())
            for model_id, color in db.query(ModelColor.model_id, ModelColor.color_name).all()
        }

        incoming_by_id = {
            clean(row.get("source_record_id"), limit=128): payload_checksum(row)
            for row in rows
        }
        existing_receipts = (
            db.query(LegacyStockReceipt)
            .filter(
                LegacyStockReceipt.source_system == SOURCE_SYSTEM,
                LegacyStockReceipt.source_warehouse_id == source_warehouse_id,
                LegacyStockReceipt.source_record_id.in_(incoming_by_id),
            )
            .all()
        )
        preflight_conflicts = [
            {
                "source_record_id": receipt.source_record_id,
                "reason": "source checksum changed",
                "existing_checksum": receipt.source_checksum,
                "incoming_checksum": incoming_by_id[receipt.source_record_id],
            }
            for receipt in existing_receipts
            if receipt.source_checksum != incoming_by_id[receipt.source_record_id]
        ]
        if preflight_conflicts:
            summary["conflicts"] = preflight_conflicts
            raise ValueError(f"{len(preflight_conflicts)} source checksum conflicts; import aborted")

        for index, row in enumerate(rows, start=1):
            record_id = clean(row.get("source_record_id"), limit=128)
            checksum = payload_checksum(row)
            existing_receipt = (
                db.query(LegacyStockReceipt)
                .filter(
                    LegacyStockReceipt.source_system == SOURCE_SYSTEM,
                    LegacyStockReceipt.source_warehouse_id == source_warehouse_id,
                    LegacyStockReceipt.source_record_id == record_id,
                )
                .first()
            )
            if existing_receipt:
                if existing_receipt.source_checksum != checksum:
                    summary["conflicts"].append(
                        {
                            "source_record_id": record_id,
                            "reason": "source checksum changed",
                            "existing_checksum": existing_receipt.source_checksum,
                            "incoming_checksum": checksum,
                        }
                    )
                    continue
                summary["skipped_existing"] += 1
                continue

            code = normalized_model_code(row)
            model = existing_models.get(code.casefold())
            if not model:
                if not args.apply:
                    model = None
                else:
                    model = Model(
                        code=code,
                        name=model_name(row),
                        category=clean(row.get("category"), limit=64) or "Legacy finished goods",
                        description="Created during verified UZERP ready-product inventory migration.",
                        brand_id=brand.id if brand else None,
                        details_json={
                            "legacy_import": True,
                            "legacy_source_system": SOURCE_SYSTEM,
                            "legacy_first_source_record_id": record_id,
                        },
                        status="approved",
                        approved_at=datetime.now(timezone.utc),
                    )
                    db.add(model)
                    db.flush()
                    existing_models[code.casefold()] = model
                    summary["created_models"] += 1

            qty = positive_int(row.get("quantity"), "quantity", record_id)
            available_qty = current_piece_quantity(row, record_id)
            color = display_color(row)
            size = clean(row.get("size"), limit=32) or "UNSPECIFIED"
            package_no, barcode = package_identity(record_id)

            if not args.apply:
                continue

            receipt = LegacyStockReceipt(
                source_system=SOURCE_SYSTEM,
                source_warehouse_id=source_warehouse_id,
                source_warehouse_name=source_warehouse_name,
                source_record_id=record_id,
                source_checksum=checksum,
                source_payload=canonical_payload(row),
                imported_by=args.imported_by,
            )
            db.add(receipt)
            db.flush()
            summary["created_receipts"] += 1

            package = Package(
                package_no=package_no,
                barcode=barcode,
                production_order_id=None,
                legacy_receipt_id=receipt.id,
                brand_id=model.brand_id or (brand.id if brand else None),
                collection_id=model.collection_id,
                model_id=model.id,
                color=color,
                package_type="legacy_stock",
                total_quantity=available_qty,
                capacity=max(60, qty),
                warehouse_id=warehouse.id,
                status="received_in_storage",
                received_by=args.imported_by,
                received_at=datetime.now(timezone.utc),
                notes=(
                    f"Imported from {SOURCE_SYSTEM} warehouse {source_warehouse_name}; "
                    f"source system no. {record_id}."
                ),
            )
            db.add(package)
            db.flush()
            summary["created_packages"] += 1

            db.add(
                PackageItem(
                    package_id=package.id,
                    model_id=model.id,
                    color=color,
                    size=size,
                    quantity=available_qty,
                )
            )
            db.add(
                FinishedGoodsStock(
                    production_order_id=None,
                    package_id=package.id,
                    model_id=model.id,
                    brand_id=package.brand_id,
                    collection_id=package.collection_id,
                    color=color,
                    size=size,
                    quantity=available_qty,
                    available_qty=available_qty,
                    reserved_qty=0,
                    sold_qty=0,
                    cost_per_piece=0,
                    selling_price=0,
                    warehouse_id=warehouse.id,
                    status="available",
                )
            )
            db.add(
                PackageScanLog(
                    package_id=package.id,
                    scanned_by=args.imported_by,
                    scan_type="legacy_import",
                    location=source_warehouse_name,
                )
            )
            summary["created_stock_rows"] += 1

            for code_type, alias in source_aliases(row):
                db.add(PackageBarcodeAlias(package_id=package.id, code=alias, code_type=code_type))
                summary["created_aliases"] += 1

            size_key = (int(model.id), size.casefold())
            if size_key not in model_sizes:
                db.add(ModelSize(model_id=model.id, size=size))
                model_sizes.add(size_key)
            color_key = (int(model.id), color.casefold())
            if color_key not in model_colors:
                db.add(ModelColor(model_id=model.id, color_name=color))
                model_colors.add(color_key)

            if index % args.batch_size == 0:
                db.commit()

        if args.apply:
            db.commit()
        else:
            db.rollback()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    summary["finished_at"] = datetime.now(timezone.utc).isoformat()
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--warehouse-id", type=int, required=True, help="Destination ERP warehouse ID")
    parser.add_argument("--legacy-brand", default="Legacy Stock")
    parser.add_argument("--imported-by", type=int)
    parser.add_argument("--expected-rows", type=int)
    parser.add_argument("--expected-quantity", type=int)
    parser.add_argument("--expected-available-quantity", type=int)
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--audit-output", type=Path)
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = run_import(args)
    rendered = json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True)
    if args.audit_output:
        args.audit_output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
