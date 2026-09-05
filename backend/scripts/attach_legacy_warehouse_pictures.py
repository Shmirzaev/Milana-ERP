"""Attach original sticker photos to hidden legacy warehouse models.

The operation is manifest-bound and dry-run by default. It creates only
``ModelImage`` rows with the warehouse-only ``warehouse_package`` type and
copies the verified original bytes into model storage. It never changes a
catalogue picture, model, variant, package, quantity, size, or QR code.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from PIL import Image
from sqlalchemy import text

from app.core.config import settings
from app.db.session import SessionLocal
from app.models import Model, ModelImage, Package, User
from app.services.audit import log_action


EXPECTED_ALEMBIC_HEAD = "0113_variant_selling_price"
EXPECTED_IMAGE_TYPE = "warehouse_package"
EXPECTED_MODEL_COUNT = 257
EXPECTED_PACKAGE_COUNT = 467
EXPECTED_WAREHOUSE_ID = 8
CONFIRMATION = "ATTACH_257_LEGACY_WAREHOUSE_PICTURES"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_manifest(path: Path, expected_hash: str) -> dict[str, Any]:
    actual_hash = sha256(path)
    if actual_hash != expected_hash:
        raise ValueError(f"Picture manifest SHA-256 changed: {actual_hash}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("rows") or []
    summary = payload.get("summary") or {}
    if payload.get("version") != 1 or payload.get("image_type") != EXPECTED_IMAGE_TYPE:
        raise ValueError("Picture manifest identity guard failed")
    if payload.get("expected_alembic_head") != EXPECTED_ALEMBIC_HEAD:
        raise ValueError("Picture manifest Alembic guard failed")
    if len(rows) != EXPECTED_MODEL_COUNT or summary.get("models") != EXPECTED_MODEL_COUNT:
        raise ValueError("Picture manifest model count changed")
    if summary.get("package_rows") != EXPECTED_PACKAGE_COUNT:
        raise ValueError("Picture manifest package count changed")
    if len({int(row["model_id"]) for row in rows}) != len(rows):
        raise ValueError("Picture manifest repeats a model")
    if len({str(row["file_name"]) for row in rows}) != summary.get("unique_files"):
        raise ValueError("Picture manifest unique file count changed")
    package_ids = [int(package_id) for row in rows for package_id in row["warehouse_package_ids"]]
    if len(package_ids) != EXPECTED_PACKAGE_COUNT or len(set(package_ids)) != len(package_ids):
        raise ValueError("Picture manifest package coverage changed")
    for row in rows:
        file_name = str(row.get("file_name") or "")
        if not file_name or Path(file_name).name != file_name:
            raise ValueError(f"Unsafe picture filename for model {row.get('model_id')}")
        if row.get("file_url") != f"/storage/model-files/{file_name}":
            raise ValueError(f"Picture URL mismatch for model {row.get('model_id')}")
        if row.get("expected_warehouse_package_images") != []:
            raise ValueError(f"Existing-image guard changed for model {row.get('model_id')}")
    return payload


def verify_source(source: Path, row: dict[str, Any]) -> None:
    if not source.is_file():
        raise ValueError(f"Source picture is missing: {source.name}")
    if source.stat().st_size != int(row["source_size_bytes"]) or sha256(source) != row["source_sha256"]:
        raise ValueError(f"Source picture changed: {source.name}")
    with Image.open(source) as image:
        image.verify()
    with Image.open(source) as image:
        if image.size != (int(row["source_width"]), int(row["source_height"])):
            raise ValueError(f"Source picture dimensions changed: {source.name}")


def assert_database(db, args: argparse.Namespace) -> User:
    parsed = urlparse(settings.DATABASE_URL.replace("postgresql+psycopg2://", "postgresql://", 1))
    database = str(db.execute(text("select current_database()" )).scalar() or "")
    heads = [str(row[0]) for row in db.execute(text("select version_num from alembic_version order by version_num"))]
    if (parsed.hostname or "").casefold() != args.expected_database_host.casefold() or database != args.expected_database_name:
        raise ValueError("Production database identity guard failed")
    if heads != [EXPECTED_ALEMBIC_HEAD]:
        raise ValueError(f"Expected Alembic {EXPECTED_ALEMBIC_HEAD}, found {heads}")
    actor = db.get(User, args.actor_id)
    permissions = set((actor.role.permissions if actor and actor.role else []) + ((actor.extra_permissions or []) if actor else []))
    if not actor or not actor.is_active or "*" not in permissions:
        raise ValueError("Picture-import actor is not an active wildcard administrator")
    return actor


def current_warehouse_images(db, model_id: int) -> list[dict[str, Any]]:
    images = (
        db.query(ModelImage)
        .filter(ModelImage.model_id == model_id, ModelImage.image_type == EXPECTED_IMAGE_TYPE)
        .order_by(ModelImage.id)
        .all()
    )
    return [
        {
            "file_url": image.file_url,
            "file_name": image.file_name,
            "content_type": image.content_type,
            "is_primary": bool(image.is_primary),
        }
        for image in images
    ]


def validate_database_rows(db, payload: dict[str, Any]) -> bool:
    applied = 0
    for row in payload["rows"]:
        model_id = int(row["model_id"])
        model = db.get(Model, model_id)
        if not model or model.code != row["model_code"] or model.name != row["model_name"]:
            raise ValueError(f"Model identity changed for {model_id}")
        if not bool((model.details_json or {}).get("legacy_import")):
            raise ValueError(f"Model {model_id} is no longer a hidden legacy model")
        package_ids = [int(package_id) for package_id in row["warehouse_package_ids"]]
        packages = db.query(Package).filter(Package.id.in_(package_ids)).all()
        if {int(package.id) for package in packages} != set(package_ids):
            raise ValueError(f"Guarded package disappeared for model {model_id}")
        if any(int(package.model_id) != model_id or int(package.warehouse_id or 0) != EXPECTED_WAREHOUSE_ID for package in packages):
            raise ValueError(f"Guarded package changed model or warehouse for {model_id}")
        current = current_warehouse_images(db, model_id)
        expected_applied = [
            {
                "file_url": row["file_url"],
                "file_name": row["file_name"],
                "content_type": row["content_type"],
                "is_primary": False,
            }
        ]
        if current == expected_applied:
            applied += 1
        elif current != row["expected_warehouse_package_images"]:
            raise ValueError(f"Warehouse picture state changed for model {model_id}")
    if applied not in {0, EXPECTED_MODEL_COUNT}:
        raise ValueError(f"Partial picture import detected: {applied}/{EXPECTED_MODEL_COUNT}")
    return applied == EXPECTED_MODEL_COUNT


def copy_verified_sources(payload: dict[str, Any], source_dir: Path, storage_dir: Path) -> list[Path]:
    storage_dir.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    for row in payload["rows"]:
        source = source_dir / row["file_name"]
        target = storage_dir / row["file_name"]
        verify_source(source, row)
        if target.exists():
            if target.stat().st_size != int(row["source_size_bytes"]) or sha256(target) != row["source_sha256"]:
                raise ValueError(f"Storage filename collision: {target.name}")
            continue
        temporary = storage_dir / f".{target.name}.{os.getpid()}.tmp"
        try:
            shutil.copyfile(source, temporary)
            if sha256(temporary) != row["source_sha256"]:
                raise ValueError(f"Copied picture changed: {target.name}")
            os.replace(temporary, target)
            created.append(target)
        finally:
            temporary.unlink(missing_ok=True)
    return created


def execute(args: argparse.Namespace) -> dict[str, Any]:
    manifest = Path(args.manifest).resolve()
    source_dir = Path(args.source_dir).resolve()
    storage_dir = Path(args.storage_dir).resolve()
    payload = read_manifest(manifest, args.manifest_sha256)
    for row in payload["rows"]:
        verify_source(source_dir / row["file_name"], row)
    created_files: list[Path] = []
    with SessionLocal() as db:
        actor = assert_database(db, args)
        already_applied = validate_database_rows(db, payload)
        if already_applied:
            db.rollback()
            return {"status": "already_applied", "models": EXPECTED_MODEL_COUNT, "files_created": 0}
        if not args.apply:
            db.rollback()
            return {"status": "dry_run", "models": EXPECTED_MODEL_COUNT, "package_rows": EXPECTED_PACKAGE_COUNT}
        if args.confirm != CONFIRMATION:
            raise ValueError("Exact production confirmation phrase is required")
        try:
            created_files = copy_verified_sources(payload, source_dir, storage_dir)
            for row in payload["rows"]:
                db.add(
                    ModelImage(
                        model_id=int(row["model_id"]),
                        file_url=row["file_url"],
                        file_name=row["file_name"],
                        content_type=row["content_type"],
                        file_data=None,
                        image_type=EXPECTED_IMAGE_TYPE,
                        is_primary=False,
                    )
                )
            db.flush()
            log_action(
                db,
                actor,
                "legacy_warehouse_pictures_attached",
                "model_images",
                old_value={"warehouse_package_images": 0},
                new_value={
                    "warehouse_package_images": EXPECTED_MODEL_COUNT,
                    "warehouse_package_rows": EXPECTED_PACKAGE_COUNT,
                    "manifest_sha256": args.manifest_sha256,
                    "original_bytes_preserved": True,
                },
            )
            db.commit()
        except Exception:
            db.rollback()
            for path in created_files:
                path.unlink(missing_ok=True)
            raise
        if not validate_database_rows(db, payload):
            raise RuntimeError("Post-commit picture verification failed")
        for row in payload["rows"]:
            target = storage_dir / row["file_name"]
            if not target.is_file() or sha256(target) != row["source_sha256"]:
                raise RuntimeError(f"Post-commit storage verification failed: {target.name}")
        db.rollback()
        return {
            "status": "applied",
            "models": EXPECTED_MODEL_COUNT,
            "package_rows": EXPECTED_PACKAGE_COUNT,
            "files_created": len(created_files),
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--source-dir", required=True)
    parser.add_argument("--storage-dir", default="/app/storage/model_files")
    parser.add_argument("--expected-database-host", required=True)
    parser.add_argument("--expected-database-name", required=True)
    parser.add_argument("--actor-id", type=int, default=1)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    return parser.parse_args()


if __name__ == "__main__":
    print(json.dumps(execute(parse_args()), sort_keys=True))
