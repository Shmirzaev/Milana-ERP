"""Import reviewed old-ERP sticker photos as local finished-goods stock.

Dry-run is the default. ``--apply-local`` is deliberately refused unless the
configured database host is local/Docker. The input manifest must already have
excluded every unreadable or conflicting sticker.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

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
QR_RE = re.compile(r"^uzerp_ii_(\d+)_(\d+)$", re.IGNORECASE)
SHA_RE = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)
LOCAL_DATABASE_HOSTS = {"db", "localhost", "127.0.0.1", "::1", "host.docker.internal"}
CONFUSABLES = str.maketrans(
    {
        "\u0410": "A",
        "\u0412": "B",
        "\u0421": "C",
        "\u0415": "E",
        "\u041d": "H",
        "\u041a": "K",
        "\u041c": "M",
        "\u041e": "O",
        "\u0420": "P",
        "\u0422": "T",
        "\u0425": "X",
        "\u0423": "Y",
        "\u0406": "I",
        "\u0408": "J",
    }
)


def clean(value: Any, *, limit: int | None = None) -> str:
    text = " ".join(unicodedata.normalize("NFKC", str(value or "")).strip().split())
    return text[:limit] if limit else text


def canonical_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {str(key): row[key] for key in sorted(row)}


def payload_checksum(row: dict[str, Any]) -> str:
    encoded = json.dumps(canonical_payload(row), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalized_base(value: Any) -> str:
    return "".join(character for character in clean(value).upper().translate(CONFUSABLES) if character.isalnum())


def normalized_variant(value: Any) -> str:
    text = re.sub(r"^V[\s_-]*", "", clean(value).upper().translate(CONFUSABLES), count=1)
    key = "".join(character for character in text if character.isalnum())
    return str(int(key)) if key.isdigit() else key


def model_identity(model: Model) -> tuple[str, str]:
    details = model.details_json if isinstance(model.details_json, dict) else {}
    general = details.get("general") if isinstance(details.get("general"), dict) else {}
    model_no = general.get("model_no") or general.get("modelNo")
    variant_no = general.get("variant_no") or general.get("variantNo")
    return normalized_base(model_no), normalized_variant(variant_no)


def resolve_model(models: list[Model], row: dict[str, Any]) -> Model:
    expected = (normalized_base(row["model_number"]), normalized_variant(row["article"]))
    matches = [model for model in models if model_identity(model) == expected]
    if not matches:
        combined = normalized_base(f"{row['model_number']}-{row['article']}")
        matches = [model for model in models if normalized_base(model.code) == combined]
    if len(matches) != 1:
        raise ValueError(
            f"{row['qr_code']}: expected one catalog model for "
            f"{row['model_number']} / {row['article']}, found {len(matches)}"
        )
    return matches[0]


def database_host() -> str:
    parsed = urlparse(settings.DATABASE_URL.replace("postgresql+psycopg2://", "postgresql://", 1))
    return (parsed.hostname or "").casefold()


def validate_row(row: dict[str, Any], photo_root: Path) -> dict[str, Any]:
    qr_code = clean(row.get("qr_code"), limit=128).lower()
    match = QR_RE.fullmatch(qr_code)
    if not match:
        raise ValueError(f"Invalid old sticker QR: {qr_code!r}")
    required = ("client", "model_number", "article", "color", "product")
    for field in required:
        if not clean(row.get(field)):
            raise ValueError(f"{qr_code}: {field} is blank")
    try:
        quantity = int(row.get("quantity"))
    except (TypeError, ValueError):
        raise ValueError(f"{qr_code}: quantity is not a whole number") from None
    if quantity <= 0:
        raise ValueError(f"{qr_code}: quantity must be positive")
    try:
        weight_kg = float(str(row.get("weight_kg")).replace(",", "."))
    except (TypeError, ValueError):
        raise ValueError(f"{qr_code}: weight_kg is not numeric") from None
    if weight_kg <= 0:
        raise ValueError(f"{qr_code}: weight_kg must be positive")
    sizes = [clean(value, limit=32) for value in row.get("sizes") or [] if clean(value)]
    if not sizes:
        raise ValueError(f"{qr_code}: sizes are blank")
    source_photo = clean(row.get("source_photo"), limit=255)
    source_sha = clean(row.get("source_photo_sha256"), limit=64).lower()
    if not source_photo or not SHA_RE.fullmatch(source_sha):
        raise ValueError(f"{qr_code}: source photo evidence is incomplete")
    photo_path = (photo_root / source_photo).resolve()
    if photo_path.parent != photo_root.resolve() or not photo_path.is_file():
        raise ValueError(f"{qr_code}: source photo is missing or unsafe")
    if file_sha256(photo_path) != source_sha:
        raise ValueError(f"{qr_code}: source photo hash changed")
    if clean(row.get("review_status")).casefold() != "approved":
        raise ValueError(f"{qr_code}: row is not explicitly approved")
    return {
        **canonical_payload(row),
        "qr_code": qr_code,
        "quantity": quantity,
        "weight_kg": weight_kg,
        "sizes": sizes,
        "source_photo": source_photo,
        "source_photo_sha256": source_sha,
    }


def read_manifest(path: Path, photo_root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("version") != 1 or not isinstance(payload.get("rows"), list):
        raise ValueError("Sticker manifest must be a version-1 object with a rows list")
    rows = [validate_row(dict(row), photo_root) for row in payload["rows"]]
    qr_codes = [row["qr_code"] for row in rows]
    duplicates = sorted({value for value in qr_codes if qr_codes.count(value) > 1})
    if duplicates:
        raise ValueError(f"Manifest repeats old sticker QR values: {duplicates[:10]}")
    expected_rows = payload.get("expected_rows")
    if expected_rows is not None and int(expected_rows) != len(rows):
        raise ValueError(f"Manifest expected {expected_rows} rows, found {len(rows)}")
    return payload, rows


def run_import(args: argparse.Namespace) -> dict[str, Any]:
    if args.apply_local and database_host() not in LOCAL_DATABASE_HOSTS:
        raise ValueError(f"--apply-local refuses database host {database_host()!r}")
    manifest, rows = read_manifest(args.input, args.photo_root)
    summary = {
        "mode": "apply-local" if args.apply_local else "dry-run",
        "source_system": SOURCE_SYSTEM,
        "rows": len(rows),
        "quantity": sum(int(row["quantity"]) for row in rows),
        "created_receipts": 0,
        "created_packages": 0,
        "created_stock_rows": 0,
        "created_aliases": 0,
        "skipped_existing": 0,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    db = SessionLocal()
    try:
        warehouse = db.get(Warehouse, args.warehouse_id)
        if not warehouse:
            raise ValueError(f"Destination warehouse {args.warehouse_id} does not exist")
        importer = db.get(User, args.imported_by) if args.imported_by else None
        if args.imported_by and not importer:
            raise ValueError(f"Importer user {args.imported_by} does not exist")
        models = db.query(Model).all()
        planned: list[tuple[dict[str, Any], Model, str]] = []
        for row in rows:
            checksum = payload_checksum(row)
            existing = (
                db.query(LegacyStockReceipt)
                .filter(
                    LegacyStockReceipt.source_system == SOURCE_SYSTEM,
                    LegacyStockReceipt.source_warehouse_id == SOURCE_WAREHOUSE_ID,
                    LegacyStockReceipt.source_record_id == row["qr_code"],
                )
                .first()
            )
            if existing:
                if existing.source_checksum != checksum:
                    raise ValueError(f"{row['qr_code']}: existing receipt checksum conflicts")
                summary["skipped_existing"] += 1
                continue
            collision = db.query(Package).filter(Package.barcode == row["qr_code"]).first()
            if collision:
                raise ValueError(f"{row['qr_code']}: package barcode already exists")
            match = QR_RE.fullmatch(row["qr_code"])
            assert match
            package_no = f"OLD-{match.group(1)}-{match.group(2)}"
            if db.query(Package).filter(Package.package_no == package_no).first():
                raise ValueError(f"{row['qr_code']}: package number {package_no!r} already exists")
            planned.append((row, resolve_model(models, row), checksum))

        if args.apply_local:
            for row, model, checksum in planned:
                match = QR_RE.fullmatch(row["qr_code"])
                assert match
                package_no = f"OLD-{match.group(1)}-{match.group(2)}"
                receipt = LegacyStockReceipt(
                    source_system=SOURCE_SYSTEM,
                    source_warehouse_id=SOURCE_WAREHOUSE_ID,
                    source_warehouse_name=SOURCE_WAREHOUSE_NAME,
                    source_record_id=row["qr_code"],
                    source_checksum=checksum,
                    source_payload=canonical_payload(row),
                    imported_by=args.imported_by,
                )
                db.add(receipt)
                db.flush()
                package = Package(
                    package_no=package_no,
                    barcode=row["qr_code"],
                    legacy_receipt_id=receipt.id,
                    model_id=model.id,
                    brand_id=model.brand_id,
                    collection_id=model.collection_id,
                    color=clean(row["color"], limit=64),
                    package_type="legacy_stock",
                    total_quantity=row["quantity"],
                    capacity=max(60, row["quantity"]),
                    weight_kg=row["weight_kg"],
                    warehouse_id=warehouse.id,
                    status="received_in_storage",
                    received_by=args.imported_by,
                    received_at=datetime.now(timezone.utc),
                    notes=f"Imported locally from reviewed old-ERP sticker photo {row['source_photo']}.",
                )
                db.add(package)
                db.flush()
                db.add_all(
                    [
                        PackageItem(
                            package_id=package.id,
                            model_id=model.id,
                            color=package.color,
                            size="ASSORTED",
                            quantity=row["quantity"],
                        ),
                        FinishedGoodsStock(
                            package_id=package.id,
                            model_id=model.id,
                            brand_id=model.brand_id,
                            collection_id=model.collection_id,
                            color=package.color,
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
                            scanned_by=args.imported_by,
                            scan_type="legacy_sticker_import",
                            location=clean(row["location"], limit=255),
                        ),
                        PackageBarcodeAlias(
                            package_id=package.id,
                            code=row["qr_code"],
                            code_type="legacy_sticker_qr",
                        ),
                    ]
                )
                summary["created_receipts"] += 1
                summary["created_packages"] += 1
                summary["created_stock_rows"] += 1
                summary["created_aliases"] += 1
            if importer and planned:
                log_action(
                    db,
                    importer,
                    "legacy_sticker_inventory_import",
                    "LegacyStockReceipt",
                    None,
                    new_value={
                        "manifest_sha256": hashlib.sha256(args.input.read_bytes()).hexdigest(),
                        "rows": len(planned),
                        "quantity": sum(int(row["quantity"]) for row, _, _ in planned),
                    },
                )
            db.commit()
        else:
            db.rollback()
        summary["planned_creates"] = len(planned)
        summary["manifest_source"] = manifest.get("source")
        summary["finished_at"] = datetime.now(timezone.utc).isoformat()
        return summary
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--photo-root", type=Path, required=True)
    parser.add_argument("--warehouse-id", type=int, required=True)
    parser.add_argument("--imported-by", type=int)
    parser.add_argument("--apply-local", action="store_true")
    return parser.parse_args()


def main() -> int:
    summary = run_import(parse_args())
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
