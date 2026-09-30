"""Guarded production importer for the reviewed final old-ERP model package.

This module deliberately does not relax any guard in the localhost importers.
It consumes a final, identity-keyed export and recompiles its plan from the
live production catalog.  Dry-run is the default.

Package schema (version 1)::

    {
      "schema_version": 1,
      "package_kind": "reviewed_old_erp_final_models",
      "source_key": "old-erp-sewing-models-final-2026-07-27",
      "source_files": {"artifact_name": "<sha256>", ...},
      "production_snapshot": {
        "artifact_name": "production-model-catalog.ndjson.gz",
        "artifact_sha256": "<sha256>",
        "model_count": 881,
        "identity_set_sha256": "<sha256>",
        "exact_package_identities_sha256": "<sha256>",
        "create_package_identities_sha256": "<sha256>"
      },
      "models": {
        "TJ2053|879": {
          "identity": "TJ2053|879",
          "target_classification": "create",
          "code": "TJ-2053-879",
          "name": "4303",
          "category": null,
          "description": null,
          "product_type": "Туника",
          "season": null,
          "sam_minutes": 0,
          "status": "draft",
          "details_json": {
            "general": {"model_no": "TJ-2053", "variant_no": "879"},
            "paid_operations": []
          },
          "sizes": [{"size": "S", "measurement_json": null}],
          "colors": [{"color_name": "Blue", "color_code": null}],
          "images": [{
            "source_path": "media/old_erp_model_<hash>.jpg",
            "target_name": "old_erp_model_<hash>.jpg",
            "file_url": "/storage/model-files/old_erp_model_<hash>.jpg",
            "file_name": "legacy-name.jpg",
            "content_type": "image/jpeg",
            "image_type": "model",
            "is_primary": true,
            "bytes": 12345,
            "sha256": "<sha256>"
          }]
        }
      },
      "quarantines": [...]
    }

Existing identities keep their code, name, and complete ModelImage row set.
Only blank scalar/JSON values, missing sizes/colors, and reviewed missing paid
operations can be added.  A same-operation disagreement blocks the whole plan.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import ipaddress
import json
import math
import os
import re
import shutil
import tarfile
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from sqlalchemy import func, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import settings
from app.db.session import SessionLocal
from app.models import Model, ModelBOM, ModelColor, ModelImage, ModelSize, User
from scripts import correct_old_erp_models_local as correction
from scripts import import_old_erp_models_local as local_import


SCHEMA_VERSION = 1
PACKAGE_KIND = "reviewed_old_erp_final_models"
RECEIPTS_KEY = "old_erp_production_receipts"
PRODUCTION_DOMAIN = "erp.milanapremium.uz"
PRODUCTION_DATABASE_VM = "172.16.10.3"
PRODUCTION_BACKEND_VM = "172.16.10.4"
PRODUCTION_DATABASE_PORT = 5432
APPLY_CONFIRMATION = "APPLY-REVIEWED-OLD-ERP-MODELS-TO-ERP-MILANAPREMIUM-UZ"
ADVISORY_LOCK_ID = 727202608
ALLOWED_SCALARS = ("category", "description", "product_type", "season")
ALLOWED_MUTATION_TYPES = (Model, ModelImage, ModelSize, ModelColor)
MUTABLE_CATALOG_TABLES = {
    "models",
    "model_images",
    "model_sizes",
    "model_colors",
}
PAID_OPERATION_FIELDS = ("paid_operations", "paidOperations")
SAFE_FILE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
SUPPORTED_IMAGE_TYPES = {
    "image/gif",
    "image/jpeg",
    "image/png",
    "image/webp",
}


class MigrationError(RuntimeError):
    """A fail-closed production migration guard or invariant failure."""


def clean(value: object) -> str:
    return local_import.clean(value)


def normalize_ip_address(value: object, label: str) -> str:
    """Return one canonical host IP from a bare IP or an inet/CIDR value."""
    raw = clean(value)
    if raw.startswith("[") or raw.endswith("]"):
        if not raw.startswith("[") or not raw.endswith("]") or raw.count("[") != 1 or raw.count("]") != 1:
            raise MigrationError(f"{label} must be a valid IP address or CIDR interface")
        raw = raw[1:-1]
    if "[" in raw or "]" in raw or "%" in raw:
        raise MigrationError(f"{label} must be a valid IP address or CIDR interface")
    try:
        address = ipaddress.ip_interface(raw).ip if "/" in raw else ipaddress.ip_address(raw)
    except ValueError as exc:
        raise MigrationError(f"{label} must be a valid IP address or CIDR interface") from exc
    return address.compressed


def object_sha256(value: object) -> str:
    return local_import.object_sha256(value)


def file_sha256(path: Path) -> str:
    return local_import.file_sha256(path)


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        return {"sha256": hashlib.sha256(value).hexdigest(), "bytes": len(value)}
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _checked_sha(value: object, label: str) -> str:
    digest = clean(value).lower()
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise MigrationError(f"{label} must be a SHA-256")
    return digest


def load_json(path: Path, expected_sha256: str, label: str) -> tuple[Any, Path, str]:
    try:
        payload, resolved, digest = local_import.load_json_file(path, expected_sha256, label)
    except local_import.MigrationError as exc:
        raise MigrationError(str(exc)) from exc
    return payload, resolved, digest


def _safe_relative_file(
    media_root: Path,
    relative: object,
    label: str,
) -> tuple[Path, str]:
    try:
        return local_import.resolve_under(media_root, relative, label)
    except local_import.MigrationError as exc:
        raise MigrationError(str(exc)) from exc


def _model_identity_from_details(details: object) -> str:
    if not isinstance(details, dict):
        raise MigrationError("Package model details_json must be an object")
    general = details.get("general")
    if not isinstance(general, dict):
        raise MigrationError("Package model details_json.general must be an object")
    model_no = clean(general.get("model_no") or general.get("modelNo"))
    variant_no = clean(general.get("variant_no") or general.get("variantNo"))
    if not local_import.base_key(model_no):
        raise MigrationError("Package model has no canonical general.model_no")
    return local_import.identity_key(model_no, variant_no)


def _validate_image_metadata(
    raw: object,
    *,
    media_root: Path,
    label: str,
    max_image_bytes: int,
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise MigrationError(f"{label} must be an object")
    _, relative = _safe_relative_file(media_root, raw.get("source_path"), f"{label} source_path")
    expected_sha = _checked_sha(raw.get("sha256"), f"{label}.sha256")
    try:
        expected_bytes = int(raw.get("bytes"))
    except (TypeError, ValueError) as exc:
        raise MigrationError(f"{label}.bytes must be an integer") from exc
    if expected_bytes <= 0 or expected_bytes > max_image_bytes:
        raise MigrationError(f"{label} byte count or size limit is invalid")
    content_type = clean(raw.get("content_type"))
    if content_type not in SUPPORTED_IMAGE_TYPES:
        raise MigrationError(f"{label}.content_type is not a supported image type")
    target_name = clean(raw.get("target_name"))
    if not SAFE_FILE_NAME.fullmatch(target_name) or target_name.startswith("."):
        raise MigrationError(f"{label}.target_name is unsafe")
    if len(target_name) > 255:
        raise MigrationError(f"{label}.target_name exceeds the storage limit")
    file_url = clean(raw.get("file_url"))
    if file_url != f"/storage/model-files/{target_name}":
        raise MigrationError(f"{label}.file_url does not match target_name")
    file_name = clean(raw.get("file_name")) or target_name
    if len(file_name) > 255:
        raise MigrationError(f"{label}.file_name exceeds the database limit")
    image_type = clean(raw.get("image_type")) or "model"
    if len(image_type) > 32:
        raise MigrationError(f"{label}.image_type exceeds the database limit")
    return {
        "kind": "source",
        "source_path": relative,
        "target_name": target_name,
        "file_url": file_url,
        "file_name": file_name,
        "content_type": content_type,
        "image_type": image_type,
        "is_primary": bool(raw.get("is_primary")),
        "bytes": expected_bytes,
        "sha256": expected_sha,
    }


def _validate_image_content(
    image: dict[str, Any],
    *,
    media_root: Path,
    label: str,
) -> dict[str, Any]:
    source, relative = _safe_relative_file(
        media_root,
        image["source_path"],
        f"{label} source_path",
    )
    if not source.is_file():
        raise MigrationError(f"{label} source file is missing: {source}")
    actual_bytes = source.stat().st_size
    if actual_bytes != int(image["bytes"]):
        raise MigrationError(f"{label} source byte count changed")
    if file_sha256(source) != image["sha256"]:
        raise MigrationError(f"{label} source content hash changed")
    with source.open("rb") as handle:
        head = handle.read(32)
        handle.seek(max(0, actual_bytes - 32))
        tail = handle.read(32)
    try:
        detected_type, _ = local_import.detect_image(head, tail)
    except local_import.MigrationError as exc:
        raise MigrationError(str(exc)) from exc
    if image["content_type"] != detected_type:
        raise MigrationError(
            f"{label} content_type changed: expected {image['content_type']}, detected {detected_type}"
        )
    try:
        from PIL import Image

        with Image.open(source) as opened:
            opened.verify()
    except Exception as exc:
        raise MigrationError(f"{label} failed complete image decode: {exc}") from exc
    return {
        "source_path": relative,
        "bytes": actual_bytes,
        "sha256": image["sha256"],
        "content_type": detected_type,
    }


def validate_planned_source_files(
    actions: Iterable[dict[str, Any]],
    *,
    media_root: Path,
) -> dict[str, Any]:
    """Hash/decode only images that can be written for planned new identities."""

    source_specs: dict[str, dict[str, Any]] = {}
    target_specs: dict[str, dict[str, Any]] = {}
    relation_count = 0
    for action in actions:
        if action.get("action") != "create_model":
            continue
        for image in action.get("images") or []:
            relation_count += 1
            if image.get("kind") != "source":
                raise MigrationError("New model image must use reviewed source media")
            source_path = clean(image.get("source_path"))
            source_fingerprint = {
                "bytes": int(image["bytes"]),
                "sha256": image["sha256"],
                "content_type": image["content_type"],
            }
            prior_source = source_specs.get(source_path)
            if prior_source is not None and prior_source != source_fingerprint:
                raise MigrationError(f"Planned source metadata conflicts for {source_path!r}")
            source_specs[source_path] = source_fingerprint

            target_name = clean(image.get("target_name"))
            target_fingerprint = {
                "bytes": int(image["bytes"]),
                "sha256": image["sha256"],
                "content_type": image["content_type"],
            }
            prior_target = target_specs.get(target_name)
            if prior_target is not None and prior_target != target_fingerprint:
                raise MigrationError(f"Planned media target collision for {target_name!r}")
            target_specs[target_name] = target_fingerprint

    validated_sources: list[dict[str, Any]] = []
    for source_path, fingerprint in sorted(source_specs.items()):
        validated_sources.append(
            _validate_image_content(
                {
                    "source_path": source_path,
                    **fingerprint,
                },
                media_root=media_root,
                label=f"Planned source image {source_path!r}",
            )
        )
    targets = [{"target_name": target_name, **fingerprint} for target_name, fingerprint in sorted(target_specs.items())]
    return {
        "image_relations": relation_count,
        "unique_source_files": len(validated_sources),
        "unique_target_files": len(targets),
        "unique_source_bytes": sum(int(row["bytes"]) for row in validated_sources),
        "source_files_sha256": object_sha256(validated_sources),
        "target_files_sha256": object_sha256(targets),
    }


def _validate_sizes(raw: object, label: str) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise MigrationError(f"{label}.sizes must be a list")
    result: dict[str, dict[str, Any]] = {}
    for position, row in enumerate(raw, start=1):
        if not isinstance(row, dict):
            raise MigrationError(f"{label}.sizes[{position}] must be an object")
        size = clean(row.get("size"))
        key = local_import.normalized_value(size)
        if not key:
            raise MigrationError(f"{label}.sizes[{position}] is blank")
        if len(size) > 32:
            raise MigrationError(f"{label}.sizes[{position}] exceeds the database limit")
        value = {
            "size": size,
            "measurement_json": copy.deepcopy(row.get("measurement_json")),
        }
        if key in result and result[key] != value:
            raise MigrationError(f"{label} has conflicting duplicate size {size!r}")
        result[key] = value
    return [result[key] for key in sorted(result)]


def _validate_colors(raw: object, label: str) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise MigrationError(f"{label}.colors must be a list")
    result: dict[str, dict[str, Any]] = {}
    for position, row in enumerate(raw, start=1):
        if not isinstance(row, dict):
            raise MigrationError(f"{label}.colors[{position}] must be an object")
        name = clean(row.get("color_name"))
        key = local_import.normalized_value(name)
        if not key:
            raise MigrationError(f"{label}.colors[{position}] is blank")
        if len(name) > 64:
            raise MigrationError(f"{label}.colors[{position}] exceeds the database limit")
        color_code = clean(row.get("color_code")) or None
        if color_code is not None and len(color_code) > 16:
            raise MigrationError(f"{label}.colors[{position}].color_code exceeds the database limit")
        value = {
            "color_name": name,
            "color_code": color_code,
        }
        if key in result and result[key] != value:
            raise MigrationError(f"{label} has conflicting duplicate color {name!r}")
        result[key] = value
    return [result[key] for key in sorted(result)]


def _validate_production_snapshot(
    raw: object,
    *,
    source_files: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise MigrationError("Reviewed package production_snapshot must be an object")
    required = {
        "artifact_name",
        "artifact_sha256",
        "model_count",
        "identity_set_sha256",
        "exact_package_identities_sha256",
        "create_package_identities_sha256",
    }
    if set(raw) != required:
        missing = sorted(required - set(raw))
        extra = sorted(set(raw) - required)
        raise MigrationError(f"Reviewed package production_snapshot fields changed: missing={missing}, extra={extra}")
    artifact_name = clean(raw.get("artifact_name"))
    if not artifact_name or not SAFE_FILE_NAME.fullmatch(artifact_name) or Path(artifact_name).name != artifact_name:
        raise MigrationError("production_snapshot.artifact_name is unsafe")
    artifact_sha256 = _checked_sha(
        raw.get("artifact_sha256"),
        "production_snapshot.artifact_sha256",
    )
    if clean(source_files.get(artifact_name)).lower() != artifact_sha256:
        raise MigrationError("production_snapshot artifact is not hash-pinned in source_files")
    model_count = raw.get("model_count")
    if isinstance(model_count, bool) or not isinstance(model_count, int):
        raise MigrationError("production_snapshot.model_count must be an integer")
    if model_count < 0:
        raise MigrationError("production_snapshot.model_count cannot be negative")
    return {
        "artifact_name": artifact_name,
        "artifact_sha256": artifact_sha256,
        "model_count": model_count,
        "identity_set_sha256": _checked_sha(
            raw.get("identity_set_sha256"),
            "production_snapshot.identity_set_sha256",
        ),
        "exact_package_identities_sha256": _checked_sha(
            raw.get("exact_package_identities_sha256"),
            "production_snapshot.exact_package_identities_sha256",
        ),
        "create_package_identities_sha256": _checked_sha(
            raw.get("create_package_identities_sha256"),
            "production_snapshot.create_package_identities_sha256",
        ),
    }


def validate_package(
    payload: object,
    *,
    package_sha256: str,
    media_root: Path,
    max_image_bytes: int,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise MigrationError("Reviewed package must be a JSON object")
    if int(payload.get("schema_version") or 0) != SCHEMA_VERSION:
        raise MigrationError("Reviewed package schema_version changed")
    if clean(payload.get("package_kind")) != PACKAGE_KIND:
        raise MigrationError("Reviewed package_kind changed")
    source_key = clean(payload.get("source_key"))
    if not source_key:
        raise MigrationError("Reviewed package source_key is blank")
    source_files = payload.get("source_files")
    if not isinstance(source_files, dict) or not source_files:
        raise MigrationError("Reviewed package source_files is missing")
    for key, digest in source_files.items():
        _checked_sha(digest, f"source_files.{key}")
    production_snapshot = _validate_production_snapshot(
        payload.get("production_snapshot"),
        source_files=source_files,
    )
    raw_models = payload.get("models")
    if not isinstance(raw_models, dict) or not raw_models:
        raise MigrationError("Reviewed package models must be a non-empty object")
    package_quarantines = payload.get("quarantines") or []
    if not isinstance(package_quarantines, list) or not all(isinstance(row, dict) for row in package_quarantines):
        raise MigrationError("Reviewed package quarantines must be a list of objects")

    models: dict[str, dict[str, Any]] = {}
    image_targets: dict[str, str] = {}
    for raw_key, raw in raw_models.items():
        label = f"models[{raw_key!r}]"
        if not isinstance(raw, dict):
            raise MigrationError(f"{label} must be an object")
        details = copy.deepcopy(raw.get("details_json"))
        if not isinstance(details, dict):
            raise MigrationError(f"{label}.details_json must be an object")
        if RECEIPTS_KEY in details:
            raise MigrationError(f"{label} may not supply production receipts")
        source_paid_check = merge_paid_operations({}, details)
        if source_paid_check["conflicts"]:
            raise MigrationError(f"{label} contains conflicting duplicate paid operations")
        if source_paid_check["field"] is not None:
            for field in PAID_OPERATION_FIELDS:
                details.pop(field, None)
            details["paid_operations"] = copy.deepcopy(source_paid_check["details"]["paid_operations"])
        identity = _model_identity_from_details(details)
        if clean(raw_key) != identity or clean(raw.get("identity")) != identity:
            raise MigrationError(f"{label} canonical identity changed to {identity!r}")
        target_classification = clean(raw.get("target_classification"))
        if target_classification not in {"existing", "create"}:
            raise MigrationError(f"{label}.target_classification must be 'existing' or 'create'")
        code = clean(raw.get("code"))
        name = clean(raw.get("name"))
        if not code or not name:
            raise MigrationError(f"{label} code and name are required")
        if len(code) > 64 or len(name) > 255:
            raise MigrationError(f"{label} code or name exceeds the database limit")
        raw_images = raw.get("images")
        if not isinstance(raw_images, list):
            raise MigrationError(f"{label}.images must be an explicit list")
        images = [
            _validate_image_metadata(
                item,
                media_root=media_root,
                label=f"{label}.images[{position}]",
                max_image_bytes=max_image_bytes,
            )
            for position, item in enumerate(raw_images, start=1)
        ]
        if target_classification == "existing" and images:
            raise MigrationError(f"{label} classified existing must have an explicit empty images list")
        for image in images:
            prior = image_targets.get(image["target_name"])
            if prior is not None and prior != image["sha256"]:
                raise MigrationError(f"Package target collision for {image['target_name']}")
            image_targets[image["target_name"]] = image["sha256"]
        sam_raw = raw.get("sam_minutes")
        try:
            sam_minutes = float(sam_raw or 0)
        except (TypeError, ValueError) as exc:
            raise MigrationError(f"{label}.sam_minutes is invalid") from exc
        if not math.isfinite(sam_minutes) or sam_minutes < 0:
            raise MigrationError(f"{label}.sam_minutes cannot be negative")
        optional_scalars = {
            "category": (clean(raw.get("category")) or None, 64),
            "description": (clean(raw.get("description")) or None, None),
            "product_type": (clean(raw.get("product_type")) or None, 64),
            "season": (clean(raw.get("season")) or None, 64),
            "status": (clean(raw.get("status")) or "draft", 32),
        }
        for field, (value, limit) in optional_scalars.items():
            if limit is not None and value is not None and len(value) > limit:
                raise MigrationError(f"{label}.{field} exceeds the database limit")
        record = {
            "identity": identity,
            "target_classification": target_classification,
            "code": code,
            "name": name,
            "category": optional_scalars["category"][0],
            "description": optional_scalars["description"][0],
            "product_type": optional_scalars["product_type"][0],
            "season": optional_scalars["season"][0],
            "sam_minutes": sam_minutes,
            "status": optional_scalars["status"][0],
            "details_json": details,
            "sizes": _validate_sizes(raw.get("sizes"), label),
            "colors": _validate_colors(raw.get("colors"), label),
            "images": images,
        }
        record["record_sha256"] = object_sha256(record)
        models[identity] = record
    exact_identities = sorted(
        identity for identity, record in models.items() if record["target_classification"] == "existing"
    )
    create_identities = sorted(
        identity for identity, record in models.items() if record["target_classification"] == "create"
    )
    if object_sha256(exact_identities) != production_snapshot["exact_package_identities_sha256"]:
        raise MigrationError("production_snapshot exact package identity set changed")
    if object_sha256(create_identities) != production_snapshot["create_package_identities_sha256"]:
        raise MigrationError("production_snapshot create package identity set changed")
    return {
        "schema_version": SCHEMA_VERSION,
        "package_kind": PACKAGE_KIND,
        "source_key": source_key,
        "package_sha256": package_sha256,
        "source_files": dict(sorted(source_files.items())),
        "production_snapshot": production_snapshot,
        "models": models,
        "quarantines": copy.deepcopy(package_quarantines),
        "quarantines_sha256": object_sha256(package_quarantines),
        "summary": {
            "models": len(models),
            "classified_existing": len(exact_identities),
            "classified_create": len(create_identities),
            "images": sum(len(row["images"]) for row in models.values()),
            "sizes": sum(len(row["sizes"]) for row in models.values()),
            "colors": sum(len(row["colors"]) for row in models.values()),
            "reviewed_source_quarantines": len(package_quarantines),
        },
    }


def validate_active_release_evidence(
    payload: object,
    *,
    evidence_sha256: str,
    expected_release: str,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise MigrationError("Active-release evidence must be an object")
    if clean(payload.get("kind")) != "milana_active_release":
        raise MigrationError("Active-release evidence kind changed")
    release = clean(payload.get("active_release"))
    if release != clean(expected_release):
        raise MigrationError(f"Active release changed: expected {expected_release}, got {release}")
    backend_image = clean(payload.get("backend_image"))
    backend_vm = clean(payload.get("backend_vm"))
    if not backend_image or not backend_vm:
        raise MigrationError("Active-release evidence is incomplete")
    if backend_vm != PRODUCTION_BACKEND_VM:
        raise MigrationError("Active-release evidence is not from the Milana production backend VM")
    return {
        "evidence_sha256": evidence_sha256,
        "active_release": release,
        "backend_image": backend_image,
        "backend_vm": backend_vm,
        "captured_at": payload.get("captured_at"),
    }


def validate_database_fingerprint(
    *,
    configured_host: str,
    configured_port: int,
    configured_database: str,
    observed_database: str,
    observed_user: str,
    observed_server_address: str,
    observed_server_port: int,
    in_recovery: bool,
    transaction_read_only: str,
    expected_host: str,
    expected_server_address: str,
    expected_port: int,
    expected_database: str,
    expected_user: str,
) -> dict[str, Any]:
    production_address = normalize_ip_address(
        PRODUCTION_DATABASE_VM,
        "Milana production PostgreSQL VM",
    )
    reviewed_host = normalize_ip_address(expected_host, "Reviewed database host")
    reviewed_server_address = normalize_ip_address(
        expected_server_address,
        "Reviewed server address",
    )
    if (
        reviewed_host != production_address
        or reviewed_server_address != production_address
        or int(expected_port) != PRODUCTION_DATABASE_PORT
    ):
        raise MigrationError("Reviewed database target is not the Milana production PostgreSQL VM")
    configured_address = normalize_ip_address(configured_host, "Configured DATABASE_URL host")
    if configured_address != reviewed_host:
        raise MigrationError("Configured DATABASE_URL host is not the reviewed host")
    if int(configured_port) != int(expected_port):
        raise MigrationError("Configured DATABASE_URL port is not the reviewed port")
    if clean(configured_database) != clean(expected_database):
        raise MigrationError("Configured DATABASE_URL database is not reviewed")
    if clean(observed_database) != clean(expected_database):
        raise MigrationError("Connected database is not the reviewed database")
    if clean(observed_user) != clean(expected_user):
        raise MigrationError("Connected database user is not the reviewed user")
    connected_server_address = normalize_ip_address(
        observed_server_address,
        "Connected server address",
    )
    if connected_server_address != reviewed_server_address:
        raise MigrationError("Connected server address is not the reviewed server")
    if int(observed_server_port) != int(expected_port):
        raise MigrationError("Connected server port is not the reviewed port")
    if in_recovery:
        raise MigrationError("Production importer refuses a recovery/replica server")
    if clean(transaction_read_only).casefold() not in {"off", "false", "0"}:
        raise MigrationError("Production importer requires a read-write transaction")
    return {
        "url_host": configured_address,
        "url_port": int(configured_port),
        "database": clean(observed_database),
        "database_user": clean(observed_user),
        "server_address": connected_server_address,
        "server_port": int(observed_server_port),
        "in_recovery": False,
        "transaction_read_only": "off",
    }


def production_database_guard(
    db,
    *,
    expected_host: str,
    expected_server_address: str,
    expected_port: int,
    expected_database: str,
    expected_user: str,
    expected_revision: str,
) -> dict[str, Any]:
    if not settings.is_production:
        raise MigrationError("Production importer requires ENV=production")
    url = make_url(settings.DATABASE_URL)
    row = db.execute(
        text(
            "SELECT current_database(), current_user, "
            "inet_server_addr()::text, inet_server_port(), "
            "pg_is_in_recovery(), current_setting('transaction_read_only')"
        )
    ).one()
    guard = validate_database_fingerprint(
        configured_host=clean(url.host),
        configured_port=int(url.port or 5432),
        configured_database=clean(url.database),
        observed_database=clean(row[0]),
        observed_user=clean(row[1]),
        observed_server_address=clean(row[2]),
        observed_server_port=int(row[3] or 0),
        in_recovery=bool(row[4]),
        transaction_read_only=clean(row[5]),
        expected_host=expected_host,
        expected_server_address=expected_server_address,
        expected_port=expected_port,
        expected_database=expected_database,
        expected_user=expected_user,
    )
    revision = clean(db.execute(text("SELECT version_num FROM alembic_version")).scalar_one())
    if revision != clean(expected_revision):
        raise MigrationError(f"Alembic revision changed: expected {expected_revision}, got {revision}")
    guard["alembic_revision"] = revision
    return guard


def verify_production_media_root(path: Path, expected_path: Path) -> Path:
    resolved = path.expanduser().resolve()
    expected = expected_path.expanduser().resolve()
    configured = Path(settings.MODEL_FILES_DIR).expanduser().resolve()
    if resolved != expected or resolved != configured:
        raise MigrationError("Target media root must be the reviewed settings.MODEL_FILES_DIR")
    if not resolved.is_dir():
        raise MigrationError(f"Production model media root is missing: {resolved}")
    return resolved


def media_inventory(root: Path) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for path in sorted(
        (item for item in root.rglob("*") if item.is_file()),
        key=lambda item: item.relative_to(root).as_posix(),
    ):
        rows.append(
            {
                "path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": file_sha256(path),
            }
        )
    return {
        "file_count": len(rows),
        "total_bytes": sum(int(row["bytes"]) for row in rows),
        "files_sha256": object_sha256(rows),
        "rows": rows,
    }


def _fresh_file_evidence(
    path: Path,
    expected_sha256: str,
    *,
    label: str,
    max_age_hours: float,
) -> tuple[Path, dict[str, Any]]:
    if max_age_hours <= 0:
        raise MigrationError("--max-backup-age-hours must be positive")
    resolved = path.expanduser().resolve()
    if not resolved.is_file() or resolved.stat().st_size <= 0:
        raise MigrationError(f"{label} is missing or empty")
    digest = _checked_sha(expected_sha256, f"{label} SHA-256")
    if file_sha256(resolved) != digest:
        raise MigrationError(f"{label} SHA-256 changed")
    modified_at = datetime.fromtimestamp(resolved.stat().st_mtime, tz=timezone.utc)
    age = (datetime.now(timezone.utc) - modified_at).total_seconds()
    if age < -300 or age > max_age_hours * 3600:
        raise MigrationError(f"{label} is not a fresh backup")
    return resolved, {
        "path": str(resolved),
        "bytes": resolved.stat().st_size,
        "sha256": digest,
        "modified_at": modified_at.isoformat(),
        "age_seconds_at_verification": max(0, int(age)),
    }


def verify_database_backup(
    path: Path,
    expected_sha256: str,
    *,
    max_age_hours: float,
) -> dict[str, Any]:
    try:
        return correction.verify_fresh_database_backup(
            path,
            expected_sha256,
            max_age_hours=max_age_hours,
        )
    except correction.MigrationError as exc:
        raise MigrationError(str(exc)) from exc


def _archive_relative_path(name: str) -> str:
    normalized = PurePosixPath(name.replace("\\", "/"))
    if normalized.is_absolute() or ".." in normalized.parts:
        raise MigrationError(f"Media backup contains unsafe member {name!r}")
    parts = [part for part in normalized.parts if part not in {"", "."}]
    if "model_files" not in parts:
        raise MigrationError(f"Media backup member is outside model_files: {name!r}")
    marker = parts.index("model_files")
    relative = "/".join(parts[marker + 1 :])
    if not relative:
        return ""
    return relative


def verify_media_backup(
    path: Path,
    expected_sha256: str,
    *,
    max_age_hours: float,
    expected_inventory: dict[str, Any],
) -> dict[str, Any]:
    resolved, evidence = _fresh_file_evidence(
        path,
        expected_sha256,
        label="Media backup",
        max_age_hours=max_age_hours,
    )
    try:
        archive = tarfile.open(resolved, mode="r:*")
    except (tarfile.TarError, OSError) as exc:
        raise MigrationError("Media backup is not a readable tar archive") from exc
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    with archive:
        for member in archive.getmembers():
            if member.isdir():
                continue
            if not member.isfile() or member.issym() or member.islnk():
                raise MigrationError(f"Media backup contains unsupported member {member.name!r}")
            relative = _archive_relative_path(member.name)
            if not relative:
                continue
            if relative in seen:
                raise MigrationError(f"Media backup repeats member {relative!r}")
            extracted = archive.extractfile(member)
            if extracted is None:
                raise MigrationError(f"Media backup member cannot be read: {member.name!r}")
            digest = hashlib.sha256()
            total = 0
            for chunk in iter(lambda: extracted.read(1024 * 1024), b""):
                total += len(chunk)
                digest.update(chunk)
            seen.add(relative)
            rows.append(
                {
                    "path": relative,
                    "bytes": total,
                    "sha256": digest.hexdigest(),
                }
            )
    rows.sort(key=lambda row: row["path"])
    archive_inventory = {
        "file_count": len(rows),
        "total_bytes": sum(int(row["bytes"]) for row in rows),
        "files_sha256": object_sha256(rows),
    }
    expected = {key: expected_inventory[key] for key in ("file_count", "total_bytes", "files_sha256")}
    if archive_inventory != expected:
        raise MigrationError("Media backup does not exactly reproduce the reviewed media root")
    return {
        **evidence,
        "archive_format": "tar",
        "inventory": archive_inventory,
    }


def _operation_id(row: dict[str, Any]) -> str:
    return clean(row.get("id"))


def _operation_semantic_key(row: dict[str, Any]) -> tuple[str, str]:
    name = local_import.normalized_value(row.get("name") or row.get("operation_name"))
    stage = local_import.normalized_value(row.get("stage"))
    return name, stage


def _operation_business_value(row: dict[str, Any]) -> dict[str, Any]:
    return {key: copy.deepcopy(value) for key, value in sorted(row.items()) if key != "id"}


def _paid_operations(details: dict[str, Any], *, source: bool) -> tuple[str | None, list]:
    present = [field for field in PAID_OPERATION_FIELDS if field in details and details[field] is not None]
    if len(present) > 1 and details[present[0]] != details[present[1]]:
        label = "Source" if source else "Existing"
        raise MigrationError(f"{label} paid-operation aliases disagree")
    if not present:
        return None, []
    field = present[0]
    value = details[field]
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise MigrationError(f"{field} must be a list of objects")
    return field, copy.deepcopy(value)


def merge_paid_operations(
    existing_details: dict[str, Any],
    source_details: dict[str, Any],
) -> dict[str, Any]:
    source_field, source_rows = _paid_operations(source_details, source=True)
    if source_field is None:
        return {
            "details": copy.deepcopy(existing_details),
            "field": None,
            "added": [],
            "exact": 0,
            "conflicts": [],
        }
    existing_field, existing_rows = _paid_operations(existing_details, source=False)
    target_field = existing_field or "paid_operations"
    by_id: dict[str, list[int]] = {}
    by_semantic: dict[tuple[str, str], list[int]] = {}
    idless_by_semantic: dict[tuple[str, str], list[int]] = {}
    for index, row in enumerate(existing_rows):
        existing_id = _operation_id(row)
        if existing_id:
            by_id.setdefault(existing_id, []).append(index)
        key = _operation_semantic_key(row)
        if any(key):
            by_semantic.setdefault(key, []).append(index)
            if not existing_id:
                idless_by_semantic.setdefault(key, []).append(index)

    added: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    exact = 0
    source_seen_by_id: dict[str, dict[str, Any]] = {}
    source_seen_idless: dict[tuple[str, str], dict[str, Any]] = {}
    unique_source_rows: list[tuple[int, dict[str, Any], str, tuple[str, str]]] = []
    for source_index, source_row in enumerate(source_rows):
        semantic = _operation_semantic_key(source_row)
        operation_id = _operation_id(source_row)
        if not operation_id and not any(semantic):
            conflicts.append(
                {
                    "reason": "unidentifiable_source_operation",
                    "source_index": source_index,
                }
            )
            continue
        prior_id = source_seen_by_id.get(operation_id) if operation_id else None
        if prior_id is not None:
            if _operation_business_value(prior_id) != _operation_business_value(source_row):
                conflicts.append(
                    {
                        "reason": "source_duplicate_operation_id_conflict",
                        "source_index": source_index,
                        "operation_id": operation_id,
                    }
                )
            continue
        if operation_id:
            source_seen_by_id[operation_id] = source_row
        else:
            prior_source = source_seen_idless.get(semantic)
            if prior_source is not None:
                if _operation_business_value(prior_source) != _operation_business_value(source_row):
                    conflicts.append(
                        {
                            "reason": "source_duplicate_operation_conflict",
                            "source_index": source_index,
                            "semantic_key": list(semantic),
                        }
                    )
                continue
            source_seen_idless[semantic] = source_row
        unique_source_rows.append((source_index, source_row, operation_id, semantic))

    source_semantic_counts: dict[tuple[str, str], int] = {}
    for _, _, _, semantic in unique_source_rows:
        if any(semantic):
            source_semantic_counts[semantic] = source_semantic_counts.get(semantic, 0) + 1

    for source_index, source_row, operation_id, semantic in unique_source_rows:
        candidates: list[int] = []
        if operation_id and operation_id in by_id:
            candidates = by_id[operation_id]
        elif operation_id:
            if any(semantic) and source_semantic_counts.get(semantic) == 1:
                candidates = idless_by_semantic.get(semantic, [])
            elif idless_by_semantic.get(semantic):
                conflicts.append(
                    {
                        "reason": "ambiguous_id_bearing_semantic_fallback",
                        "source_index": source_index,
                        "operation_id": operation_id,
                        "semantic_key": list(semantic),
                    }
                )
                continue
        else:
            if source_semantic_counts.get(semantic, 0) > 1:
                conflicts.append(
                    {
                        "reason": "ambiguous_idless_source_operation",
                        "source_index": source_index,
                        "semantic_key": list(semantic),
                    }
                )
                continue
            candidates = by_semantic.get(semantic, [])
        if len(candidates) > 1:
            conflicts.append(
                {
                    "reason": "ambiguous_existing_operation",
                    "source_index": source_index,
                    "semantic_key": list(semantic),
                }
            )
            continue
        if not candidates:
            added.append(copy.deepcopy(source_row))
            continue
        current = existing_rows[candidates[0]]
        if _operation_business_value(current) == _operation_business_value(source_row):
            exact += 1
            continue
        conflicts.append(
            {
                "reason": "same_operation_content_conflict",
                "source_index": source_index,
                "existing_index": candidates[0],
                "operation_id": operation_id or None,
                "semantic_key": list(semantic),
                "existing_sha256": object_sha256(current),
                "source_sha256": object_sha256(source_row),
            }
        )
    result = copy.deepcopy(existing_details)
    if not conflicts:
        result[target_field] = [*existing_rows, *added]
    return {
        "details": result,
        "field": target_field,
        "added": added,
        "exact": exact,
        "conflicts": conflicts,
    }


def _is_blank(value: object) -> bool:
    return (
        value is None
        or (isinstance(value, str) and not value.strip())
        or (isinstance(value, (list, dict)) and not value)
    )


def _merge_missing_json(
    current: Any,
    source: Any,
    *,
    path: tuple[str, ...] = (),
) -> tuple[Any, list[dict[str, Any]], list[str]]:
    if isinstance(current, dict) and isinstance(source, dict):
        result = copy.deepcopy(current)
        fills: list[dict[str, Any]] = []
        preserved: list[str] = []
        for key in sorted(source):
            if not path and key in {*PAID_OPERATION_FIELDS, RECEIPTS_KEY}:
                continue
            child_path = (*path, str(key))
            if key not in result or _is_blank(result.get(key)):
                result[key] = copy.deepcopy(source[key])
                fills.append({"path": ".".join(child_path), "value": copy.deepcopy(source[key])})
                continue
            merged, child_fills, child_preserved = _merge_missing_json(result[key], source[key], path=child_path)
            result[key] = merged
            fills.extend(child_fills)
            preserved.extend(child_preserved)
        return result, fills, preserved
    if _is_blank(current) and not _is_blank(source):
        return (
            copy.deepcopy(source),
            [{"path": ".".join(path), "value": copy.deepcopy(source)}],
            [],
        )
    if current != source:
        return copy.deepcopy(current), [], [".".join(path)]
    return copy.deepcopy(current), [], []


def desired_existing_state(
    model: Any,
    source: dict[str, Any],
) -> dict[str, Any]:
    scalar_fills: dict[str, Any] = {}
    for field in ALLOWED_SCALARS:
        incoming = source.get(field)
        if _is_blank(getattr(model, field, None)) and not _is_blank(incoming):
            scalar_fills[field] = copy.deepcopy(incoming)
    try:
        current_sam = float(getattr(model, "sam_minutes", 0) or 0)
    except (TypeError, ValueError):
        current_sam = 0
    if current_sam == 0 and float(source.get("sam_minutes") or 0) > 0:
        scalar_fills["sam_minutes"] = float(source["sam_minutes"])

    current_details = copy.deepcopy(model.details_json) if isinstance(model.details_json, dict) else {}
    merged, detail_fills, preserved = _merge_missing_json(current_details, source["details_json"])
    paid = merge_paid_operations(merged, source["details_json"])
    details_after = paid["details"]

    existing_sizes = {local_import.normalized_value(row.size): row for row in model.sizes or []}
    add_sizes = [
        copy.deepcopy(row)
        for row in source["sizes"]
        if local_import.normalized_value(row["size"]) not in existing_sizes
    ]
    existing_colors = {local_import.normalized_value(row.color_name): row for row in model.colors or []}
    add_colors = [
        copy.deepcopy(row)
        for row in source["colors"]
        if local_import.normalized_value(row["color_name"]) not in existing_colors
    ]
    return {
        "scalar_fills": scalar_fills,
        "details_after": details_after,
        "details_changed": details_after != current_details,
        "detail_fills": detail_fills,
        "preserved_detail_paths": sorted(set(preserved)),
        "paid_operations": {
            "field": paid["field"],
            "added": len(paid["added"]),
            "exact": paid["exact"],
        },
        "operation_conflicts": paid["conflicts"],
        "add_sizes": add_sizes,
        "add_colors": add_colors,
    }


def plan_existing_model(model: Model, source: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    desired = desired_existing_state(model, source)
    if desired["operation_conflicts"]:
        return None, {
            "identity": source["identity"],
            "target_model_id": int(model.id),
            "reason": "paid_operation_conflict",
            "conflicts": desired["operation_conflicts"],
            "existing_name_preserved": True,
            "existing_images_preserved": True,
        }
    if not (desired["scalar_fills"] or desired["details_changed"] or desired["add_sizes"] or desired["add_colors"]):
        return None, None
    return {
        "action": "update_existing",
        "identity": source["identity"],
        "target_model_id": int(model.id),
        "source_record_sha256": source["record_sha256"],
        "expected_code": model.code,
        "expected_name": model.name,
        "expected_images": local_import.model_image_snapshot(model),
        "expected_details_sha256": object_sha256(model.details_json),
        **desired,
    }, None


def load_models(db) -> list[Model]:
    return (
        db.query(Model)
        .options(
            selectinload(Model.images),
            selectinload(Model.sizes),
            selectinload(Model.colors),
        )
        .order_by(Model.id)
        .all()
    )


def _complete_catalog_snapshot(models: Iterable[Model]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for model in sorted(models, key=lambda item: int(item.id)):
        rows.append(
            _jsonable(
                {
                    "id": int(model.id),
                    "code": model.code,
                    "name": model.name,
                    "category": model.category,
                    "description": model.description,
                    "brand_id": model.brand_id,
                    "collection_id": model.collection_id,
                    "product_type": model.product_type,
                    "season": model.season,
                    "constructor_employee_id": model.constructor_employee_id,
                    "designer_employee_id": model.designer_employee_id,
                    "details_json": model.details_json,
                    "status": model.status,
                    "created_by": model.created_by,
                    "approved_by": model.approved_by,
                    "approved_at": model.approved_at,
                    "sam_minutes": model.sam_minutes,
                    "created_at": model.created_at,
                    "updated_at": model.updated_at,
                    "images": local_import.model_image_snapshot(model),
                    "sizes": [
                        {
                            "id": int(row.id),
                            "size": row.size,
                            "measurement_json": row.measurement_json,
                        }
                        for row in sorted(model.sizes or [], key=lambda item: int(item.id))
                    ],
                    "colors": [
                        {
                            "id": int(row.id),
                            "color_name": row.color_name,
                            "color_code": row.color_code,
                        }
                        for row in sorted(model.colors or [], key=lambda item: int(item.id))
                    ],
                }
            )
        )
    return rows


def _public_table_names(db) -> list[str]:
    names = [
        clean(row[0])
        for row in db.execute(
            text("SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname = 'public' ORDER BY tablename")
        ).all()
    ]
    for name in names:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
            raise MigrationError(f"Unsafe public table name {name!r}")
    if len(names) != len(set(names)):
        raise MigrationError("Public table catalog contains duplicate names")
    return names


def all_public_table_counts(db) -> dict[str, int]:
    result: dict[str, int] = {}
    for name in _public_table_names(db):
        result[name] = int(db.execute(text(f'SELECT count(*) FROM "{name}"')).scalar_one())
    return result


def _primary_key_columns(db, table_name: str) -> list[str]:
    rows = db.execute(
        text(
            "SELECT attribute.attname "
            "FROM pg_catalog.pg_index AS idx "
            "JOIN LATERAL unnest(idx.indkey) WITH ORDINALITY "
            "AS indexed_key(attnum, position) ON true "
            "JOIN pg_catalog.pg_attribute AS attribute "
            "ON attribute.attrelid = idx.indrelid "
            "AND attribute.attnum = indexed_key.attnum "
            "WHERE idx.indrelid = CAST(:qualified_table AS regclass) "
            "AND idx.indisprimary "
            "ORDER BY indexed_key.position"
        ),
        {"qualified_table": f"public.{table_name}"},
    ).all()
    columns = [clean(row[0]) for row in rows]
    for column in columns:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", column):
            raise MigrationError(f"Unsafe primary-key column {table_name}.{column!r}")
    if len(columns) != len(set(columns)):
        raise MigrationError(f"Duplicate primary-key columns discovered for {table_name}")
    return columns


def _hash_canonical_table_rows(
    table_name: str,
    rows: Iterable[object],
) -> dict[str, Any]:
    digest = hashlib.sha256()
    digest.update(b"milana-public-table-content-v1\0")
    digest.update(table_name.encode("utf-8"))
    digest.update(b"\0")
    row_count = 0
    for raw in rows:
        value = raw[0] if not isinstance(raw, str) else raw
        if not isinstance(value, str):
            raise MigrationError(f"Canonical row encoding for {table_name} is not text")
        encoded = value.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        row_count += 1
    return {
        "row_count": row_count,
        "content_sha256": digest.hexdigest(),
    }


def immutable_public_table_snapshots(db) -> dict[str, dict[str, Any]]:
    snapshots: dict[str, dict[str, Any]] = {}
    for table_name in _public_table_names(db):
        if table_name in MUTABLE_CATALOG_TABLES:
            continue
        primary_columns = _primary_key_columns(db, table_name)
        if primary_columns:
            order_by = ", ".join(f'table_row."{column}"' for column in primary_columns)
        else:
            order_by = 'to_jsonb(table_row)::text COLLATE "C"'
        statement = text(
            f'SELECT to_jsonb(table_row)::text FROM "{table_name}" AS table_row ORDER BY {order_by}'
        ).execution_options(stream_results=True, max_row_buffer=1000)
        result = db.execute(statement)
        try:
            streaming_rows = result.yield_per(1000) if callable(getattr(result, "yield_per", None)) else result
            snapshot = _hash_canonical_table_rows(
                table_name,
                streaming_rows,
            )
        finally:
            close = getattr(result, "close", None)
            if callable(close):
                close()
        snapshots[table_name] = {
            **snapshot,
            "primary_key_columns": primary_columns,
            "row_encoding": "postgresql_to_jsonb_text",
        }
    return snapshots


def acquire_production_locks(db) -> None:
    db.execute(text(f"SELECT pg_advisory_xact_lock({ADVISORY_LOCK_ID})"))
    db.execute(
        text("LOCK TABLE models, model_images, model_sizes, model_colors, model_bom IN SHARE ROW EXCLUSIVE MODE")
    )


def verify_frozen_target_classification(
    *,
    package: dict[str, Any],
    models: list[Model],
    db_exact: dict[str, Model],
) -> dict[str, Any]:
    snapshot = package["production_snapshot"]
    package_identities = sorted(package["models"])
    classified_existing = sorted(
        identity for identity, record in package["models"].items() if record["target_classification"] == "existing"
    )
    classified_create = sorted(
        identity for identity, record in package["models"].items() if record["target_classification"] == "create"
    )
    live_identity_set = sorted(db_exact)
    live_exact_package = sorted(identity for identity in package_identities if identity in db_exact)
    live_create_package = sorted(identity for identity in package_identities if identity not in db_exact)
    observed = {
        "model_count": len(models),
        "identity_set_sha256": object_sha256(live_identity_set),
        "exact_package_identities_sha256": object_sha256(live_exact_package),
        "create_package_identities_sha256": object_sha256(live_create_package),
    }
    package_fingerprints = {
        "exact_package_identities_sha256": object_sha256(classified_existing),
        "create_package_identities_sha256": object_sha256(classified_create),
    }
    changed = {
        field: {
            "frozen": snapshot[field],
            "observed": observed[field],
        }
        for field in observed
        if observed[field] != snapshot[field]
    }
    for field, digest in package_fingerprints.items():
        if digest != snapshot[field]:
            changed[f"package_{field}"] = {
                "frozen": snapshot[field],
                "observed": digest,
            }
    classification_shifts = [
        {
            "identity": identity,
            "frozen": package["models"][identity]["target_classification"],
            "observed": "existing" if identity in db_exact else "create",
        }
        for identity in package_identities
        if package["models"][identity]["target_classification"] != ("existing" if identity in db_exact else "create")
    ]
    if classification_shifts:
        changed["target_classification"] = classification_shifts[:50]
    if changed:
        raise MigrationError(f"Frozen production snapshot or target classification changed: {changed}")
    return {
        **observed,
        "canonical_identity_count": len(live_identity_set),
        "exact_package_identity_count": len(live_exact_package),
        "create_package_identity_count": len(live_create_package),
        "target_classifications_verified": len(package_identities),
    }


def compile_plan(
    *,
    db,
    package: dict[str, Any],
    package_media_root: Path,
    database_guard: dict[str, Any],
    active_release: dict[str, Any],
    target_media_root: Path,
    creator_user_id: int,
) -> dict[str, Any]:
    if not db.get(User, int(creator_user_id)):
        raise MigrationError("Reviewed creator_user_id does not exist")
    models = load_models(db)
    try:
        db_exact, _ = local_import.assert_no_duplicate_db_identities(models)
    except local_import.MigrationError as exc:
        raise MigrationError(str(exc)) from exc
    snapshot_verification = verify_frozen_target_classification(
        package=package,
        models=models,
        db_exact=db_exact,
    )
    existing_codes = {local_import.base_key(model.code): int(model.id) for model in models}
    planned_codes: dict[str, str] = {}
    actions: list[dict[str, Any]] = []
    quarantines: list[dict[str, Any]] = []
    for identity, source in sorted(package["models"].items()):
        target = db_exact.get(identity)
        if target is not None:
            action, quarantine = plan_existing_model(target, source)
            if action is not None:
                actions.append(action)
            if quarantine is not None:
                quarantines.append(quarantine)
            continue
        code_key = local_import.base_key(source["code"])
        collision = existing_codes.get(code_key)
        if collision is not None or code_key in planned_codes:
            quarantines.append(
                {
                    "identity": identity,
                    "reason": "new_identity_code_collision",
                    "code": source["code"],
                    "existing_model_id": collision,
                    "planned_identity": planned_codes.get(code_key),
                }
            )
            continue
        planned_codes[code_key] = identity
        actions.append(
            {
                "action": "create_model",
                "identity": identity,
                "source_record_sha256": source["record_sha256"],
                "record": copy.deepcopy(source),
                "images": copy.deepcopy(source["images"]),
            }
        )
    actions.sort(
        key=lambda row: (
            0 if row["action"] == "update_existing" else 1,
            row["identity"],
        )
    )
    source_media_validation = validate_planned_source_files(
        actions,
        media_root=package_media_root,
    )
    inventory = media_inventory(target_media_root)
    try:
        media_preflight = local_import.media_preflight({"actions": actions}, target_media_root)
    except local_import.MigrationError as exc:
        raise MigrationError(str(exc)) from exc
    table_counts = all_public_table_counts(db)
    immutable_table_snapshots = immutable_public_table_snapshots(db)
    protected = local_import.protected_snapshot(models)
    catalog = _complete_catalog_snapshot(models)
    summary = {
        "source_models": len(package["models"]),
        "update_existing": sum(row["action"] == "update_existing" for row in actions),
        "create_models": sum(row["action"] == "create_model" for row in actions),
        "add_images": sum(len(row.get("images") or []) for row in actions if row["action"] == "create_model"),
        "add_sizes": sum(len((row.get("record") or {}).get("sizes") or row.get("add_sizes") or []) for row in actions),
        "add_colors": sum(
            len((row.get("record") or {}).get("colors") or row.get("add_colors") or []) for row in actions
        ),
        "paid_operations_added": sum(int((row.get("paid_operations") or {}).get("added") or 0) for row in actions),
        "quarantines": len(quarantines),
        "reviewed_source_quarantines": len(package["quarantines"]),
        "ready_for_apply": not quarantines,
    }
    plan = {
        "schema_version": SCHEMA_VERSION,
        "mode": "production_plan",
        "production_domain": PRODUCTION_DOMAIN,
        "target_environment": "production",
        "production_targeted": True,
        "production_touched": False,
        "source_key": package["source_key"],
        "package_sha256": package["package_sha256"],
        "source_files": copy.deepcopy(package["source_files"]),
        "production_snapshot": copy.deepcopy(package["production_snapshot"]),
        "production_snapshot_verification": snapshot_verification,
        "database_guard": copy.deepcopy(database_guard),
        "active_release": copy.deepcopy(active_release),
        "media_root": str(target_media_root),
        "media_inventory": {key: inventory[key] for key in ("file_count", "total_bytes", "files_sha256")},
        "media_preflight": media_preflight,
        "source_media_validation": source_media_validation,
        "database_preconditions": {
            "creator_user_id": int(creator_user_id),
            "catalog_sha256": object_sha256(catalog),
            "protected_names_images_sha256": object_sha256(protected),
            "table_counts": table_counts,
            "immutable_table_snapshots": immutable_table_snapshots,
            "immutable_table_snapshots_sha256": object_sha256(immutable_table_snapshots),
            "counts": {
                "models": int(db.query(func.count(Model.id)).scalar() or 0),
                "model_images": int(db.query(func.count(ModelImage.id)).scalar() or 0),
                "model_sizes": int(db.query(func.count(ModelSize.id)).scalar() or 0),
                "model_colors": int(db.query(func.count(ModelColor.id)).scalar() or 0),
                "model_bom": int(db.query(func.count(ModelBOM.id)).scalar() or 0),
            },
        },
        "summary": summary,
        "reviewed_source_quarantines": copy.deepcopy(package["quarantines"]),
        "reviewed_source_quarantines_sha256": package["quarantines_sha256"],
        "quarantines": quarantines,
        "actions": actions,
        "invariants": {
            "existing_codes_names_images_immutable": True,
            "existing_images_never_added": True,
            "blank_only_scalar_and_json_fill": True,
            "paid_operations_additive_exact_or_missing_only": True,
            "same_operation_conflicts_block_apply": True,
            "reviewed_source_quarantines_are_evidence_not_actions": True,
            "operational_table_rows_immutable": True,
            "operational_table_row_content_sha256_verified": True,
        },
    }
    plan["plan_sha256"] = object_sha256(plan)
    return plan


def _append_receipt(
    details: dict[str, Any],
    *,
    plan: dict[str, Any],
    identity: str,
    action: str,
    action_index: int,
) -> dict[str, Any]:
    result = copy.deepcopy(details)
    current = result.get(RECEIPTS_KEY)
    if current is None:
        receipts: list[dict[str, Any]] = []
    elif isinstance(current, list) and all(isinstance(row, dict) for row in current):
        receipts = copy.deepcopy(current)
    else:
        raise MigrationError(f"Existing {RECEIPTS_KEY} is malformed")
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "target_environment": "production",
        "source_key": plan["source_key"],
        "package_sha256": plan["package_sha256"],
        "plan_sha256": plan["plan_sha256"],
        "identity": identity,
        "action": action,
        "action_index": action_index,
        "action_count": len(plan["actions"]),
        "active_release": plan["active_release"]["active_release"],
        "applied_at": datetime.now(timezone.utc).isoformat(),
    }
    if not any(
        row.get("plan_sha256") == receipt["plan_sha256"] and row.get("identity") == identity for row in receipts
    ):
        receipts.append(receipt)
    result[RECEIPTS_KEY] = receipts
    return result


def _add_sizes(db, model: Model, rows: list[dict[str, Any]]) -> int:
    existing = {local_import.normalized_value(row.size) for row in model.sizes or []}
    added = 0
    for row in rows:
        key = local_import.normalized_value(row["size"])
        if key in existing:
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


def _add_colors(db, model: Model, rows: list[dict[str, Any]]) -> int:
    existing = {local_import.normalized_value(row.color_name) for row in model.colors or []}
    added = 0
    for row in rows:
        key = local_import.normalized_value(row["color_name"])
        if key in existing:
            continue
        db.add(
            ModelColor(
                model_id=int(model.id),
                color_name=row["color_name"],
                color_code=row.get("color_code"),
            )
        )
        existing.add(key)
        added += 1
    return added


def _add_images(db, model: Model, rows: list[dict[str, Any]]) -> int:
    added = 0
    for row in rows:
        if row.get("kind") != "source":
            raise MigrationError("New model image must use reviewed source media")
        db.add(
            ModelImage(
                model_id=int(model.id),
                file_url=row["file_url"],
                file_name=row["file_name"],
                content_type=row["content_type"],
                file_data=None,
                image_type=row["image_type"],
                is_primary=bool(row["is_primary"]),
            )
        )
        added += 1
    return added


def _assert_orm_mutation_scope(db) -> None:
    if db.deleted:
        raise MigrationError("Production model migration never deletes ORM rows")
    unexpected = [type(row).__name__ for row in [*db.new, *db.dirty] if not isinstance(row, ALLOWED_MUTATION_TYPES)]
    if unexpected:
        raise MigrationError("Unexpected ORM mutation types: " + ", ".join(sorted(set(unexpected))))


def cleanup_created_files(
    paths: Iterable[Path],
    *,
    target_root: Path,
    commit_started: bool,
) -> None:
    if commit_started:
        return
    root = target_root.resolve()
    for path in reversed(list(paths)):
        try:
            resolved = path.resolve()
            if resolved.is_file() and resolved.parent == root and resolved.name and not resolved.name.startswith("."):
                resolved.unlink()
        except OSError:
            pass


def apply_plan(
    *,
    db,
    plan: dict[str, Any],
    media_root: Path,
    target_media_root: Path,
) -> dict[str, Any]:
    if not plan["summary"]["ready_for_apply"]:
        raise MigrationError("Production plan has quarantines/blocking conflicts")
    models_before = load_models(db)
    before_by_id = {int(model.id): model for model in models_before}
    before_catalog_sha = object_sha256(_complete_catalog_snapshot(models_before))
    expected = plan["database_preconditions"]
    if before_catalog_sha != expected["catalog_sha256"]:
        raise MigrationError("Catalog changed after the reviewed production plan")
    protected_before = local_import.protected_snapshot(models_before)
    protected_before_sha = object_sha256(protected_before)
    if protected_before_sha != expected["protected_names_images_sha256"]:
        raise MigrationError("Protected model names/images changed after review")
    table_counts_before = all_public_table_counts(db)
    if table_counts_before != expected["table_counts"]:
        raise MigrationError("Public table counts changed after review")
    immutable_tables_before = immutable_public_table_snapshots(db)
    if (
        immutable_tables_before != expected["immutable_table_snapshots"]
        or object_sha256(immutable_tables_before) != expected["immutable_table_snapshots_sha256"]
    ):
        raise MigrationError("Immutable public table content changed after the reviewed plan")
    current_inventory = media_inventory(target_media_root)
    inventory_summary = {key: current_inventory[key] for key in ("file_count", "total_bytes", "files_sha256")}
    if inventory_summary != plan["media_inventory"]:
        raise MigrationError("Production model media inventory changed after review")
    try:
        current_media_preflight = local_import.media_preflight(plan, target_media_root)
    except local_import.MigrationError as exc:
        raise MigrationError(str(exc)) from exc
    if current_media_preflight != plan["media_preflight"]:
        raise MigrationError("Production media preflight changed after review")
    required_bytes = int(current_media_preflight.get("source_bytes_to_create") or 0)
    safety_margin = max(512 * 1024 * 1024, required_bytes // 10) if required_bytes else 0
    if shutil.disk_usage(target_media_root).free < required_bytes + safety_margin:
        raise MigrationError("Insufficient production media disk space")

    created_files: list[Path] = []
    commit_started = False
    result = {
        "created_models": 0,
        "updated_existing": 0,
        "added_images": 0,
        "added_sizes": 0,
        "added_colors": 0,
        "created_model_ids": [],
        "updated_model_ids": [],
    }
    try:
        try:
            created_files = local_import.materialize_source_images(
                plan,
                media_root=media_root,
                target_dir=target_media_root,
            )
        except local_import.MigrationError as exc:
            raise MigrationError(str(exc)) from exc
        creator_user_id = int(expected["creator_user_id"])
        for action_index, action in enumerate(plan["actions"], start=1):
            if action["action"] == "update_existing":
                model = db.get(Model, int(action["target_model_id"]))
                if model is None:
                    raise MigrationError(f"Existing target {action['target_model_id']} disappeared")
                if (
                    model.code != action["expected_code"]
                    or model.name != action["expected_name"]
                    or local_import.model_image_snapshot(model) != action["expected_images"]
                ):
                    raise MigrationError(f"Protected identity changed for model {model.id}")
                if object_sha256(model.details_json) != action["expected_details_sha256"]:
                    raise MigrationError(f"Details changed for model {model.id}")
                for field, value in action["scalar_fills"].items():
                    if field == "sam_minutes":
                        if float(model.sam_minutes or 0) != 0:
                            raise MigrationError(f"SAM became nonblank for model {model.id}")
                    elif not _is_blank(getattr(model, field)):
                        raise MigrationError(f"Scalar {field} became nonblank for model {model.id}")
                    setattr(model, field, value)
                model.details_json = _append_receipt(
                    action["details_after"],
                    plan=plan,
                    identity=action["identity"],
                    action="update_existing",
                    action_index=action_index,
                )
                flag_modified(model, "details_json")
                result["added_sizes"] += _add_sizes(db, model, action["add_sizes"])
                result["added_colors"] += _add_colors(db, model, action["add_colors"])
                result["updated_existing"] += 1
                result["updated_model_ids"].append(int(model.id))
                continue

            if action["action"] != "create_model":
                raise MigrationError(f"Unsupported production action {action['action']!r}")
            record = action["record"]
            if (
                object_sha256({key: value for key, value in record.items() if key != "record_sha256"})
                != record["record_sha256"]
            ):
                raise MigrationError(f"Source record changed for {action['identity']}")
            details = _append_receipt(
                record["details_json"],
                plan=plan,
                identity=action["identity"],
                action="create_model",
                action_index=action_index,
            )
            model = Model(
                code=record["code"],
                name=record["name"],
                category=record.get("category"),
                description=record.get("description"),
                brand_id=None,
                collection_id=None,
                product_type=record.get("product_type"),
                season=record.get("season"),
                details_json=details,
                status=record["status"],
                created_by=creator_user_id,
                sam_minutes=record["sam_minutes"],
            )
            db.add(model)
            db.flush()
            result["added_sizes"] += _add_sizes(db, model, record["sizes"])
            result["added_colors"] += _add_colors(db, model, record["colors"])
            result["added_images"] += _add_images(
                db,
                model,
                record["images"],
            )
            result["created_models"] += 1
            result["created_model_ids"].append(int(model.id))

        _assert_orm_mutation_scope(db)
        db.flush()
        db.expire_all()
        models_after = load_models(db)
        after_by_id = {int(model.id): model for model in models_after}
        protected_after = local_import.protected_snapshot(after_by_id[model_id] for model_id in sorted(before_by_id))
        protected_after_sha = object_sha256(protected_after)
        if protected_after_sha != protected_before_sha:
            raise MigrationError("An existing model code, name, or image row changed")
        table_counts_after = all_public_table_counts(db)
        immutable_tables_after = immutable_public_table_snapshots(db)
        if immutable_tables_after != immutable_tables_before:
            changed_content = {
                name: {
                    "before": immutable_tables_before.get(name),
                    "after": immutable_tables_after.get(name),
                }
                for name in set(immutable_tables_before) | set(immutable_tables_after)
                if immutable_tables_before.get(name) != immutable_tables_after.get(name)
            }
            raise MigrationError(
                f"Immutable public table row content changed inside the migration transaction: {changed_content}"
            )
        changed_unexpected = {
            name: {
                "before": table_counts_before.get(name),
                "after": table_counts_after.get(name),
            }
            for name in set(table_counts_before) | set(table_counts_after)
            if name not in MUTABLE_CATALOG_TABLES and table_counts_before.get(name) != table_counts_after.get(name)
        }
        if changed_unexpected:
            raise MigrationError(f"Operational table counts changed: {changed_unexpected}")
        reconciliations = {
            "models": result["created_models"],
            "model_images": result["added_images"],
            "model_sizes": result["added_sizes"],
            "model_colors": result["added_colors"],
        }
        for table_name, expected_delta in reconciliations.items():
            actual_delta = table_counts_after[table_name] - table_counts_before[table_name]
            if actual_delta != expected_delta:
                raise MigrationError(f"{table_name} delta changed: expected {expected_delta}, got {actual_delta}")
        commit_started = True
        db.commit()
        result.update(
            {
                "created_files": [str(path) for path in created_files],
                "table_counts_before": table_counts_before,
                "table_counts_after": table_counts_after,
                "immutable_table_snapshots_sha256_before": object_sha256(immutable_tables_before),
                "immutable_table_snapshots_sha256_after": object_sha256(immutable_tables_after),
                "protected_names_images_sha256_before": protected_before_sha,
                "protected_names_images_sha256_after": protected_after_sha,
                "transactional_receipt_plan_sha256": plan["plan_sha256"],
            }
        )
        return result
    except Exception:
        db.rollback()
        cleanup_created_files(
            created_files,
            target_root=target_media_root,
            commit_started=commit_started,
        )
        raise


def write_durable_json(path: Path, payload: object, *, overwrite: bool) -> None:
    resolved = path.expanduser().resolve()
    if resolved.exists() and not overwrite:
        raise MigrationError(f"Output already exists: {resolved}")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    temporary = resolved.with_name(f".{resolved.name}.{os.getpid()}.tmp")
    if temporary.exists():
        raise MigrationError(f"Stale output staging file exists: {temporary}")
    flags = "w" if overwrite else "x"
    with temporary.open(flags, encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, resolved)
    try:
        directory_fd = os.open(str(resolved.parent), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(directory_fd)
    except OSError:
        pass
    finally:
        os.close(directory_fd)


def enforce_expected_counts(args: argparse.Namespace, plan: dict[str, Any]) -> None:
    checks = {
        "--expect-source-models": (
            args.expect_source_models,
            plan["summary"]["source_models"],
        ),
        "--expect-update-existing": (
            args.expect_update_existing,
            plan["summary"]["update_existing"],
        ),
        "--expect-create-models": (
            args.expect_create_models,
            plan["summary"]["create_models"],
        ),
        "--expect-add-images": (
            args.expect_add_images,
            plan["summary"]["add_images"],
        ),
        "--expect-add-sizes": (
            args.expect_add_sizes,
            plan["summary"]["add_sizes"],
        ),
        "--expect-add-colors": (
            args.expect_add_colors,
            plan["summary"]["add_colors"],
        ),
        "--expect-paid-operations-added": (
            args.expect_paid_operations_added,
            plan["summary"]["paid_operations_added"],
        ),
        "--expect-quarantines": (
            args.expect_quarantines,
            plan["summary"]["quarantines"],
        ),
        "--expect-reviewed-source-quarantines": (
            args.expect_reviewed_source_quarantines,
            plan["summary"]["reviewed_source_quarantines"],
        ),
    }
    missing: list[str] = []
    for flag, (expected, actual) in checks.items():
        if expected is None:
            if args.apply:
                missing.append(flag)
            continue
        if int(expected) != int(actual):
            raise MigrationError(f"Reviewed count {flag} changed: expected {expected}, got {actual}")
    if missing:
        raise MigrationError("Apply requires every reviewed count: " + ", ".join(missing))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Plan/apply the reviewed final old-ERP model package to production.")
    parser.add_argument("--package", required=True, type=Path)
    parser.add_argument("--package-sha256", required=True)
    parser.add_argument("--media-root", required=True, type=Path)
    parser.add_argument("--target-media-dir", required=True, type=Path)
    parser.add_argument("--expected-media-root", required=True, type=Path)
    parser.add_argument("--max-image-bytes", type=int, default=25 * 1024 * 1024)
    parser.add_argument("--active-release-evidence", required=True, type=Path)
    parser.add_argument("--active-release-evidence-sha256", required=True)
    parser.add_argument("--expected-active-release", required=True)
    parser.add_argument("--expected-database-host", required=True)
    parser.add_argument("--expected-server-address", required=True)
    parser.add_argument("--expected-server-port", type=int, default=5432)
    parser.add_argument("--expected-database-name", default="erp")
    parser.add_argument("--expected-database-user", required=True)
    parser.add_argument("--expected-db-revision", required=True)
    parser.add_argument("--creator-user-id", required=True, type=int)
    parser.add_argument("--expected-media-inventory-sha256")
    parser.add_argument("--expected-reviewed-source-quarantines-sha256")
    parser.add_argument("--plan-output", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--overwrite-output", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-production")
    parser.add_argument("--expected-plan-sha256")
    parser.add_argument("--database-backup", type=Path)
    parser.add_argument("--database-backup-sha256")
    parser.add_argument("--media-backup", type=Path)
    parser.add_argument("--media-backup-sha256")
    parser.add_argument("--max-backup-age-hours", type=float, default=24.0)
    parser.add_argument("--expect-source-models", type=int)
    parser.add_argument("--expect-update-existing", type=int)
    parser.add_argument("--expect-create-models", type=int)
    parser.add_argument("--expect-add-images", type=int)
    parser.add_argument("--expect-add-sizes", type=int)
    parser.add_argument("--expect-add-colors", type=int)
    parser.add_argument("--expect-paid-operations-added", type=int)
    parser.add_argument("--expect-quarantines", type=int)
    parser.add_argument("--expect-reviewed-source-quarantines", type=int)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    plan_output = args.plan_output.expanduser().resolve()
    report_output = args.report.expanduser().resolve()
    if plan_output == report_output:
        raise MigrationError("--plan-output and --report must differ")
    protected_inputs = {
        path.expanduser().resolve()
        for path in (
            args.package,
            args.active_release_evidence,
            args.database_backup,
            args.media_backup,
        )
        if path is not None
    }
    if plan_output in protected_inputs or report_output in protected_inputs:
        raise MigrationError("Outputs must not overwrite an input or backup")
    if not args.overwrite_output:
        existing_outputs = [str(path) for path in (plan_output, report_output) if path.exists()]
        if existing_outputs:
            raise MigrationError("Output already exists: " + ", ".join(existing_outputs))
    if args.max_image_bytes <= 0:
        raise MigrationError("--max-image-bytes must be positive")
    if args.apply:
        if args.confirm_production != APPLY_CONFIRMATION:
            raise MigrationError(f"Apply requires --confirm-production {APPLY_CONFIRMATION}")
        expected_plan_sha = _checked_sha(args.expected_plan_sha256, "--expected-plan-sha256")
        if not args.expected_media_inventory_sha256:
            raise MigrationError("Apply requires --expected-media-inventory-sha256")
        expected_reviewed_quarantines_sha = _checked_sha(
            args.expected_reviewed_source_quarantines_sha256,
            "--expected-reviewed-source-quarantines-sha256",
        )
    else:
        expected_plan_sha = ""
        expected_reviewed_quarantines_sha = ""

    package_payload, _, package_sha = load_json(args.package, args.package_sha256, "Reviewed final model package")
    media_root = args.media_root.expanduser().resolve()
    if not media_root.is_dir():
        raise MigrationError(f"Package media root is missing: {media_root}")
    package = validate_package(
        package_payload,
        package_sha256=package_sha,
        media_root=media_root,
        max_image_bytes=args.max_image_bytes,
    )
    release_payload, _, release_sha = load_json(
        args.active_release_evidence,
        args.active_release_evidence_sha256,
        "Active-release evidence",
    )
    active_release = validate_active_release_evidence(
        release_payload,
        evidence_sha256=release_sha,
        expected_release=args.expected_active_release,
    )
    target_media_root = verify_production_media_root(
        args.target_media_dir,
        args.expected_media_root,
    )

    db = SessionLocal()
    try:
        database_guard = production_database_guard(
            db,
            expected_host=args.expected_database_host,
            expected_server_address=args.expected_server_address,
            expected_port=args.expected_server_port,
            expected_database=args.expected_database_name,
            expected_user=args.expected_database_user,
            expected_revision=args.expected_db_revision,
        )
        if args.apply:
            acquire_production_locks(db)
        plan = compile_plan(
            db=db,
            package=package,
            package_media_root=media_root,
            database_guard=database_guard,
            active_release=active_release,
            target_media_root=target_media_root,
            creator_user_id=args.creator_user_id,
        )
        enforce_expected_counts(args, plan)
        expected_inventory_sha = clean(args.expected_media_inventory_sha256).lower()
        if expected_inventory_sha:
            expected_inventory_sha = _checked_sha(
                expected_inventory_sha,
                "--expected-media-inventory-sha256",
            )
            if plan["media_inventory"]["files_sha256"] != expected_inventory_sha:
                raise MigrationError("Reviewed production media inventory changed")
        if (
            expected_reviewed_quarantines_sha
            and plan["reviewed_source_quarantines_sha256"] != expected_reviewed_quarantines_sha
        ):
            raise MigrationError("Reviewed source quarantine evidence changed")
        if args.apply and plan["plan_sha256"] != expected_plan_sha:
            raise MigrationError(
                "Live production plan differs from reviewed plan: "
                f"expected {expected_plan_sha}, got {plan['plan_sha256']}"
            )
        if args.apply and not plan["summary"]["ready_for_apply"]:
            raise MigrationError("Production plan contains quarantines")

        # This fsync-backed plan exists before the first file/DB mutation.
        write_durable_json(
            args.plan_output,
            plan,
            overwrite=args.overwrite_output,
        )
        backup_evidence = None
        if args.apply:
            if (
                not args.database_backup
                or not args.database_backup_sha256
                or not args.media_backup
                or not args.media_backup_sha256
            ):
                raise MigrationError("Apply requires fresh database and media backups with SHA-256")
            live_inventory = media_inventory(target_media_root)
            backup_evidence = {
                "database": verify_database_backup(
                    args.database_backup,
                    args.database_backup_sha256,
                    max_age_hours=args.max_backup_age_hours,
                ),
                "media": verify_media_backup(
                    args.media_backup,
                    args.media_backup_sha256,
                    max_age_hours=args.max_backup_age_hours,
                    expected_inventory=live_inventory,
                ),
            }
            reconciliation = apply_plan(
                db=db,
                plan=plan,
                media_root=media_root,
                target_media_root=target_media_root,
            )
            mode = "apply"
        else:
            db.rollback()
            reconciliation = None
            mode = "dry_run"
        report = {
            "schema_version": SCHEMA_VERSION,
            "mode": mode,
            "target_environment": "production",
            "production_targeted": True,
            "production_touched": bool(args.apply),
            "plan_sha256": plan["plan_sha256"],
            "package_sha256": package["package_sha256"],
            "production_snapshot": plan["production_snapshot"],
            "production_snapshot_verification": plan["production_snapshot_verification"],
            "active_release": active_release,
            "database_guard": database_guard,
            "media_inventory": plan["media_inventory"],
            "source_media_validation": plan["source_media_validation"],
            "summary": plan["summary"],
            "reviewed_source_quarantines": plan["reviewed_source_quarantines"],
            "reviewed_source_quarantines_sha256": plan["reviewed_source_quarantines_sha256"],
            "quarantines": plan["quarantines"],
            "backup_evidence": backup_evidence,
            "reconciliation": reconciliation,
            "transactional_receipt": {
                "storage": f"models.details_json.{RECEIPTS_KEY}",
                "plan_sha256": plan["plan_sha256"],
                "expected_rows": len(plan["actions"]) if args.apply else 0,
            },
            "apply_guards": None
            if args.apply
            else {
                "confirmation": APPLY_CONFIRMATION,
                "expected_plan_sha256": plan["plan_sha256"],
                "expected_media_inventory_sha256": plan["media_inventory"]["files_sha256"],
                "expected_reviewed_source_quarantines_sha256": plan["reviewed_source_quarantines_sha256"],
                "all_reviewed_counts_required": True,
                "fresh_database_and_exact_media_backups_required": True,
            },
        }
        write_durable_json(
            args.report,
            report,
            overwrite=args.overwrite_output,
        )
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
