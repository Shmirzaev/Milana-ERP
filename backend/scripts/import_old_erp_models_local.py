"""Plan and apply the reviewed old-ERP model migration to localhost only.

This importer is intentionally narrower than the generic catalog importer:

* dry-run is the default;
* both frozen source files and their validated-image mirrors are hash pinned;
* database identities come only from ``details_json.general``;
* existing model names, codes, and image rows are immutable;
* source conflicts are quarantined as whole logical identities;
* apply requires a reviewed plan hash, quarantine hash, local database
  preconditions, and verified database/media backups.

The script creates catalog Models, ModelSizes, ModelColors, and ModelImages
only. It never creates BOM, item, stock, order, package, or shipment data.

Run from ``backend`` so the ``app`` package resolves. A typical first pass is::

    python -m scripts.import_old_erp_models_local \
      --models-source .../models-list.json --models-source-sha256 ... \
      --variants-source .../variants-list.json --variants-source-sha256 ... \
      --validated-models-list .../models-list-validated.json \
      --validated-models-sha256 ... \
      --validated-variants-list .../variants-list-validated.json \
      --validated-variants-sha256 ... \
      --sizes-list .../model-details-sizes.json --sizes-sha256 ... \
      --plan-output .../migration-plan.json --report .../dry-run-report.json

Apply is deliberately not documented as a copy/paste command. Review the
dry-run artifacts and pass every apply guard printed in the report.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import shutil
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import func, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import settings
from app.db.session import SessionLocal
from app.models import Model, ModelBOM, ModelColor, ModelImage, ModelSize, User


SCHEMA_VERSION = 1
SOURCE_KEY = "old-erp-sewing-models-2026-07-25"
APPLY_CONFIRMATION = "APPLY-REVIEWED-OLD-ERP-MODELS-TO-LOCALHOST"
DEFAULT_LOCAL_DB_PORT = 15432

MODEL_IMAGE_FIELDS = ("primary_image",)
VARIANT_IMAGE_FIELDS = ("main_image", "thermal_image", "embroidery_image", "design_image")
VARIANT_IMAGE_TYPES = {
    "main_image": "material",
    "thermal_image": "pattern",
    "embroidery_image": "pattern",
    "design_image": "pattern",
}
VARIANT_IMAGE_ROLES = {
    "main_image": "variant_main",
    "thermal_image": "thermal",
    "embroidery_image": "embroidery",
    "design_image": "design",
}

# These are visually confusable Cyrillic letters found in the old and new ERP
# identifiers. Other Unicode letters are intentionally preserved.
CONFUSABLES = str.maketrans(
    {
        "\u0410": "A",  # А
        "\u0412": "B",  # В
        "\u0421": "C",  # С
        "\u0415": "E",  # Е
        "\u041d": "H",  # Н
        "\u041a": "K",  # К
        "\u041c": "M",  # М
        "\u041e": "O",  # О
        "\u0420": "P",  # Р
        "\u0422": "T",  # Т
        "\u0425": "X",  # Х
        "\u0423": "Y",  # У
        "\u0406": "I",  # І
        "\u0408": "J",  # Ј
    }
)
DASH_RE = re.compile(r"[\u2010-\u2015\u2212]")
EXPLICIT_VARIANT_PATTERNS = (
    re.compile(r"^(.*?)(?:[\s_-]+V[\s_-]*)(\d+)$", re.IGNORECASE),
    re.compile(r"^(.*?[^V])V[\s_-]*(\d+)$", re.IGNORECASE),
)

BUSINESS_TABLES = (
    "items",
    "stock_batches",
    "sales_orders",
    "production_orders",
    "packages",
    "finished_goods_stock",
    "model_bom",
)
MUTABLE_CATALOG_TABLES = {"models", "model_images", "model_sizes", "model_colors"}


class MigrationError(RuntimeError):
    """A fail-closed migration precondition or invariant failure."""


def clean(value: object) -> str:
    return " ".join(unicodedata.normalize("NFKC", str(value or "")).strip().split())


def translated_upper(value: object) -> str:
    return clean(value).upper().translate(CONFUSABLES)


def base_key(value: object) -> str:
    return "".join(char for char in translated_upper(value) if char.isalnum())


def variant_key(value: object) -> str:
    value_text = translated_upper(value)
    value_text = re.sub(r"^V[\s_-]*", "", value_text, count=1, flags=re.IGNORECASE)
    key = "".join(char for char in value_text if char.isalnum())
    if key.isdigit():
        return str(int(key))
    return key


def identity_key(base: object, variant: object) -> str:
    return f"{base_key(base)}|{variant_key(variant)}"


def identity_parts(identity: str) -> tuple[str, str]:
    base, separator, variant = identity.partition("|")
    if not separator:
        raise MigrationError(f"Malformed canonical identity: {identity!r}")
    return base, variant


def display_base(value: object) -> str:
    result = DASH_RE.sub("-", translated_upper(value))
    result = result.replace("_", "-")
    result = re.sub(r"\s+", "", result)
    result = re.sub(r"-+", "-", result).strip("-")
    result = re.sub(r"^([^\W\d_]+)(\d)", r"\1-\2", result, count=1, flags=re.UNICODE)
    return result


def parse_explicit_variant(value: object) -> tuple[str, str] | None:
    code = clean(value)
    for pattern in EXPLICIT_VARIANT_PATTERNS:
        match = pattern.fullmatch(code)
        if not match:
            continue
        base = re.sub(r"[\s_-]+$", "", clean(match.group(1)))
        variant = variant_key(match.group(2))
        if base_key(base) and variant:
            return base, variant
    return None


def meaningful(value: object) -> str:
    result = clean(value)
    return "" if result in {"", "-"} else result


def informative_master_name(row: dict[str, Any]) -> str:
    name = meaningful(row.get("name"))
    if name and base_key(name) == base_key(row.get("code")):
        return ""
    return name


def normalized_value(value: object) -> str:
    return clean(value).casefold()


def flag_value(value: object) -> bool | None:
    raw = clean(value).casefold()
    if raw in {"", "none", "null"}:
        return None
    if raw in {"+", "1", "true", "yes", "y", "ha", "да"}:
        return True
    if raw in {"-", "0", "false", "no", "n", "yo'q", "нет"}:
        return False
    raise MigrationError(f"Unrecognized legacy yes/no value: {value!r}")


def json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def object_sha256(value: object) -> str:
    return hashlib.sha256(json_bytes(value)).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def checked_file(path: Path, expected_sha256: str, label: str) -> tuple[Path, str]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise MigrationError(f"{label} does not exist: {resolved}")
    expected = clean(expected_sha256).lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise MigrationError(f"{label} requires a 64-character SHA-256")
    actual = file_sha256(resolved)
    if actual != expected:
        raise MigrationError(f"{label} SHA-256 changed: expected {expected}, got {actual}")
    return resolved, actual


def load_json_file(path: Path, expected_sha256: str, label: str) -> tuple[Any, Path, str]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise MigrationError(f"{label} does not exist: {resolved}")
    expected = clean(expected_sha256).lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise MigrationError(f"{label} requires a 64-character SHA-256")
    try:
        content = resolved.read_bytes()
        actual = hashlib.sha256(content).hexdigest()
        if actual != expected:
            raise MigrationError(
                f"{label} SHA-256 changed: expected {expected}, got {actual}"
            )
        payload = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MigrationError(f"{label} is not valid UTF-8 JSON: {exc}") from exc
    return payload, resolved, actual


def index_rows(rows: Any, id_field: str, label: str) -> dict[int, dict[str, Any]]:
    if not isinstance(rows, list) or not rows:
        raise MigrationError(f"{label} must be a non-empty JSON array")
    indexed: dict[int, dict[str, Any]] = {}
    for position, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise MigrationError(f"{label} row {position} is not an object")
        try:
            row_id = int(row.get(id_field))
        except (TypeError, ValueError) as exc:
            raise MigrationError(f"{label} row {position} has an invalid {id_field}") from exc
        if row_id <= 0 or row_id in indexed:
            raise MigrationError(f"{label} has duplicate/invalid {id_field} {row_id}")
        indexed[row_id] = row
    return indexed


def without_image_fields(row: dict[str, Any], image_fields: Iterable[str]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key not in set(image_fields)}


def verify_validated_mirror(
    raw_rows: dict[int, dict[str, Any]],
    validated_rows: dict[int, dict[str, Any]],
    *,
    image_fields: Iterable[str],
    label: str,
) -> None:
    if set(raw_rows) != set(validated_rows):
        missing = sorted(set(raw_rows) - set(validated_rows))[:10]
        extra = sorted(set(validated_rows) - set(raw_rows))[:10]
        raise MigrationError(f"{label} row IDs changed; missing={missing}, extra={extra}")
    for row_id in sorted(raw_rows):
        raw_non_image = without_image_fields(raw_rows[row_id], image_fields)
        validated_non_image = without_image_fields(validated_rows[row_id], image_fields)
        if raw_non_image != validated_non_image:
            raise MigrationError(f"{label} changed non-image data for source ID {row_id}")


def detect_image(content_head: bytes, content_tail: bytes) -> tuple[str, str]:
    if content_head.startswith(b"\xff\xd8\xff"):
        if not content_tail.endswith(b"\xff\xd9"):
            raise MigrationError("JPEG is missing its final EOI marker")
        return "image/jpeg", ".jpg"
    if content_head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", ".png"
    if content_head.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif", ".gif"
    if len(content_head) >= 12 and content_head[:4] == b"RIFF" and content_head[8:12] == b"WEBP":
        return "image/webp", ".webp"
    raise MigrationError("Unsupported or unrecognized image content")


def resolve_under(root: Path, relative_value: object, label: str) -> tuple[Path, str]:
    relative = Path(clean(relative_value))
    if not clean(relative_value) or relative.is_absolute():
        raise MigrationError(f"{label} must be a non-empty relative path")
    resolved_root = root.resolve()
    resolved = (resolved_root / relative).resolve()
    try:
        normalized_relative = resolved.relative_to(resolved_root).as_posix()
    except ValueError as exc:
        raise MigrationError(f"{label} escapes the media root") from exc
    return resolved, normalized_relative


def validate_image_object(
    image: object,
    *,
    media_root: Path,
    role: str,
    max_bytes: int,
    decode: bool,
) -> dict[str, Any] | None:
    if image is None:
        return None
    if not isinstance(image, dict):
        raise MigrationError(f"{role} image metadata is not an object")
    source, relative = resolve_under(media_root, image.get("path"), f"{role} image path")
    if not source.is_file():
        raise MigrationError(f"Missing {role} image: {source}")
    expected_sha = clean(image.get("sha256")).lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha):
        raise MigrationError(f"{role} image {relative} has an invalid SHA-256")
    try:
        expected_bytes = int(image.get("bytes"))
    except (TypeError, ValueError) as exc:
        raise MigrationError(f"{role} image {relative} has an invalid byte count") from exc
    actual_bytes = source.stat().st_size
    if actual_bytes <= 0 or actual_bytes != expected_bytes:
        raise MigrationError(
            f"{role} image {relative} byte count changed: expected {expected_bytes}, got {actual_bytes}"
        )
    if actual_bytes > max_bytes:
        raise MigrationError(f"{role} image {relative} exceeds the {max_bytes}-byte safety limit")
    actual_sha = file_sha256(source)
    if actual_sha != expected_sha:
        raise MigrationError(f"{role} image {relative} SHA-256 changed")
    with source.open("rb") as handle:
        head = handle.read(32)
        handle.seek(max(0, actual_bytes - 32))
        tail = handle.read(32)
    content_type, suffix = detect_image(head, tail)
    declared = clean(image.get("detected_mime"))
    if declared and declared != content_type:
        raise MigrationError(
            f"{role} image {relative} detected MIME changed: manifest={declared}, file={content_type}"
        )
    if decode:
        try:
            from PIL import Image

            with Image.open(source) as opened:
                opened.verify()
        except Exception as exc:  # Pillow exposes several format-specific exceptions.
            raise MigrationError(f"{role} image {relative} failed full decode verification: {exc}") from exc
    target_name = f"old_erp_{role}_{expected_sha[:24]}{suffix}"
    return {
        "kind": "source",
        "role": role,
        "source_path": relative,
        "sha256": expected_sha,
        "bytes": actual_bytes,
        "content_type": content_type,
        "target_name": target_name,
        "file_url": f"/storage/model-files/{target_name}",
    }


def load_sizes(payload: Any) -> dict[int, dict[str, Any]]:
    if payload is None:
        return {}
    if isinstance(payload, dict) and "rows" in payload:
        payload = payload["rows"]
    if isinstance(payload, dict) and "models" in payload:
        payload = payload["models"]
    if isinstance(payload, dict) and "records" in payload:
        payload = payload["records"]

    rows: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        for raw_id, value in payload.items():
            if not isinstance(value, dict):
                value = {"sizes": value}
            row = dict(value)
            row.setdefault("old_model_id", raw_id)
            rows.append(row)
    elif isinstance(payload, list):
        rows = payload
    else:
        raise MigrationError("Sizes/details manifest must be an object or array")

    indexed: dict[int, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise MigrationError("Sizes/details manifest contains a non-object row")
        try:
            old_model_id = int(row.get("old_model_id"))
        except (TypeError, ValueError) as exc:
            raise MigrationError("Sizes/details manifest has an invalid old_model_id") from exc
        if old_model_id in indexed:
            raise MigrationError(f"Sizes/details manifest repeats old_model_id {old_model_id}")
        normalized_sizes: list[dict[str, Any]] = []
        for source_size in row.get("sizes") or []:
            if isinstance(source_size, dict):
                size = meaningful(source_size.get("size") or source_size.get("name") or source_size.get("value"))
                measurement = source_size.get("measurement_json")
                if measurement is None:
                    measurement = source_size.get("measurement")
            else:
                size = meaningful(source_size)
                measurement = None
            if not size:
                continue
            normalized_sizes.append({"size": size, "measurement_json": measurement})
        scalar = row.get("scalar") if isinstance(row.get("scalar"), dict) else {}
        indexed[old_model_id] = {
            "sizes": normalized_sizes,
            "scalar": copy.deepcopy(scalar),
            "raw": copy.deepcopy(row),
        }
    return indexed


def image_sha(row: dict[str, Any], field: str) -> str:
    image = row.get(field)
    return clean(image.get("sha256")).lower() if isinstance(image, dict) else ""


def distinct_nonblank(
    rows: Iterable[dict[str, Any]],
    getter,
    *,
    normalizer=normalized_value,
) -> dict[str, list[Any]]:
    values: dict[str, list[Any]] = defaultdict(list)
    for row in rows:
        raw = getter(row)
        if raw is None or meaningful(raw) == "":
            continue
        normalized = normalizer(raw)
        if normalized:
            values[normalized].append(raw)
    return dict(values)


def consensus(
    values: Iterable[object],
    *,
    ignore_self_references: bool = False,
) -> tuple[str, list[str]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for value in values:
        result = meaningful(value)
        if not result:
            continue
        grouped[normalized_value(result)].append(result)
    if not grouped:
        return "", []
    if len(grouped) > 1:
        conflicts = sorted(min(entries, key=lambda item: (len(item), item)) for entries in grouped.values())
        return "", conflicts
    only = next(iter(grouped.values()))
    return min(only, key=lambda item: (len(item), item)), []


def source_conflicts_for_variant(group: dict[str, Any]) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    children = group["children"]
    explicit = group["explicit"]
    if len(children) > 1:
        checks = {
            "color": lambda row: meaningful(row.get("color")),
            "design": lambda row: meaningful(row.get("design")),
            "model_name": lambda row: meaningful(row.get("sew_model_name")),
            "thermal_print": lambda row: flag_value(row.get("thermal_print")),
            "embroidery": lambda row: flag_value(row.get("embroidery")),
            "main_image": lambda row: image_sha(row, "main_image"),
            "thermal_image": lambda row: image_sha(row, "thermal_image"),
            "embroidery_image": lambda row: image_sha(row, "embroidery_image"),
            "design_image": lambda row: image_sha(row, "design_image"),
        }
        for field, getter in checks.items():
            normalized = (
                (lambda value: str(value).lower())
                if field in {"thermal_print", "embroidery"}
                else normalized_value
            )
            values = distinct_nonblank(children, getter, normalizer=normalized)
            if len(values) > 1:
                conflicts.append({"role": field, "values": sorted(values)})
    if len(explicit) > 1:
        checks = {
            "informative_name": informative_master_name,
            "product": lambda row: meaningful(row.get("product")),
            "style": lambda row: meaningful(row.get("style")),
            "company": lambda row: meaningful(row.get("company")),
            "primary_image": lambda row: image_sha(row, "primary_image"),
        }
        for field, getter in checks.items():
            values = distinct_nonblank(explicit, getter)
            if len(values) > 1:
                conflicts.append({"role": f"explicit_master_{field}", "values": sorted(values)})
    return conflicts


def source_conflicts_for_standalone(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    checks = {
        "informative_name": informative_master_name,
        "product": lambda row: meaningful(row.get("product")),
        "style": lambda row: meaningful(row.get("style")),
        "company": lambda row: meaningful(row.get("company")),
        "primary_image": lambda row: image_sha(row, "primary_image"),
    }
    for field, getter in checks.items():
        values = distinct_nonblank(rows, getter)
        if len(values) > 1:
            conflicts.append({"role": f"standalone_{field}", "values": sorted(values)})
    return conflicts


def model_general(model: Model) -> dict[str, Any]:
    details = model.details_json if isinstance(model.details_json, dict) else {}
    general = details.get("general")
    return general if isinstance(general, dict) else {}


def is_imported_standalone_master(
    model: Model,
    *,
    identity: str,
    old_model_id: int,
) -> bool:
    """Recognize a standalone source row already created by this migration.

    A newly created standalone has the same normalized code as its old-ERP
    master. Without this provenance check, the next plan reclassifies that
    master as generic DB metadata, even though it is still the primary source
    record for the standalone. Keeping the source role stable makes repeated
    plans converge without weakening the protected name/image rules.
    """

    details = model.details_json if isinstance(model.details_json, dict) else {}
    provenance = details.get("old_erp_migration")
    if not isinstance(provenance, dict):
        return False
    if clean(provenance.get("source_key")) != SOURCE_KEY:
        return False
    if clean(provenance.get("identity")) != clean(identity):
        return False
    source_rows = [
        *(provenance.get("master_records") or []),
        *(provenance.get("metadata_only_records") or []),
    ]
    for row in source_rows:
        if not isinstance(row, dict):
            continue
        try:
            if int(row.get("old_model_id")) == int(old_model_id):
                return True
        except (TypeError, ValueError):
            continue
    return False


def db_identity(model: Model) -> str | None:
    general = model_general(model)
    model_no = clean(general.get("model_no") or general.get("modelNo"))
    variant_no = clean(general.get("variant_no") or general.get("variantNo"))
    if not base_key(model_no):
        return None
    return identity_key(model_no, variant_no)


def model_image_snapshot(model: Model) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for image in sorted(model.images or [], key=lambda row: int(row.id or 0)):
        rows.append(
            {
                "id": int(image.id),
                "file_url": image.file_url,
                "file_name": image.file_name,
                "content_type": image.content_type,
                "image_type": image.image_type,
                "is_primary": bool(image.is_primary),
                "file_data_sha256": hashlib.sha256(image.file_data).hexdigest() if image.file_data else None,
            }
        )
    return rows


def protected_snapshot(models: Iterable[Model]) -> list[dict[str, Any]]:
    return [
        {
            "id": int(model.id),
            "code": model.code,
            "name": model.name,
            "images": model_image_snapshot(model),
        }
        for model in sorted(models, key=lambda row: int(row.id))
    ]


def catalog_snapshot(models: Iterable[Model]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for model in sorted(models, key=lambda row: int(row.id)):
        result.append(
            {
                "id": int(model.id),
                "code": model.code,
                "name": model.name,
                "category": model.category,
                "description": model.description,
                "product_type": model.product_type,
                "season": model.season,
                "details_json": model.details_json,
                "status": model.status,
                "sizes": [
                    {"id": int(row.id), "size": row.size, "measurement_json": row.measurement_json}
                    for row in sorted(model.sizes or [], key=lambda item: int(item.id))
                ],
                "colors": [
                    {"id": int(row.id), "color_name": row.color_name, "color_code": row.color_code}
                    for row in sorted(model.colors or [], key=lambda item: int(item.id))
                ],
                "images": model_image_snapshot(model),
            }
        )
    return result


def count_business_tables(db) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table_name in BUSINESS_TABLES:
        counts[table_name] = int(db.execute(text(f'SELECT count(*) FROM "{table_name}"')).scalar_one())
    return counts


def count_named_tables(db, table_names: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table_name in sorted(set(table_names)):
        if not re.fullmatch(r"[a-z][a-z0-9_]*", table_name):
            raise MigrationError(f"Invariant snapshot contains an unsafe table name: {table_name!r}")
        counts[table_name] = int(
            db.execute(text(f'SELECT count(*) FROM "{table_name}"')).scalar_one()
        )
    return counts


def db_counts(db) -> dict[str, int]:
    return {
        "models": int(db.query(func.count(Model.id)).scalar() or 0),
        "model_images": int(db.query(func.count(ModelImage.id)).scalar() or 0),
        "model_sizes": int(db.query(func.count(ModelSize.id)).scalar() or 0),
        "model_colors": int(db.query(func.count(ModelColor.id)).scalar() or 0),
        "model_bom": int(db.query(func.count(ModelBOM.id)).scalar() or 0),
    }


def local_database_guard(db, *, expected_port: int) -> dict[str, Any]:
    if settings.is_production or settings.is_public_deployment:
        raise MigrationError("This localhost-only importer refuses production/public configuration")
    url = make_url(settings.DATABASE_URL)
    host = clean(url.host).strip("[]").casefold()
    if host not in {"localhost", "127.0.0.1", "::1"}:
        raise MigrationError("DATABASE_URL host must be localhost, 127.0.0.1, or ::1")
    port = int(url.port or 5432)
    if port != int(expected_port):
        raise MigrationError(f"DATABASE_URL port must be the reviewed local port {expected_port}")
    if clean(url.database) != "erp":
        raise MigrationError("DATABASE_URL database must be the local 'erp' database")
    row = db.execute(
        text(
            "SELECT current_database(), current_user, "
            "inet_server_addr()::text, inet_server_port(), pg_is_in_recovery()"
        )
    ).one()
    if clean(row[0]) != "erp":
        raise MigrationError("Connected database name changed")
    revision = clean(db.execute(text("SELECT version_num FROM alembic_version")).scalar_one())
    return {
        "url_host": host,
        "url_port": port,
        "database": clean(row[0]),
        "database_user": clean(row[1]),
        "server_address": clean(row[2]),
        "server_port": int(row[3] or 0),
        "in_recovery": bool(row[4]),
        "alembic_revision": revision,
    }


def effective_primary_model_image(model: Model) -> ModelImage | None:
    images = sorted(model.images or [], key=lambda row: int(row.id or 0), reverse=True)
    return (
        next((row for row in images if row.image_type == "model" and row.is_primary), None)
        or next((row for row in images if row.is_primary), None)
        or next((row for row in images if row.image_type == "model"), None)
    )


def stable_rows(rows: Iterable[dict[str, Any]], id_field: str) -> list[dict[str, Any]]:
    return sorted((copy.deepcopy(row) for row in rows), key=lambda row: int(row[id_field]))


def consensus_from_masters(
    rows: list[dict[str, Any]],
    sizes_by_model: dict[int, dict[str, Any]],
) -> tuple[dict[str, str], list[str]]:
    warnings: list[str] = []
    fields: dict[str, str] = {}

    def detail_value(row: dict[str, Any], field: str) -> object:
        detail = sizes_by_model.get(int(row["old_model_id"])) or {}
        scalar = detail.get("scalar") if isinstance(detail.get("scalar"), dict) else {}
        return scalar.get(field)

    def source_value(row: dict[str, Any], field: str) -> object:
        direct = row.get(field)
        if meaningful(direct):
            return direct
        return detail_value(row, field)

    def source_name(row: dict[str, Any]) -> str:
        direct = informative_master_name(row)
        if direct:
            return direct
        detail_name = meaningful(detail_value(row, "name"))
        if detail_name and base_key(detail_name) != base_key(row.get("code")):
            return detail_name
        return ""

    extractors = {
        "name": source_name,
        "product": lambda row: meaningful(source_value(row, "product")),
        "style": lambda row: meaningful(source_value(row, "style")),
        "company": lambda row: meaningful(source_value(row, "company")),
        "description": lambda row: meaningful(
            (sizes_by_model.get(int(row["old_model_id"])) or {}).get("scalar", {}).get("description")
        ),
        "planning_type": lambda row: meaningful(source_value(row, "planning_type")),
        "parent_sew_model": lambda row: meaningful(source_value(row, "parent_sew_model")),
        "source_date": lambda row: meaningful(source_value(row, "date")),
        "legacy_model_variant": lambda row: meaningful(source_value(row, "model_variant")),
        "master_thermal_print": lambda row: meaningful(source_value(row, "thermal_print")),
        "master_embroidery": lambda row: meaningful(source_value(row, "embroidery")),
    }
    for field, extractor in extractors.items():
        value, conflicts = consensus(extractor(row) for row in rows)
        if conflicts:
            warnings.append(f"source_{field}_omitted_no_consensus")
        if value:
            fields[field] = value
    return fields, warnings


def consensus_with_metadata_fallback(
    primary_rows: list[dict[str, Any]],
    metadata_rows: list[dict[str, Any]],
    sizes_by_model: dict[int, dict[str, Any]],
) -> tuple[dict[str, str], list[str]]:
    """Use duplicate/group metadata only where exact-parent data is absent.

    Exact parent or explicit-variant masters remain authoritative. Metadata
    rows may enrich blank product/description/detail fields, but cannot
    override a primary value or influence protected model names and pictures.
    """

    primary_fields, primary_warnings = consensus_from_masters(
        primary_rows,
        sizes_by_model,
    )
    if not metadata_rows:
        return primary_fields, primary_warnings

    metadata_fields, metadata_warnings = consensus_from_masters(
        metadata_rows,
        sizes_by_model,
    )
    fields = dict(primary_fields)
    for key, value in metadata_fields.items():
        if key == "name":
            continue
        fields.setdefault(key, value)
    warnings = [
        *primary_warnings,
        *(f"metadata_{warning}" for warning in metadata_warnings),
    ]
    return fields, sorted(set(warnings))


def sizes_from_masters(
    rows: Iterable[dict[str, Any]],
    sizes_by_model: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    for row in rows:
        detail = sizes_by_model.get(int(row["old_model_id"])) or {}
        for size in detail.get("sizes") or []:
            key = normalized_value(size.get("size"))
            if not key:
                continue
            current = by_key.get(key)
            if current and current.get("measurement_json") != size.get("measurement_json"):
                # Measurements are optional in this extraction. Conflicting
                # measurements are retained in provenance but not invented.
                current["measurement_json"] = None
            elif not current:
                by_key[key] = copy.deepcopy(size)
    return sorted(by_key.values(), key=lambda row: normalized_value(row["size"]))


def validated_image_for_master(row: dict[str, Any]) -> dict[str, Any] | None:
    image = row.get("primary_image")
    return copy.deepcopy(image) if isinstance(image, dict) else None


def db_model_image_sha(image: ModelImage, target_dir: Path | None) -> str | None:
    file_url = clean(image.file_url)
    prefix = "/storage/model-files/"
    if target_dir is not None and file_url.startswith(prefix):
        target_name = file_url[len(prefix) :]
        if target_name and "/" not in target_name and "\\" not in target_name:
            target = (target_dir / target_name).resolve()
            try:
                target.relative_to(target_dir)
            except ValueError:
                target = Path()
            if target.is_file():
                return file_sha256(target)
    if image.file_data:
        return hashlib.sha256(image.file_data).hexdigest()
    return None


def source_protected_defaults(
    *,
    group: dict[str, Any],
    sources: dict[str, Any],
    db_group: list[Model] | None,
    target_media_dir: Path | None,
) -> tuple[str, dict[str, Any] | None, list[str]]:
    """Resolve only exact-source protected fields for a new variant row.

    Model-primary images are variant-row-specific in the current catalog. An
    arbitrary existing DB row must therefore never be used as a template.
    """

    explicit_rows = sorted(
        group["explicit"], key=lambda row: int(row["old_model_id"])
    )
    if explicit_rows:
        candidate_rows = explicit_rows
        source_kind = "explicit_variant_master"
    else:
        candidate_rows = [
            sources["models"][old_model_id]
            for old_model_id in sorted(group["child_parent_ids"])
        ]
        source_kind = "exact_parent_master"

    candidate_fields, candidate_warnings = consensus_from_masters(
        candidate_rows,
        sources["sizes"],
    )
    name = candidate_fields.get("name") or ""
    warnings = [
        warning
        for warning in candidate_warnings
        if warning == "source_name_omitted_no_consensus"
    ]

    images = [
        validated_image_for_master(row)
        for row in candidate_rows
        if validated_image_for_master(row)
    ]
    by_sha: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for image in images:
        by_sha[image["sha256"]].append(image)

    selected: dict[str, Any] | None = None
    if len(by_sha) == 1:
        selected = sorted(
            next(iter(by_sha.values())),
            key=lambda row: (row["sha256"], row["source_path"]),
        )[0]
    elif len(by_sha) > 1:
        db_shas = {
            sha
            for model in db_group or []
            if (image := effective_primary_model_image(model)) is not None
            if (sha := db_model_image_sha(image, target_media_dir)) is not None
        }
        matching = sorted(set(by_sha) & db_shas)
        if len(matching) == 1:
            selected = sorted(
                by_sha[matching[0]],
                key=lambda row: (row["sha256"], row["source_path"]),
            )[0]
            warnings.append(f"{source_kind}_picture_resolved_by_unique_db_hash_match")
        else:
            warnings.append(f"{source_kind}_picture_omitted_no_unique_evidence")

    if selected is not None:
        selected = copy.deepcopy(selected)
        selected["image_type"] = "model"
        selected["is_primary"] = True
    return name, selected, sorted(set(warnings))


def variant_image_specs(children: list[dict[str, Any]]) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for field in VARIANT_IMAGE_FIELDS:
        candidates = [
            row[field]
            for row in sorted(children, key=lambda value: int(value["old_variant_id"]))
            if isinstance(row.get(field), dict)
        ]
        if not candidates:
            continue
        shas = {clean(candidate.get("sha256")).lower() for candidate in candidates}
        if len(shas) != 1:
            raise MigrationError(f"Unquarantined variant image conflict in {field}")
        specs.append(copy.deepcopy(candidates[0]))
    return specs


def details_patch(
    *,
    model_no: str | None,
    variant_no: str | None,
    fields: dict[str, str],
    child_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    if model_no:
        patch["model_no"] = model_no
    if variant_no:
        patch["variant_no"] = variant_no
    if fields.get("product"):
        patch["legacy_product"] = fields["product"]
    if fields.get("style"):
        patch["legacy_style"] = fields["style"]
    if fields.get("company"):
        patch["legacy_company"] = fields["company"]
    if fields.get("planning_type"):
        patch["legacy_planning_type"] = fields["planning_type"]
    if fields.get("parent_sew_model"):
        patch["legacy_parent_sew_model"] = fields["parent_sew_model"]
    if fields.get("source_date"):
        patch["legacy_source_date"] = fields["source_date"]
    if fields.get("legacy_model_variant"):
        patch["legacy_model_variant"] = fields["legacy_model_variant"]
    for source_field, target_field in (
        ("master_thermal_print", "legacy_master_thermal_print"),
        ("master_embroidery", "legacy_master_embroidery"),
    ):
        raw_flag = fields.get(source_field)
        if raw_flag:
            try:
                parsed = flag_value(raw_flag)
            except MigrationError:
                parsed = None
            if parsed is not None:
                patch[target_field] = parsed

    for field in ("color", "design"):
        value, _ = consensus(meaningful(row.get(field)) for row in child_rows)
        if value:
            patch[f"legacy_{field}"] = value
    for field in ("thermal_print", "embroidery"):
        values = {flag_value(row.get(field)) for row in child_rows if flag_value(row.get(field)) is not None}
        if len(values) == 1:
            patch[f"legacy_{field}"] = values.pop()
    return patch


def provenance_payload(
    *,
    sources: dict[str, Any],
    identity: str,
    master_rows: list[dict[str, Any]],
    variant_rows: list[dict[str, Any]],
    metadata_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    relevant_ids = {int(row["old_model_id"]) for row in [*master_rows, *metadata_rows]}
    relevant_variant_ids = {int(row["old_variant_id"]) for row in variant_rows}
    detail_rows = {
        str(old_model_id): copy.deepcopy(sources["sizes"][old_model_id])
        for old_model_id in sorted(relevant_ids)
        if old_model_id in sources["sizes"]
    }
    validated_images = {
        "models": {
            str(old_model_id): copy.deepcopy(sources["models"][old_model_id].get("primary_image"))
            for old_model_id in sorted(relevant_ids)
            if sources["models"][old_model_id].get("primary_image")
        },
        "variants": {
            str(old_variant_id): {
                field: copy.deepcopy(sources["variants"][old_variant_id].get(field))
                for field in VARIANT_IMAGE_FIELDS
                if sources["variants"][old_variant_id].get(field)
            }
            for old_variant_id in sorted(relevant_variant_ids)
            if any(sources["variants"][old_variant_id].get(field) for field in VARIANT_IMAGE_FIELDS)
        },
    }
    return {
        "source_key": SOURCE_KEY,
        "source_files": dict(sorted(sources["source_files"].items())),
        "identity": identity,
        "master_records": stable_rows(
            (sources["raw_models"][int(row["old_model_id"])] for row in master_rows),
            "old_model_id",
        ),
        "variant_records": stable_rows(
            (sources["raw_variants"][int(row["old_variant_id"])] for row in variant_rows),
            "old_variant_id",
        ),
        "metadata_only_records": stable_rows(
            (sources["raw_models"][int(row["old_model_id"])] for row in metadata_rows),
            "old_model_id",
        ),
        "validated_images": validated_images,
        "details_and_sizes": detail_rows,
    }


def existing_additions(model: Model, sizes: list[dict[str, Any]], colors: list[str]) -> tuple[list, list]:
    existing_sizes = {normalized_value(row.size) for row in model.sizes or []}
    add_sizes = [row for row in sizes if normalized_value(row["size"]) not in existing_sizes]
    existing_colors = {normalized_value(row.color_name) for row in model.colors or []}
    add_colors = [value for value in colors if normalized_value(value) not in existing_colors]
    return add_sizes, add_colors


def scalar_fills(model: Model, fields: dict[str, str]) -> dict[str, str]:
    fills: dict[str, str] = {}
    if not meaningful(model.product_type) and fields.get("product"):
        fills["product_type"] = fields["product"]
    if not meaningful(model.description) and fields.get("description"):
        fills["description"] = fields["description"]
    return fills


def missing_details_patch(model: Model, patch: dict[str, Any]) -> dict[str, Any]:
    """Return only general-detail values the existing model does not have."""

    general = model_general(model)
    return {
        key: copy.deepcopy(value)
        for key, value in patch.items()
        if value not in (None, "") and general.get(key) in (None, "")
    }


def provenance_would_change(model: Model, incoming: dict[str, Any]) -> bool:
    """Check the additive provenance merge without mutating the ORM model."""

    details = copy.deepcopy(model.details_json) if isinstance(model.details_json, dict) else {}
    before = copy.deepcopy(details.get("old_erp_migration"))
    merge_provenance(details, incoming)
    return details.get("old_erp_migration") != before


def assert_no_duplicate_db_identities(models: list[Model]) -> tuple[dict[str, Model], dict[str, list[Model]]]:
    exact: dict[str, Model] = {}
    bases: dict[str, list[Model]] = defaultdict(list)
    missing_general: list[int] = []
    for model in models:
        identity = db_identity(model)
        if identity is None:
            missing_general.append(int(model.id))
            continue
        if identity in exact:
            raise MigrationError(
                f"Database has duplicate canonical identity {identity}: "
                f"models {exact[identity].id} and {model.id}"
            )
        exact[identity] = model
        base, _ = identity_parts(identity)
        bases[base].append(model)
    if missing_general:
        raise MigrationError(
            "Database identity authority is missing details_json.general.model_no "
            f"for model IDs {missing_general[:10]}"
        )
    for rows in bases.values():
        rows.sort(key=lambda row: int(row.id))
    return exact, dict(bases)


def canonical_db_base_display(models: list[Model]) -> str:
    values = {
        clean(model_general(model).get("model_no") or model_general(model).get("modelNo"))
        for model in models
    }
    values.discard("")
    if len(values) != 1:
        raise MigrationError(
            "Existing DB base has multiple raw general.model_no spellings: " + ", ".join(sorted(values))
        )
    return next(iter(values))


def prepare_sources(args: argparse.Namespace) -> dict[str, Any]:
    raw_models, raw_models_path, raw_models_sha = load_json_file(
        args.models_source, args.models_source_sha256, "Frozen models source"
    )
    raw_variants, raw_variants_path, raw_variants_sha = load_json_file(
        args.variants_source, args.variants_source_sha256, "Frozen variants source"
    )
    validated_models_path = args.validated_models_list or args.models_source
    validated_models_expected = args.validated_models_sha256 or args.models_source_sha256
    validated_variants_path = args.validated_variants_list or args.variants_source
    validated_variants_expected = args.validated_variants_sha256 or args.variants_source_sha256
    if args.apply and (not args.validated_models_list or not args.validated_variants_list):
        raise MigrationError("Apply requires explicit validated model and variant manifests")
    validated_models, validated_models_path, validated_models_sha = load_json_file(
        validated_models_path, validated_models_expected, "Validated models list"
    )
    validated_variants, validated_variants_path, validated_variants_sha = load_json_file(
        validated_variants_path, validated_variants_expected, "Validated variants list"
    )

    raw_model_rows = index_rows(raw_models, "old_model_id", "Frozen models source")
    raw_variant_rows = index_rows(raw_variants, "old_variant_id", "Frozen variants source")
    validated_model_rows = index_rows(validated_models, "old_model_id", "Validated models list")
    validated_variant_rows = index_rows(validated_variants, "old_variant_id", "Validated variants list")
    verify_validated_mirror(
        raw_model_rows,
        validated_model_rows,
        image_fields=MODEL_IMAGE_FIELDS,
        label="Validated models list",
    )
    verify_validated_mirror(
        raw_variant_rows,
        validated_variant_rows,
        image_fields=VARIANT_IMAGE_FIELDS,
        label="Validated variants list",
    )

    sizes_by_model: dict[int, dict[str, Any]] = {}
    sizes_sha = ""
    sizes_path: Path | None = None
    if args.sizes_list:
        if not args.sizes_sha256:
            raise MigrationError("--sizes-list requires --sizes-sha256")
        sizes_payload, sizes_path, sizes_sha = load_json_file(
            args.sizes_list, args.sizes_sha256, "Sizes/details manifest"
        )
        if isinstance(sizes_payload, dict) and sizes_payload.get("source_models_sha256"):
            embedded_source_sha = clean(sizes_payload["source_models_sha256"]).lower()
            if embedded_source_sha != raw_models_sha:
                raise MigrationError(
                    "Sizes/details manifest refers to a different frozen models source"
                )
        sizes_by_model = load_sizes(sizes_payload)
        unknown = sorted(set(sizes_by_model) - set(raw_model_rows))
        if unknown:
            raise MigrationError(f"Sizes/details manifest references unknown old model IDs: {unknown[:10]}")

    source_files = {
        "models_source_sha256": raw_models_sha,
        "variants_source_sha256": raw_variants_sha,
        "validated_models_sha256": validated_models_sha,
        "validated_variants_sha256": validated_variants_sha,
    }
    if sizes_sha:
        source_files["sizes_sha256"] = sizes_sha

    return {
        "raw_models": raw_model_rows,
        "raw_variants": raw_variant_rows,
        "models": validated_model_rows,
        "variants": validated_variant_rows,
        "sizes": sizes_by_model,
        "source_files": source_files,
        "paths": {
            "models_source": raw_models_path,
            "variants_source": raw_variants_path,
            "validated_models": validated_models_path,
            "validated_variants": validated_variants_path,
            "sizes": sizes_path,
        },
    }


def validate_all_images(
    sources: dict[str, Any],
    *,
    media_root: Path,
    max_bytes: int,
    decode: bool,
) -> dict[str, Any]:
    inventory: list[dict[str, Any]] = []
    for old_model_id, row in sorted(sources["models"].items()):
        spec = validate_image_object(
            row.get("primary_image"),
            media_root=media_root,
            role="model",
            max_bytes=max_bytes,
            decode=decode,
        )
        row["primary_image"] = spec
        if spec:
            inventory.append({"source_type": "model", "source_id": old_model_id, **spec})
    for old_variant_id, row in sorted(sources["variants"].items()):
        for field in VARIANT_IMAGE_FIELDS:
            spec = validate_image_object(
                row.get(field),
                media_root=media_root,
                role=VARIANT_IMAGE_ROLES[field],
                max_bytes=max_bytes,
                decode=decode,
            )
            if spec:
                spec["image_type"] = VARIANT_IMAGE_TYPES[field]
                spec["is_primary"] = False
                inventory.append(
                    {
                        "source_type": "variant",
                        "source_id": old_variant_id,
                        "source_field": field,
                        **spec,
                    }
                )
            row[field] = spec
    return {
        "validated": bool(decode),
        "references": len(inventory),
        "unique_sha256": len({row["sha256"] for row in inventory}),
        "bytes_referenced": sum(int(row["bytes"]) for row in inventory),
        "inventory_sha256": object_sha256(inventory),
    }


def build_groups(sources: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], set[int]]:
    model_rows = sources["models"]
    variant_groups: dict[str, dict[str, Any]] = {}
    parent_ids: set[int] = set()
    for old_variant_id, row in sorted(sources["variants"].items()):
        exact_parents = [int(value) for value in row.get("exact_parent_model_ids") or []]
        resolved_value = row.get("resolved_parent_model_id")
        if resolved_value is not None:
            try:
                parent_id = int(resolved_value)
            except (TypeError, ValueError) as exc:
                raise MigrationError(f"Variant {old_variant_id} has invalid resolved parent ID") from exc
            if exact_parents and parent_id not in exact_parents:
                raise MigrationError(f"Variant {old_variant_id} resolved parent is not an exact candidate")
        elif len(exact_parents) == 1:
            parent_id = exact_parents[0]
        else:
            raise MigrationError(
                f"Variant {old_variant_id} does not have one reviewed resolved parent model"
            )
        if parent_id not in model_rows:
            raise MigrationError(f"Variant {old_variant_id} references unknown parent model {parent_id}")
        reviewed_parent_ids = sorted(set(exact_parents or [parent_id]))
        unknown_parents = [value for value in reviewed_parent_ids if value not in model_rows]
        if unknown_parents:
            raise MigrationError(
                f"Variant {old_variant_id} references unknown exact parent models {unknown_parents}"
            )
        parent_ids.update(reviewed_parent_ids)
        base = meaningful(row.get("sew_model_code"))
        variant = meaningful(row.get("variant_code"))
        identity = identity_key(base, variant)
        base_part, variant_part = identity_parts(identity)
        if not base_part or not variant_part:
            raise MigrationError(f"Variant {old_variant_id} has an unusable identity")
        group = variant_groups.setdefault(
            identity,
            {
                "identity": identity,
                "children": [],
                "explicit": [],
                "parent_ids": set(),
                "child_parent_ids": set(),
                "raw_bases": [],
            },
        )
        group["children"].append(row)
        group["parent_ids"].update(reviewed_parent_ids)
        group["child_parent_ids"].update(reviewed_parent_ids)
        group["raw_bases"].append((old_variant_id, base))

    for old_model_id, row in sorted(model_rows.items()):
        if old_model_id in parent_ids:
            continue
        parsed = parse_explicit_variant(row.get("code"))
        if not parsed:
            continue
        raw_base, canonical_variant = parsed
        identity = identity_key(raw_base, canonical_variant)
        group = variant_groups.setdefault(
            identity,
            {
                "identity": identity,
                "children": [],
                "explicit": [],
                "parent_ids": set(),
                "child_parent_ids": set(),
                "raw_bases": [],
            },
        )
        group["explicit"].append(row)
        group["parent_ids"].add(old_model_id)
        group["raw_bases"].append((old_model_id, raw_base))
    return variant_groups, parent_ids


def quarantine_entry(
    identity: str,
    reason: str,
    *,
    master_rows: Iterable[dict[str, Any]] = (),
    variant_rows: Iterable[dict[str, Any]] = (),
    conflicts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "identity": identity,
        "reason": reason,
        "old_model_ids": sorted({int(row["old_model_id"]) for row in master_rows}),
        "old_variant_ids": sorted({int(row["old_variant_id"]) for row in variant_rows}),
        "conflicts": conflicts or [],
    }


def classify_nonvariant_masters(
    *,
    sources: dict[str, Any],
    parent_ids: set[int],
    variant_groups: dict[str, dict[str, Any]],
    db_exact: dict[str, Model],
    db_bases: dict[str, list[Model]],
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    explicit_ids = {
        int(row["old_model_id"])
        for group in variant_groups.values()
        for row in group["explicit"]
    }
    candidates = [
        row
        for old_model_id, row in sorted(sources["models"].items())
        if old_model_id not in parent_ids and old_model_id not in explicit_ids
    ]

    db_code_map: dict[str, list[Model]] = defaultdict(list)
    for model in db_exact.values():
        db_code_map[base_key(model.code)].append(model)
    concat_map: dict[str, list[str]] = defaultdict(list)
    for identity in variant_groups:
        base, variant = identity_parts(identity)
        concat_map[f"{base}{variant}"].append(identity)
    known_variant_bases = {identity_parts(identity)[0] for identity in variant_groups}

    metadata: dict[str, list[dict[str, Any]]] = defaultdict(list)
    standalone_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    quarantined: list[dict[str, Any]] = []
    counts: dict[str, int] = defaultdict(int)

    for row in candidates:
        old_model_id = int(row["old_model_id"])
        full_key = base_key(row.get("code"))
        if not full_key:
            quarantined.append(
                quarantine_entry(
                    f"MALFORMED-MASTER-{old_model_id}",
                    "blank_or_unusable_master_code",
                    master_rows=[row],
                )
            )
            counts["quarantine_malformed"] += 1
            continue

        variant_candidates = sorted(set(concat_map.get(full_key, [])))
        collides_with_known_base = full_key in known_variant_bases
        if len(variant_candidates) == 1 and not collides_with_known_base:
            metadata[f"variant:{variant_candidates[0]}"].append(row)
            counts["metadata_old_variant"] += 1
            continue
        if len(variant_candidates) > 1 or (variant_candidates and collides_with_known_base):
            quarantined.append(
                quarantine_entry(
                    full_key,
                    "ambiguous_full_code_variant_or_base_collision",
                    master_rows=[row],
                )
            )
            counts["quarantine_ambiguous"] += 1
            continue

        if full_key in known_variant_bases:
            metadata[f"old_base:{full_key}"].append(row)
            counts["metadata_old_group"] += 1
            continue

        db_code_candidates = db_code_map.get(full_key, [])
        if len(db_code_candidates) == 1:
            db_target = db_code_candidates[0]
            standalone_identity = f"{full_key}|"
            if is_imported_standalone_master(
                db_target,
                identity=standalone_identity,
                old_model_id=old_model_id,
            ):
                standalone_groups[full_key].append(row)
                continue
            metadata[f"db_model:{int(db_target.id)}"].append(row)
            counts["metadata_db_exact_code"] += 1
            continue
        if len(db_code_candidates) > 1:
            quarantined.append(
                quarantine_entry(
                    full_key,
                    "ambiguous_full_code_matches_multiple_db_models",
                    master_rows=[row],
                )
            )
            counts["quarantine_ambiguous"] += 1
            continue

        if full_key in db_bases:
            metadata[f"db_base:{full_key}"].append(row)
            counts["metadata_db_group"] += 1
            continue

        standalone_groups[full_key].append(row)

    safe_standalone: dict[str, list[dict[str, Any]]] = {}
    for standalone_key, rows in sorted(standalone_groups.items()):
        conflicts = source_conflicts_for_standalone(rows)
        if conflicts:
            quarantined.append(
                quarantine_entry(
                    standalone_key,
                    "standalone_master_source_conflict",
                    master_rows=rows,
                    conflicts=conflicts,
                )
            )
            counts["quarantine_standalone_conflict"] += 1
        else:
            safe_standalone[standalone_key] = rows
    counts["standalone_rows"] = sum(len(rows) for rows in standalone_groups.values())
    counts["standalone_identities"] = len(standalone_groups)
    counts["safe_standalone_identities"] = len(safe_standalone)
    return {"counts": dict(counts), "standalone": safe_standalone}, dict(metadata), quarantined


def attach_metadata(
    *,
    metadata: dict[str, list[dict[str, Any]]],
    variant_groups: dict[str, dict[str, Any]],
    db_bases: dict[str, list[Model]],
) -> tuple[dict[str, list[dict[str, Any]]], dict[int, list[dict[str, Any]]]]:
    by_variant: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_db_model: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for target, rows in metadata.items():
        kind, _, value = target.partition(":")
        if kind == "variant":
            by_variant[value].extend(rows)
        elif kind == "old_base":
            for identity in variant_groups:
                if identity_parts(identity)[0] == value:
                    by_variant[identity].extend(rows)
        elif kind == "db_model":
            by_db_model[int(value)].extend(rows)
        elif kind == "db_base":
            for model in db_bases[value]:
                by_db_model[int(model.id)].extend(rows)
        else:
            raise MigrationError(f"Unknown metadata target {target}")
    return dict(by_variant), dict(by_db_model)


def compile_plan(
    *,
    db,
    sources: dict[str, Any],
    image_validation: dict[str, Any],
    database_guard: dict[str, Any],
    target_media_dir: Path | None = None,
) -> dict[str, Any]:
    db_models = (
        db.query(Model)
        .options(
            selectinload(Model.images),
            selectinload(Model.sizes),
            selectinload(Model.colors),
        )
        .order_by(Model.id)
        .all()
    )
    db_exact, db_bases = assert_no_duplicate_db_identities(db_models)
    variant_groups, parent_ids = build_groups(sources)

    quarantined: list[dict[str, Any]] = []
    variant_conflicts: set[str] = set()
    for identity, group in sorted(variant_groups.items()):
        conflicts = source_conflicts_for_variant(group)
        if conflicts:
            variant_conflicts.add(identity)
            parent_rows = [sources["models"][old_id] for old_id in sorted(group["parent_ids"])]
            quarantined.append(
                quarantine_entry(
                    identity,
                    "variant_source_conflict",
                    master_rows=parent_rows,
                    variant_rows=group["children"],
                    conflicts=conflicts,
                )
            )

    classification, metadata, nonvariant_quarantine = classify_nonvariant_masters(
        sources=sources,
        parent_ids=parent_ids,
        variant_groups=variant_groups,
        db_exact=db_exact,
        db_bases=db_bases,
    )
    quarantined.extend(nonvariant_quarantine)
    metadata_by_variant, metadata_by_db_model = attach_metadata(
        metadata=metadata,
        variant_groups=variant_groups,
        db_bases=db_bases,
    )

    # Every raw source model must have exactly one classification.
    classified_model_ids: list[int] = []
    classified_model_ids.extend(parent_ids)
    classified_model_ids.extend(
        int(row["old_model_id"])
        for group in variant_groups.values()
        for row in group["explicit"]
    )
    classified_model_ids.extend(
        int(row["old_model_id"])
        for rows in metadata.values()
        for row in rows
    )
    classified_model_ids.extend(
        int(row["old_model_id"])
        for rows in classification["standalone"].values()
        for row in rows
    )
    classified_model_ids.extend(
        old_id
        for row in nonvariant_quarantine
        for old_id in row["old_model_ids"]
    )
    if len(classified_model_ids) != len(set(classified_model_ids)):
        duplicates = sorted(
            key
            for key, count in __import__("collections").Counter(classified_model_ids).items()
            if count > 1
        )
        raise MigrationError(f"Old model masters received multiple classifications: {duplicates[:10]}")
    if set(classified_model_ids) != set(sources["models"]):
        missing = sorted(set(sources["models"]) - set(classified_model_ids))
        raise MigrationError(f"Old model masters were not completely classified: {missing[:10]}")

    actions_by_existing_id: dict[int, dict[str, Any]] = {}
    create_actions: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    planned_new_codes: dict[str, str] = {}
    existing_normalized_codes: dict[str, int] = {}
    for model in db_models:
        code_key = base_key(model.code)
        if code_key in existing_normalized_codes:
            raise MigrationError(
                f"Existing DB has normalized code collision for models "
                f"{existing_normalized_codes[code_key]} and {model.id}"
            )
        existing_normalized_codes[code_key] = int(model.id)

    def plan_existing(
        model: Model,
        *,
        identity: str,
        master_rows: list[dict[str, Any]],
        child_rows: list[dict[str, Any]],
        metadata_rows: list[dict[str, Any]],
        fields: dict[str, str],
        patch: dict[str, Any],
        sizes: list[dict[str, Any]],
        colors: list[str],
        action_warnings: list[str],
    ) -> None:
        add_sizes, add_colors = existing_additions(model, sizes, colors)
        payload = {
            "action": "update_existing",
            "identity": identity,
            "target_model_id": int(model.id),
            "expected_code": model.code,
            "expected_name": model.name,
            "expected_images": model_image_snapshot(model),
            "scalar_fills": scalar_fills(model, fields),
            "details_patch": patch,
            "add_sizes": add_sizes,
            "add_colors": add_colors,
            "provenance": provenance_payload(
                sources=sources,
                identity=identity,
                master_rows=master_rows,
                variant_rows=child_rows,
                metadata_rows=metadata_rows,
            ),
            "warnings": sorted(set(action_warnings)),
        }
        existing = actions_by_existing_id.get(int(model.id))
        if not existing:
            actions_by_existing_id[int(model.id)] = payload
            return
        if existing["identity"] != identity:
            raise MigrationError(
                f"Existing model {model.id} received different identities "
                f"{existing['identity']} and {identity}"
            )
        # Merge metadata-only sources without losing the variant's primary
        # provenance. Recompute the additive pieces from the union.
        combined_metadata = {
            int(row["old_model_id"]): row
            for row in [
                *existing["provenance"]["metadata_only_records"],
                *payload["provenance"]["metadata_only_records"],
            ]
        }
        existing["provenance"]["metadata_only_records"] = stable_rows(
            combined_metadata.values(), "old_model_id"
        )
        existing_details = dict(existing["provenance"].get("details_and_sizes") or {})
        for key, value in (payload["provenance"].get("details_and_sizes") or {}).items():
            if key in existing_details and existing_details[key] != value:
                raise MigrationError(f"Plan provenance disagrees on details/sizes for old model {key}")
            existing_details[key] = copy.deepcopy(value)
        existing["provenance"]["details_and_sizes"] = dict(
            sorted(existing_details.items(), key=lambda pair: int(pair[0]))
        )
        existing_validated = existing["provenance"].get("validated_images") or {
            "models": {},
            "variants": {},
        }
        payload_validated = payload["provenance"].get("validated_images") or {}
        for source_type in ("models", "variants"):
            target_rows = dict(existing_validated.get(source_type) or {})
            for key, value in (payload_validated.get(source_type) or {}).items():
                if key in target_rows and target_rows[key] != value:
                    raise MigrationError(
                        f"Plan provenance disagrees on validated {source_type} image {key}"
                    )
                target_rows[key] = copy.deepcopy(value)
            existing_validated[source_type] = dict(
                sorted(target_rows.items(), key=lambda pair: int(pair[0]))
            )
        existing["provenance"]["validated_images"] = existing_validated
        for key, value in payload["scalar_fills"].items():
            existing["scalar_fills"].setdefault(key, value)
        for key, value in payload["details_patch"].items():
            existing["details_patch"].setdefault(key, value)
        existing["add_sizes"] = {
            normalized_value(row["size"]): row
            for row in [*existing["add_sizes"], *payload["add_sizes"]]
        }
        existing["add_sizes"] = sorted(
            existing["add_sizes"].values(), key=lambda row: normalized_value(row["size"])
        )
        existing["add_colors"] = sorted(
            set([*existing["add_colors"], *payload["add_colors"]]), key=normalized_value
        )
        existing["warnings"] = sorted(set([*existing["warnings"], *payload["warnings"]]))

    # Plan every canonical child/explicit variant identity.
    exact_existing_count = 0
    missing_existing_base_count = 0
    missing_new_base_count = 0
    safe_create_existing_base = 0
    safe_create_new_base = 0
    base_display_candidates: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for identity, group in variant_groups.items():
        base, _ = identity_parts(identity)
        base_display_candidates[base].extend(group["raw_bases"])

    canonical_new_base_display: dict[str, str] = {}
    for base, candidates in sorted(base_display_candidates.items()):
        displays = {display_base(value) for _, value in candidates if display_base(value)}
        if len(displays) != 1:
            raise MigrationError(
                f"Old source base {base} has non-converging display spellings: {sorted(displays)}"
            )
        canonical_new_base_display[base] = next(iter(displays))

    for identity, group in sorted(variant_groups.items()):
        base, variant = identity_parts(identity)
        db_target = db_exact.get(identity)
        db_group = db_bases.get(base)
        if db_target:
            exact_existing_count += 1
        elif db_group:
            missing_existing_base_count += 1
        else:
            missing_new_base_count += 1
        if identity in variant_conflicts:
            continue

        primary_master_rows = [
            sources["models"][old_id] for old_id in sorted(group["parent_ids"])
        ]
        metadata_rows = metadata_by_variant.get(identity, [])
        fields, field_warnings = consensus_with_metadata_fallback(
            primary_master_rows,
            metadata_rows,
            sources["sizes"],
        )
        all_size_masters = [
            *primary_master_rows,
            *metadata_rows,
        ]
        sizes = sizes_from_masters(all_size_masters, sources["sizes"])
        color, _ = consensus(meaningful(row.get("color")) for row in group["children"])
        colors = [color] if color else []

        if db_group:
            raw_model_no = canonical_db_base_display(db_group)
        else:
            raw_model_no = canonical_new_base_display[base]
        patch = details_patch(
            model_no=raw_model_no,
            variant_no=variant,
            fields=fields,
            child_rows=group["children"],
        )

        if db_target:
            plan_existing(
                db_target,
                identity=identity,
                master_rows=primary_master_rows,
                child_rows=group["children"],
                metadata_rows=metadata_rows,
                fields=fields,
                patch=patch,
                sizes=sizes,
                colors=colors,
                action_warnings=field_warnings,
            )
            continue

        protected_name, protected_image, protected_warnings = source_protected_defaults(
            group=group,
            sources=sources,
            db_group=db_group,
            target_media_dir=target_media_dir,
        )
        if db_group:
            name = protected_name
            model_images = [protected_image] if protected_image else []
            group_origin = "existing_db_base"
            safe_create_existing_base += 1
        else:
            name = protected_name
            model_images = [protected_image] if protected_image else []
            group_origin = "new_base"
            safe_create_new_base += 1

        code = f"{raw_model_no}-{variant}"
        if len(code) > 64:
            raise MigrationError(f"Planned model code exceeds 64 characters: {code}")
        normalized_code = base_key(code)
        if code in {model.code for model in db_models} or normalized_code in existing_normalized_codes:
            raise MigrationError(f"Planned variant code collides with existing DB code: {code}")
        if normalized_code in planned_new_codes:
            raise MigrationError(
                f"Planned variants normalize to the same code: {planned_new_codes[normalized_code]} and {code}"
            )
        planned_new_codes[normalized_code] = code
        images = [*model_images]
        for image in variant_image_specs(group["children"]):
            images.append(image)
        create_actions.append(
            {
                "action": "create_variant",
                "identity": identity,
                "code": code,
                "name": name,
                "category": None,
                "description": fields.get("description") or None,
                "product_type": fields.get("product") or None,
                "status": "draft",
                "group_origin": group_origin,
                "details_patch": patch,
                "sizes": sizes,
                "colors": colors,
                "images": images,
                "provenance": provenance_payload(
                    sources=sources,
                    identity=identity,
                    master_rows=primary_master_rows,
                    variant_rows=group["children"],
                    metadata_rows=metadata_rows,
                ),
                "warnings": sorted(set([*field_warnings, *protected_warnings])),
            }
        )

    # Plan standalone base Models. Ordinary dashed codes are never split and no
    # legacy "model_variant=1" value is invented.
    safe_standalone_count = 0
    for standalone_key, master_rows in sorted(classification["standalone"].items()):
        representative = min(master_rows, key=lambda row: int(row["old_model_id"]))
        raw_model_no = display_base(representative.get("code"))
        if not raw_model_no:
            raise MigrationError(f"Safe standalone {standalone_key} lost its display code")
        identity = f"{standalone_key}|"
        fields, field_warnings = consensus_from_masters(master_rows, sources["sizes"])
        sizes = sizes_from_masters(master_rows, sources["sizes"])
        patch = details_patch(
            model_no=raw_model_no,
            variant_no=None,
            fields=fields,
            child_rows=[],
        )
        db_target = db_exact.get(identity)
        if db_target is not None:
            plan_existing(
                db_target,
                identity=identity,
                master_rows=master_rows,
                child_rows=[],
                metadata_rows=[],
                fields=fields,
                patch=patch,
                sizes=sizes,
                colors=[],
                action_warnings=[
                    *field_warnings,
                    "imported_standalone_protected_fields_preserved",
                ],
            )
            continue

        name = fields.get("name") or meaningful(representative.get("name")) or raw_model_no
        primary_images = [
            validated_image_for_master(row)
            for row in master_rows
            if validated_image_for_master(row)
        ]
        primary_image_shas = {row["sha256"] for row in primary_images}
        images: list[dict[str, Any]] = []
        if len(primary_image_shas) == 1:
            chosen = sorted(primary_images, key=lambda row: (row["sha256"], row["source_path"]))[0]
            chosen["image_type"] = "model"
            chosen["is_primary"] = True
            images.append(chosen)
        elif len(primary_image_shas) > 1:
            raise MigrationError(f"Unquarantined standalone image conflict for {standalone_key}")
        code = raw_model_no
        if len(code) > 64:
            raise MigrationError(f"Planned standalone model code exceeds 64 characters: {code}")
        normalized_code = base_key(code)
        if code in {model.code for model in db_models} or normalized_code in existing_normalized_codes:
            raise MigrationError(f"Planned standalone code collides with existing DB code: {code}")
        if normalized_code in planned_new_codes:
            raise MigrationError(
                f"Planned codes normalize to the same value: {planned_new_codes[normalized_code]} and {code}"
            )
        planned_new_codes[normalized_code] = code
        create_actions.append(
            {
                "action": "create_standalone",
                "identity": identity,
                "code": code,
                "name": name,
                "category": None,
                "description": fields.get("description") or None,
                "product_type": fields.get("product") or None,
                "status": "draft",
                "group_origin": "standalone",
                "details_patch": patch,
                "sizes": sizes,
                "colors": [],
                "images": images,
                "provenance": provenance_payload(
                    sources=sources,
                    identity=identity,
                    master_rows=master_rows,
                    variant_rows=[],
                    metadata_rows=[],
                ),
                "warnings": field_warnings,
            }
        )
        safe_standalone_count += 1

    # Metadata-only rows targeting an existing exact identity/group can add
    # blank scalar/details values and sizes/colors, but never protected fields.
    for model_id, metadata_rows in sorted(metadata_by_db_model.items()):
        model = next((row for row in db_models if int(row.id) == model_id), None)
        if not model:
            raise MigrationError(f"Metadata-only target model {model_id} disappeared")
        identity = db_identity(model)
        if not identity:
            raise MigrationError(f"Metadata-only target model {model_id} has no canonical identity")
        fields, field_warnings = consensus_from_masters(metadata_rows, sources["sizes"])
        sizes = sizes_from_masters(metadata_rows, sources["sizes"])
        base, variant = identity_parts(identity)
        raw_model_no = clean(model_general(model).get("model_no") or model_general(model).get("modelNo"))
        patch = details_patch(
            model_no=raw_model_no,
            variant_no=clean(
                model_general(model).get("variant_no") or model_general(model).get("variantNo")
            ),
            fields=fields,
            child_rows=[],
        )
        plan_existing(
            model,
            identity=identity,
            master_rows=[],
            child_rows=[],
            metadata_rows=metadata_rows,
            fields=fields,
            patch=patch,
            sizes=sizes,
            colors=[],
            action_warnings=[*field_warnings, "metadata_only_duplicate_protected_fields_preserved"],
        )

    db_models_by_id = {int(model.id): model for model in db_models}
    pending_existing_actions: list[dict[str, Any]] = []
    for action in actions_by_existing_id.values():
        model = db_models_by_id[int(action["target_model_id"])]
        action["details_patch"] = missing_details_patch(model, action["details_patch"])
        provenance_merge = provenance_would_change(model, action["provenance"])
        planned_changes = {
            "scalar_fields": sorted(action["scalar_fills"]),
            "detail_fields": sorted(action["details_patch"]),
            "provenance_merge": provenance_merge,
            "add_sizes": len(action["add_sizes"]),
            "add_colors": len(action["add_colors"]),
        }
        if not (
            planned_changes["scalar_fields"]
            or planned_changes["detail_fields"]
            or planned_changes["provenance_merge"]
            or planned_changes["add_sizes"]
            or planned_changes["add_colors"]
        ):
            continue
        action["planned_changes"] = planned_changes
        pending_existing_actions.append(action)

    actions = sorted(
        [*pending_existing_actions, *create_actions],
        key=lambda action: (
            0 if action["action"] == "update_existing" else 1,
            action["identity"],
            int(action.get("target_model_id") or 0),
        ),
    )
    quarantined = sorted(quarantined, key=lambda row: (row["identity"], row["reason"]))

    create_variant_count = sum(action["action"] == "create_variant" for action in actions)
    create_standalone_count = sum(action["action"] == "create_standalone" for action in actions)
    planned_images = sum(len(action.get("images") or []) for action in actions)
    planned_sizes = sum(
        len(action.get("sizes") or action.get("add_sizes") or [])
        for action in actions
    )
    planned_colors = sum(
        len(action.get("colors") or action.get("add_colors") or [])
        for action in actions
    )
    planned_scalar_fields = sum(
        len((action.get("planned_changes") or {}).get("scalar_fields") or [])
        for action in pending_existing_actions
    )
    planned_detail_fields = sum(
        len((action.get("planned_changes") or {}).get("detail_fields") or [])
        for action in pending_existing_actions
    )
    planned_provenance_merges = sum(
        bool((action.get("planned_changes") or {}).get("provenance_merge"))
        for action in pending_existing_actions
    )
    pre_counts = db_counts(db)
    pre_business_counts = count_business_tables(db)
    catalog = catalog_snapshot(db_models)
    protected = protected_snapshot(db_models)
    summary = {
        "source_model_rows": len(sources["models"]),
        "source_variant_rows": len(sources["variants"]),
        "source_detail_model_rows": len(sources["sizes"]),
        "canonical_variant_identities": len(variant_groups),
        "exact_existing_identities": exact_existing_count,
        "missing_variant_existing_base_before_quarantine": missing_existing_base_count,
        "missing_variant_new_base_before_quarantine": missing_new_base_count,
        "create_variants_existing_base": safe_create_existing_base,
        "create_variants_new_base": safe_create_new_base,
        "create_variants_total": create_variant_count,
        "create_standalone_models": create_standalone_count,
        "create_models_total": create_variant_count + create_standalone_count,
        "update_existing_models": len(pending_existing_actions),
        "quarantined_identities": len(quarantined),
        "planned_model_images": planned_images,
        "planned_model_sizes": planned_sizes,
        "planned_model_colors": planned_colors,
        "planned_scalar_fields": planned_scalar_fields,
        "planned_detail_fields": planned_detail_fields,
        "planned_provenance_merges": planned_provenance_merges,
        "metadata_classification": classification["counts"],
    }
    plan = {
        "schema_version": SCHEMA_VERSION,
        "source_key": SOURCE_KEY,
        "mode": "apply" if False else "dry_run_plan",
        "source_files": dict(sorted(sources["source_files"].items())),
        "image_validation": image_validation,
        "database_guard": database_guard,
        "database_preconditions": {
            "counts": pre_counts,
            "business_counts": pre_business_counts,
            "catalog_sha256": object_sha256(catalog),
            "protected_names_images_sha256": object_sha256(protected),
            "creator_user_id": int(db.query(User.id).order_by(User.id).limit(1).scalar() or 0),
        },
        "summary": summary,
        "quarantines": quarantined,
        "quarantine_sha256": object_sha256(quarantined),
        "warnings": warnings,
        "actions": actions,
        "invariants": {
            "existing_model_code_name_rows_immutable": True,
            "existing_model_image_rows_immutable": True,
            "no_bom_items_stock_orders_packages_shipments": True,
            "database_identity_authority": "details_json.general.model_no+variant_no",
        },
    }
    plan["plan_sha256"] = object_sha256(plan)
    return plan


def enforce_expected_counts(args: argparse.Namespace, plan: dict[str, Any], *, apply: bool) -> None:
    summary = plan["summary"]
    checks = {
        "expect_source_models": ("source_model_rows", args.expect_source_models),
        "expect_source_variants": ("source_variant_rows", args.expect_source_variants),
        "expect_detail_models": ("source_detail_model_rows", args.expect_detail_models),
        "expect_db_models": ("__db_models__", args.expect_db_models),
        "expect_db_images": ("__db_images__", args.expect_db_images),
        "expect_db_sizes": ("__db_sizes__", args.expect_db_sizes),
        "expect_db_colors": ("__db_colors__", args.expect_db_colors),
        "expect_db_bom": ("__db_bom__", args.expect_db_bom),
        "expect_variant_identities": (
            "canonical_variant_identities",
            args.expect_variant_identities,
        ),
        "expect_existing_identities": ("exact_existing_identities", args.expect_existing_identities),
        "expect_create_variants_existing_base": (
            "create_variants_existing_base",
            args.expect_create_variants_existing_base,
        ),
        "expect_create_variants_new_base": (
            "create_variants_new_base",
            args.expect_create_variants_new_base,
        ),
        "expect_create_variants": ("create_variants_total", args.expect_create_variants),
        "expect_standalone_identities": (
            "__standalone_identities__",
            args.expect_standalone_identities,
        ),
        "expect_create_base_models": ("create_standalone_models", args.expect_create_base_models),
        "expect_total_creations": ("create_models_total", args.expect_total_creations),
        "expect_quarantines": ("quarantined_identities", args.expect_quarantines),
    }
    pre_counts = plan["database_preconditions"]["counts"]
    special = {
        "__db_models__": pre_counts["models"],
        "__db_images__": pre_counts["model_images"],
        "__db_sizes__": pre_counts["model_sizes"],
        "__db_colors__": pre_counts["model_colors"],
        "__db_bom__": pre_counts["model_bom"],
        "__standalone_identities__": int(
            summary.get("metadata_classification", {}).get("standalone_identities") or 0
        ),
    }
    missing: list[str] = []
    if args.expect_db_revision is None:
        if apply:
            missing.append("--expect-db-revision")
    elif clean(args.expect_db_revision) != clean(plan["database_guard"].get("alembic_revision")):
        raise MigrationError(
            "Reviewed database revision changed: "
            f"expected {args.expect_db_revision}, "
            f"got {plan['database_guard'].get('alembic_revision')}"
        )
    for argument, (summary_key, expected) in checks.items():
        if expected is None:
            if apply:
                missing.append(f"--{argument.replace('_', '-')}")
            continue
        actual = special.get(summary_key, summary.get(summary_key))
        if int(actual) != int(expected):
            raise MigrationError(
                f"Reviewed count {argument} changed: expected {expected}, got {actual}"
            )
    if missing:
        raise MigrationError("Apply requires every reviewed count assertion: " + ", ".join(missing))


def verify_backup(path: Path | None, expected_sha: str | None, label: str) -> dict[str, Any]:
    if not path or not expected_sha:
        raise MigrationError(f"Apply requires {label} path and SHA-256")
    resolved, digest = checked_file(path, expected_sha, label)
    return {"path": str(resolved), "bytes": resolved.stat().st_size, "sha256": digest}


def repo_local_media_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "backend" / "storage" / "model_files"


def verify_media_target(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    expected = repo_local_media_dir().resolve()
    if resolved != expected:
        raise MigrationError(f"Media target must be the local workspace directory {expected}")
    if not resolved.is_dir():
        raise MigrationError(f"Local model media directory does not exist: {resolved}")
    return resolved


def validate_external_invariant_snapshot(
    *,
    db,
    snapshot: object,
    snapshot_sha256: str,
    plan: dict[str, Any],
    target_media_dir: Path,
) -> dict[str, Any]:
    if not isinstance(snapshot, dict):
        raise MigrationError("Pre-apply invariant snapshot must be a JSON object")
    if clean(snapshot.get("snapshot_kind")) != "pre_local_old_erp_model_migration":
        raise MigrationError("Pre-apply invariant snapshot kind changed")
    database = snapshot.get("database")
    catalog = snapshot.get("catalog")
    source = snapshot.get("source_artifacts")
    expectations = snapshot.get("post_apply_expectations")
    table_counts = snapshot.get("table_row_counts")
    filesystem = snapshot.get("filesystem_baseline")
    if not all(
        isinstance(value, dict)
        for value in (database, catalog, source, expectations, table_counts, filesystem)
    ):
        raise MigrationError("Pre-apply invariant snapshot is missing required sections")

    if clean(database.get("name")) != plan["database_guard"]["database"]:
        raise MigrationError("Invariant snapshot database name changed")
    if clean(database.get("alembic_version")) != plan["database_guard"]["alembic_revision"]:
        raise MigrationError("Invariant snapshot Alembic revision changed")
    summary = plan["summary"]
    expected_pairs = (
        (source.get("models_list_rows"), summary["source_model_rows"], "source model rows"),
        (source.get("variants_list_rows"), summary["source_variant_rows"], "source variant rows"),
        (
            source.get("total_image_references"),
            plan["image_validation"]["references"],
            "source image references",
        ),
        (
            expectations.get("safe_candidate_models"),
            summary["create_models_total"],
            "safe candidate models",
        ),
        (
            expectations.get("safe_candidate_variants"),
            summary["create_variants_total"],
            "safe candidate variants",
        ),
        (
            expectations.get("safe_candidate_base_only_models"),
            summary["create_standalone_models"],
            "safe standalone models",
        ),
        (
            expectations.get("quarantined_identities"),
            summary["quarantined_identities"],
            "quarantined identities",
        ),
    )
    for snapshot_value, live_value, label in expected_pairs:
        if int(snapshot_value or 0) != int(live_value):
            raise MigrationError(
                f"Invariant snapshot {label} changed: snapshot={snapshot_value}, live={live_value}"
            )

    pre_counts = plan["database_preconditions"]["counts"]
    snapshot_catalog_counts = {
        "models": int((catalog.get("models") or {}).get("rows") or 0),
        "model_images": int((catalog.get("model_images") or {}).get("rows") or 0),
        "model_sizes": int((catalog.get("model_sizes") or {}).get("rows") or 0),
        "model_colors": int((catalog.get("model_colors") or {}).get("rows") or 0),
        "model_bom": int((catalog.get("model_bom") or {}).get("rows") or 0),
    }
    if snapshot_catalog_counts != pre_counts:
        raise MigrationError(
            f"Invariant snapshot catalog counts changed: "
            f"snapshot={snapshot_catalog_counts}, live={pre_counts}"
        )

    reviewed_table_counts = {str(key): int(value) for key, value in table_counts.items()}
    live_table_counts = count_named_tables(db, reviewed_table_counts)
    if live_table_counts != reviewed_table_counts:
        changed = {
            key: {"snapshot": reviewed_table_counts[key], "live": live_table_counts.get(key)}
            for key in reviewed_table_counts
            if live_table_counts.get(key) != reviewed_table_counts[key]
        }
        raise MigrationError(f"Pre-apply table counts changed: {changed}")

    media_section = filesystem.get("existing_model_files")
    if not isinstance(media_section, dict):
        raise MigrationError("Invariant snapshot is missing existing model-file counts")
    files = [path for path in target_media_dir.rglob("*") if path.is_file()]
    live_media = {
        "file_count": len(files),
        "total_bytes": sum(path.stat().st_size for path in files),
    }
    reviewed_media = {
        "file_count": int(media_section.get("file_count") or 0),
        "total_bytes": int(media_section.get("total_bytes") or 0),
    }
    if live_media != reviewed_media:
        raise MigrationError(
            f"Pre-apply model-file baseline changed: snapshot={reviewed_media}, live={live_media}"
        )

    unchanged_table_counts = {
        key: value
        for key, value in reviewed_table_counts.items()
        if key not in MUTABLE_CATALOG_TABLES
    }
    return {
        "snapshot_kind": snapshot["snapshot_kind"],
        "snapshot_sha256": snapshot_sha256,
        "generated_at": snapshot.get("generated_at"),
        "unchanged_table_counts": unchanged_table_counts,
        "catalog_counts": snapshot_catalog_counts,
        "model_files_baseline": reviewed_media,
    }


def media_preflight(plan: dict[str, Any], target_dir: Path) -> dict[str, Any]:
    source_targets = source_image_specs(plan)
    existing_source_targets: list[dict[str, Any]] = []
    missing_source_targets = 0
    missing_source_bytes = 0
    for target_name, spec in sorted(source_targets.items()):
        target = (target_dir / target_name).resolve()
        try:
            target.relative_to(target_dir)
        except ValueError as exc:
            raise MigrationError("Planned source image target escaped the local media directory") from exc
        if not target.exists():
            missing_source_targets += 1
            missing_source_bytes += int(spec["bytes"])
            continue
        if not target.is_file():
            raise MigrationError(f"Planned source image target is not a file: {target}")
        actual_sha = file_sha256(target)
        if actual_sha != spec["sha256"]:
            raise MigrationError(f"Existing source-image target has different content: {target}")
        existing_source_targets.append(
            {"target_name": target_name, "sha256": actual_sha, "bytes": target.stat().st_size}
        )

    inherited_urls = sorted(
        {
            image["file_url"]
            for action in plan["actions"]
            for image in action.get("images") or []
            if image.get("kind") == "existing_relation"
        }
    )
    inherited_files: list[dict[str, Any]] = []
    for file_url in inherited_urls:
        prefix = "/storage/model-files/"
        if not clean(file_url).startswith(prefix):
            raise MigrationError(
                f"Existing model picture cannot be inherited from a non-local URL: {file_url}"
            )
        target_name = clean(file_url)[len(prefix) :]
        if not target_name or "/" in target_name or "\\" in target_name:
            raise MigrationError(f"Existing inherited model picture has an unsafe URL: {file_url}")
        target = (target_dir / target_name).resolve()
        if not target.is_file():
            raise MigrationError(f"Existing inherited model picture is missing: {target}")
        inherited_files.append(
            {
                "file_url": file_url,
                "sha256": file_sha256(target),
                "bytes": target.stat().st_size,
            }
        )
    snapshot = {
        "source_targets_total": len(source_targets),
        "source_targets_already_present": len(existing_source_targets),
        "source_targets_to_create": missing_source_targets,
        "source_bytes_to_create": missing_source_bytes,
        "inherited_files": inherited_files,
        "existing_source_targets": existing_source_targets,
    }
    return {
        **{key: value for key, value in snapshot.items() if key not in {"inherited_files", "existing_source_targets"}},
        "inherited_files_total": len(inherited_files),
        "filesystem_snapshot_sha256": object_sha256(snapshot),
    }


def merge_provenance(details: dict[str, Any], incoming: dict[str, Any]) -> None:
    current = details.get("old_erp_migration")
    if current is None:
        details["old_erp_migration"] = copy.deepcopy(incoming)
        return
    if not isinstance(current, dict) or clean(current.get("source_key")) != SOURCE_KEY:
        raise MigrationError("Existing old_erp_migration provenance has an unexpected owner")
    current_files = dict(current.get("source_files") or {})
    incoming_files = dict(incoming.get("source_files") or {})
    for key in (
        "models_source_sha256",
        "variants_source_sha256",
        "validated_models_sha256",
        "validated_variants_sha256",
    ):
        if current_files.get(key) != incoming_files.get(key):
            raise MigrationError("Existing old-ERP provenance refers to different frozen source files")
    current_sizes = clean(current_files.get("sizes_sha256"))
    incoming_sizes = clean(incoming_files.get("sizes_sha256"))
    if current_sizes and incoming_sizes and current_sizes != incoming_sizes:
        raise MigrationError("Existing old-ERP provenance refers to a different sizes/details source")
    if incoming_sizes and not current_sizes:
        current_files["sizes_sha256"] = incoming_sizes
    current["source_files"] = dict(sorted(current_files.items()))
    if clean(current.get("identity")) != clean(incoming.get("identity")):
        raise MigrationError("Existing old-ERP provenance maps source rows to a different identity")

    for field, id_field in (
        ("master_records", "old_model_id"),
        ("variant_records", "old_variant_id"),
        ("metadata_only_records", "old_model_id"),
    ):
        merged: dict[int, dict[str, Any]] = {}
        for row in [*(current.get(field) or []), *(incoming.get(field) or [])]:
            row_id = int(row[id_field])
            previous = merged.get(row_id)
            if previous is not None and previous != row:
                raise MigrationError(f"Existing provenance changed source {id_field} {row_id}")
            merged[row_id] = copy.deepcopy(row)
        current[field] = stable_rows(merged.values(), id_field)
    details_rows = dict(current.get("details_and_sizes") or {})
    for key, value in (incoming.get("details_and_sizes") or {}).items():
        if key in details_rows and details_rows[key] != value:
            raise MigrationError(f"Existing provenance changed details/sizes for old model {key}")
        details_rows[key] = copy.deepcopy(value)
    current["details_and_sizes"] = dict(sorted(details_rows.items(), key=lambda pair: int(pair[0])))
    current_validated = current.get("validated_images")
    if not isinstance(current_validated, dict):
        current_validated = {"models": {}, "variants": {}}
    incoming_validated = incoming.get("validated_images") or {}
    for source_type in ("models", "variants"):
        existing_rows = dict(current_validated.get(source_type) or {})
        for key, value in (incoming_validated.get(source_type) or {}).items():
            if key in existing_rows and existing_rows[key] != value:
                raise MigrationError(
                    f"Existing provenance changed validated image metadata for {source_type} {key}"
                )
            existing_rows[key] = copy.deepcopy(value)
        current_validated[source_type] = dict(
            sorted(existing_rows.items(), key=lambda pair: int(pair[0]))
        )
    current["validated_images"] = current_validated


def apply_details(model: Model, patch: dict[str, Any], provenance: dict[str, Any], *, created: bool) -> None:
    details = copy.deepcopy(model.details_json) if isinstance(model.details_json, dict) else {}
    general = details.get("general")
    if not isinstance(general, dict):
        general = {}
    for key, value in patch.items():
        if value in (None, ""):
            continue
        current = general.get(key)
        if created:
            general[key] = copy.deepcopy(value)
        elif current in (None, ""):
            general[key] = copy.deepcopy(value)
        # Existing nonblank ERP data is authoritative and remains untouched.
    details["general"] = general
    merge_provenance(details, provenance)
    model.details_json = details
    flag_modified(model, "details_json")


def add_sizes(db, model: Model, rows: list[dict[str, Any]]) -> int:
    existing = {normalized_value(row.size) for row in model.sizes or []}
    added = 0
    for row in rows:
        key = normalized_value(row["size"])
        if not key or key in existing:
            continue
        db.add(
            ModelSize(
                model_id=int(model.id),
                size=row["size"],
                measurement_json=copy.deepcopy(row.get("measurement_json")),
            )
        )
        existing.add(key)
        added += 1
    return added


def add_colors(db, model: Model, rows: list[str]) -> int:
    existing = {normalized_value(row.color_name) for row in model.colors or []}
    added = 0
    for color in rows:
        key = normalized_value(color)
        if not key or key in existing:
            continue
        db.add(ModelColor(model_id=int(model.id), color_name=color, color_code=None))
        existing.add(key)
        added += 1
    return added


def add_images(db, model: Model, rows: list[dict[str, Any]]) -> int:
    added = 0
    for row in rows:
        if row["kind"] == "existing_relation":
            file_name = row.get("file_name")
            content_type = row.get("content_type")
        else:
            file_name = Path(row["source_path"]).name
            content_type = row["content_type"]
        db.add(
            ModelImage(
                model_id=int(model.id),
                file_url=row["file_url"],
                file_name=file_name,
                content_type=content_type,
                file_data=None,
                image_type=row.get("image_type") or "model",
                is_primary=bool(row.get("is_primary")),
            )
        )
        added += 1
    return added


def source_image_specs(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    by_target: dict[str, dict[str, Any]] = {}
    for action in plan["actions"]:
        for image in action.get("images") or []:
            if image.get("kind") != "source":
                continue
            target_name = image["target_name"]
            previous = by_target.get(target_name)
            if previous and previous["sha256"] != image["sha256"]:
                raise MigrationError(f"Content-addressed target collision: {target_name}")
            by_target[target_name] = image
    return by_target


def materialize_source_images(
    plan: dict[str, Any],
    *,
    media_root: Path,
    target_dir: Path,
) -> list[Path]:
    created: list[Path] = []
    for target_name, spec in sorted(source_image_specs(plan).items()):
        source, _ = resolve_under(media_root, spec["source_path"], "Planned source image")
        target = (target_dir / target_name).resolve()
        try:
            target.relative_to(target_dir)
        except ValueError as exc:
            raise MigrationError("Planned media target escaped the local model directory") from exc
        if target.exists():
            if not target.is_file() or file_sha256(target) != spec["sha256"]:
                raise MigrationError(f"Existing media target has different content: {target}")
            continue
        temporary = target_dir / f".{target_name}.{os.getpid()}.tmp"
        if temporary.exists():
            raise MigrationError(f"Unexpected stale media staging file: {temporary}")
        try:
            with source.open("rb") as source_handle, temporary.open("xb") as target_handle:
                shutil.copyfileobj(source_handle, target_handle, length=1024 * 1024)
                target_handle.flush()
                os.fsync(target_handle.fileno())
            if file_sha256(temporary) != spec["sha256"]:
                raise MigrationError(f"Staged media hash changed for {target_name}")
            linked = False
            try:
                os.link(temporary, target)
                linked = True
            except FileExistsError:
                if file_sha256(target) != spec["sha256"]:
                    raise MigrationError(f"Concurrent media target collision for {target_name}")
            if linked:
                created.append(target)
        finally:
            if temporary.exists():
                temporary.unlink()
    return created


def apply_plan(
    *,
    db,
    plan: dict[str, Any],
    media_root: Path,
    target_dir: Path,
) -> dict[str, Any]:
    preexisting_models = (
        db.query(Model)
        .options(selectinload(Model.images), selectinload(Model.sizes), selectinload(Model.colors))
        .order_by(Model.id)
        .all()
    )
    protected_before = protected_snapshot(preexisting_models)
    protected_before_sha = object_sha256(protected_before)
    business_before = count_business_tables(db)
    counts_before = db_counts(db)
    expected_preconditions = plan["database_preconditions"]
    if counts_before != expected_preconditions["counts"]:
        raise MigrationError("Database catalog counts changed after the reviewed plan")
    if business_before != expected_preconditions["business_counts"]:
        raise MigrationError("Business table counts changed after the reviewed plan")
    if object_sha256(catalog_snapshot(preexisting_models)) != expected_preconditions["catalog_sha256"]:
        raise MigrationError("Database catalog content changed after the reviewed plan")
    if protected_before_sha != expected_preconditions["protected_names_images_sha256"]:
        raise MigrationError("Protected names/images changed after the reviewed plan")
    external_invariants = plan.get("external_invariant_snapshot") or {}
    unchanged_table_counts = external_invariants.get("unchanged_table_counts") or {}
    if unchanged_table_counts:
        live_unchanged_before = count_named_tables(db, unchanged_table_counts)
        if live_unchanged_before != unchanged_table_counts:
            raise MigrationError("Reviewed non-catalog table counts changed before apply")
    created_files: list[Path] = []
    result = {
        "created_models": 0,
        "updated_existing_models": 0,
        "added_images": 0,
        "added_sizes": 0,
        "added_colors": 0,
        "created_model_ids": [],
    }
    try:
        required_media_bytes = int(
            media_preflight(plan, target_dir)["source_bytes_to_create"]
        )
        safety_margin = (
            max(512 * 1024 * 1024, required_media_bytes // 10)
            if required_media_bytes
            else 0
        )
        free_bytes = shutil.disk_usage(target_dir).free
        if free_bytes < required_media_bytes + safety_margin:
            raise MigrationError(
                "Insufficient local disk space for reviewed model images: "
                f"need {required_media_bytes + safety_margin} bytes including margin, "
                f"have {free_bytes}"
            )
        created_files = materialize_source_images(
            plan, media_root=media_root, target_dir=target_dir
        )
        creator_id = int(plan["database_preconditions"].get("creator_user_id") or 0) or None
        for action in plan["actions"]:
            if action["action"] == "update_existing":
                model = db.get(Model, int(action["target_model_id"]))
                if not model:
                    raise MigrationError(f"Existing target {action['target_model_id']} disappeared")
                if model.code != action["expected_code"] or model.name != action["expected_name"]:
                    raise MigrationError(f"Protected code/name changed for model {model.id}")
                if model_image_snapshot(model) != action["expected_images"]:
                    raise MigrationError(f"Protected image rows changed for model {model.id}")
                for field, value in action["scalar_fills"].items():
                    current = meaningful(getattr(model, field))
                    if current:
                        raise MigrationError(f"Planned blank field {field} became nonblank for model {model.id}")
                    setattr(model, field, value)
                apply_details(
                    model,
                    action["details_patch"],
                    action["provenance"],
                    created=False,
                )
                result["added_sizes"] += add_sizes(db, model, action["add_sizes"])
                result["added_colors"] += add_colors(db, model, action["add_colors"])
                result["updated_existing_models"] += 1
                continue

            model = Model(
                code=action["code"],
                name=action["name"],
                category=action.get("category"),
                description=action.get("description"),
                brand_id=None,
                collection_id=None,
                product_type=action.get("product_type"),
                season=None,
                details_json={},
                status=action["status"],
                created_by=creator_id,
                sam_minutes=0,
            )
            db.add(model)
            db.flush()
            apply_details(
                model,
                action["details_patch"],
                action["provenance"],
                created=True,
            )
            result["added_sizes"] += add_sizes(db, model, action["sizes"])
            result["added_colors"] += add_colors(db, model, action["colors"])
            result["added_images"] += add_images(db, model, action["images"])
            result["created_models"] += 1
            result["created_model_ids"].append(int(model.id))

        db.flush()
        # Existing names, codes, and image records are globally immutable,
        # including existing rows that had no source match.
        protected_after_models = (
            db.query(Model)
            .options(selectinload(Model.images))
            .filter(Model.id.in_([int(row["id"]) for row in protected_before]))
            .order_by(Model.id)
            .all()
        )
        protected_after_sha = object_sha256(protected_snapshot(protected_after_models))
        if protected_after_sha != protected_before_sha:
            raise MigrationError("Existing model code/name/image invariant failed")
        business_after = count_business_tables(db)
        if business_after != business_before:
            raise MigrationError("A non-catalog business table count changed")
        if unchanged_table_counts:
            live_unchanged_after = count_named_tables(db, unchanged_table_counts)
            if live_unchanged_after != unchanged_table_counts:
                raise MigrationError("A reviewed non-catalog table count changed during apply")
        counts_after = db_counts(db)
        if counts_after["models"] - counts_before["models"] != result["created_models"]:
            raise MigrationError("Created Model reconciliation failed")
        if counts_after["model_images"] - counts_before["model_images"] != result["added_images"]:
            raise MigrationError("Created ModelImage reconciliation failed")
        if counts_after["model_sizes"] - counts_before["model_sizes"] != result["added_sizes"]:
            raise MigrationError("Created ModelSize reconciliation failed")
        if counts_after["model_colors"] - counts_before["model_colors"] != result["added_colors"]:
            raise MigrationError("Created ModelColor reconciliation failed")
        if counts_after["model_bom"] != counts_before["model_bom"]:
            raise MigrationError("ModelBOM count changed")
        db.commit()
        result["created_files"] = [str(path) for path in created_files]
        result["counts_before"] = counts_before
        result["counts_after"] = counts_after
        result["business_counts_before"] = business_before
        result["business_counts_after"] = business_after
        result["protected_names_images_sha256_before"] = protected_before_sha
        result["protected_names_images_sha256_after"] = protected_after_sha
        return result
    except Exception:
        db.rollback()
        for path in reversed(created_files):
            try:
                if path.is_file() and path.parent.resolve() == target_dir.resolve():
                    path.unlink()
            except OSError:
                # Do not mask the original migration failure. The report cannot
                # claim success, and the content-addressed orphan is harmless.
                pass
        raise


def write_json(path: Path | None, payload: object, *, overwrite: bool) -> None:
    if path is None:
        return
    resolved = path.expanduser().resolve()
    if resolved.exists() and not overwrite:
        raise MigrationError(f"Output already exists (pass --overwrite-output to replace): {resolved}")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    temporary = resolved.with_name(f".{resolved.name}.{os.getpid()}.tmp")
    if temporary.exists():
        raise MigrationError(f"Unexpected stale output staging file: {temporary}")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, resolved)


def preflight_output_paths(
    plan_output: Path | None,
    report_output: Path | None,
    *,
    overwrite: bool,
) -> None:
    resolved = [
        path.expanduser().resolve()
        for path in (plan_output, report_output)
        if path is not None
    ]
    if len(resolved) != len(set(resolved)):
        raise MigrationError("--plan-output and --report must be different files")
    if not overwrite:
        existing = [str(path) for path in resolved if path.exists()]
        if existing:
            raise MigrationError(
                "Output already exists (pass --overwrite-output to replace): "
                + ", ".join(existing)
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plan/apply the frozen old-ERP model catalog to localhost only."
    )
    parser.add_argument("--models-source", required=True, type=Path)
    parser.add_argument("--models-source-sha256", required=True)
    parser.add_argument("--variants-source", required=True, type=Path)
    parser.add_argument("--variants-source-sha256", required=True)
    parser.add_argument("--validated-models-list", type=Path)
    parser.add_argument("--validated-models-sha256")
    parser.add_argument("--validated-variants-list", type=Path)
    parser.add_argument("--validated-variants-sha256")
    parser.add_argument("--sizes-list", type=Path)
    parser.add_argument("--sizes-sha256")
    parser.add_argument("--invariant-snapshot", type=Path)
    parser.add_argument("--invariant-snapshot-sha256")
    parser.add_argument(
        "--media-root",
        type=Path,
        help="Root for relative image paths; defaults to the validated models-list directory.",
    )
    parser.add_argument(
        "--target-media-dir",
        type=Path,
        default=repo_local_media_dir(),
        help="Must resolve to backend/storage/model_files in this workspace.",
    )
    parser.add_argument("--max-image-bytes", type=int, default=25 * 1024 * 1024)
    parser.add_argument(
        "--skip-image-decode",
        action="store_true",
        help="Dry-run metadata planning only; apply refuses this option.",
    )
    parser.add_argument("--plan-output", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--overwrite-output", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-localhost")
    parser.add_argument("--expected-plan-sha256")
    parser.add_argument("--accept-quarantine-sha256")
    parser.add_argument("--local-db-port", type=int, default=DEFAULT_LOCAL_DB_PORT)
    parser.add_argument("--database-backup", type=Path)
    parser.add_argument("--database-backup-sha256")
    parser.add_argument("--media-backup", type=Path)
    parser.add_argument("--media-backup-sha256")

    parser.add_argument("--expect-source-models", type=int)
    parser.add_argument("--expect-source-variants", type=int)
    parser.add_argument("--expect-detail-models", type=int)
    parser.add_argument("--expect-db-models", type=int)
    parser.add_argument("--expect-db-revision")
    parser.add_argument("--expect-db-images", type=int)
    parser.add_argument("--expect-db-sizes", type=int)
    parser.add_argument("--expect-db-colors", type=int)
    parser.add_argument("--expect-db-bom", type=int)
    parser.add_argument("--expect-variant-identities", type=int)
    parser.add_argument("--expect-existing-identities", type=int)
    parser.add_argument("--expect-create-variants-existing-base", type=int)
    parser.add_argument("--expect-create-variants-new-base", type=int)
    parser.add_argument("--expect-create-variants", type=int)
    parser.add_argument("--expect-standalone-identities", type=int)
    parser.add_argument("--expect-create-base-models", type=int)
    parser.add_argument("--expect-total-creations", type=int)
    parser.add_argument("--expect-quarantines", type=int)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    preflight_output_paths(
        args.plan_output,
        args.report,
        overwrite=args.overwrite_output,
    )
    if args.max_image_bytes <= 0:
        raise MigrationError("--max-image-bytes must be positive")
    if args.apply:
        if args.skip_image_decode:
            raise MigrationError("Apply refuses --skip-image-decode")
        if args.confirm_localhost != APPLY_CONFIRMATION:
            raise MigrationError(
                f"Apply requires --confirm-localhost {APPLY_CONFIRMATION}"
            )
        if not args.expected_plan_sha256 or not re.fullmatch(
            r"[0-9a-fA-F]{64}", args.expected_plan_sha256
        ):
            raise MigrationError("Apply requires the reviewed --expected-plan-sha256")
        if not args.accept_quarantine_sha256 or not re.fullmatch(
            r"[0-9a-fA-F]{64}", args.accept_quarantine_sha256
        ):
            raise MigrationError("Apply requires the reviewed --accept-quarantine-sha256")
        if not args.plan_output or not args.report:
            raise MigrationError("Apply requires both --plan-output and --report")

    sources = prepare_sources(args)
    invariant_snapshot = None
    invariant_snapshot_sha = ""
    if args.invariant_snapshot:
        if not args.invariant_snapshot_sha256:
            raise MigrationError(
                "--invariant-snapshot requires --invariant-snapshot-sha256"
            )
        invariant_snapshot, _, invariant_snapshot_sha = load_json_file(
            args.invariant_snapshot,
            args.invariant_snapshot_sha256,
            "Pre-apply invariant snapshot",
        )
    elif args.apply:
        raise MigrationError("Apply requires the hash-pinned pre-apply invariant snapshot")
    media_root = (
        args.media_root.expanduser().resolve()
        if args.media_root
        else sources["paths"]["validated_models"].parent.resolve()
    )
    if not media_root.is_dir():
        raise MigrationError(f"Media root does not exist: {media_root}")
    target_media_dir = verify_media_target(args.target_media_dir)
    image_validation = validate_all_images(
        sources,
        media_root=media_root,
        max_bytes=args.max_image_bytes,
        decode=not args.skip_image_decode,
    )

    backup_evidence = None
    if args.apply:
        backup_evidence = {
            "database": verify_backup(
                args.database_backup,
                args.database_backup_sha256,
                "Database backup",
            ),
            "media": verify_backup(
                args.media_backup,
                args.media_backup_sha256,
                "Media backup",
            ),
        }

    with SessionLocal() as db:
        guard = local_database_guard(db, expected_port=args.local_db_port)
        plan = compile_plan(
            db=db,
            sources=sources,
            image_validation=image_validation,
            database_guard=guard,
            target_media_dir=target_media_dir,
        )
        plan.pop("plan_sha256", None)
        if invariant_snapshot is not None:
            plan["external_invariant_snapshot"] = validate_external_invariant_snapshot(
                db=db,
                snapshot=invariant_snapshot,
                snapshot_sha256=invariant_snapshot_sha,
                plan=plan,
                target_media_dir=target_media_dir,
            )
        plan["media_preconditions"] = media_preflight(plan, target_media_dir)
        plan["plan_sha256"] = object_sha256(plan)
        enforce_expected_counts(args, plan, apply=args.apply)
        if args.apply:
            if plan["plan_sha256"] != args.expected_plan_sha256.lower():
                raise MigrationError(
                    "Reviewed plan SHA-256 changed: "
                    f"expected {args.expected_plan_sha256.lower()}, got {plan['plan_sha256']}"
                )
            if plan["quarantine_sha256"] != args.accept_quarantine_sha256.lower():
                raise MigrationError(
                    "Reviewed quarantine SHA-256 changed: "
                    f"expected {args.accept_quarantine_sha256.lower()}, "
                    f"got {plan['quarantine_sha256']}"
                )

        write_json(args.plan_output, plan, overwrite=args.overwrite_output)
        if args.apply:
            reconciliation = apply_plan(
                db=db,
                plan=plan,
                media_root=media_root,
                target_dir=target_media_dir,
            )
            report = {
                "schema_version": SCHEMA_VERSION,
                "mode": "apply",
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "plan_sha256": plan["plan_sha256"],
                "quarantine_sha256": plan["quarantine_sha256"],
                "summary": plan["summary"],
                "backup_evidence": backup_evidence,
                "reconciliation": reconciliation,
                "production_touched": False,
            }
        else:
            db.rollback()
            report = {
                "schema_version": SCHEMA_VERSION,
                "mode": "dry_run",
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "plan_sha256": plan["plan_sha256"],
                "quarantine_sha256": plan["quarantine_sha256"],
                "summary": plan["summary"],
                "apply_guards": {
                    "confirmation": APPLY_CONFIRMATION,
                    "expected_plan_sha256": plan["plan_sha256"],
                    "accept_quarantine_sha256": plan["quarantine_sha256"],
                    "all_reviewed_count_arguments_required": True,
                    "reviewed_counts": {
                        "expect_source_models": plan["summary"]["source_model_rows"],
                        "expect_source_variants": plan["summary"]["source_variant_rows"],
                        "expect_detail_models": plan["summary"]["source_detail_model_rows"],
                        "expect_db_models": plan["database_preconditions"]["counts"]["models"],
                        "expect_db_revision": plan["database_guard"]["alembic_revision"],
                        "expect_db_images": plan["database_preconditions"]["counts"]["model_images"],
                        "expect_db_sizes": plan["database_preconditions"]["counts"]["model_sizes"],
                        "expect_db_colors": plan["database_preconditions"]["counts"]["model_colors"],
                        "expect_db_bom": plan["database_preconditions"]["counts"]["model_bom"],
                        "expect_variant_identities": plan["summary"][
                            "canonical_variant_identities"
                        ],
                        "expect_existing_identities": plan["summary"][
                            "exact_existing_identities"
                        ],
                        "expect_create_variants_existing_base": plan["summary"][
                            "create_variants_existing_base"
                        ],
                        "expect_create_variants_new_base": plan["summary"][
                            "create_variants_new_base"
                        ],
                        "expect_create_variants": plan["summary"]["create_variants_total"],
                        "expect_standalone_identities": plan["summary"][
                            "metadata_classification"
                        ]["standalone_identities"],
                        "expect_create_base_models": plan["summary"][
                            "create_standalone_models"
                        ],
                        "expect_total_creations": plan["summary"]["create_models_total"],
                        "expect_quarantines": plan["summary"]["quarantined_identities"],
                    },
                    "database_and_media_backups_required": True,
                },
                "database_mutated": False,
                "media_mutated": False,
                "production_touched": False,
            }
        write_json(args.report, report, overwrite=args.overwrite_output)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
