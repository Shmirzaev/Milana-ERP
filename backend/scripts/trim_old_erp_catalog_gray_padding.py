"""Remove exact #808080 tail padding from guarded old-ERP catalogue images.

The original normalized files remain untouched. The script creates lossless
cropped derivatives, updates only the affected ``ModelImage`` file references,
and records one audit event. Dry-run is the default.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from PIL import Image, ImageChops
from sqlalchemy import text

from app.core.config import settings
from app.db.session import SessionLocal
from app.models import Model, ModelImage, User
from app.services.audit import log_action
from app.services.image_storage import prebuild_webp_thumbnails


EXPECTED_ALEMBIC_HEAD = "0113_variant_selling_price"
EXPECTED_HQ_FILES = 323
EXPECTED_SOURCE_FILES = 70
EXPECTED_RELATIONS = 145
EXPECTED_MODELS = 143
EXPECTED_IMAGE_TYPES = {"material": 5, "model": 140}
EXPECTED_SOURCE_IDENTITY = "929368015299246af0dc4779af34cb1985e28a692818e48c23d0dafeb189b81a"
EXPECTED_REFERENCE_IDENTITY = "15940c99087488b807e04c4869884e6f45c6474a7556a3fb1101c0edbe7546da"
SOURCE_PREFIX = "old_erp_catalog_hq_"
TARGET_PREFIX = "old_erp_catalog_trim_"
GRAY = (128, 128, 128)
MIN_GRAY_ROWS = 16
THUMBNAIL_SIZES = (160, 320, 640)
CONFIRMATION = "TRIM_70_OLD_ERP_CATALOG_GRAY_TAILS"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def pixel_sha256(image: Image.Image) -> str:
    digest = hashlib.sha256()
    digest.update(f"{image.mode}:{image.width}x{image.height}:".encode())
    digest.update(image.tobytes())
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def gray_tail_rows(image: Image.Image) -> int:
    rgb = image if image.mode == "RGB" else image.convert("RGB")
    try:
        gray = Image.new("RGB", rgb.size, GRAY)
        try:
            bounds = ImageChops.difference(rgb, gray).getbbox()
        finally:
            gray.close()
        return rgb.height if bounds is None else rgb.height - int(bounds[3])
    finally:
        if rgb is not image:
            rgb.close()


def inspect_source(path: Path) -> dict[str, Any] | None:
    with Image.open(path) as opened:
        opened.load()
        image = opened.convert("RGB")
    try:
        padding = gray_tail_rows(image)
        if padding < MIN_GRAY_ROWS:
            return None
        content_height = image.height - padding
        if content_height <= 0:
            raise ValueError(f"Image is entirely padding: {path.name}")
        cropped = image.crop((0, 0, image.width, content_height))
        try:
            cropped_hash = pixel_sha256(cropped)
        finally:
            cropped.close()
        source_hash = file_sha256(path)
        return {
            "name": path.name,
            "bytes": path.stat().st_size,
            "sha256": source_hash,
            "width": image.width,
            "height": image.height,
            "bottom_gray_rows": padding,
            "content_height": content_height,
            "cropped_pixel_sha256": cropped_hash,
            "source_url": f"/storage/model-files/{path.name}",
            "target_name": f"{TARGET_PREFIX}{source_hash[:24]}.webp",
            "target_url": f"/storage/model-files/{TARGET_PREFIX}{source_hash[:24]}.webp",
        }
    finally:
        image.close()


def source_identity_rows(specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keys = (
        "name",
        "bytes",
        "sha256",
        "width",
        "height",
        "bottom_gray_rows",
        "content_height",
        "cropped_pixel_sha256",
    )
    return [{key: row[key] for key in keys} for row in specs]


def inspect_sources(storage_dir: Path) -> list[dict[str, Any]]:
    paths = sorted(storage_dir.glob(f"{SOURCE_PREFIX}*.webp"))
    if len(paths) != EXPECTED_HQ_FILES:
        raise ValueError(f"Expected {EXPECTED_HQ_FILES} normalized files, found {len(paths)}")
    specs = [spec for path in paths if (spec := inspect_source(path)) is not None]
    if len(specs) != EXPECTED_SOURCE_FILES:
        raise ValueError(f"Expected {EXPECTED_SOURCE_FILES} padded files, found {len(specs)}")
    identity = canonical_sha256(source_identity_rows(specs))
    if identity != EXPECTED_SOURCE_IDENTITY:
        raise ValueError(f"Padded source identity changed: {identity}")
    return specs


def validate_source(path: Path, spec: dict[str, Any]) -> None:
    if not path.is_file():
        raise ValueError(f"Source image is missing: {path.name}")
    if path.stat().st_size != int(spec["bytes"]) or file_sha256(path) != spec["sha256"]:
        raise ValueError(f"Source image changed: {path.name}")
    current = inspect_source(path)
    if current is None or any(
        current[key] != spec[key]
        for key in (
            "width",
            "height",
            "bottom_gray_rows",
            "content_height",
            "cropped_pixel_sha256",
        )
    ):
        raise ValueError(f"Source image pixels changed: {path.name}")


def validate_target(path: Path, spec: dict[str, Any]) -> None:
    if not path.is_file():
        raise ValueError(f"Trimmed image is missing: {path.name}")
    with Image.open(path) as opened:
        opened.load()
        image = opened.convert("RGB")
    try:
        expected_size = (int(spec["width"]), int(spec["content_height"]))
        if image.size != expected_size or pixel_sha256(image) != spec["cropped_pixel_sha256"]:
            raise ValueError(f"Trimmed image pixels changed: {path.name}")
        if gray_tail_rows(image) != 0:
            raise ValueError(f"Trimmed image still has a gray tail: {path.name}")
    finally:
        image.close()


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
        raise ValueError("Picture-correction actor is not an active wildcard administrator")
    return actor


def relation_state(db, specs: list[dict[str, Any]]) -> tuple[str, list[ModelImage]]:
    source_by_url = {str(spec["source_url"]): spec for spec in specs}
    target_by_url = {str(spec["target_url"]): spec for spec in specs}
    all_urls = sorted([*source_by_url, *target_by_url])
    query_rows = (
        db.query(ModelImage, Model.code)
        .join(Model, Model.id == ModelImage.model_id)
        .filter(ModelImage.file_url.in_(all_urls))
        .order_by(ModelImage.id)
        .all()
    )
    images = [image for image, _ in query_rows]
    if len(images) != EXPECTED_RELATIONS:
        raise ValueError(f"Expected {EXPECTED_RELATIONS} affected relations, found {len(images)}")
    if len({int(image.model_id) for image in images}) != EXPECTED_MODELS:
        raise ValueError("Affected model count changed")
    types = dict(sorted(Counter(str(image.image_type) for image in images).items()))
    if types != EXPECTED_IMAGE_TYPES:
        raise ValueError(f"Affected image-type counts changed: {types}")
    states: set[str] = set()
    identity_rows = []
    for image, code in query_rows:
        current_url = str(image.file_url)
        if current_url in source_by_url:
            state = "source"
            spec = source_by_url[current_url]
        elif current_url in target_by_url:
            state = "target"
            spec = target_by_url[current_url]
        else:
            raise ValueError(f"Unexpected image URL: {current_url}")
        states.add(state)
        expected_name = spec["name"] if state == "source" else spec["target_name"]
        if image.file_name != expected_name or image.content_type != "image/webp" or image.file_data is not None:
            raise ValueError(f"Image metadata changed for relation {image.id}")
        identity_rows.append(
            {
                "id": int(image.id),
                "model_id": int(image.model_id),
                "image_type": str(image.image_type),
                "file_url": spec["source_url"],
                "code": str(code),
            }
        )
    if len(states) != 1:
        raise ValueError(f"Partial gray-padding correction detected: {sorted(states)}")
    identity = canonical_sha256(identity_rows)
    if identity != EXPECTED_REFERENCE_IDENTITY:
        raise ValueError(f"Affected relation identity changed: {identity}")
    return next(iter(states)), images


def create_trimmed_files(
    specs: list[dict[str, Any]], storage_dir: Path
) -> tuple[list[Path], list[Path]]:
    thumbnail_root = storage_dir / "_thumbs"
    created_files: list[Path] = []
    created_thumbnails: list[Path] = []
    try:
        for spec in specs:
            source = storage_dir / spec["name"]
            target = storage_dir / spec["target_name"]
            validate_source(source, spec)
            if target.exists():
                validate_target(target, spec)
            else:
                temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
                try:
                    with Image.open(source) as opened:
                        opened.load()
                        image = opened.convert("RGB")
                    try:
                        cropped = image.crop((0, 0, image.width, int(spec["content_height"])))
                        try:
                            cropped.save(temporary, format="WEBP", lossless=True, quality=100, method=1)
                        finally:
                            cropped.close()
                    finally:
                        image.close()
                    validate_target(temporary, spec)
                    os.replace(temporary, target)
                    created_files.append(target)
                finally:
                    temporary.unlink(missing_ok=True)
            content = target.read_bytes()
            expected_thumbnails = [thumbnail_root / f"{size}_{target.name}.webp" for size in THUMBNAIL_SIZES]
            missing_before = [path for path in expected_thumbnails if not path.exists()]
            prebuild_webp_thumbnails(
                content,
                thumbnail_root=thumbnail_root,
                source_file_name=target.name,
                sizes=THUMBNAIL_SIZES,
            )
            created_thumbnails.extend(missing_before)
            for thumbnail in expected_thumbnails:
                with Image.open(thumbnail) as preview:
                    preview.verify()
        return created_files, created_thumbnails
    except Exception:
        for path in reversed(created_thumbnails + created_files):
            path.unlink(missing_ok=True)
        raise


def execute(args: argparse.Namespace) -> dict[str, Any]:
    storage_dir = Path(args.storage_dir).resolve()
    specs = inspect_sources(storage_dir)
    created_files: list[Path] = []
    created_thumbnails: list[Path] = []
    with SessionLocal() as db:
        actor = assert_database(db, args)
        state, images = relation_state(db, specs)
        if state == "target":
            for spec in specs:
                validate_source(storage_dir / spec["name"], spec)
                validate_target(storage_dir / spec["target_name"], spec)
            db.rollback()
            return {
                "status": "already_applied",
                "source_files": EXPECTED_SOURCE_FILES,
                "relations": EXPECTED_RELATIONS,
                "models": EXPECTED_MODELS,
            }
        if not args.apply:
            db.rollback()
            return {
                "status": "dry_run",
                "source_files": EXPECTED_SOURCE_FILES,
                "relations": EXPECTED_RELATIONS,
                "models": EXPECTED_MODELS,
                "removed_gray_rows": sum(int(spec["bottom_gray_rows"]) for spec in specs),
            }
        if args.confirm != CONFIRMATION:
            raise ValueError("Exact production confirmation phrase is required")
        try:
            created_files, created_thumbnails = create_trimmed_files(specs, storage_dir)
            by_source_url = {str(spec["source_url"]): spec for spec in specs}
            for image in images:
                spec = by_source_url[str(image.file_url)]
                image.file_url = str(spec["target_url"])
                image.file_name = str(spec["target_name"])
                image.content_type = "image/webp"
                image.file_data = None
            db.flush()
            final_state, _ = relation_state(db, specs)
            if final_state != "target":
                raise RuntimeError("In-transaction picture correction verification failed")
            log_action(
                db,
                actor,
                "old_erp_catalog_gray_padding_trimmed",
                "model_images",
                old_value={
                    "source_files": EXPECTED_SOURCE_FILES,
                    "relations": EXPECTED_RELATIONS,
                    "source_identity_sha256": EXPECTED_SOURCE_IDENTITY,
                },
                new_value={
                    "trimmed_files": EXPECTED_SOURCE_FILES,
                    "relations": EXPECTED_RELATIONS,
                    "models": EXPECTED_MODELS,
                    "removed_gray_rows": sum(int(spec["bottom_gray_rows"]) for spec in specs),
                    "reference_identity_sha256": EXPECTED_REFERENCE_IDENTITY,
                    "original_files_preserved": True,
                    "lossless_crop": True,
                },
            )
            db.commit()
        except Exception:
            db.rollback()
            for path in reversed(created_thumbnails + created_files):
                path.unlink(missing_ok=True)
            raise
    with SessionLocal() as verify_db:
        assert_database(verify_db, args)
        final_state, _ = relation_state(verify_db, specs)
        if final_state != "target":
            raise RuntimeError("Committed picture correction verification failed")
        for spec in specs:
            validate_source(storage_dir / spec["name"], spec)
            validate_target(storage_dir / spec["target_name"], spec)
        verify_db.rollback()
    return {
        "status": "applied",
        "source_files": EXPECTED_SOURCE_FILES,
        "relations": EXPECTED_RELATIONS,
        "models": EXPECTED_MODELS,
        "files_created": len(created_files),
        "thumbnails_created": len(created_thumbnails),
        "removed_gray_rows": sum(int(spec["bottom_gray_rows"]) for spec in specs),
        "original_files_preserved": True,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storage-dir", default=settings.MODEL_FILES_DIR)
    parser.add_argument("--expected-database-host", required=True)
    parser.add_argument("--expected-database-name", required=True)
    parser.add_argument("--actor-id", type=int, default=1)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    return parser.parse_args()


if __name__ == "__main__":
    print(json.dumps(execute(parse_args()), sort_keys=True))
