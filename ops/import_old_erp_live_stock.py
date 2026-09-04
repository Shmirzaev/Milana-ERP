"""Guarded, transactional import of live-audited UZERP finished-goods packages.

Dry-run is the default. Apply requires an exact confirmation phrase, validates
the target database and immutable evidence, rejects every identifier collision,
and commits all packages in one transaction.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
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
    ModelSize,
    Package,
    PackageBarcodeAlias,
    PackageItem,
    PackageScanLog,
    User,
    Warehouse,
)
from app.services.audit import log_action


SOURCE_SYSTEM = "UZERP_LIVE_STOCK"
SOURCE_WAREHOUSE_ID = "18"
SOURCE_WAREHOUSE_NAME = "TAYYOR MAHSULOT OMBORI"
EXPECTED_ALEMBIC_HEAD = "0113_variant_selling_price"
EXPECTED_WAREHOUSE_ID = 8
EXPECTED_WAREHOUSE_NAME = "Finished Goods"
EXPECTED_WAREHOUSE_TYPE = "finished_goods"
EXPECTED_IMPORTER_ID = 1
QR_RE = re.compile(r"^uzerp_ii_(\d+)_1$", re.IGNORECASE)
SHA_RE = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)
QUANTITY_SOURCES = {"direct_exact_query", "exhaustive_item_barcode_report"}
CONFUSABLES = str.maketrans(
    {
        "А": "A", "В": "B", "С": "C", "Е": "E", "Н": "H", "К": "K",
        "М": "M", "О": "O", "Р": "P", "Т": "T", "Х": "X", "У": "Y",
        "І": "I", "Ј": "J",
    }
)


def clean(value: Any, *, limit: int | None = None) -> str:
    result = " ".join(unicodedata.normalize("NFKC", str(value or "")).strip().split())
    return result[:limit] if limit else result


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): canonical(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [canonical(item) for item in value]
    return value


def checksum(value: Any) -> str:
    encoded = json.dumps(canonical(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def normalized_base(value: Any) -> str:
    return "".join(ch for ch in clean(value).upper().translate(CONFUSABLES) if ch.isalnum())


def normalized_variant(value: Any) -> str:
    value = re.sub(r"^V[\s_-]*", "", clean(value).upper().translate(CONFUSABLES), count=1)
    token = "".join(ch for ch in value if ch.isalnum())
    return str(int(token)) if token.isdigit() else token


def item_identity(item: dict[str, Any]) -> tuple[str, str]:
    return normalized_base(item["model_number"]), normalized_variant(item["variant_number"])


def model_identity(model: Model) -> tuple[str, str]:
    details = model.details_json if isinstance(model.details_json, dict) else {}
    general = details.get("general") if isinstance(details.get("general"), dict) else {}
    return (
        normalized_base(general.get("model_no") or general.get("modelNo")),
        normalized_variant(general.get("variant_no") or general.get("variantNo")),
    )


def hidden_model_code(identity: tuple[str, str]) -> str:
    digest = hashlib.sha256("\0".join(identity).encode("utf-8")).hexdigest()[:16].upper()
    return f"LEGACY-STICKER-{digest}"


def validate_hidden_model(model: Model, identity: tuple[str, str]) -> None:
    details = model.details_json if isinstance(model.details_json, dict) else {}
    if details.get("legacy_import") is not True or model_identity(model) != identity:
        raise ValueError(f"Hidden legacy model guard failed for {model.code}")
    if clean(model.status).casefold() != "approved":
        raise ValueError(f"Hidden legacy model {model.code} is not approved")


def validate_item(raw: dict[str, Any], source_record_id: str) -> dict[str, Any]:
    item = canonical(dict(raw))
    item["model_number"] = clean(item.get("model_number"), limit=64)
    item["variant_number"] = clean(item.get("variant_number"), limit=64)
    item["size"] = clean(item.get("size"), limit=32)
    item["expected_model_code"] = clean(item.get("expected_model_code"), limit=64)
    try:
        item["quantity"] = int(item.get("quantity"))
    except (TypeError, ValueError):
        raise ValueError(f"{source_record_id}: item quantity is not a whole number") from None
    if not item["model_number"] or not item["variant_number"] or not item["size"] or item["quantity"] <= 0:
        raise ValueError(f"{source_record_id}: item identity, size, or quantity is invalid")
    if item.get("target_kind") not in {"catalog", "hidden_legacy"}:
        raise ValueError(f"{source_record_id}: invalid item target kind")
    if item["target_kind"] == "catalog":
        if not isinstance(item.get("expected_model_id"), int) or item["expected_model_id"] <= 0:
            raise ValueError(f"{source_record_id}: catalog item lacks an expected model ID")
        if not item["expected_model_code"]:
            raise ValueError(f"{source_record_id}: catalog item lacks an expected model code")
    elif item.get("expected_model_id") is not None or item["expected_model_code"]:
        raise ValueError(f"{source_record_id}: hidden item unexpectedly names a catalog target")
    return item


def validate_row(raw: dict[str, Any]) -> dict[str, Any]:
    row = canonical(dict(raw))
    source_record_id = clean(row.get("source_record_id"), limit=128)
    external_qr = clean(row.get("external_qr"), limit=64)
    qr_code = clean(row.get("qr_code"), limit=64).casefold()
    package_no = clean(row.get("package_no"), limit=64)
    if not source_record_id.isdigit() or external_qr != source_record_id:
        raise ValueError(f"Invalid source record {source_record_id!r}")
    match = QR_RE.fullmatch(qr_code)
    if not match or match.group(1) != external_qr:
        raise ValueError(f"{source_record_id}: QR code does not encode the external QR")
    if package_no != f"OLD-{external_qr}-1":
        raise ValueError(f"{source_record_id}: package number is not canonical")
    try:
        quantity = int(row.get("quantity"))
        candidate_quantity = int(row.get("candidate_quantity"))
        exhaustive_quantity = int(row.get("exhaustive_quantity"))
    except (TypeError, ValueError):
        raise ValueError(f"{source_record_id}: invalid package quantity") from None
    if quantity <= 0 or candidate_quantity <= 0 or exhaustive_quantity <= 0:
        raise ValueError(f"{source_record_id}: package quantity must be positive")
    quantity_source = clean(row.get("quantity_source"), limit=64)
    if quantity_source not in QUANTITY_SOURCES:
        raise ValueError(f"{source_record_id}: invalid quantity source")
    if quantity_source == "exhaustive_item_barcode_report" and quantity != exhaustive_quantity:
        raise ValueError(f"{source_record_id}: exhaustive quantity source does not match package quantity")
    if row.get("quantity_corrected_from_live_query") is not (quantity != candidate_quantity):
        raise ValueError(f"{source_record_id}: corrected-quantity flag is inconsistent")
    if row.get("weight_kg") is not None or row.get("allowed_blank_weight") is not True:
        raise ValueError(f"{source_record_id}: the approved blank-weight rule was not preserved")
    items = [validate_item(dict(item), source_record_id) for item in row.get("items") or []]
    if not items or sum(item["quantity"] for item in items) != quantity:
        raise ValueError(f"{source_record_id}: item rows do not equal package quantity")
    keys = [(item_identity(item), item["size"].casefold()) for item in items]
    if len(keys) != len(set(keys)):
        raise ValueError(f"{source_record_id}: duplicate model/size item row")
    return {
        **row,
        "source_record_id": source_record_id,
        "external_qr": external_qr,
        "qr_code": qr_code,
        "package_no": package_no,
        "quantity": quantity,
        "candidate_quantity": candidate_quantity,
        "exhaustive_quantity": exhaustive_quantity,
        "quantity_source": quantity_source,
        "color": clean(row.get("color"), limit=64) or "Not specified",
        "items": items,
    }


def read_manifest(path: Path, expected_hash: str, evidence_root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    actual_hash = sha256(path)
    if actual_hash != expected_hash:
        raise ValueError(f"Manifest SHA-256 changed: {actual_hash}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    fixed = {
        "version": 1,
        "source_system": SOURCE_SYSTEM,
        "source_warehouse_id": SOURCE_WAREHOUSE_ID,
        "source_warehouse_name": SOURCE_WAREHOUSE_NAME,
        "destination_warehouse_id": EXPECTED_WAREHOUSE_ID,
        "destination_warehouse_name": EXPECTED_WAREHOUSE_NAME,
    }
    for key, value in fixed.items():
        if payload.get(key) != value:
            raise ValueError(f"Manifest guard failed for {key}")
    for entry in payload.get("source_files", {}).values():
        name = clean(entry.get("name"), limit=255)
        digest = clean(entry.get("sha256"), limit=64).casefold()
        candidate = (evidence_root.resolve() / name).resolve()
        if candidate.parent != evidence_root.resolve() or not SHA_RE.fullmatch(digest):
            raise ValueError(f"Unsafe evidence path {name!r}")
        if not candidate.is_file() or sha256(candidate) != digest:
            raise ValueError(f"Evidence file is missing or changed: {name}")
    rows = [validate_row(dict(row)) for row in payload.get("rows") or []]
    record_ids = [row["source_record_id"] for row in rows]
    qrs = [row["qr_code"] for row in rows]
    package_nos = [row["package_no"] for row in rows]
    if len(record_ids) != len(set(record_ids)) or len(qrs) != len(set(qrs)) or len(package_nos) != len(set(package_nos)):
        raise ValueError("Manifest repeats a package identifier")
    expected = {
        "expected_packages": len(rows),
        "expected_quantity": sum(row["quantity"] for row in rows),
        "expected_item_rows": sum(len(row["items"]) for row in rows),
        "expected_corrected_quantity_packages": sum(row["quantity_corrected_from_live_query"] for row in rows),
        "expected_hidden_legacy_items": sum(
            item["target_kind"] == "hidden_legacy" for row in rows for item in row["items"]
        ),
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise ValueError(f"Manifest summary mismatch for {key}: {payload.get(key)!r} != {value!r}")
    held_ids = [clean(row.get("external_qr"), limit=64) for row in payload.get("held_packages") or []]
    if len(held_ids) != len(set(held_ids)) or set(held_ids) & set(record_ids):
        raise ValueError("Held package records overlap or repeat imported package records")
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


def create_hidden_model(db, identity: tuple[str, str], example: dict[str, Any], importer: User) -> Model:
    code = hidden_model_code(identity)
    model = Model(
        code=code,
        name=f"{example['model_number']} / {example['variant_number']}",
        category="Legacy finished goods",
        description="Warehouse-only identity created from a live old-ERP stock audit.",
        details_json={
            "legacy_import": True,
            "legacy_source_system": SOURCE_SYSTEM,
            "general": {
                "model_no": example["model_number"],
                "variant_no": example["variant_number"],
            },
        },
        status="approved",
        created_by=importer.id,
        approved_by=importer.id,
        approved_at=datetime.now(timezone.utc),
    )
    db.add(model)
    db.flush()
    validate_hidden_model(model, identity)
    return model


def resolve_models(db, rows: list[dict[str, Any]], *, apply: bool, importer: User) -> tuple[dict[tuple[str, str], Model], int]:
    examples: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        for item in row["items"]:
            examples.setdefault(item_identity(item), item)
    resolved: dict[tuple[str, str], Model] = {}
    created = 0
    for identity, example in examples.items():
        if example["target_kind"] == "catalog":
            model = db.get(Model, example["expected_model_id"])
            if (
                not model
                or model.code != example["expected_model_code"]
                or model_identity(model) != identity
                or clean(model.status).casefold() != "approved"
            ):
                raise ValueError(f"Catalog model guard failed for {identity}")
        else:
            code = hidden_model_code(identity)
            model = db.query(Model).filter(func.lower(Model.code) == code.casefold()).one_or_none()
            if model:
                validate_hidden_model(model, identity)
            elif apply:
                model = create_hidden_model(db, identity, example, importer)
                created += 1
            else:
                model = None
        if model:
            resolved[identity] = model
    return resolved, created


def collision_counts(db, rows: list[dict[str, Any]]) -> dict[str, int]:
    record_ids = [row["source_record_id"] for row in rows]
    qrs = [row["qr_code"] for row in rows]
    numeric_qrs = [row["external_qr"] for row in rows]
    package_nos = [row["package_no"] for row in rows]
    all_codes = qrs + numeric_qrs + package_nos
    return {
        "receipts": db.query(LegacyStockReceipt).filter(
            LegacyStockReceipt.source_system == SOURCE_SYSTEM,
            LegacyStockReceipt.source_warehouse_id == SOURCE_WAREHOUSE_ID,
            LegacyStockReceipt.source_record_id.in_(record_ids),
        ).count(),
        "package_barcodes": db.query(Package).filter(Package.barcode.in_(all_codes)).count(),
        "package_numbers": db.query(Package).filter(Package.package_no.in_(all_codes)).count(),
        "aliases": db.query(PackageBarcodeAlias).filter(PackageBarcodeAlias.code.in_(all_codes)).count(),
    }


def assert_zero_collisions(db, rows: list[dict[str, Any]]) -> None:
    counts = collision_counts(db, rows)
    if any(counts.values()):
        raise ValueError(f"Target identifiers are not empty: {counts}")


def import_rows(db, rows: list[dict[str, Any]], models: dict[tuple[str, str], Model], warehouse: Warehouse, importer: User, manifest_hash: str) -> tuple[int, int]:
    now = datetime.now(timezone.utc)
    known_sizes = {
        (int(model_id), clean(size).casefold())
        for model_id, size in db.query(ModelSize.model_id, ModelSize.size).all()
    }
    created_sizes = 0
    for row in rows:
        item_models = [(item, models[item_identity(item)]) for item in row["items"]]
        primary = max(item_models, key=lambda pair: pair[0]["quantity"])[1]
        receipt = LegacyStockReceipt(
            source_system=SOURCE_SYSTEM,
            source_warehouse_id=SOURCE_WAREHOUSE_ID,
            source_warehouse_name=SOURCE_WAREHOUSE_NAME,
            source_record_id=row["source_record_id"],
            source_checksum=checksum(row),
            source_payload=canonical(row),
            imported_by=importer.id,
        )
        db.add(receipt)
        db.flush()
        package = Package(
            package_no=row["package_no"],
            barcode=row["qr_code"],
            legacy_receipt_id=receipt.id,
            model_id=primary.id,
            brand_id=primary.brand_id,
            collection_id=primary.collection_id,
            color=row["color"],
            package_type="legacy_stock",
            total_quantity=row["quantity"],
            capacity=max(60, row["quantity"]),
            weight_kg=None,
            warehouse_id=warehouse.id,
            status="received_in_storage",
            received_by=importer.id,
            received_at=now,
            notes="Imported from the live old-ERP finished-goods stock audit dated 2026-09-04.",
        )
        db.add(package)
        db.flush()
        for item, model in item_models:
            db.add(
                PackageItem(
                    package_id=package.id,
                    model_id=model.id,
                    color=row["color"],
                    size=item["size"],
                    quantity=item["quantity"],
                )
            )
            db.add(
                FinishedGoodsStock(
                    package_id=package.id,
                    model_id=model.id,
                    brand_id=model.brand_id,
                    collection_id=model.collection_id,
                    color=row["color"],
                    size=item["size"],
                    quantity=item["quantity"],
                    available_qty=item["quantity"],
                    reserved_qty=0,
                    sold_qty=0,
                    cost_per_piece=0,
                    selling_price=0,
                    warehouse_id=warehouse.id,
                    status="available",
                )
            )
            size_key = (int(model.id), item["size"].casefold())
            if size_key not in known_sizes:
                db.add(ModelSize(model_id=model.id, size=item["size"]))
                known_sizes.add(size_key)
                created_sizes += 1
        db.add_all(
            [
                PackageBarcodeAlias(package_id=package.id, code=row["external_qr"], code_type="legacy_external_qr"),
                PackageScanLog(
                    package_id=package.id,
                    scanned_by=importer.id,
                    scan_type="legacy_live_stock_import",
                    location=SOURCE_WAREHOUSE_NAME,
                ),
            ]
        )
    db.flush()
    audit = log_action(
        db,
        importer,
        "legacy_live_stock_import",
        "LegacyStockReceipt",
        None,
        new_value={
            "manifest_sha256": manifest_hash,
            "packages": len(rows),
            "quantity": sum(row["quantity"] for row in rows),
            "item_rows": sum(len(row["items"]) for row in rows),
            "corrected_quantity_packages": sum(row["quantity_corrected_from_live_query"] for row in rows),
            "warehouse_id": warehouse.id,
            "source_system": SOURCE_SYSTEM,
        },
    )
    return int(audit.id), created_sizes


def readback(db, rows: list[dict[str, Any]], models: dict[tuple[str, str], Model], importer_id: int) -> dict[str, Any]:
    record_ids = [row["source_record_id"] for row in rows]
    receipts = db.query(LegacyStockReceipt).filter(
        LegacyStockReceipt.source_system == SOURCE_SYSTEM,
        LegacyStockReceipt.source_warehouse_id == SOURCE_WAREHOUSE_ID,
        LegacyStockReceipt.source_record_id.in_(record_ids),
    ).all()
    receipt_by_record = {receipt.source_record_id: receipt for receipt in receipts}
    packages = db.query(Package).filter(Package.legacy_receipt_id.in_([r.id for r in receipts] or [-1])).all()
    package_by_receipt = {package.legacy_receipt_id: package for package in packages}
    package_ids = [package.id for package in packages]
    items = db.query(PackageItem).filter(PackageItem.package_id.in_(package_ids or [-1])).all()
    stocks = db.query(FinishedGoodsStock).filter(FinishedGoodsStock.package_id.in_(package_ids or [-1])).all()
    aliases = db.query(PackageBarcodeAlias).filter(PackageBarcodeAlias.package_id.in_(package_ids or [-1])).all()
    scans = db.query(PackageScanLog).filter(PackageScanLog.package_id.in_(package_ids or [-1])).all()
    items_by_package: dict[int, list[PackageItem]] = defaultdict(list)
    stocks_by_package: dict[int, list[FinishedGoodsStock]] = defaultdict(list)
    for item in items:
        items_by_package[item.package_id].append(item)
    for stock in stocks:
        stocks_by_package[stock.package_id].append(stock)
    alias_by_package = {alias.package_id: alias for alias in aliases}
    scan_by_package = {scan.package_id: scan for scan in scans}
    expected_item_rows = sum(len(row["items"]) for row in rows)
    counts = {
        "receipts": len(receipts), "packages": len(packages), "items": len(items),
        "stock_rows": len(stocks), "aliases": len(aliases), "scans": len(scans),
    }
    if counts != {
        "receipts": len(rows), "packages": len(rows), "items": expected_item_rows,
        "stock_rows": expected_item_rows, "aliases": len(rows), "scans": len(rows),
    }:
        raise ValueError(f"Readback count mismatch: {counts}")
    for row in rows:
        receipt = receipt_by_record.get(row["source_record_id"])
        if not receipt or receipt.source_checksum != checksum(row) or receipt.source_payload != canonical(row):
            raise ValueError(f"{row['source_record_id']}: receipt evidence mismatch")
        package = package_by_receipt.get(receipt.id)
        if (
            not package or package.package_no != row["package_no"] or package.barcode.casefold() != row["qr_code"]
            or package.total_quantity != row["quantity"] or package.warehouse_id != EXPECTED_WAREHOUSE_ID
            or package.status != "received_in_storage" or package.weight_kg is not None
        ):
            raise ValueError(f"{row['source_record_id']}: package mismatch")
        expected = sorted(
            (models[item_identity(item)].id, item["size"], item["quantity"]) for item in row["items"]
        )
        actual_items = sorted((item.model_id, item.size, item.quantity) for item in items_by_package[package.id])
        actual_stocks = sorted((stock.model_id, stock.size, stock.quantity) for stock in stocks_by_package[package.id])
        if actual_items != expected or actual_stocks != expected:
            raise ValueError(f"{row['source_record_id']}: package item or stock breakdown mismatch")
        for stock in stocks_by_package[package.id]:
            if stock.available_qty != stock.quantity or stock.reserved_qty != 0 or stock.sold_qty != 0 or stock.status != "available":
                raise ValueError(f"{row['source_record_id']}: stock balance mismatch")
        alias = alias_by_package.get(package.id)
        scan = scan_by_package.get(package.id)
        if not alias or alias.code != row["external_qr"] or alias.code_type != "legacy_external_qr":
            raise ValueError(f"{row['source_record_id']}: QR alias mismatch")
        if not scan or scan.scan_type != "legacy_live_stock_import" or scan.scanned_by != importer_id:
            raise ValueError(f"{row['source_record_id']}: scan evidence mismatch")
    return {
        **counts,
        "quantity": sum(package.total_quantity for package in packages),
        "available_quantity": sum(stock.available_qty for stock in stocks),
        "unique_models": len({stock.model_id for stock in stocks}),
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    payload, rows = read_manifest(args.input, args.expected_manifest_sha256, args.evidence_root)
    with SessionLocal() as db:
        warehouse, importer = assert_target_guard(db, args)
        models, created_hidden = resolve_models(db, rows, apply=args.mode == "apply", importer=importer)
        identities = {item_identity(item) for row in rows for item in row["items"]}
        unresolved = sorted(identities - set(models))
        base = {
            "mode": args.mode,
            "environment": args.environment,
            "manifest_sha256": args.expected_manifest_sha256,
            "packages": len(rows),
            "quantity": sum(row["quantity"] for row in rows),
            "item_rows": sum(len(row["items"]) for row in rows),
            "held_packages": len(payload["held_packages"]),
            "corrected_quantity_packages": sum(row["quantity_corrected_from_live_query"] for row in rows),
            "planned_hidden_model_creates": len(unresolved) if args.mode == "dry-run" else 0,
            "created_hidden_models": created_hidden,
            "warehouse": {"id": warehouse.id, "name": warehouse.name},
        }
        if args.mode == "dry-run":
            collisions = collision_counts(db, rows)
            db.rollback()
            if any(collisions.values()):
                raise ValueError(f"Target identifiers are not empty: {collisions}")
            return {**base, "planned_creates": len(rows), "collisions": collisions}
        if unresolved:
            raise ValueError(f"Unresolved model identities: {unresolved}")
        if args.mode == "verify":
            state = readback(db, rows, models, importer.id)
            db.rollback()
            return {**base, "state": state}
        confirmation = f"APPLY-{len(rows)}-UZERP-LIVE-PACKS-TO-{args.environment.upper()}"
        if args.confirm != confirmation:
            raise ValueError("Apply confirmation phrase is missing or incorrect")
        assert_zero_collisions(db, rows)
        try:
            audit_id, created_sizes = import_rows(
                db, rows, models, warehouse, importer, args.expected_manifest_sha256
            )
            readback(db, rows, models, importer.id)
            db.commit()
        except Exception:
            db.rollback()
            raise
    with SessionLocal() as verify_db:
        _, verify_importer = assert_target_guard(verify_db, args)
        models, _ = resolve_models(verify_db, rows, apply=False, importer=verify_importer)
        committed_state = readback(verify_db, rows, models, args.imported_by)
        audit = verify_db.execute(
            text("select id, action, user_id, entry_hash from audit_logs where id=:id"), {"id": audit_id}
        ).mappings().one()
        if audit["action"] != "legacy_live_stock_import" or audit["user_id"] != args.imported_by or not audit["entry_hash"]:
            raise ValueError("Committed audit readback failed")
        verify_db.rollback()
    return {**base, "committed": True, "created_model_sizes": created_sizes, "audit": dict(audit), "state": committed_state}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--expected-database-host", required=True)
    parser.add_argument("--expected-database-name", required=True)
    parser.add_argument("--environment", choices=("local", "production"), required=True)
    parser.add_argument("--imported-by", type=int, default=EXPECTED_IMPORTER_ID)
    parser.add_argument("--mode", choices=("dry-run", "apply", "verify"), default="dry-run")
    parser.add_argument("--confirm")
    return parser.parse_args()


if __name__ == "__main__":
    print(json.dumps(run(parse_args()), ensure_ascii=False, indent=2, sort_keys=True, default=str))
