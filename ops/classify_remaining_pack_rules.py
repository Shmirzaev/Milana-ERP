from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from sqlalchemy import func

from app.db.session import SessionLocal
from app.models import Model, Package, PackageBarcodeAlias


def clean(value: Any) -> str:
    return str(value or "").strip()


def normalized_base(value: Any) -> str:
    return re.sub(r"[^A-Z0-9А-Я]", "", clean(value).upper())


def normalized_variant(value: Any) -> str:
    value = clean(value).upper()
    value = re.sub(r"^(?:VARIANT|VAR|V)\s*[-_:#]*\s*", "", value)
    return re.sub(r"[^A-Z0-9А-Я]", "", value)


def model_identity(model: Model) -> tuple[str, str]:
    details = model.details_json if isinstance(model.details_json, dict) else {}
    general = details.get("general") if isinstance(details.get("general"), dict) else {}
    return (
        normalized_base(general.get("model_no") or general.get("modelNo")),
        normalized_variant(general.get("variant_no") or general.get("variantNo")),
    )


def is_internal_legacy_model(model: Model) -> bool:
    details = model.details_json if isinstance(model.details_json, dict) else {}
    return details.get("legacy_import") is True


def package_summary(package: Package, models: dict[int, Model]) -> dict[str, Any]:
    model = models[package.model_id]
    identity = model_identity(model)
    return {
        "package_id": package.id,
        "package_no": package.package_no,
        "barcode": package.barcode,
        "quantity": package.total_quantity,
        "model_id": package.model_id,
        "model_number": identity[0],
        "variant_number": identity[1],
        "status": package.status,
    }


def run(input_path: Path) -> dict[str, Any]:
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    rows = [dict(row) for row in payload["rows"]]
    candidate_qrs = sorted(
        {
            clean(row.get("qr_code")).casefold()
            for row in rows
            if row.get("action") == "import" and clean(row.get("qr_code"))
        }
    )

    with SessionLocal() as db:
        models = {model.id: model for model in db.query(Model).all()}
        catalog_by_identity: dict[tuple[str, str], list[Model]] = {}
        for model in models.values():
            if not is_internal_legacy_model(model):
                catalog_by_identity.setdefault(model_identity(model), []).append(model)

        packages_by_qr: dict[str, dict[int, Package]] = {}
        if candidate_qrs:
            for package in db.query(Package).filter(func.lower(Package.barcode).in_(candidate_qrs)):
                packages_by_qr.setdefault(package.barcode.casefold(), {})[package.id] = package
            aliases = (
                db.query(PackageBarcodeAlias).filter(func.lower(PackageBarcodeAlias.code).in_(candidate_qrs)).all()
            )
            alias_package_ids = {alias.package_id for alias in aliases}
            alias_packages = {
                package.id: package for package in db.query(Package).filter(Package.id.in_(alias_package_ids or {-1}))
            }
            for alias in aliases:
                packages_by_qr.setdefault(alias.code.casefold(), {})[alias.package_id] = alias_packages[
                    alias.package_id
                ]

        for row in rows:
            if row.get("action") != "import":
                continue
            identity = (
                normalized_base(row.get("model_number")),
                normalized_variant(row.get("article")),
            )
            matches = catalog_by_identity.get(identity, []) if all(identity) else []
            approved = [model for model in matches if clean(model.status).casefold() == "approved"]
            if len(approved) == 1:
                row["target_kind"] = "catalog"
                row["target_model_id"] = approved[0].id
                row["target_model_code"] = approved[0].code
            else:
                row["target_kind"] = "hidden_legacy"
                row["target_model_id"] = None
                row["target_model_code"] = None
                row["catalog_match_count"] = len(matches)

            qr = clean(row.get("qr_code")).casefold()
            existing = list(packages_by_qr.get(qr, {}).values()) if qr else []
            if not existing:
                continue
            row["production_qr_matches"] = [package_summary(package, models) for package in existing]
            same = all(
                normalized_base(row.get("model_number")) == model_identity(models[package.model_id])[0]
                and int(row["quantity"]) == int(package.total_quantity)
                for package in existing
            )
            if same:
                row["action"] = "already_in_production_same_model_quantity"
                row["action_reason"] = "Supplied QR already exists in production with the same model and quantity"
            else:
                row["action"] = "review_production_qr_conflict"
                row["action_reason"] = "Supplied QR already exists in production with a different model or quantity"

        db.rollback()

    summary: dict[str, int] = {}
    target_summary: dict[str, int] = {}
    for row in rows:
        summary[row["action"]] = summary.get(row["action"], 0) + 1
        if row["action"] == "import":
            target = row["target_kind"]
            target_summary[target] = target_summary.get(target, 0) + 1
    return {**payload, "rows": rows, "summary": summary, "target_summary": target_summary}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    return parser.parse_args()


if __name__ == "__main__":
    print(json.dumps(run(parse_args().input), ensure_ascii=False, indent=2, sort_keys=True))
