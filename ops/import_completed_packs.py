"""Guarded import for user-completed old-ERP pack stickers.

The manifest is immutable, photo-backed, and production-classified before this
script runs. Dry-run is the default. Apply requires an environment-specific
confirmation phrase and performs the import in one database transaction.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import func, text

from app.core.config import settings
from app.db.session import SessionLocal
from app.models import (
    FinishedGoodsStock,
    LegacyStockReceipt,
    Model,
    Package,
    PackageBarcodeAlias,
    PackageItem,
    PackageScanLog,
    User,
    Warehouse,
)
from app.services.audit import log_action


SOURCE_SYSTEM = "UZERP_STICKER_PHOTO"
SOURCE_WAREHOUSE_ID = "18"
SOURCE_WAREHOUSE_NAME = "TAYYOR MAHSULOT OMBORI"
EXPECTED_ALEMBIC_HEAD = "0113_variant_selling_price"
EXPECTED_WAREHOUSE_ID = 8
EXPECTED_WAREHOUSE_NAME = "Finished Goods"
EXPECTED_WAREHOUSE_TYPE = "finished_goods"
EXPECTED_IMPORTER_ID = 1
QR_RE = re.compile(r"^(?:uzerp_ii_(\d+)_(\d+)|(\d{7}))$", re.IGNORECASE)
SHA_RE = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)
CONFUSABLES = str.maketrans(
    {
        "А": "A", "В": "B", "С": "C", "Е": "E", "Н": "H", "К": "K",
        "М": "M", "О": "O", "Р": "P", "Т": "T", "Х": "X", "У": "Y",
        "І": "I", "Ј": "J",
    }
)


def clean(value: Any, *, limit: int | None = None) -> str:
    value = " ".join(unicodedata.normalize("NFKC", str(value or "")).strip().split())
    return value[:limit] if limit else value


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {str(key): row[key] for key in sorted(row)}


def payload_checksum(row: dict[str, Any]) -> str:
    encoded = json.dumps(canonical_payload(row), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def normalized_base(value: Any) -> str:
    return "".join(ch for ch in clean(value).upper().translate(CONFUSABLES) if ch.isalnum())


def normalized_variant(value: Any) -> str:
    value = re.sub(r"^V[\s_-]*", "", clean(value).upper().translate(CONFUSABLES), count=1)
    key = "".join(ch for ch in value if ch.isalnum())
    return str(int(key)) if key.isdigit() else key


def model_identity(model: Model) -> tuple[str, str]:
    details = model.details_json if isinstance(model.details_json, dict) else {}
    general = details.get("general") if isinstance(details.get("general"), dict) else {}
    return (
        normalized_base(general.get("model_no") or general.get("modelNo")),
        normalized_variant(general.get("variant_no") or general.get("variantNo")),
    )


def package_number(qr: str) -> str:
    match = QR_RE.fullmatch(qr)
    if not match:
        raise ValueError(f"Invalid old sticker QR: {qr!r}")
    return (
        f"OLD-{match.group(1)}-{match.group(2)}"
        if match.group(1) and match.group(2)
        else f"OLD-{match.group(3)}"
    )


def validate_row(row: dict[str, Any], photo_root: Path) -> dict[str, Any]:
    qr = clean(row.get("qr_code"), limit=128).casefold()
    if not QR_RE.fullmatch(qr):
        raise ValueError(f"Invalid old sticker QR: {qr!r}")
    if not clean(row.get("model_number")) or not clean(row.get("article")):
        raise ValueError(f"{qr}: model or variant is blank")
    try:
        quantity = int(row.get("quantity"))
    except (TypeError, ValueError):
        raise ValueError(f"{qr}: quantity is not a whole number") from None
    if quantity <= 0:
        raise ValueError(f"{qr}: quantity must be positive")
    raw_weight = row.get("weight_kg")
    weight = None if raw_weight in (None, "") else Decimal(clean(raw_weight).replace(",", "."))
    if weight is not None and weight <= 0:
        raise ValueError(f"{qr}: weight must be positive")
    if weight is None and row.get("allowed_blank_weight") is not True:
        raise ValueError(f"{qr}: blank weight lacks explicit user approval")
    if weight is not None and row.get("allowed_blank_weight") is True:
        raise ValueError(f"{qr}: blank-weight exception conflicts with supplied weight")
    sizes = [clean(value, limit=32) for value in row.get("sizes") or [] if clean(value)]
    if not sizes:
        raise ValueError(f"{qr}: sizes are blank")
    photo_name = clean(row.get("source_photo"), limit=255)
    photo_hash = clean(row.get("source_photo_sha256"), limit=64).casefold()
    if not photo_name or not SHA_RE.fullmatch(photo_hash):
        raise ValueError(f"{qr}: source photo evidence is incomplete")
    root = photo_root.resolve()
    photo_path = (root / photo_name).resolve()
    if photo_path.parent != root or not photo_path.is_file() or file_sha256(photo_path) != photo_hash:
        raise ValueError(f"{qr}: source photo is missing, unsafe, or changed")
    if clean(row.get("review_status")).casefold() != "approved":
        raise ValueError(f"{qr}: row is not explicitly approved")
    return {
        **canonical_payload(row),
        "qr_code": qr,
        "model_number": clean(row["model_number"]),
        "article": clean(row["article"]),
        "quantity": quantity,
        "weight_kg": str(weight) if weight is not None else None,
        "sizes": sizes,
        "source_photo": photo_name,
        "source_photo_sha256": photo_hash,
    }


def read_manifest(path: Path, photo_root: Path, expected_hash: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    actual_hash = file_sha256(path)
    if actual_hash != expected_hash:
        raise ValueError(f"Manifest SHA-256 changed: {actual_hash}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("version") != 1 or not isinstance(payload.get("rows"), list):
        raise ValueError("Manifest must be a version-1 object with rows")
    rows = [validate_row(dict(row), photo_root) for row in payload["rows"]]
    qrs = [row["qr_code"] for row in rows]
    if len(qrs) != len(set(qrs)):
        raise ValueError("Manifest repeats QR values")
    expected = {
        "expected_rows": len(rows),
        "expected_quantity": sum(row["quantity"] for row in rows),
        "expected_known_weight_kg": str(sum((Decimal(row["weight_kg"]) for row in rows if row["weight_kg"] is not None), Decimal("0"))),
        "expected_null_weight_rows": sum(row["weight_kg"] is None for row in rows),
        "expected_unique_identities": len({
            (normalized_base(row["model_number"]), normalized_variant(row["article"])) for row in rows
        }),
    }
    for key, value in expected.items():
        if str(payload.get(key)) != str(value):
            raise ValueError(f"Manifest summary mismatch for {key}: expected {value!r}, found {payload.get(key)!r}")
    return payload, rows


def assert_target_guard(db, args: argparse.Namespace) -> tuple[Warehouse, User]:
    parsed = urlparse(settings.DATABASE_URL.replace("postgresql+psycopg2://", "postgresql://", 1))
    host = (parsed.hostname or "").casefold()
    current_db = str(db.execute(text("select current_database()" )).scalar() or "")
    heads = [str(row[0]) for row in db.execute(text("select version_num from alembic_version order by version_num"))]
    if host != args.expected_database_host.casefold() or current_db != args.expected_database_name:
        raise ValueError(f"Database guard failed for host={host!r}, database={current_db!r}")
    if heads != [EXPECTED_ALEMBIC_HEAD]:
        raise ValueError(f"Expected migration head {EXPECTED_ALEMBIC_HEAD}, found {heads}")
    warehouse = db.get(Warehouse, EXPECTED_WAREHOUSE_ID)
    if not warehouse or warehouse.name != EXPECTED_WAREHOUSE_NAME or warehouse.type != EXPECTED_WAREHOUSE_TYPE:
        raise ValueError("Finished Goods warehouse guard failed")
    importer = db.get(User, args.imported_by)
    permissions = set(
        (importer.role.permissions if importer and importer.role else [])
        + ((importer.extra_permissions or []) if importer else [])
    )
    if not importer or not importer.is_active or "*" not in permissions:
        raise ValueError("Import actor is missing, inactive, or not a wildcard administrator")
    return warehouse, importer


def resolve_all(db, rows: list[dict[str, Any]], expected_unique: int) -> dict[str, Model]:
    by_identity: dict[tuple[str, str], list[Model]] = {}
    for model in db.query(Model).all():
        by_identity.setdefault(model_identity(model), []).append(model)
    resolved: dict[str, Model] = {}
    for row in rows:
        key = (normalized_base(row["model_number"]), normalized_variant(row["article"]))
        matches = by_identity.get(key, [])
        if len(matches) != 1 or clean(matches[0].status).casefold() != "approved":
            raise ValueError(f"{row['qr_code']}: expected one approved catalog model for {key}, found {len(matches)}")
        resolved[row["qr_code"]] = matches[0]
    if len({model.id for model in resolved.values()}) != expected_unique:
        raise ValueError("Resolved unique model count changed")
    return resolved


def assert_zero_collisions(db, rows: list[dict[str, Any]]) -> None:
    qrs = [row["qr_code"] for row in rows]
    package_nos = [package_number(qr) for qr in qrs]
    counts = {
        "receipts": db.query(LegacyStockReceipt).filter(
            LegacyStockReceipt.source_system == SOURCE_SYSTEM,
            LegacyStockReceipt.source_warehouse_id == SOURCE_WAREHOUSE_ID,
            func.lower(LegacyStockReceipt.source_record_id).in_(qrs),
        ).count(),
        "barcodes": db.query(Package).filter(func.lower(Package.barcode).in_(qrs)).count(),
        "package_nos": db.query(Package).filter(Package.package_no.in_(package_nos)).count(),
        "aliases": db.query(PackageBarcodeAlias).filter(func.lower(PackageBarcodeAlias.code).in_(qrs)).count(),
    }
    if any(counts.values()):
        raise ValueError(f"Target identifiers are not empty: {counts}")


def import_rows(db, rows, resolved, warehouse, importer, manifest_hash: str) -> int:
    now = datetime.now(timezone.utc)
    for row in rows:
        model = resolved[row["qr_code"]]
        color = clean(row.get("color"), limit=64) or "Not specified"
        receipt = LegacyStockReceipt(
            source_system=SOURCE_SYSTEM,
            source_warehouse_id=SOURCE_WAREHOUSE_ID,
            source_warehouse_name=SOURCE_WAREHOUSE_NAME,
            source_record_id=row["qr_code"],
            source_checksum=payload_checksum(row),
            source_payload=canonical_payload(row),
            imported_by=importer.id,
        )
        db.add(receipt)
        db.flush()
        package = Package(
            package_no=package_number(row["qr_code"]),
            barcode=row["qr_code"],
            legacy_receipt_id=receipt.id,
            model_id=model.id,
            brand_id=model.brand_id,
            collection_id=model.collection_id,
            color=color,
            package_type="legacy_stock",
            total_quantity=row["quantity"],
            capacity=max(60, row["quantity"]),
            weight_kg=row["weight_kg"],
            warehouse_id=warehouse.id,
            status="received_in_storage",
            received_by=importer.id,
            received_at=now,
            notes=f"Imported from user-completed old-ERP sticker evidence: {row['source_reference']}.",
        )
        db.add(package)
        db.flush()
        db.add_all(
            [
                PackageItem(
                    package_id=package.id, model_id=model.id, color=color,
                    size="ASSORTED", quantity=row["quantity"],
                ),
                FinishedGoodsStock(
                    package_id=package.id, model_id=model.id, brand_id=model.brand_id,
                    collection_id=model.collection_id, color=color, size="ASSORTED",
                    quantity=row["quantity"], available_qty=row["quantity"], reserved_qty=0,
                    sold_qty=0, cost_per_piece=0, selling_price=0, warehouse_id=warehouse.id,
                    status="available",
                ),
                PackageScanLog(
                    package_id=package.id, scanned_by=importer.id,
                    scan_type="legacy_sticker_import", location=None,
                ),
                PackageBarcodeAlias(
                    package_id=package.id, code=row["qr_code"], code_type="legacy_sticker_qr",
                ),
            ]
        )
    db.flush()
    audit = log_action(
        db,
        importer,
        "legacy_sticker_inventory_import",
        "LegacyStockReceipt",
        None,
        new_value={
            "manifest_sha256": manifest_hash,
            "rows": len(rows),
            "quantity": sum(row["quantity"] for row in rows),
            "null_weight_rows": sum(row["weight_kg"] is None for row in rows),
            "warehouse_id": warehouse.id,
            "source_system": SOURCE_SYSTEM,
            "source_workbook_sha256": rows[0]["source_workbook_sha256"] if rows else None,
        },
    )
    return int(audit.id)


def readback(db, rows, resolved, importer_id: int) -> dict[str, Any]:
    expected = {row["qr_code"]: row for row in rows}
    qrs = list(expected)
    receipts = db.query(LegacyStockReceipt).filter(
        LegacyStockReceipt.source_system == SOURCE_SYSTEM,
        LegacyStockReceipt.source_warehouse_id == SOURCE_WAREHOUSE_ID,
        func.lower(LegacyStockReceipt.source_record_id).in_(qrs),
    ).all()
    receipt_by_qr = {row.source_record_id.casefold(): row for row in receipts}
    packages = db.query(Package).filter(
        Package.legacy_receipt_id.in_([row.id for row in receipts] or [-1])
    ).all()
    package_by_receipt = {row.legacy_receipt_id: row for row in packages}
    package_ids = [row.id for row in packages]
    items = db.query(PackageItem).filter(PackageItem.package_id.in_(package_ids or [-1])).all()
    stocks = db.query(FinishedGoodsStock).filter(FinishedGoodsStock.package_id.in_(package_ids or [-1])).all()
    aliases = db.query(PackageBarcodeAlias).filter(PackageBarcodeAlias.package_id.in_(package_ids or [-1])).all()
    scans = db.query(PackageScanLog).filter(PackageScanLog.package_id.in_(package_ids or [-1])).all()
    maps = {
        "item": {row.package_id: row for row in items},
        "stock": {row.package_id: row for row in stocks},
        "alias": {row.package_id: row for row in aliases},
        "scan": {row.package_id: row for row in scans},
    }
    counts = {
        "receipts": len(receipts), "packages": len(packages), "items": len(items),
        "stock_rows": len(stocks), "aliases": len(aliases), "scans": len(scans),
    }
    if any(value != len(rows) for value in counts.values()):
        raise ValueError(f"Readback count mismatch: {counts}")
    for qr, source in expected.items():
        receipt = receipt_by_qr.get(qr)
        if not receipt or receipt.source_checksum != payload_checksum(source) or receipt.source_payload != canonical_payload(source):
            raise ValueError(f"{qr}: receipt evidence mismatch")
        package = package_by_receipt.get(receipt.id)
        model_id = resolved[qr].id
        if (
            not package or package.model_id != model_id or package.total_quantity != source["quantity"]
            or package.warehouse_id != EXPECTED_WAREHOUSE_ID or package.status != "received_in_storage"
            or package.barcode.casefold() != qr or package.package_no != package_number(qr)
        ):
            raise ValueError(f"{qr}: package mismatch")
        if source["weight_kg"] is None:
            if package.weight_kg is not None:
                raise ValueError(f"{qr}: blank package weight was not preserved")
        elif Decimal(str(package.weight_kg)) != Decimal(source["weight_kg"]):
            raise ValueError(f"{qr}: package weight mismatch")
        item, stock, alias, scan = (maps[key].get(package.id) for key in ("item", "stock", "alias", "scan"))
        if not item or item.model_id != model_id or item.quantity != source["quantity"] or item.size != "ASSORTED":
            raise ValueError(f"{qr}: item mismatch")
        if (
            not stock or stock.available_qty != source["quantity"] or stock.reserved_qty != 0
            or stock.sold_qty != 0 or stock.status != "available"
        ):
            raise ValueError(f"{qr}: stock mismatch")
        if not alias or alias.code.casefold() != qr or alias.code_type != "legacy_sticker_qr":
            raise ValueError(f"{qr}: QR alias mismatch")
        if not scan or scan.scan_type != "legacy_sticker_import" or scan.scanned_by != importer_id:
            raise ValueError(f"{qr}: scan evidence mismatch")
    return {
        **counts,
        "quantity": sum(row.total_quantity for row in packages),
        "available_quantity": sum(row.available_qty for row in stocks),
        "known_weight_kg": str(sum(
            (Decimal(str(row.weight_kg)) for row in packages if row.weight_kg is not None), Decimal("0")
        )),
        "null_weight_rows": sum(row.weight_kg is None for row in packages),
        "unique_models": len({row.model_id for row in packages}),
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    payload, rows = read_manifest(args.input, args.photo_root, args.expected_manifest_sha256)
    with SessionLocal() as db:
        warehouse, importer = assert_target_guard(db, args)
        resolved = resolve_all(db, rows, int(payload["expected_unique_identities"]))
        base = {
            "mode": args.mode,
            "environment": args.environment,
            "manifest_sha256": args.expected_manifest_sha256,
            "rows": len(rows),
            "quantity": sum(row["quantity"] for row in rows),
            "known_weight_kg": payload["expected_known_weight_kg"],
            "null_weight_rows": payload["expected_null_weight_rows"],
            "unique_models": len({model.id for model in resolved.values()}),
            "warehouse": {"id": warehouse.id, "name": warehouse.name},
        }
        if args.mode == "dry-run":
            assert_zero_collisions(db, rows)
            db.rollback()
            return {**base, "planned_creates": len(rows), "collisions": 0}
        if args.mode == "verify":
            state = readback(db, rows, resolved, importer.id)
            db.rollback()
            return {**base, "state": state}
        confirmation = f"APPLY-{len(rows)}-COMPLETED-PACKS-TO-{args.environment.upper()}"
        if args.confirm != confirmation:
            raise ValueError("Apply confirmation phrase is missing or incorrect")
        assert_zero_collisions(db, rows)
        try:
            audit_id = import_rows(db, rows, resolved, warehouse, importer, args.expected_manifest_sha256)
            readback(db, rows, resolved, importer.id)
            db.commit()
        except Exception:
            db.rollback()
            raise
    with SessionLocal() as verify_db:
        assert_target_guard(verify_db, args)
        resolved = resolve_all(verify_db, rows, int(payload["expected_unique_identities"]))
        committed_state = readback(verify_db, rows, resolved, args.imported_by)
        audit = verify_db.execute(
            text("select id, action, user_id, entry_hash from audit_logs where id=:id"), {"id": audit_id}
        ).mappings().one()
        if audit["action"] != "legacy_sticker_inventory_import" or audit["user_id"] != args.imported_by or not audit["entry_hash"]:
            raise ValueError("Committed audit readback failed")
        verify_db.rollback()
    return {**base, "committed": True, "audit": dict(audit), "state": committed_state}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--photo-root", type=Path, required=True)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--expected-database-host", required=True)
    parser.add_argument("--expected-database-name", required=True)
    parser.add_argument("--environment", choices=("local", "production"), required=True)
    parser.add_argument("--imported-by", type=int, default=EXPECTED_IMPORTER_ID)
    parser.add_argument("--mode", choices=("dry-run", "apply", "verify"), default="dry-run")
    parser.add_argument("--confirm")
    return parser.parse_args()


if __name__ == "__main__":
    print(json.dumps(run(parse_args()), ensure_ascii=False, indent=2, sort_keys=True))
