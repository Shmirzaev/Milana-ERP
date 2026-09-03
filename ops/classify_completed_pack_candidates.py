"""Read-only production classifier for completed old-ERP pack candidates."""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import func, or_, text

from app.core.config import settings
from app.db.session import SessionLocal
from app.models import LegacyStockReceipt, Model, Package, PackageBarcodeAlias


SOURCE_SYSTEM = "UZERP_STICKER_PHOTO"
SOURCE_WAREHOUSE_ID = "18"
EXPECTED_ALEMBIC_HEAD = "0113_variant_selling_price"
QR_RE = re.compile(r"^(?:uzerp_ii_(\d+)_(\d+)|(\d{7}))$", re.IGNORECASE)
CONFUSABLES = str.maketrans(
    {
        "А": "A", "В": "B", "С": "C", "Е": "E", "Н": "H", "К": "K",
        "М": "M", "О": "O", "Р": "P", "Т": "T", "Х": "X", "У": "Y",
        "І": "I", "Ј": "J",
    }
)


def clean(value: Any) -> str:
    return " ".join(unicodedata.normalize("NFKC", str(value or "")).strip().split())


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
        raise ValueError(f"Invalid QR in candidate manifest: {qr!r}")
    return (
        f"OLD-{match.group(1)}-{match.group(2)}"
        if match.group(1) and match.group(2)
        else f"OLD-{match.group(3)}"
    )


def decimal_or_none(value: Any) -> Decimal | None:
    return None if value in (None, "") else Decimal(str(value))


def package_matches(package: Package, row: dict[str, Any], model_by_id: dict[int, Model]) -> bool:
    model = model_by_id.get(package.model_id)
    return (
        clean(package.barcode).casefold() == row["qr_code"]
        and model is not None
        and model_identity(model) == row["identity"]
        and int(package.total_quantity) == row["quantity"]
        and decimal_or_none(package.weight_kg) == row["weight_kg"]
        and package.warehouse_id == 8
        and package.status == "received_in_storage"
    )


def main(args: argparse.Namespace) -> dict[str, Any]:
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for raw in payload.get("rows") or []:
        qr = clean(raw.get("qr_code")).casefold()
        if not QR_RE.fullmatch(qr):
            raise ValueError(f"Invalid QR in manifest: {qr!r}")
        rows.append(
            {
                "qr_code": qr,
                "model_number": clean(raw.get("model_number")),
                "article": clean(raw.get("article")),
                "identity": (
                    normalized_base(raw.get("model_number")),
                    normalized_variant(raw.get("article")),
                ),
                "quantity": int(raw.get("quantity")),
                "weight_kg": decimal_or_none(raw.get("weight_kg")),
                "workbook_excel_row": raw.get("workbook_excel_row"),
            }
        )
    qrs = [row["qr_code"] for row in rows]
    package_nos = [package_number(qr) for qr in qrs]

    with SessionLocal() as db:
        parsed = urlparse(settings.DATABASE_URL.replace("postgresql+psycopg2://", "postgresql://", 1))
        host = (parsed.hostname or "").casefold()
        database = str(db.execute(text("select current_database()" )).scalar() or "")
        heads = [str(value) for value, in db.execute(text("select version_num from alembic_version order by version_num"))]
        if host != args.expected_database_host.casefold() or database != args.expected_database_name:
            raise ValueError(f"Database guard failed for host={host!r}, database={database!r}")
        if heads != [EXPECTED_ALEMBIC_HEAD]:
            raise ValueError(f"Expected migration head {EXPECTED_ALEMBIC_HEAD}, found {heads}")

        by_identity: dict[tuple[str, str], list[Model]] = defaultdict(list)
        models = db.query(Model).all()
        model_by_id = {model.id: model for model in models}
        for model in models:
            by_identity[model_identity(model)].append(model)

        receipts = db.query(LegacyStockReceipt).filter(
            LegacyStockReceipt.source_system == SOURCE_SYSTEM,
            LegacyStockReceipt.source_warehouse_id == SOURCE_WAREHOUSE_ID,
            func.lower(LegacyStockReceipt.source_record_id).in_(qrs),
        ).all()
        packages = db.query(Package).filter(
            or_(func.lower(Package.barcode).in_(qrs), Package.package_no.in_(package_nos))
        ).all()
        aliases = db.query(PackageBarcodeAlias).filter(func.lower(PackageBarcodeAlias.code).in_(qrs)).all()
        receipt_package_ids = [receipt.package.id for receipt in receipts if receipt.package]
        alias_package_ids = [alias.package_id for alias in aliases]
        more_ids = set(receipt_package_ids + alias_package_ids) - {package.id for package in packages}
        if more_ids:
            packages.extend(db.query(Package).filter(Package.id.in_(more_ids)).all())

        receipts_by_qr: dict[str, list[LegacyStockReceipt]] = defaultdict(list)
        for receipt in receipts:
            receipts_by_qr[receipt.source_record_id.casefold()].append(receipt)
        packages_by_qr: dict[str, list[Package]] = defaultdict(list)
        by_id = {package.id: package for package in packages}
        expected_no_to_qr = {package_number(qr): qr for qr in qrs}
        for package in packages:
            barcode_qr = clean(package.barcode).casefold()
            if barcode_qr in qrs:
                packages_by_qr[barcode_qr].append(package)
            package_no_qr = expected_no_to_qr.get(package.package_no)
            if package_no_qr and package not in packages_by_qr[package_no_qr]:
                packages_by_qr[package_no_qr].append(package)
        for qr, matching_receipts in receipts_by_qr.items():
            for receipt in matching_receipts:
                if receipt.package and receipt.package not in packages_by_qr[qr]:
                    packages_by_qr[qr].append(receipt.package)
        for alias in aliases:
            qr = alias.code.casefold()
            package = by_id.get(alias.package_id)
            if package and package not in packages_by_qr[qr]:
                packages_by_qr[qr].append(package)

        result_rows: list[dict[str, Any]] = []
        counts: dict[str, int] = defaultdict(int)
        for row in rows:
            identity_matches = by_identity.get(row["identity"], [])
            approved = [model for model in identity_matches if clean(model.status).casefold() == "approved"]
            collided = packages_by_qr.get(row["qr_code"], [])
            if collided:
                exact = [package for package in collided if package_matches(package, row, model_by_id)]
                classification = "already_present_exact" if len(collided) == 1 and len(exact) == 1 else "identifier_collision_conflict"
            elif len(approved) == 1 and len(identity_matches) == 1:
                classification = "new_importable"
            elif not identity_matches:
                classification = "catalog_identity_missing"
            elif len(approved) != 1:
                classification = "catalog_identity_not_single_approved"
            else:
                classification = "catalog_identity_ambiguous"
            counts[classification] += 1
            result_rows.append(
                {
                    **{key: value for key, value in row.items() if key != "weight_kg"},
                    "weight_kg": None if row["weight_kg"] is None else str(row["weight_kg"]),
                    "classification": classification,
                    "catalog_matches": [
                        {"id": model.id, "status": model.status, "code": model.code}
                        for model in identity_matches
                    ],
                    "colliding_packages": [
                        {
                            "id": package.id,
                            "barcode": package.barcode,
                            "package_no": package.package_no,
                            "model_id": package.model_id,
                            "model_identity": model_identity(model_by_id[package.model_id]),
                            "quantity": package.total_quantity,
                            "weight_kg": None if package.weight_kg is None else str(package.weight_kg),
                            "warehouse_id": package.warehouse_id,
                            "status": package.status,
                        }
                        for package in collided
                    ],
                }
            )
        db.rollback()

    return {
        "read_only": True,
        "database": {"host": host, "name": database, "alembic": heads},
        "candidate_rows": len(rows),
        "classification_counts": dict(sorted(counts.items())),
        "rows": result_rows,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--expected-database-host", required=True)
    parser.add_argument("--expected-database-name", required=True)
    return parser.parse_args()


if __name__ == "__main__":
    print(json.dumps(main(parse_args()), ensure_ascii=False, indent=2, sort_keys=True))
