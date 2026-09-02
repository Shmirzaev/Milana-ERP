"""Guarded lossless image normalization for the 2026-09-02 catalog import."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from PIL import Image
from sqlalchemy import func, text
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import settings
from app.db.session import SessionLocal
from app.models import Model, ModelImage, User
from app.services.audit import log_action
from app.services.image_storage import prebuild_webp_thumbnails


EXPECTED_MAP_SHA256 = "8141d8d50c06129344bb4e21fdc3b3db1c0b9d052e042047c67cd9d901c8415c"
EXPECTED_SOURCE_MANIFEST_SHA256 = "2bb7f5469ad2e85f003fbdcc4540098fededdf006715490ca612378503e9f418"
EXPECTED_MODELS = 261
EXPECTED_RELATIONS = 536
EXPECTED_SOURCE_IMAGES = 323
EXPECTED_NORMALIZED_FILES = 323
EXPECTED_DATABASE_HOST = "172.16.10.3"
EXPECTED_DATABASE_NAME = "erp"
EXPECTED_ALEMBIC_HEAD = "0112_price_calc_requests"
EXPECTED_IMPORTER_ID = 1
SOURCE_KEY = "old-erp-catalog-full-delta-2026-09-02"
AUDIT_ACTION = "old_erp_catalog_lossless_image_normalization"
CONFIRMATION = "APPLY-LOSSLESS-IMAGE-NORMALIZATION-FOR-261-OLD-ERP-MODELS"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pixel_sha256(image: Image.Image) -> str:
    digest = hashlib.sha256()
    digest.update(f"{image.mode}:{image.width}x{image.height}:".encode())
    digest.update(image.tobytes())
    return digest.hexdigest()


def safe_asset(root: Path, relative: str) -> Path:
    resolved_root = root.resolve()
    path = (resolved_root / relative).resolve()
    if not path.is_file() or resolved_root not in path.parents:
        raise ValueError(f"Unsafe or missing normalized image: {relative!r}")
    return path


def validate_normalized_image(path: Path, spec: dict[str, Any]) -> dict[str, Any]:
    if path.stat().st_size != int(spec["bytes"]) or file_sha256(path) != spec["sha256"]:
        raise ValueError(f"Normalized image bytes changed: {path}")
    try:
        with Image.open(path) as opened:
            opened.verify()
        with Image.open(path) as opened:
            opened.load()
            mode = "RGBA" if "A" in opened.getbands() else "RGB"
            pixels = opened.convert(mode)
            width, height = pixels.size
            pixels_hash = pixel_sha256(pixels)
            pixels.close()
    except OSError as exc:
        raise ValueError(f"Normalized image cannot be decoded: {path}: {exc}") from exc
    if (
        (width, height) != (int(spec["width"]), int(spec["height"]))
        or pixels_hash != spec["pixel_sha256"]
        or spec.get("content_type") != "image/webp"
    ):
        raise ValueError(f"Normalized image pixel evidence changed: {path}")
    return {
        "sha256": spec["sha256"],
        "bytes": int(spec["bytes"]),
        "width": width,
        "height": height,
        "pixel_sha256": pixels_hash,
    }


def validate_map(path: Path, asset_root: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    if file_sha256(path) != EXPECTED_MAP_SHA256:
        raise ValueError("Normalization map SHA-256 changed")
    payload = json.loads(path.read_text(encoding="utf-8"))
    mapping = payload.get("mapping") if isinstance(payload, dict) else None
    if (
        payload.get("version") != 1
        or payload.get("kind") != "old_erp_catalog_lossless_image_normalization"
        or payload.get("source_manifest_sha256") != EXPECTED_SOURCE_MANIFEST_SHA256
        or int(payload.get("source_images") or -1) != EXPECTED_SOURCE_IMAGES
        or int(payload.get("normalized_unique_files") or -1) != EXPECTED_NORMALIZED_FILES
        or not isinstance(mapping, dict)
        or len(mapping) != EXPECTED_SOURCE_IMAGES
    ):
        raise ValueError("Normalization map metadata changed")
    normalized_hashes: set[str] = set()
    for source_sha, row in mapping.items():
        if row.get("source", {}).get("sha256") != source_sha:
            raise ValueError(f"Source mapping changed: {source_sha}")
        spec = row.get("normalized")
        if not isinstance(spec, dict):
            raise ValueError(f"Normalized spec missing: {source_sha}")
        validate_normalized_image(safe_asset(asset_root, spec["path"]), spec)
        normalized_hashes.add(spec["sha256"])
    if len(normalized_hashes) != EXPECTED_NORMALIZED_FILES:
        raise ValueError("Normalized file deduplication count changed")
    return payload, mapping


def assert_production_guard(db, imported_by: int) -> User:
    parsed = urlparse(settings.DATABASE_URL.replace("postgresql+psycopg2://", "postgresql://", 1))
    current_name = str(db.execute(text("select current_database()" )).scalar() or "")
    heads = [
        str(row[0])
        for row in db.execute(text("select version_num from alembic_version order by version_num"))
    ]
    if (
        (parsed.hostname or "").casefold() != EXPECTED_DATABASE_HOST
        or (parsed.path or "").lstrip("/") != EXPECTED_DATABASE_NAME
        or current_name != EXPECTED_DATABASE_NAME
        or heads != [EXPECTED_ALEMBIC_HEAD]
    ):
        raise ValueError(
            f"Production guard failed for host={parsed.hostname!r}, database={current_name!r}, heads={heads}"
        )
    if imported_by != EXPECTED_IMPORTER_ID:
        raise ValueError("Importer ID changed")
    importer = db.get(User, imported_by)
    permissions = set(
        (importer.role.permissions if importer and importer.role else [])
        + ((importer.extra_permissions or []) if importer else [])
    )
    if not importer or not importer.is_active or "*" not in permissions:
        raise ValueError("Production import actor is not the active wildcard administrator")
    return importer


def target_models(db) -> list[Model]:
    models = (
        db.query(Model)
        .filter(
            Model.details_json["old_erp_catalog_sync"]["source_key"].as_string()
            == SOURCE_KEY,
            Model.details_json["old_erp_catalog_sync"]["manifest_sha256"].as_string()
            == EXPECTED_SOURCE_MANIFEST_SHA256,
        )
        .order_by(Model.id)
        .all()
    )
    if len(models) != EXPECTED_MODELS:
        raise ValueError(f"Expected {EXPECTED_MODELS} imported models, found {len(models)}")
    return models


def _source_relation_map(
    model: Model, mapping: dict[str, dict[str, Any]]
) -> dict[tuple[str, str], tuple[str, dict[str, Any]]]:
    provenance = (model.details_json or {}).get("old_erp_catalog_sync")
    if not isinstance(provenance, dict):
        raise ValueError(f"Catalog provenance missing for model {model.id}")
    primary_sha = str(provenance.get("primary_image_sha256") or "")
    material_sha = [str(value) for value in provenance.get("material_image_sha256") or []]
    expected = [("model", primary_sha), *[("material", value) for value in material_sha]]
    result = {}
    for image_type, source_sha in expected:
        mapped = mapping.get(source_sha)
        if not mapped:
            raise ValueError(f"Image source is absent from normalization map: {source_sha}")
        suffix = Path(mapped["source"]["path"]).suffix.lower()
        raw_url = f"/storage/model-files/old_erp_catalog_{source_sha[:24]}{suffix}"
        result[(image_type, raw_url)] = (source_sha, mapped["normalized"])
    return result


def assert_raw_relations(
    models: list[Model], mapping: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    relation_count = 0
    for model in models:
        expected = _source_relation_map(model, mapping)
        actual = {(str(row.image_type), str(row.file_url)): row for row in model.images or []}
        if set(actual) != set(expected):
            raise ValueError(f"Raw image relations changed for model {model.id}")
        if any(row.file_data is not None for row in actual.values()):
            raise ValueError(f"Unexpected database image bytes for model {model.id}")
        relation_count += len(actual)
    if relation_count != EXPECTED_RELATIONS:
        raise ValueError(f"Expected {EXPECTED_RELATIONS} image relations, found {relation_count}")
    return {"models": len(models), "raw_relations": relation_count}


def stage_normalized_media(
    mapping: dict[str, dict[str, Any]], asset_root: Path
) -> tuple[dict[str, dict[str, Any]], list[Path], list[Path]]:
    target_root = Path(settings.MODEL_FILES_DIR).resolve()
    target_root.mkdir(parents=True, exist_ok=True)
    thumb_root = target_root / "_thumbs"
    prepared: dict[str, dict[str, Any]] = {}
    created_files: list[Path] = []
    created_thumbs: list[Path] = []
    try:
        for source_sha, row in sorted(mapping.items()):
            spec = row["normalized"]
            source = safe_asset(asset_root, spec["path"])
            validate_normalized_image(source, spec)
            filename = Path(spec["path"]).name
            target = (target_root / filename).resolve()
            if target.parent != target_root:
                raise ValueError(f"Unsafe target normalized path: {target}")
            if target.exists():
                validate_normalized_image(target, spec)
            else:
                temporary = target.with_name(f".{target.name}.tmp-{os.getpid()}")
                shutil.copyfile(source, temporary)
                validate_normalized_image(temporary, spec)
                os.replace(temporary, target)
                created_files.append(target)
            content = target.read_bytes()
            for size in (160, 320):
                thumb = thumb_root / f"{size}_{filename}.webp"
                existed = thumb.exists()
                prebuild_webp_thumbnails(
                    content,
                    thumbnail_root=thumb_root,
                    source_file_name=filename,
                    sizes=(size,),
                )
                if not existed:
                    created_thumbs.append(thumb)
            prepared[source_sha] = {
                "file_url": f"/storage/model-files/{filename}",
                "file_name": filename,
                "content_type": "image/webp",
            }
        return prepared, created_files, created_thumbs
    except Exception:
        for path in reversed(created_thumbs + created_files):
            try:
                path.unlink()
            except OSError:
                pass
        raise


def apply_relations(
    db,
    models: list[Model],
    mapping: dict[str, dict[str, Any]],
    prepared: dict[str, dict[str, Any]],
    importer: User,
) -> int:
    changed_relations = 0
    for model in models:
        expected = _source_relation_map(model, mapping)
        actual = {(str(row.image_type), str(row.file_url)): row for row in model.images or []}
        normalized_primary = None
        normalized_material = []
        for relation, (source_sha, spec) in expected.items():
            image = actual[relation]
            target = prepared[source_sha]
            image.file_url = target["file_url"]
            image.file_name = target["file_name"]
            image.content_type = target["content_type"]
            image.file_data = None
            changed_relations += 1
            if relation[0] == "model":
                normalized_primary = spec["sha256"]
            else:
                normalized_material.append(spec["sha256"])
        details = copy.deepcopy(model.details_json)
        details["old_erp_catalog_sync"]["image_normalization"] = {
            "kind": "lossless_webp",
            "pixel_identical": True,
            "normalization_map_sha256": EXPECTED_MAP_SHA256,
            "primary_image_sha256": normalized_primary,
            "material_image_sha256": normalized_material,
        }
        model.details_json = details
        flag_modified(model, "details_json")
    db.flush()
    audit = log_action(
        db,
        importer,
        AUDIT_ACTION,
        "ModelImage",
        None,
        new_value={
            "source_key": SOURCE_KEY,
            "source_manifest_sha256": EXPECTED_SOURCE_MANIFEST_SHA256,
            "normalization_map_sha256": EXPECTED_MAP_SHA256,
            "models": EXPECTED_MODELS,
            "relations": EXPECTED_RELATIONS,
            "source_images": EXPECTED_SOURCE_IMAGES,
            "normalized_files": EXPECTED_NORMALIZED_FILES,
            "pixel_identical": True,
        },
    )
    if changed_relations != EXPECTED_RELATIONS:
        raise ValueError(f"Unexpected changed relation count: {changed_relations}")
    return int(audit.id)


def verify_normalized_relations(
    models: list[Model], mapping: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    relations = 0
    files: set[str] = set()
    for model in models:
        expected_sources = _source_relation_map(model, mapping)
        expected = {}
        for (image_type, _), (source_sha, spec) in expected_sources.items():
            filename = Path(spec["path"]).name
            expected[(image_type, f"/storage/model-files/{filename}")] = source_sha
        actual = {(str(row.image_type), str(row.file_url)): row for row in model.images or []}
        if set(actual) != set(expected):
            raise ValueError(f"Normalized image relations differ for model {model.id}")
        provenance = (model.details_json or {}).get("old_erp_catalog_sync", {})
        normalization = provenance.get("image_normalization")
        if (
            not isinstance(normalization, dict)
            or normalization.get("normalization_map_sha256") != EXPECTED_MAP_SHA256
            or normalization.get("pixel_identical") is not True
        ):
            raise ValueError(f"Normalization provenance differs for model {model.id}")
        for relation, image in actual.items():
            source_sha = expected[relation]
            spec = mapping[source_sha]["normalized"]
            if image.file_data is not None or image.content_type != "image/webp":
                raise ValueError(f"Normalized image metadata differs for model {model.id}")
            filename = image.file_url.removeprefix("/storage/model-files/")
            target = Path(settings.MODEL_FILES_DIR) / filename
            validate_normalized_image(target, spec)
            for size in (160, 320):
                thumb = Path(settings.MODEL_FILES_DIR) / "_thumbs" / f"{size}_{filename}.webp"
                if not thumb.is_file() or thumb.stat().st_size <= 0:
                    raise ValueError(f"Thumbnail is missing: {thumb}")
                with Image.open(thumb) as preview:
                    preview.verify()
            files.add(filename)
            relations += 1
    if relations != EXPECTED_RELATIONS or len(files) != EXPECTED_NORMALIZED_FILES:
        raise ValueError(
            f"Normalized totals failed: relations={relations}, unique_files={len(files)}"
        )
    return {"models": len(models), "relations": relations, "normalized_files": len(files)}


def run(args: argparse.Namespace) -> dict[str, Any]:
    _, mapping = validate_map(args.input, args.asset_root)
    base = {
        "mode": args.mode,
        "normalization_map_sha256": EXPECTED_MAP_SHA256,
        "source_manifest_sha256": EXPECTED_SOURCE_MANIFEST_SHA256,
        "models": EXPECTED_MODELS,
        "relations": EXPECTED_RELATIONS,
        "normalized_files": EXPECTED_NORMALIZED_FILES,
        "pixel_identical": True,
    }
    if args.mode == "validate":
        return {**base, "validated": True}
    with SessionLocal() as db:
        importer = assert_production_guard(db, args.imported_by)
        models = target_models(db)
        base["imported_by"] = {"id": importer.id, "name": importer.name}
        if args.mode == "dry-run":
            state = assert_raw_relations(models, mapping)
            db.rollback()
            return {**base, "planned_updates": EXPECTED_RELATIONS, "state": state}
        if args.mode == "verify":
            state = verify_normalized_relations(models, mapping)
            db.rollback()
            return {**base, "state": state}
        if args.confirm != CONFIRMATION:
            raise ValueError("Apply confirmation phrase is missing or incorrect")
        raw_state = assert_raw_relations(models, mapping)
        relation_count_before = int(db.query(func.count(ModelImage.id)).scalar() or 0)
        prepared, created_files, created_thumbs = stage_normalized_media(mapping, args.asset_root)
        try:
            audit_id = apply_relations(db, models, mapping, prepared, importer)
            normalized_state = verify_normalized_relations(models, mapping)
            relation_count_after = int(db.query(func.count(ModelImage.id)).scalar() or 0)
            if relation_count_after != relation_count_before:
                raise ValueError("Image normalization changed the relation count")
            db.commit()
        except Exception:
            db.rollback()
            for path in reversed(created_thumbs + created_files):
                try:
                    path.unlink()
                except OSError:
                    pass
            raise
    with SessionLocal() as verify_db:
        assert_production_guard(verify_db, args.imported_by)
        committed_state = verify_normalized_relations(target_models(verify_db), mapping)
        audit = verify_db.execute(
            text("select id, action, user_id, entry_hash from audit_logs where id=:id"),
            {"id": audit_id},
        ).mappings().one()
        if audit["action"] != AUDIT_ACTION or audit["user_id"] != args.imported_by or not audit["entry_hash"]:
            raise ValueError("Normalization audit readback failed")
        verify_db.rollback()
    return {
        **base,
        "committed": True,
        "raw_state": raw_state,
        "state": committed_state,
        "created_media_files": len(created_files),
        "created_thumbnail_files": len(created_thumbs),
        "audit": {"id": audit_id, "entry_hash": audit["entry_hash"]},
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--asset-root", type=Path, required=True)
    parser.add_argument("--imported-by", type=int, default=EXPECTED_IMPORTER_ID)
    parser.add_argument("--mode", choices=("validate", "dry-run", "apply", "verify"), default="validate")
    parser.add_argument("--confirm")
    return parser.parse_args()


if __name__ == "__main__":
    print(json.dumps(run(parse_args()), ensure_ascii=False, indent=2, sort_keys=True))
