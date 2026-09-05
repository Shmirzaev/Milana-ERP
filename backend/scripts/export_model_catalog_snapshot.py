"""Export a read-only, identity-focused snapshot of the model catalog.

The script is intentionally non-mutating. It is used by guarded catalog-data
reconciliation tasks to compare an external catalog against the current ERP
without exposing database credentials.
"""

from __future__ import annotations

import argparse
import json
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import text

from app.core.config import settings
from app.db.session import SessionLocal
from app.models import Model, ModelColor, ModelImage, ModelSize


EXPECTED_DATABASE_NAME = "erp"


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    return value


def _assert_expected_database(db) -> dict[str, Any]:
    parsed = urlparse(
        settings.DATABASE_URL.replace("postgresql+psycopg2://", "postgresql://", 1)
    )
    configured_name = (parsed.path or "").lstrip("/")
    current_name = str(db.execute(text("select current_database()" )).scalar() or "")
    heads = [
        str(row[0])
        for row in db.execute(
            text("select version_num from alembic_version order by version_num")
        )
    ]
    if configured_name != EXPECTED_DATABASE_NAME or current_name != EXPECTED_DATABASE_NAME:
        raise RuntimeError(
            f"Database guard failed: configured={configured_name!r}, current={current_name!r}"
        )
    return {
        "database": current_name,
        "database_host": parsed.hostname,
        "alembic_heads": heads,
    }


def export_snapshot() -> dict[str, Any]:
    with SessionLocal() as db:
        guard = _assert_expected_database(db)
        models = (
            db.query(
                Model.id,
                Model.code,
                Model.name,
                Model.catalog_scope,
                Model.factory_code,
                Model.category,
                Model.brand_id,
                Model.collection_id,
                Model.product_type,
                Model.season,
                Model.details_json["general"].label("general_details"),
                Model.status,
                Model.created_by,
                Model.approved_by,
                Model.sam_minutes,
            )
            .order_by(Model.id)
            .all()
        )
        images_by_model: dict[int, list[dict[str, Any]]] = {}
        for image in (
            db.query(
                ModelImage.id,
                ModelImage.model_id,
                ModelImage.file_url,
                ModelImage.file_name,
                ModelImage.content_type,
                ModelImage.image_type,
                ModelImage.is_primary,
                (ModelImage.file_data.isnot(None)).label("has_file_data"),
            )
            .order_by(ModelImage.id)
        ):
            images_by_model.setdefault(int(image.model_id), []).append(
                {
                    "id": int(image.id),
                    "file_url": image.file_url,
                    "file_name": image.file_name,
                    "content_type": image.content_type,
                    "image_type": image.image_type,
                    "is_primary": bool(image.is_primary),
                    "has_file_data": bool(image.has_file_data),
                }
            )
        sizes_by_model: dict[int, list[str]] = {}
        for size in db.query(ModelSize.model_id, ModelSize.size).order_by(ModelSize.id):
            sizes_by_model.setdefault(int(size.model_id), []).append(size.size)
        colors_by_model: dict[int, list[str]] = {}
        for color in db.query(ModelColor.model_id, ModelColor.color_name).order_by(
            ModelColor.id
        ):
            colors_by_model.setdefault(int(color.model_id), []).append(color.color_name)
        rows = []
        for model in models:
            rows.append(
                {
                    "id": int(model.id),
                    "code": model.code,
                    "name": model.name,
                    "catalog_scope": model.catalog_scope,
                    "factory_code": model.factory_code,
                    "category": model.category,
                    "brand_id": model.brand_id,
                    "collection_id": model.collection_id,
                    "product_type": model.product_type,
                    "season": model.season,
                    "general_details": model.general_details,
                    "status": model.status,
                    "created_by": model.created_by,
                    "approved_by": model.approved_by,
                    "sam_minutes": _json_value(model.sam_minutes),
                    "sizes": sizes_by_model.get(int(model.id), []),
                    "colors": colors_by_model.get(int(model.id), []),
                    "images": images_by_model.get(int(model.id), []),
                }
            )
        db.rollback()
        return {"guard": guard, "models": rows}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = json.dumps(export_snapshot(), ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)


if __name__ == "__main__":
    main()
