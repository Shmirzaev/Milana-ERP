from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm.attributes import flag_modified

from app.core.config import settings
from app.db.session import SessionLocal
from app.models import Model, ModelImage, ModelSize, User


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import a grouped Excel catalog manifest into local ERP models.")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--media-dir", required=True, type=Path)
    parser.add_argument("--source-key", required=True)
    parser.add_argument(
        "--merge-existing",
        action="store_true",
        help="Merge sizes/images into matching codes owned by another import instead of failing.",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def clean(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def normalize_model_no(value: object) -> str:
    text = clean(value)
    text = re.sub(r"[\u2010-\u2015\u2212]", "-", text)
    return re.sub(r"\s*-\s*", "-", text)


def normalize_variant_no(value: object) -> str:
    text = clean(value)
    return str(int(text)) if text.isdigit() else text


def record_code(record: dict) -> str:
    model_no = normalize_model_no(record.get("modelNo"))
    variant_no = normalize_variant_no(record.get("variantNo"))
    return f"{model_no}-{variant_no}" if model_no and variant_no else clean(record.get("code"))


def image_target(source: Path, expected_sha256: str, target_dir: Path, *, dry_run: bool) -> tuple[str, str, bytes]:
    content = source.read_bytes()
    actual_sha256 = hashlib.sha256(content).hexdigest()
    if actual_sha256 != expected_sha256:
        raise ValueError(f"Image hash mismatch for {source.name}")
    suffix = source.suffix.lower() or ".png"
    target_name = f"excel_{actual_sha256[:20]}{suffix}"
    target_path = target_dir / target_name
    if not dry_run and not target_path.exists():
        target_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target_path)
    return target_name, mimetypes.guess_type(target_name)[0] or "application/octet-stream", content


def source_owned(model: Model, source_key: str) -> bool:
    details = model.details_json if isinstance(model.details_json, dict) else {}
    source = details.get("source") if isinstance(details.get("source"), dict) else {}
    return clean(source.get("import_key")) == source_key


def upsert_details(
    model: Model,
    record: dict,
    *,
    source_key: str,
    workbook: str,
    preserve_existing: bool = False,
) -> None:
    details = dict(model.details_json) if isinstance(model.details_json, dict) else {}
    general = dict(details.get("general")) if isinstance(details.get("general"), dict) else {}
    incoming_general = {
        "model_no": normalize_model_no(record.get("modelNo")),
        "variant_no": normalize_variant_no(record.get("variantNo")),
        "variant_fabric": clean(record.get("fabric")),
    }
    for key, value in incoming_general.items():
        if value and (not preserve_existing or not clean(general.get(key))):
            general[key] = value
    details["general"] = general
    source_entry = {
        "import_key": source_key,
        "workbook": workbook,
        "excel_rows": [int(row) for row in record.get("sourceRows") or []],
        "imported_at": datetime.now(timezone.utc).isoformat(),
    }
    current_source = details.get("source") if isinstance(details.get("source"), dict) else None
    imports = [entry for entry in (details.get("sources") or []) if isinstance(entry, dict)]
    if current_source and clean(current_source.get("import_key")):
        imports.append(current_source)
    imports = [entry for entry in imports if clean(entry.get("import_key")) != source_key]
    imports.append(source_entry)
    details["sources"] = list({clean(entry.get("import_key")): entry for entry in imports}.values())
    if not preserve_existing or not current_source:
        details["source"] = source_entry
    model.details_json = details
    flag_modified(model, "details_json")


def ensure_sizes(db, model: Model, sizes: list[str]) -> int:
    existing = {clean(row.size) for row in model.sizes or []}
    added = 0
    for size in sizes:
        value = clean(size)
        if not value or value in existing:
            continue
        db.add(ModelSize(model_id=model.id, size=value, measurement_json=None))
        existing.add(value)
        added += 1
    return added


def ensure_images(
    db,
    model: Model,
    images: list[dict],
    *,
    image_type: str,
    media_dir: Path,
    target_dir: Path,
    dry_run: bool,
) -> int:
    existing = {(clean(row.file_url), clean(row.image_type)) for row in model.images or []}
    added = 0
    for index, image in enumerate(images):
        source_name = clean(image.get("name"))
        expected_sha256 = clean(image.get("sha256"))
        if not source_name or not expected_sha256:
            continue
        source = media_dir / source_name
        if not source.is_file():
            raise FileNotFoundError(f"Missing image: {source}")
        target_name, content_type, _ = image_target(source, expected_sha256, target_dir, dry_run=dry_run)
        file_url = f"/storage/model-files/{target_name}"
        key = (file_url, image_type)
        if key in existing:
            continue
        db.add(
            ModelImage(
                model_id=model.id,
                file_url=file_url,
                file_name=source_name,
                content_type=content_type,
                file_data=None,
                image_type=image_type,
                is_primary=image_type == "model" and index == 0 and not any(row.is_primary for row in model.images or []),
            )
        )
        existing.add(key)
        added += 1
    return added


def main() -> None:
    args = parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    records = manifest.get("records") or []
    workbook = clean(manifest.get("source"))
    codes = [record_code(record) for record in records]
    if not records:
        raise ValueError("Manifest contains no import records")
    if any(not code for code in codes):
        raise ValueError("Every import record must have a system model code")
    if len(codes) != len(set(codes)):
        raise ValueError("Manifest contains duplicate model codes")
    if any(len(code) > 64 for code in codes):
        raise ValueError("One or more model codes exceed the ERP 64-character limit")

    target_dir = Path(settings.MODEL_FILES_DIR)
    summary = {
        "source_key": args.source_key,
        "workbook": workbook,
        "dry_run": bool(args.dry_run),
        "created_models": 0,
        "updated_models": 0,
        "merged_existing_models": 0,
        "added_sizes": 0,
        "added_model_images": 0,
        "added_material_images": 0,
        "skipped_rows_without_model_no": int((manifest.get("stats") or {}).get("skippedRowsWithoutModelNo") or 0),
    }

    with SessionLocal() as db:
        creator = db.query(User).order_by(User.id.asc()).first()
        existing_by_code = {
            model.code: model
            for model in db.query(Model).filter(Model.code.in_(codes)).all()
        }
        conflicts = [
            code for code, model in existing_by_code.items()
            if not source_owned(model, args.source_key) and not args.merge_existing
        ]
        if conflicts:
            preview = ", ".join(sorted(conflicts)[:10])
            raise ValueError(f"Existing non-import models use manifest codes: {preview}")

        for record in records:
            code = record_code(record)
            model = existing_by_code.get(code)
            preserve_existing = bool(model is not None and not source_owned(model, args.source_key))
            if model is None:
                model = Model(
                    code=code,
                    name=clean(record.get("name")),
                    category=None,
                    description=None,
                    brand_id=None,
                    collection_id=None,
                    product_type=None,
                    season=None,
                    details_json={},
                    status="draft",
                    created_by=creator.id if creator else None,
                    sam_minutes=0,
                )
                db.add(model)
                db.flush()
                existing_by_code[code] = model
                summary["created_models"] += 1
            elif preserve_existing:
                summary["merged_existing_models"] += 1
            else:
                summary["updated_models"] += 1

            upsert_details(
                model,
                record,
                source_key=args.source_key,
                workbook=workbook,
                preserve_existing=preserve_existing,
            )
            summary["added_sizes"] += ensure_sizes(db, model, record.get("sizes") or [])
            summary["added_model_images"] += ensure_images(
                db,
                model,
                record.get("modelImages") or [],
                image_type="model",
                media_dir=args.media_dir,
                target_dir=target_dir,
                dry_run=args.dry_run,
            )
            summary["added_material_images"] += ensure_images(
                db,
                model,
                record.get("fabricImages") or [],
                image_type="material",
                media_dir=args.media_dir,
                target_dir=target_dir,
                dry_run=args.dry_run,
            )

        if args.dry_run:
            db.rollback()
        else:
            db.commit()

    print(json.dumps(summary, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
