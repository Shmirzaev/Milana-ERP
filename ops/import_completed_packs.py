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
        "А": "A",
        "В": "B",
        "С": "C",
        "Е": "E",
        "Н": "H",
        "К": "K",
        "М": "M",
        "О": "O",
        "Р": "P",
        "Т": "T",
        "Х": "X",
        "У": "Y",
        "І": "I",
        "Ј": "J",
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
    return f"OLD-{match.group(1)}-{match.group(2)}" if match.group(1) and match.group(2) else f"OLD-{match.group(3)}"


def row_key(row: dict[str, Any]) -> str:
    return clean(row.get("record_key") or row.get("qr_code"), limit=128).casefold()


def row_package_barcode(row: dict[str, Any]) -> str:
    return clean(row.get("package_barcode") or row.get("qr_code"), limit=64).casefold()


def row_has_source_qr(row: dict[str, Any]) -> bool:
    return bool(clean(row.get("qr_code")))


def row_package_number(row: dict[str, Any]) -> str:
    supplied = clean(row.get("package_no"), limit=64)
    return supplied or package_number(clean(row.get("qr_code"), limit=128).casefold())


def validate_row(row: dict[str, Any], photo_root: Path, *, manifest_version: int = 2) -> dict[str, Any]:
    qr = clean(row.get("qr_code"), limit=128).casefold()
    key = row_key(row)
    package_barcode = row_package_barcode(row)
    package_no = row_package_number(row) if (manifest_version >= 3 or qr) else ""
    has_source_qr = bool(qr)
    if manifest_version < 3 and not QR_RE.fullmatch(qr):
        raise ValueError(f"Invalid old sticker QR: {qr!r}")
    if manifest_version >= 3:
        if not key or not package_barcode or not package_no:
            raise ValueError("Version 3 rows require record_key, package_barcode, and package_no")
        if row.get("has_source_qr") is not has_source_qr:
            raise ValueError(f"{key}: has_source_qr does not match qr_code")
    model_number = clean(row.get("model_number"))
    article = clean(row.get("article"))
    try:
        quantity = int(row.get("quantity"))
    except (TypeError, ValueError):
        raise ValueError(f"{key}: quantity is not a whole number") from None
    if quantity <= 0:
        raise ValueError(f"{key}: quantity must be positive")
    raw_weight = row.get("weight_kg")
    weight = None if raw_weight in (None, "") else Decimal(clean(raw_weight).replace(",", "."))
    if weight is not None and weight <= 0:
        raise ValueError(f"{key}: weight must be positive")
    if weight is None and row.get("allowed_blank_weight") is not True:
        raise ValueError(f"{key}: blank weight lacks explicit user approval")
    if weight is not None and row.get("allowed_blank_weight") is True:
        raise ValueError(f"{key}: blank-weight exception conflicts with supplied weight")
    sizes = [clean(value, limit=32) for value in row.get("sizes") or [] if clean(value)]
    if not sizes and not (manifest_version >= 3 and row.get("allowed_blank_sizes") is True):
        raise ValueError(f"{key}: sizes are blank")
    photo_name = clean(row.get("source_photo"), limit=255)
    photo_hash = clean(row.get("source_photo_sha256"), limit=64).casefold()
    if not photo_name or not SHA_RE.fullmatch(photo_hash):
        raise ValueError(f"{key}: source photo evidence is incomplete")
    root = photo_root.resolve()
    photo_path = (root / photo_name).resolve()
    if photo_path.parent != root or not photo_path.is_file() or file_sha256(photo_path) != photo_hash:
        raise ValueError(f"{key}: source photo is missing, unsafe, or changed")
    if clean(row.get("review_status")).casefold() != "approved":
        raise ValueError(f"{key}: row is not explicitly approved")
    target_kind = clean(row.get("target_kind") or "catalog").casefold()
    if target_kind not in {"catalog", "hidden_legacy"}:
        raise ValueError(f"{key}: unsupported target_kind {target_kind!r}")
    if target_kind == "catalog" and (not model_number or not article):
        raise ValueError(f"{key}: catalog model or variant is blank")
    original_model_number = clean(row.get("original_model_number") or model_number)
    original_article = clean(row.get("original_article") or article)
    if manifest_version < 3 and target_kind == "hidden_legacy" and (not original_model_number or not original_article):
        raise ValueError(f"{key}: hidden legacy identity is incomplete")
    validated = {
        **canonical_payload(row),
        "qr_code": qr,
        "model_number": model_number,
        "article": article,
        "quantity": quantity,
        "weight_kg": str(weight) if weight is not None else None,
        "sizes": sizes,
        "source_photo": photo_name,
        "source_photo_sha256": photo_hash,
        "target_kind": target_kind,
        "original_model_number": original_model_number,
        "original_article": original_article,
    }
    if manifest_version >= 3:
        validated.update(
            {
                "record_key": key,
                "qr_code": qr or None,
                "has_source_qr": has_source_qr,
                "package_barcode": package_barcode,
                "package_no": package_no,
            }
        )
    return validated


def read_manifest(path: Path, photo_root: Path, expected_hash: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    actual_hash = file_sha256(path)
    if actual_hash != expected_hash:
        raise ValueError(f"Manifest SHA-256 changed: {actual_hash}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("version") not in {1, 2, 3} or not isinstance(payload.get("rows"), list):
        raise ValueError("Manifest must be a supported version object with rows")
    version = int(payload["version"])
    rows = [validate_row(dict(row), photo_root, manifest_version=version) for row in payload["rows"]]
    keys = [row_key(row) for row in rows]
    barcodes = [row_package_barcode(row) for row in rows]
    package_nos = [row_package_number(row) for row in rows]
    qrs = [row["qr_code"] for row in rows if row_has_source_qr(row)]
    if len(keys) != len(set(keys)):
        raise ValueError("Manifest repeats record keys")
    if len(barcodes) != len(set(barcodes)) or len(package_nos) != len(set(package_nos)):
        raise ValueError("Manifest repeats package identifiers")
    if len(qrs) != len(set(qrs)):
        raise ValueError("Manifest repeats source QR values")
    expected = {
        "expected_rows": len(rows),
        "expected_quantity": sum(row["quantity"] for row in rows),
        "expected_known_weight_kg": str(
            sum((Decimal(row["weight_kg"]) for row in rows if row["weight_kg"] is not None), Decimal("0"))
        ),
        "expected_null_weight_rows": sum(row["weight_kg"] is None for row in rows),
        "expected_unique_identities": len(
            {
                (
                    row["target_kind"],
                    normalized_base(row["model_number"]),
                    normalized_variant(row["article"]),
                )
                for row in rows
            }
        ),
    }
    for key, value in expected.items():
        if str(payload.get(key)) != str(value):
            raise ValueError(f"Manifest summary mismatch for {key}: expected {value!r}, found {payload.get(key)!r}")
    if version >= 3:
        extended = {
            "expected_source_qr_rows": sum(row_has_source_qr(row) for row in rows),
            "expected_no_source_qr_rows": sum(not row_has_source_qr(row) for row in rows),
            "expected_default_quantity_rows": sum(row.get("quantity_defaulted") is True for row in rows),
            "expected_catalog_rows": sum(row["target_kind"] == "catalog" for row in rows),
            "expected_hidden_legacy_rows": sum(row["target_kind"] == "hidden_legacy" for row in rows),
        }
        for key, value in extended.items():
            if int(payload.get(key, -1)) != value:
                raise ValueError(f"Manifest summary mismatch for {key}: expected {value!r}, found {payload.get(key)!r}")
    return payload, rows


def assert_target_guard(db, args: argparse.Namespace) -> tuple[Warehouse, User]:
    parsed = urlparse(settings.DATABASE_URL.replace("postgresql+psycopg2://", "postgresql://", 1))
    host = (parsed.hostname or "").casefold()
    current_db = str(db.execute(text("select current_database()")).scalar() or "")
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


def is_internal_legacy_model(model: Model) -> bool:
    details = model.details_json if isinstance(model.details_json, dict) else {}
    return details.get("legacy_import") is True


def hidden_model_code(row: dict[str, Any]) -> str:
    identity = "\0".join(
        (
            normalized_base(row["original_model_number"]) or "<MISSING-MODEL>",
            normalized_variant(row["original_article"]) or "<MISSING-VARIANT>",
        )
    )
    return f"LEGACY-STICKER-{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:16].upper()}"


def validate_hidden_model(model: Model, row: dict[str, Any]) -> None:
    details = model.details_json if isinstance(model.details_json, dict) else {}
    general = details.get("general") if isinstance(details.get("general"), dict) else {}
    expected_identity = (
        normalized_base(row["original_model_number"]),
        normalized_variant(row["original_article"]),
    )
    actual_identity = (
        normalized_base(general.get("model_no") or details.get("legacy_original_model_no")),
        normalized_variant(general.get("variant_no") or details.get("legacy_original_variant_no")),
    )
    if (
        details.get("legacy_import") is not True
        or actual_identity != expected_identity
        or clean(model.status).casefold() != "approved"
    ):
        raise ValueError(f"{row['qr_code']}: hidden model guard failed for {model.code}")


def create_hidden_model(db, row: dict[str, Any], importer: User) -> Model:
    model_label = row["original_model_number"] or "Unknown model"
    variant_label = row["original_article"] or "Unknown variant"
    model = Model(
        code=hidden_model_code(row),
        name=f"{model_label} / {variant_label}",
        category="Legacy finished goods",
        description="Warehouse-only model created from unresolved old-ERP sticker evidence.",
        details_json={
            "legacy_import": True,
            "legacy_source_system": SOURCE_SYSTEM,
            "legacy_first_source_record_id": row_key(row),
            "legacy_original_model_no": row["original_model_number"],
            "legacy_original_variant_no": row["original_article"],
            "general": {
                "model_no": row["original_model_number"],
                "variant_no": row["original_article"],
            },
        },
        status="approved",
        created_by=importer.id,
        approved_by=importer.id,
        approved_at=datetime.now(timezone.utc),
    )
    db.add(model)
    db.flush()
    validate_hidden_model(model, row)
    return model


def resolve_all(
    db,
    rows: list[dict[str, Any]],
    expected_unique: int,
    *,
    importer: User | None = None,
    create_hidden: bool = False,
) -> tuple[dict[str, Model], int]:
    by_identity: dict[tuple[str, str], list[Model]] = {}
    hidden_by_code: dict[str, Model] = {}
    for model in db.query(Model).all():
        if is_internal_legacy_model(model):
            hidden_by_code[model.code.casefold()] = model
        else:
            by_identity.setdefault(model_identity(model), []).append(model)
    resolved: dict[str, Model] = {}
    created_hidden = 0
    for row in rows:
        if row["target_kind"] == "hidden_legacy":
            code = hidden_model_code(row)
            model = hidden_by_code.get(code.casefold())
            if model:
                validate_hidden_model(model, row)
            elif create_hidden:
                if importer is None:
                    raise ValueError("Importer is required to create hidden models")
                model = create_hidden_model(db, row, importer)
                hidden_by_code[code.casefold()] = model
                created_hidden += 1
            else:
                raise ValueError(f"{row['qr_code']}: hidden model {code} does not exist")
            resolved[row_key(row)] = model
            continue
        key = (normalized_base(row["model_number"]), normalized_variant(row["article"]))
        matches = by_identity.get(key, [])
        if len(matches) != 1 or clean(matches[0].status).casefold() != "approved":
            raise ValueError(f"{row_key(row)}: expected one approved catalog model for {key}, found {len(matches)}")
        resolved[row_key(row)] = matches[0]
    if len({model.id for model in resolved.values()}) != expected_unique:
        raise ValueError("Resolved unique model count changed")
    return resolved, created_hidden


def count_planned_hidden_models(db, rows: list[dict[str, Any]]) -> tuple[int, int]:
    unique_rows: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row["target_kind"] == "hidden_legacy":
            unique_rows.setdefault(hidden_model_code(row), row)
    existing = {
        model.code.casefold(): model
        for model in db.query(Model).all()
        if model.code.casefold() in {code.casefold() for code in unique_rows}
    }
    for code, row in unique_rows.items():
        model = existing.get(code.casefold())
        if model:
            validate_hidden_model(model, row)
    return len(unique_rows) - len(existing), len(existing)


def assert_zero_collisions(db, rows: list[dict[str, Any]]) -> None:
    keys = [row_key(row) for row in rows]
    qrs = [row["qr_code"] for row in rows if row_has_source_qr(row)]
    barcodes = [row_package_barcode(row) for row in rows]
    package_nos = [row_package_number(row) for row in rows]
    counts = {
        "receipts": db.query(LegacyStockReceipt)
        .filter(
            LegacyStockReceipt.source_system == SOURCE_SYSTEM,
            LegacyStockReceipt.source_warehouse_id == SOURCE_WAREHOUSE_ID,
            func.lower(LegacyStockReceipt.source_record_id).in_(keys),
        )
        .count(),
        "barcodes": db.query(Package).filter(func.lower(Package.barcode).in_(barcodes)).count(),
        "package_nos": db.query(Package).filter(Package.package_no.in_(package_nos)).count(),
        "aliases": db.query(PackageBarcodeAlias).filter(func.lower(PackageBarcodeAlias.code).in_(qrs)).count(),
    }
    if any(counts.values()):
        raise ValueError(f"Target identifiers are not empty: {counts}")


def import_rows(db, rows, resolved, warehouse, importer, manifest_hash: str) -> int:
    now = datetime.now(timezone.utc)
    for row in rows:
        key = row_key(row)
        model = resolved[key]
        color = clean(row.get("color"), limit=64) or "Not specified"
        receipt = LegacyStockReceipt(
            source_system=SOURCE_SYSTEM,
            source_warehouse_id=SOURCE_WAREHOUSE_ID,
            source_warehouse_name=SOURCE_WAREHOUSE_NAME,
            source_record_id=key,
            source_checksum=payload_checksum(row),
            source_payload=canonical_payload(row),
            imported_by=importer.id,
        )
        db.add(receipt)
        db.flush()
        package = Package(
            package_no=row_package_number(row),
            barcode=row_package_barcode(row),
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
        linked_rows = [
            PackageItem(
                package_id=package.id,
                model_id=model.id,
                color=color,
                size="ASSORTED",
                quantity=row["quantity"],
            ),
            FinishedGoodsStock(
                package_id=package.id,
                model_id=model.id,
                brand_id=model.brand_id,
                collection_id=model.collection_id,
                color=color,
                size="ASSORTED",
                quantity=row["quantity"],
                available_qty=row["quantity"],
                reserved_qty=0,
                sold_qty=0,
                cost_per_piece=0,
                selling_price=0,
                warehouse_id=warehouse.id,
                status="available",
            ),
            PackageScanLog(
                package_id=package.id,
                scanned_by=importer.id,
                scan_type="legacy_sticker_import",
                location=None,
            ),
        ]
        if row_has_source_qr(row):
            linked_rows.append(
                PackageBarcodeAlias(
                    package_id=package.id,
                    code=row["qr_code"],
                    code_type="legacy_sticker_qr",
                )
            )
        db.add_all(linked_rows)
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
            "catalog_rows": sum(row["target_kind"] == "catalog" for row in rows),
            "hidden_legacy_rows": sum(row["target_kind"] == "hidden_legacy" for row in rows),
            "source_qr_rows": sum(row_has_source_qr(row) for row in rows),
            "no_source_qr_rows": sum(not row_has_source_qr(row) for row in rows),
            "default_quantity_rows": sum(row.get("quantity_defaulted") is True for row in rows),
            "warehouse_id": warehouse.id,
            "source_system": SOURCE_SYSTEM,
            "source_workbook_sha256": rows[0]["source_workbook_sha256"] if rows else None,
        },
    )
    return int(audit.id)


def readback(db, rows, resolved, importer_id: int) -> dict[str, Any]:
    expected = {row_key(row): row for row in rows}
    keys = list(expected)
    receipts = (
        db.query(LegacyStockReceipt)
        .filter(
            LegacyStockReceipt.source_system == SOURCE_SYSTEM,
            LegacyStockReceipt.source_warehouse_id == SOURCE_WAREHOUSE_ID,
            func.lower(LegacyStockReceipt.source_record_id).in_(keys),
        )
        .all()
    )
    receipt_by_qr = {row.source_record_id.casefold(): row for row in receipts}
    packages = db.query(Package).filter(Package.legacy_receipt_id.in_([row.id for row in receipts] or [-1])).all()
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
    expected_aliases = sum(row_has_source_qr(row) for row in rows)
    counts = {
        "receipts": len(receipts),
        "packages": len(packages),
        "items": len(items),
        "stock_rows": len(stocks),
        "aliases": len(aliases),
        "scans": len(scans),
    }
    if any(counts[name] != len(rows) for name in ("receipts", "packages", "items", "stock_rows", "scans")):
        raise ValueError(f"Readback count mismatch: {counts}")
    if counts["aliases"] != expected_aliases:
        raise ValueError(f"Readback alias count mismatch: {counts['aliases']} != {expected_aliases}")
    for key, source in expected.items():
        receipt = receipt_by_qr.get(key)
        if (
            not receipt
            or receipt.source_checksum != payload_checksum(source)
            or receipt.source_payload != canonical_payload(source)
        ):
            raise ValueError(f"{key}: receipt evidence mismatch")
        package = package_by_receipt.get(receipt.id)
        model_id = resolved[key].id
        if (
            not package
            or package.model_id != model_id
            or package.total_quantity != source["quantity"]
            or package.warehouse_id != EXPECTED_WAREHOUSE_ID
            or package.status != "received_in_storage"
            or package.barcode.casefold() != row_package_barcode(source)
            or package.package_no != row_package_number(source)
        ):
            raise ValueError(f"{key}: package mismatch")
        if source["weight_kg"] is None:
            if package.weight_kg is not None:
                raise ValueError(f"{key}: blank package weight was not preserved")
        elif Decimal(str(package.weight_kg)) != Decimal(source["weight_kg"]):
            raise ValueError(f"{key}: package weight mismatch")
        item, stock, alias, scan = (maps[key].get(package.id) for key in ("item", "stock", "alias", "scan"))
        if not item or item.model_id != model_id or item.quantity != source["quantity"] or item.size != "ASSORTED":
            raise ValueError(f"{key}: item mismatch")
        if (
            not stock
            or stock.available_qty != source["quantity"]
            or stock.reserved_qty != 0
            or stock.sold_qty != 0
            or stock.status != "available"
        ):
            raise ValueError(f"{key}: stock mismatch")
        if row_has_source_qr(source):
            if not alias or alias.code.casefold() != source["qr_code"] or alias.code_type != "legacy_sticker_qr":
                raise ValueError(f"{key}: QR alias mismatch")
        elif alias is not None:
            raise ValueError(f"{key}: no-QR package unexpectedly has a barcode alias")
        if not scan or scan.scan_type != "legacy_sticker_import" or scan.scanned_by != importer_id:
            raise ValueError(f"{key}: scan evidence mismatch")
    return {
        **counts,
        "quantity": sum(row.total_quantity for row in packages),
        "available_quantity": sum(row.available_qty for row in stocks),
        "known_weight_kg": str(
            sum((Decimal(str(row.weight_kg)) for row in packages if row.weight_kg is not None), Decimal("0"))
        ),
        "null_weight_rows": sum(row.weight_kg is None for row in packages),
        "source_qr_rows": expected_aliases,
        "no_source_qr_rows": len(rows) - expected_aliases,
        "unique_models": len({row.model_id for row in packages}),
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    payload, rows = read_manifest(args.input, args.photo_root, args.expected_manifest_sha256)
    with SessionLocal() as db:
        warehouse, importer = assert_target_guard(db, args)
        planned_hidden, existing_hidden = count_planned_hidden_models(db, rows)
        created_hidden = 0
        if args.mode == "dry-run":
            catalog_rows = [row for row in rows if row["target_kind"] == "catalog"]
            catalog_unique = len(
                {(normalized_base(row["model_number"]), normalized_variant(row["article"])) for row in catalog_rows}
            )
            resolved, _ = resolve_all(db, catalog_rows, catalog_unique)
        else:
            resolved, created_hidden = resolve_all(
                db,
                rows,
                int(payload["expected_unique_identities"]),
                importer=importer,
                create_hidden=args.mode == "apply",
            )
        base = {
            "mode": args.mode,
            "environment": args.environment,
            "manifest_sha256": args.expected_manifest_sha256,
            "rows": len(rows),
            "quantity": sum(row["quantity"] for row in rows),
            "known_weight_kg": payload["expected_known_weight_kg"],
            "null_weight_rows": payload["expected_null_weight_rows"],
            "catalog_rows": sum(row["target_kind"] == "catalog" for row in rows),
            "hidden_legacy_rows": sum(row["target_kind"] == "hidden_legacy" for row in rows),
            "source_qr_rows": sum(row_has_source_qr(row) for row in rows),
            "no_source_qr_rows": sum(not row_has_source_qr(row) for row in rows),
            "default_quantity_rows": sum(row.get("quantity_defaulted") is True for row in rows),
            "unique_models": int(payload["expected_unique_identities"]),
            "planned_hidden_model_creates": planned_hidden,
            "existing_hidden_models": existing_hidden,
            "created_hidden_models": created_hidden,
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
        resolved, _ = resolve_all(verify_db, rows, int(payload["expected_unique_identities"]))
        committed_state = readback(verify_db, rows, resolved, args.imported_by)
        audit = (
            verify_db.execute(
                text("select id, action, user_id, entry_hash from audit_logs where id=:id"), {"id": audit_id}
            )
            .mappings()
            .one()
        )
        if (
            audit["action"] != "legacy_sticker_inventory_import"
            or audit["user_id"] != args.imported_by
            or not audit["entry_hash"]
        ):
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
