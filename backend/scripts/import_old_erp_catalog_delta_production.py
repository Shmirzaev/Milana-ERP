"""Guarded production import for the reviewed 2026-09-02 old-ERP catalog delta.

Validation is the default. Database dry-run, apply, and committed readback are
separate modes. Apply is blocked unless the exact reviewed manifest, production
database, migration head, absent identities/codes, and confirmation phrase all
match.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from PIL import Image, ImageFile, ImageOps
from sqlalchemy import func, text

from app.core.config import settings
from app.db.session import SessionLocal
from app.models import Model, ModelColor, ModelImage, ModelSize, User
from app.services.audit import log_action


EXPECTED_MANIFEST_SHA256 = "2bb7f5469ad2e85f003fbdcc4540098fededdf006715490ca612378503e9f418"
EXPECTED_MODELS = 261
EXPECTED_PRIMARY_IMAGES = 261
EXPECTED_MATERIAL_IMAGES = 275
EXPECTED_SIZES = 1610
EXPECTED_COLORS = 265
EXPECTED_DATABASE_HOST = "172.16.10.3"
EXPECTED_DATABASE_NAME = "erp"
EXPECTED_ALEMBIC_HEAD = "0112_price_calc_requests"
EXPECTED_IMPORTER_ID = 1
EXPECTED_EXCLUDED = {("00000000", "5889"), ("XJ3062", "5709")}
EXPECTED_UNRESOLVED = {("PJ1211", "5746")}
CONFIRMATION = "APPLY-261-OLD-ERP-CATALOG-DELTA-TO-PRODUCTION"
SOURCE_KEY = "old-erp-catalog-full-delta-2026-09-02"
AUDIT_ACTION = "old_erp_catalog_full_delta_import"
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
    result = " ".join(unicodedata.normalize("NFKC", str(value or "")).strip().split())
    return result[:limit] if limit else result


def normalized_base(value: Any) -> str:
    return "".join(ch for ch in clean(value).upper().translate(CONFUSABLES) if ch.isalnum())


def normalized_variant(value: Any) -> str:
    value = re.sub(r"^V[\s_-]*", "", clean(value).upper().translate(CONFUSABLES), count=1)
    key = "".join(ch for ch in value if ch.isalnum())
    return str(int(key)) if key.isdigit() else key


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_asset(root: Path, relative: str) -> Path:
    resolved_root = root.resolve()
    path = (resolved_root / relative).resolve()
    if not path.is_file() or resolved_root not in path.parents:
        raise ValueError(f"Unsafe or missing bundled media path: {relative!r}")
    return path


def validate_image(path: Path, spec: dict[str, Any]) -> dict[str, Any]:
    digest = file_sha256(path)
    size = path.stat().st_size
    if digest != clean(spec.get("sha256")).lower() or size != int(spec.get("bytes") or -1):
        raise ValueError(f"Image bytes changed: {path}")
    try:
        ImageFile.LOAD_TRUNCATED_IMAGES = True
        with Image.open(path) as image:
            image.load()
            width, height = ImageOps.exif_transpose(image).size
    except OSError as exc:
        raise ValueError(f"Image cannot be decoded: {path}: {exc}") from exc
    if (width, height) != (int(spec["width"]), int(spec["height"])):
        raise ValueError(f"Image dimensions changed: {path}")
    return {
        "sha256": digest,
        "bytes": size,
        "width": width,
        "height": height,
        "content_type": clean(spec.get("content_type")),
    }


def _review_identity(row: dict[str, Any]) -> tuple[str, str]:
    identity = row.get("normalized_identity") or []
    if len(identity) != 2:
        return "", ""
    return normalized_base(identity[0]), normalized_variant(identity[1])


def validate_manifest(path: Path, asset_root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    actual_hash = file_sha256(path)
    if actual_hash != EXPECTED_MANIFEST_SHA256:
        raise ValueError(f"Manifest SHA-256 changed: {actual_hash}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("models") if isinstance(payload, dict) else None
    if payload.get("version") != 1 or payload.get("package_kind") != "old_erp_catalog_full_delta_2026_09_02":
        raise ValueError("Unexpected manifest version or package kind")
    if not isinstance(rows, list) or len(rows) != EXPECTED_MODELS:
        raise ValueError(f"Expected {EXPECTED_MODELS} models")
    expected_counts = {
        "expected_models": EXPECTED_MODELS,
        "expected_primary_images": EXPECTED_PRIMARY_IMAGES,
        "expected_material_images": EXPECTED_MATERIAL_IMAGES,
        "expected_sizes": EXPECTED_SIZES,
        "expected_colors": EXPECTED_COLORS,
    }
    for key, expected in expected_counts.items():
        if int(payload.get(key) or -1) != expected:
            raise ValueError(f"Manifest {key} changed")
    if {_review_identity(row) for row in payload.get("excluded") or []} != EXPECTED_EXCLUDED:
        raise ValueError("Excluded identity list changed")
    if {_review_identity(row) for row in payload.get("unresolved") or []} != EXPECTED_UNRESOLVED:
        raise ValueError("Unresolved identity list changed")

    identities: set[tuple[str, str]] = set()
    codes: set[str] = set()
    primary_count = material_count = size_count = color_count = 0
    for row in rows:
        identity = (
            normalized_base(row.get("model_number")),
            normalized_variant(row.get("variant_number")),
        )
        code = normalized_base(row.get("code"))
        if not all(identity) or identity in identities:
            raise ValueError(f"Invalid or duplicate model identity: {identity}")
        if not code or code in codes:
            raise ValueError(f"Invalid or duplicate target code: {row.get('code')!r}")
        if not clean(row.get("name")) or not row.get("sizes"):
            raise ValueError(f"Name or sizes missing for {identity}")
        identities.add(identity)
        codes.add(code)
        primary = row.get("primary_image")
        materials = row.get("material_images") or []
        if not isinstance(primary, dict) or not isinstance(materials, list):
            raise ValueError(f"Image manifest invalid for {identity}")
        validate_image(safe_asset(asset_root, primary["path"]), primary)
        primary_count += 1
        seen_material: set[str] = set()
        for spec in materials:
            validate_image(safe_asset(asset_root, spec["path"]), spec)
            if spec["sha256"] in seen_material:
                raise ValueError(f"Duplicate material image for {identity}")
            seen_material.add(spec["sha256"])
            material_count += 1
        sizes = [clean(value, limit=32) for value in row.get("sizes") or []]
        colors = [clean(value, limit=64) for value in row.get("colors") or []]
        if not all(sizes) or len(sizes) != len(set(sizes)):
            raise ValueError(f"Invalid sizes for {identity}")
        if not all(colors) or len(colors) != len(set(colors)):
            raise ValueError(f"Invalid colors for {identity}")
        size_count += len(sizes)
        color_count += len(colors)
    actual_counts = (primary_count, material_count, size_count, color_count)
    expected = (
        EXPECTED_PRIMARY_IMAGES,
        EXPECTED_MATERIAL_IMAGES,
        EXPECTED_SIZES,
        EXPECTED_COLORS,
    )
    if actual_counts != expected:
        raise ValueError(f"Manifest relationship totals changed: {actual_counts}")
    return payload, rows


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


def _catalog_indexes(db) -> tuple[dict[tuple[str, str], list[int]], dict[str, list[int]], int]:
    exact: dict[tuple[str, str], list[int]] = {}
    codes: dict[str, list[int]] = {}
    rows = db.query(
        Model.id,
        Model.code,
        Model.details_json["general"].label("general_details"),
    ).all()
    for row in rows:
        general = row.general_details if isinstance(row.general_details, dict) else {}
        identity = (
            normalized_base(general.get("model_no") or general.get("modelNo")),
            normalized_variant(general.get("variant_no") or general.get("variantNo")),
        )
        exact.setdefault(identity, []).append(int(row.id))
        codes.setdefault(normalized_base(row.code), []).append(int(row.id))
    return exact, codes, len(rows)


def assert_targets_absent(db, rows: list[dict[str, Any]]) -> dict[str, Any]:
    exact, codes, model_count = _catalog_indexes(db)
    for row in rows:
        identity = (
            normalized_base(row["model_number"]),
            normalized_variant(row["variant_number"]),
        )
        identity_matches = exact.get(identity, [])
        code_matches = codes.get(normalized_base(row["code"]), [])
        if identity_matches or code_matches:
            raise ValueError(
                f"Duplicate target blocked for {identity}: identities={identity_matches}, codes={code_matches}"
            )
    return {"existing_models": model_count, "identity_collisions": 0, "code_collisions": 0}


def _target_filename(spec: dict[str, Any]) -> str:
    suffix = Path(spec["path"]).suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
        raise ValueError(f"Unsupported image extension: {suffix}")
    return f"old_erp_catalog_{spec['sha256'][:24]}{suffix}"


def stage_media(
    rows: list[dict[str, Any]], asset_root: Path
) -> tuple[dict[str, dict[str, Any]], list[Path]]:
    specs: dict[str, dict[str, Any]] = {}
    for row in rows:
        for spec in [row["primary_image"], *(row.get("material_images") or [])]:
            specs[spec["sha256"]] = spec
    target_root = Path(settings.MODEL_FILES_DIR).resolve()
    target_root.mkdir(parents=True, exist_ok=True)
    prepared: dict[str, dict[str, Any]] = {}
    created: list[Path] = []
    try:
        for digest, spec in sorted(specs.items()):
            source = safe_asset(asset_root, spec["path"])
            validate_image(source, spec)
            filename = _target_filename(spec)
            target = (target_root / filename).resolve()
            if target.parent != target_root:
                raise ValueError(f"Unsafe target media path: {target}")
            if target.exists():
                validate_image(target, spec)
            else:
                temporary = target.with_name(f".{target.name}.tmp-{os.getpid()}")
                shutil.copyfile(source, temporary)
                validate_image(temporary, spec)
                os.replace(temporary, target)
                created.append(target)
            prepared[digest] = {
                "file_url": f"/storage/model-files/{filename}",
                "file_name": filename,
                "content_type": spec["content_type"],
            }
        return prepared, created
    except Exception:
        for path in reversed(created):
            try:
                path.unlink()
            except OSError:
                pass
        raise


def _details(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "general": {
            "model_no": row["model_number"],
            "variant_no": row["variant_number"],
            "name": row["name"],
            "product": row.get("product_type"),
        },
        "old_erp_catalog_sync": {
            "source_key": SOURCE_KEY,
            "manifest_sha256": EXPECTED_MANIFEST_SHA256,
            **row["old_erp"],
            "primary_image_sha256": row["primary_image"]["sha256"],
            "material_image_sha256": [spec["sha256"] for spec in row["material_images"]],
        },
    }


def create_models(
    db,
    rows: list[dict[str, Any]],
    importer: User,
    prepared: dict[str, dict[str, Any]],
) -> tuple[list[int], int]:
    created_ids: list[int] = []
    approved_at = datetime.now(timezone.utc)
    for row in rows:
        model = Model(
            code=row["code"],
            name=row["name"],
            catalog_scope="standard",
            factory_code=None,
            category=row.get("category"),
            description=None,
            brand_id=row.get("brand_id"),
            collection_id=row.get("collection_id"),
            product_type=row.get("product_type"),
            season=row.get("season"),
            details_json=_details(row),
            status="approved",
            created_by=importer.id,
            approved_by=importer.id,
            approved_at=approved_at,
            sam_minutes=row.get("sam_minutes") or 0,
        )
        db.add(model)
        db.flush()
        created_ids.append(int(model.id))
        for size in row["sizes"]:
            db.add(ModelSize(model_id=model.id, size=clean(size, limit=32), measurement_json=None))
        for color in row["colors"]:
            db.add(ModelColor(model_id=model.id, color_name=clean(color, limit=64), color_code=None))
        primary = prepared[row["primary_image"]["sha256"]]
        db.add(
            ModelImage(
                model_id=model.id,
                **primary,
                file_data=None,
                image_type="model",
                is_primary=True,
            )
        )
        for spec in row["material_images"]:
            db.add(
                ModelImage(
                    model_id=model.id,
                    **prepared[spec["sha256"]],
                    file_data=None,
                    image_type="material",
                    is_primary=False,
                )
            )
    db.flush()
    audit = log_action(
        db,
        importer,
        AUDIT_ACTION,
        "Model",
        None,
        new_value={
            "source_key": SOURCE_KEY,
            "manifest_sha256": EXPECTED_MANIFEST_SHA256,
            "models": EXPECTED_MODELS,
            "primary_images": EXPECTED_PRIMARY_IMAGES,
            "material_images": EXPECTED_MATERIAL_IMAGES,
            "sizes": EXPECTED_SIZES,
            "colors": EXPECTED_COLORS,
            "created_model_ids": created_ids,
            "excluded_identities": sorted([list(value) for value in EXPECTED_EXCLUDED]),
            "unresolved_identities": sorted([list(value) for value in EXPECTED_UNRESOLVED]),
        },
    )
    return created_ids, int(audit.id)


def verify_targets(db, rows: list[dict[str, Any]], imported_by: int) -> dict[str, Any]:
    exact, _, _ = _catalog_indexes(db)
    model_ids: list[int] = []
    totals = {"primary_images": 0, "material_images": 0, "sizes": 0, "colors": 0}
    for row in rows:
        identity = (
            normalized_base(row["model_number"]),
            normalized_variant(row["variant_number"]),
        )
        matches = exact.get(identity, [])
        if len(matches) != 1:
            raise ValueError(f"Readback identity count is {len(matches)} for {identity}")
        model = db.get(Model, matches[0])
        provenance = (model.details_json or {}).get("old_erp_catalog_sync")
        if any(
            (
                model.code != row["code"],
                model.name != row["name"],
                model.status != "approved",
                model.created_by != imported_by,
                model.approved_by != imported_by,
                not model.approved_at,
                not isinstance(provenance, dict),
                provenance.get("source_key") != SOURCE_KEY if isinstance(provenance, dict) else True,
                provenance.get("manifest_sha256") != EXPECTED_MANIFEST_SHA256
                if isinstance(provenance, dict)
                else True,
            )
        ):
            raise ValueError(f"Model readback mismatch: {identity}")
        expected_sizes = set(row["sizes"])
        expected_colors = set(row["colors"])
        actual_sizes = {clean(value.size) for value in model.sizes or []}
        actual_colors = {clean(value.color_name) for value in model.colors or []}
        if actual_sizes != expected_sizes or actual_colors != expected_colors:
            raise ValueError(f"Size/color readback mismatch: {identity}")
        primary = [img for img in model.images or [] if img.image_type == "model" and img.is_primary]
        material = [img for img in model.images or [] if img.image_type == "material" and not img.is_primary]
        if len(primary) != 1 or len(material) != len(row["material_images"]):
            raise ValueError(f"Image relation readback mismatch: {identity}")
        expected_relations = {
            ("model", f"/storage/model-files/{_target_filename(row['primary_image'])}"): row[
                "primary_image"
            ],
            **{
                ("material", f"/storage/model-files/{_target_filename(spec)}"): spec
                for spec in row["material_images"]
            },
        }
        actual_relations = {
            (str(image.image_type), str(image.file_url)): image for image in [*primary, *material]
        }
        if set(actual_relations) != set(expected_relations):
            raise ValueError(f"Image URL readback mismatch: {identity}")
        for relation, image in actual_relations.items():
            spec = expected_relations[relation]
            if image.file_data is not None or not image.file_url.startswith("/storage/model-files/"):
                raise ValueError(f"Image storage readback mismatch: {identity}")
            filename = image.file_url.removeprefix("/storage/model-files/")
            if Path(filename).name != filename:
                raise ValueError(f"Unsafe image URL: {identity}")
            validate_image(Path(settings.MODEL_FILES_DIR) / filename, spec)
        model_ids.append(int(model.id))
        totals["primary_images"] += len(primary)
        totals["material_images"] += len(material)
        totals["sizes"] += len(actual_sizes)
        totals["colors"] += len(actual_colors)
    expected_totals = {
        "primary_images": EXPECTED_PRIMARY_IMAGES,
        "material_images": EXPECTED_MATERIAL_IMAGES,
        "sizes": EXPECTED_SIZES,
        "colors": EXPECTED_COLORS,
    }
    if totals != expected_totals or len(set(model_ids)) != EXPECTED_MODELS:
        raise ValueError(f"Readback totals failed: {totals}")
    return {"models": len(model_ids), "model_ids": sorted(model_ids), **totals}


def run(args: argparse.Namespace) -> dict[str, Any]:
    payload, rows = validate_manifest(args.input, args.asset_root)
    base = {
        "mode": args.mode,
        "manifest_sha256": EXPECTED_MANIFEST_SHA256,
        "models": EXPECTED_MODELS,
        "primary_images": EXPECTED_PRIMARY_IMAGES,
        "material_images": EXPECTED_MATERIAL_IMAGES,
        "sizes": EXPECTED_SIZES,
        "colors": EXPECTED_COLORS,
        "excluded": len(payload["excluded"]),
        "unresolved": len(payload["unresolved"]),
    }
    if args.mode == "validate":
        return {**base, "validated": True}
    with SessionLocal() as db:
        importer = assert_production_guard(db, args.imported_by)
        base["imported_by"] = {"id": importer.id, "name": importer.name}
        if args.mode == "dry-run":
            target_guard = assert_targets_absent(db, rows)
            db.rollback()
            return {**base, "planned_creates": EXPECTED_MODELS, "target_guard": target_guard}
        if args.mode == "verify":
            state = verify_targets(db, rows, importer.id)
            db.rollback()
            return {**base, "state": state}
        if args.confirm != CONFIRMATION:
            raise ValueError("Apply confirmation phrase is missing or incorrect")
        target_guard = assert_targets_absent(db, rows)
        counts_before = {
            "models": int(db.query(func.count(Model.id)).scalar() or 0),
            "images": int(db.query(func.count(ModelImage.id)).scalar() or 0),
            "sizes": int(db.query(func.count(ModelSize.id)).scalar() or 0),
            "colors": int(db.query(func.count(ModelColor.id)).scalar() or 0),
        }
        prepared, created_files = stage_media(rows, args.asset_root)
        try:
            created_ids, audit_id = create_models(db, rows, importer, prepared)
            state = verify_targets(db, rows, importer.id)
            counts_after = {
                "models": int(db.query(func.count(Model.id)).scalar() or 0),
                "images": int(db.query(func.count(ModelImage.id)).scalar() or 0),
                "sizes": int(db.query(func.count(ModelSize.id)).scalar() or 0),
                "colors": int(db.query(func.count(ModelColor.id)).scalar() or 0),
            }
            expected_deltas = {
                "models": EXPECTED_MODELS,
                "images": EXPECTED_PRIMARY_IMAGES + EXPECTED_MATERIAL_IMAGES,
                "sizes": EXPECTED_SIZES,
                "colors": EXPECTED_COLORS,
            }
            actual_deltas = {
                key: counts_after[key] - counts_before[key] for key in counts_before
            }
            if actual_deltas != expected_deltas:
                raise ValueError(
                    f"Catalog count deltas failed: expected={expected_deltas}, actual={actual_deltas}"
                )
            db.commit()
        except Exception:
            db.rollback()
            for path in reversed(created_files):
                try:
                    path.unlink()
                except OSError:
                    pass
            raise
    with SessionLocal() as verify_db:
        assert_production_guard(verify_db, args.imported_by)
        committed_state = verify_targets(verify_db, rows, args.imported_by)
        audit = verify_db.execute(
            text("select id, action, entity_type, user_id, entry_hash from audit_logs where id=:id"),
            {"id": audit_id},
        ).mappings().one()
        if audit["action"] != AUDIT_ACTION or audit["user_id"] != args.imported_by or not audit["entry_hash"]:
            raise ValueError("Committed audit record readback failed")
        verify_db.rollback()
    return {
        **base,
        "committed": True,
        "created_model_ids": created_ids,
        "created_media_files": [str(path) for path in created_files],
        "target_guard": target_guard,
        "counts_before": counts_before,
        "counts_after": counts_after,
        "audit": {"id": audit_id, "entry_hash": audit["entry_hash"]},
        "state": committed_state,
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
