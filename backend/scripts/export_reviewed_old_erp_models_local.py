"""Export the reviewed localhost old-ERP models for the guarded importer.

The exporter is deliberately localhost-only and read-only with respect to the
database.  It binds the final reviewed catalog to the exact original,
correction, delta, name-correction, empty-paid-operation, and production
catalog artifacts used during review.

Existing production identities are exported with ``images: []`` so their
picture rows cannot be changed.  Only identities absent from the frozen
production snapshot carry image metadata and staged source files.
"""

from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import json
import math
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable
from urllib.parse import unquote, urlsplit

from sqlalchemy import text
from sqlalchemy.orm import selectinload

from app.db.session import SessionLocal
from app.models import Model
from scripts import import_old_erp_models_local as local_import
from scripts import migrate_reviewed_old_erp_models_production as production_import


SCHEMA_VERSION = production_import.SCHEMA_VERSION
PACKAGE_KIND = production_import.PACKAGE_KIND
SOURCE_KEY = "old-erp-sewing-models-final-2026-07-27"
ORIGINAL_DETAILS_KEY = "old_erp_migration"
DELTA_DETAILS_KEY = "old_erp_delta_migration"
PRODUCTION_RECEIPTS_KEY = production_import.RECEIPTS_KEY
DEFAULT_LOCAL_DB_PORT = local_import.DEFAULT_LOCAL_DB_PORT
SUPPORTED_IMAGE_TYPES = production_import.SUPPORTED_IMAGE_TYPES
SAFE_FILE_NAME = production_import.SAFE_FILE_NAME
DEFAULT_MAX_IMAGE_BYTES = 25 * 1024 * 1024


MigrationError = local_import.MigrationError


@dataclass(frozen=True)
class Artifact:
    """A hash-pinned JSON artifact loaded from disk."""

    key: str
    path: Path
    sha256: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class MediaFile:
    """One unique, fully validated file to stage in the package."""

    source: Path
    relative_path: str
    target_name: str
    bytes: int
    sha256: str
    content_type: str


def clean(value: object) -> str:
    return local_import.clean(value)


def object_sha256(value: object) -> str:
    return local_import.object_sha256(value)


def file_sha256(path: Path) -> str:
    return local_import.file_sha256(path)


def _checked_sha256(value: object, label: str) -> str:
    digest = clean(value).lower()
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise MigrationError(f"{label} must be a SHA-256")
    return digest


def load_artifact(
    key: str,
    path: Path,
    expected_sha256: str,
) -> Artifact:
    payload, resolved, digest = local_import.load_json_file(
        path,
        expected_sha256,
        key,
    )
    if not isinstance(payload, dict):
        raise MigrationError(f"{key} must be a JSON object")
    return Artifact(key=key, path=resolved, sha256=digest, payload=payload)


def _validate_internal_plan_hash(artifact: Artifact) -> str:
    claimed = _checked_sha256(
        artifact.payload.get("plan_sha256"),
        f"{artifact.key}.plan_sha256",
    )
    body = copy.deepcopy(artifact.payload)
    body.pop("plan_sha256", None)
    actual = object_sha256(body)
    if claimed != actual:
        raise MigrationError(
            f"{artifact.key} logical plan hash changed: expected {claimed}, got {actual}"
        )
    return claimed


def validate_receipt_pair(
    plan: Artifact,
    report: Artifact,
    *,
    expected_source_key: str | None = None,
) -> dict[str, Any]:
    """Validate an immutable dry-run plan and its successful local apply receipt."""

    if int(plan.payload.get("schema_version") or 0) != SCHEMA_VERSION:
        raise MigrationError(f"{plan.key} schema_version changed")
    if int(report.payload.get("schema_version") or 0) != SCHEMA_VERSION:
        raise MigrationError(f"{report.key} schema_version changed")
    logical_plan_sha = _validate_internal_plan_hash(plan)
    if clean(report.payload.get("plan_sha256")).lower() != logical_plan_sha:
        raise MigrationError(f"{plan.key} and {report.key} plan hashes disagree")
    if clean(report.payload.get("mode")) != "apply":
        raise MigrationError(f"{report.key} is not an apply receipt")
    if bool(report.payload.get("production_touched")):
        raise MigrationError(f"{report.key} claims production was touched")
    source_key = clean(plan.payload.get("source_key"))
    report_source_key = clean(report.payload.get("source_key"))
    if report_source_key and report_source_key != source_key:
        raise MigrationError(f"{plan.key} and {report.key} source_key values disagree")
    if expected_source_key is not None and source_key != expected_source_key:
        raise MigrationError(
            f"{plan.key} source_key changed: expected {expected_source_key}, got {source_key}"
        )
    actions = plan.payload.get("actions")
    if not isinstance(actions, list) or not all(isinstance(row, dict) for row in actions):
        raise MigrationError(f"{plan.key}.actions must be a list of objects")
    return {
        "source_key": source_key,
        "logical_plan_sha256": logical_plan_sha,
        "actions": actions,
    }


def _action_identities(actions: Iterable[dict[str, Any]], label: str) -> list[str]:
    identities: list[str] = []
    seen: set[str] = set()
    for position, action in enumerate(actions, start=1):
        identity = clean(action.get("identity"))
        if not identity:
            raise MigrationError(f"{label}.actions[{position}] has no identity")
        if identity in seen:
            raise MigrationError(f"{label} repeats action identity {identity!r}")
        seen.add(identity)
        identities.append(identity)
    return identities


def _validate_source_files(payload: object, label: str) -> dict[str, str]:
    if not isinstance(payload, dict) or not payload:
        raise MigrationError(f"{label} is missing")
    result: dict[str, str] = {}
    for raw_key, value in payload.items():
        key = clean(raw_key)
        if not key:
            raise MigrationError(f"{label} contains a blank key")
        result[key] = _checked_sha256(value, f"{label}.{key}")
    return dict(sorted(result.items()))


def validate_review_artifacts(
    *,
    original_plan: Artifact,
    original_report: Artifact,
    correction_plan: Artifact,
    correction_report: Artifact,
    delta_plan: Artifact,
    delta_report: Artifact,
    name_plan: Artifact,
    name_report: Artifact,
    empty_ops_plan: Artifact,
    empty_ops_report: Artifact,
    expected_quarantine_sha256: str,
    expected_quarantine_identities: int,
    expected_quarantine_records: int,
) -> dict[str, Any]:
    """Validate the complete chain of frozen localhost review receipts."""

    original = validate_receipt_pair(original_plan, original_report)
    correction = validate_receipt_pair(
        correction_plan,
        correction_report,
        expected_source_key=original["source_key"],
    )
    delta = validate_receipt_pair(delta_plan, delta_report)
    name = validate_receipt_pair(
        name_plan,
        name_report,
        expected_source_key=delta["source_key"],
    )
    empty_ops = validate_receipt_pair(
        empty_ops_plan,
        empty_ops_report,
        expected_source_key=delta["source_key"],
    )

    original_identities = _action_identities(original["actions"], original_plan.key)
    correction_identities = _action_identities(correction["actions"], correction_plan.key)
    delta_identities = _action_identities(delta["actions"], delta_plan.key)
    name_identities = _action_identities(name["actions"], name_plan.key)
    empty_ops_identities = _action_identities(empty_ops["actions"], empty_ops_plan.key)
    original_set = set(original_identities)
    delta_set = set(delta_identities)
    reviewed_set = original_set | delta_set
    if set(correction_identities) != original_set:
        raise MigrationError("Correction receipt identity scope differs from the original apply receipt")
    if not set(name_identities).issubset(reviewed_set):
        raise MigrationError("Name-correction receipt contains an unreviewed identity")
    if not set(empty_ops_identities).issubset(reviewed_set):
        raise MigrationError("Empty-paid-operation receipt contains an unreviewed identity")

    original_source_files = _validate_source_files(
        original_plan.payload.get("source_files"),
        f"{original_plan.key}.source_files",
    )
    if _validate_source_files(
        (correction_plan.payload.get("prior_receipt") or {}).get("source_files"),
        f"{correction_plan.key}.prior_receipt.source_files",
    ) != original_source_files:
        raise MigrationError("Correction receipt no longer binds the original source files")
    delta_source_files = _validate_source_files(
        delta_plan.payload.get("source_files"),
        f"{delta_plan.key}.source_files",
    )
    for artifact in (delta_report, name_plan, name_report, empty_ops_plan, empty_ops_report):
        source_files = _validate_source_files(
            artifact.payload.get("source_files"),
            f"{artifact.key}.source_files",
        )
        if source_files != delta_source_files:
            raise MigrationError(f"{artifact.key} no longer binds the reviewed delta source files")

    prior = correction_plan.payload.get("prior_receipt")
    if not isinstance(prior, dict):
        raise MigrationError("Correction plan prior_receipt is missing")
    if clean(prior.get("plan_file_sha256")).lower() != original_plan.sha256:
        raise MigrationError("Correction plan no longer binds the original plan file")
    if clean(prior.get("report_file_sha256")).lower() != original_report.sha256:
        raise MigrationError("Correction plan no longer binds the original report file")
    if delta_source_files.get("prior_apply_plan_sha256") != original_plan.sha256:
        raise MigrationError("Delta receipt no longer binds the original plan file")
    if delta_source_files.get("prior_apply_report_sha256") != original_report.sha256:
        raise MigrationError("Delta receipt no longer binds the original report file")

    raw_quarantines = delta_report.payload.get("unresolved_quarantines")
    if not isinstance(raw_quarantines, list) or not all(
        isinstance(row, dict) for row in raw_quarantines
    ):
        raise MigrationError("Delta report unresolved_quarantines must be a list of objects")
    quarantine_sha = object_sha256(raw_quarantines)
    expected_quarantine_sha = _checked_sha256(
        expected_quarantine_sha256,
        "expected unresolved quarantine SHA-256",
    )
    for artifact in (delta_plan, delta_report, name_plan, name_report, empty_ops_plan, empty_ops_report):
        claimed = _checked_sha256(
            artifact.payload.get("unresolved_quarantine_sha256"),
            f"{artifact.key}.unresolved_quarantine_sha256",
        )
        if claimed != quarantine_sha:
            raise MigrationError(f"{artifact.key} unresolved quarantine evidence changed")
    for artifact in (delta_report, name_report, empty_ops_report):
        accepted = _checked_sha256(
            artifact.payload.get("accepted_unresolved_quarantine_sha256"),
            f"{artifact.key}.accepted_unresolved_quarantine_sha256",
        )
        if accepted != quarantine_sha:
            raise MigrationError(f"{artifact.key} did not accept the reviewed quarantine evidence")
    if quarantine_sha != expected_quarantine_sha:
        raise MigrationError(
            "Unresolved quarantine hash changed: "
            f"expected {expected_quarantine_sha}, got {quarantine_sha}"
        )
    quarantine_records = 0
    quarantine_identity_values: list[str | None] = []
    quarantine_record_ids: set[int] = set()
    for position, row in enumerate(raw_quarantines, start=1):
        old_model_ids = row.get("old_model_ids")
        if not isinstance(old_model_ids, list):
            raise MigrationError(f"Unresolved quarantine {position} old_model_ids is invalid")
        for raw_id in old_model_ids:
            try:
                old_model_id = int(raw_id)
            except (TypeError, ValueError) as exc:
                raise MigrationError(
                    f"Unresolved quarantine {position} has an invalid old_model_id"
                ) from exc
            if old_model_id <= 0 or old_model_id in quarantine_record_ids:
                raise MigrationError("Unresolved quarantine old_model_ids are invalid or repeated")
            quarantine_record_ids.add(old_model_id)
        quarantine_records += len(old_model_ids)
        quarantine_identity_values.append(clean(row.get("identity")) or None)
    if len(raw_quarantines) != int(expected_quarantine_identities):
        raise MigrationError(
            "Unresolved quarantine identity count changed: "
            f"expected {expected_quarantine_identities}, got {len(raw_quarantines)}"
        )
    if quarantine_records != int(expected_quarantine_records):
        raise MigrationError(
            "Unresolved quarantine record count changed: "
            f"expected {expected_quarantine_records}, got {quarantine_records}"
        )
    summary = delta_report.payload.get("summary")
    if not isinstance(summary, dict):
        raise MigrationError("Delta report summary is missing")
    if int(summary.get("quarantine_unresolved_identities") or -1) != len(raw_quarantines):
        raise MigrationError("Delta report quarantine identity summary changed")
    if int(summary.get("quarantine_unresolved_records") or -1) != quarantine_records:
        raise MigrationError("Delta report quarantine record summary changed")

    protected_identities = {
        clean(row.get("identity"))
        for row in original["actions"]
        if clean(row.get("action")) == "update_existing"
    }
    if "" in protected_identities:
        raise MigrationError("Original protected action contains a blank identity")
    return {
        "original_source_key": original["source_key"],
        "delta_source_key": delta["source_key"],
        "reviewed_identities": sorted(reviewed_set),
        "original_identities": sorted(original_set),
        "delta_identities": sorted(delta_set),
        "protected_identities": sorted(protected_identities),
        "quarantines": copy.deepcopy(raw_quarantines),
        "quarantine_sha256": quarantine_sha,
        "quarantine_records": quarantine_records,
        "original_source_files": original_source_files,
        "delta_source_files": delta_source_files,
    }


def load_production_snapshot(
    path: Path,
    expected_sha256: str,
) -> dict[str, Any]:
    """Load the frozen production NDJSON catalog and index canonical identities."""

    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise MigrationError(f"Production catalog snapshot does not exist: {resolved}")
    expected_sha = _checked_sha256(
        expected_sha256,
        "production catalog snapshot SHA-256",
    )
    actual_sha = file_sha256(resolved)
    if actual_sha != expected_sha:
        raise MigrationError(
            "Production catalog snapshot SHA-256 changed: "
            f"expected {expected_sha}, got {actual_sha}"
        )
    opener = gzip.open if resolved.suffix.casefold() == ".gz" else open
    identities: list[str] = []
    seen: set[str] = set()
    model_rows = 0
    try:
        with opener(resolved, "rt", encoding="utf-8") as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                if not raw_line.strip():
                    continue
                row = json.loads(raw_line)
                if not isinstance(row, dict):
                    raise MigrationError(
                        f"Production catalog line {line_number} is not an object"
                    )
                if clean(row.get("type")) != "model":
                    continue
                model_rows += 1
                identity = _identity_from_details(
                    row.get("details_json"),
                    f"Production catalog model line {line_number}",
                )
                if identity in seen:
                    raise MigrationError(
                        f"Production catalog repeats canonical identity {identity!r}"
                    )
                seen.add(identity)
                identities.append(identity)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MigrationError(f"Could not read production catalog snapshot: {exc}") from exc
    if not identities or model_rows != len(identities):
        raise MigrationError("Production catalog snapshot contains no usable model identities")
    sorted_identities = sorted(identities)
    return {
        "artifact_name": resolved.name,
        "artifact_sha256": actual_sha,
        "model_count": len(sorted_identities),
        "identities": sorted_identities,
        "identity_set_sha256": object_sha256(sorted_identities),
    }


def _identity_from_details(details: object, label: str) -> str:
    if not isinstance(details, dict):
        raise MigrationError(f"{label} details_json is not an object")
    general = details.get("general")
    if not isinstance(general, dict):
        raise MigrationError(f"{label} details_json.general is not an object")
    model_no = clean(general.get("model_no") or general.get("modelNo"))
    variant_no = clean(general.get("variant_no") or general.get("variantNo"))
    if not local_import.base_key(model_no):
        raise MigrationError(f"{label} has no canonical model_no")
    return local_import.identity_key(model_no, variant_no)


def load_reviewed_models(db) -> list[Model]:
    models = (
        db.query(Model)
        .options(
            selectinload(Model.images),
            selectinload(Model.sizes),
            selectinload(Model.colors),
        )
        .order_by(Model.id)
        .all()
    )
    return [
        model
        for model in models
        if isinstance(model.details_json, dict)
        and (
            ORIGINAL_DETAILS_KEY in model.details_json
            or DELTA_DETAILS_KEY in model.details_json
        )
    ]


def validate_reviewed_model_scope(
    models: Iterable[Model],
    *,
    receipts: dict[str, Any],
) -> dict[str, Model]:
    indexed: dict[str, Model] = {}
    expected_identities = set(receipts["reviewed_identities"])
    for model in models:
        details = model.details_json
        if not isinstance(details, dict):
            raise MigrationError("Reviewed model details_json changed to a non-object")
        identity = _identity_from_details(details, f"Local reviewed model {model.id}")
        if identity in indexed:
            raise MigrationError(f"Local reviewed catalog repeats identity {identity!r}")
        for key, expected_source_key in (
            (ORIGINAL_DETAILS_KEY, receipts["original_source_key"]),
            (DELTA_DETAILS_KEY, receipts["delta_source_key"]),
        ):
            provenance = details.get(key)
            if provenance is None:
                continue
            if not isinstance(provenance, dict):
                raise MigrationError(f"Local model {identity} has invalid {key} provenance")
            if clean(provenance.get("source_key")) != expected_source_key:
                raise MigrationError(f"Local model {identity} {key}.source_key changed")
            if clean(provenance.get("identity")) != identity:
                raise MigrationError(f"Local model {identity} {key}.identity changed")
        indexed[identity] = model
    actual_identities = set(indexed)
    if actual_identities != expected_identities:
        missing = sorted(expected_identities - actual_identities)
        extra = sorted(actual_identities - expected_identities)
        raise MigrationError(
            "Final localhost reviewed identity scope differs from the frozen receipts: "
            f"missing={missing[:10]}, extra={extra[:10]}"
        )
    quarantine_identities = {
        clean(row.get("identity"))
        for row in receipts["quarantines"]
        if clean(row.get("identity"))
    }
    overlap = sorted(actual_identities & quarantine_identities)
    if overlap:
        raise MigrationError(
            "An unresolved quarantine identity appears in the export scope: "
            + ", ".join(overlap[:10])
        )
    return indexed


def _strip_production_receipts(value: Any) -> tuple[Any, int]:
    """Deep-copy JSON while removing every production receipt key."""

    if isinstance(value, dict):
        result: dict[str, Any] = {}
        removed = 0
        for key, child in value.items():
            if str(key) == PRODUCTION_RECEIPTS_KEY:
                removed += 1
                continue
            stripped, child_removed = _strip_production_receipts(child)
            result[str(key)] = stripped
            removed += child_removed
        return result, removed
    if isinstance(value, list):
        result_list: list[Any] = []
        removed = 0
        for child in value:
            stripped, child_removed = _strip_production_receipts(child)
            result_list.append(stripped)
            removed += child_removed
        return result_list, removed
    return copy.deepcopy(value), 0


def _canonical_details(details: object) -> tuple[dict[str, Any], int]:
    stripped, removed = _strip_production_receipts(details)
    if not isinstance(stripped, dict):
        raise MigrationError("Reviewed model details_json must be an object")
    _validate_lossless_paid_operation_ids(stripped)
    paid = production_import.merge_paid_operations({}, stripped)
    if paid["conflicts"]:
        raise MigrationError("Reviewed model contains conflicting duplicate paid operations")
    if paid["field"] is not None:
        for field in production_import.PAID_OPERATION_FIELDS:
            stripped.pop(field, None)
        stripped["paid_operations"] = copy.deepcopy(
            paid["details"]["paid_operations"]
        )
    return stripped, removed


def _validate_lossless_paid_operation_ids(details: dict[str, Any]) -> None:
    """Require one stable ID per reviewed operation before any canonicalization."""

    present = [
        field
        for field in production_import.PAID_OPERATION_FIELDS
        if field in details and details[field] is not None
    ]
    if not present:
        return
    if len(present) > 1 and details[present[0]] != details[present[1]]:
        raise MigrationError("Reviewed paid-operation aliases disagree")
    rows = details[present[0]]
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise MigrationError("Reviewed paid operations must be a list of objects")
    seen: set[str] = set()
    for position, row in enumerate(rows, start=1):
        operation_id = clean(row.get("id"))
        if not operation_id:
            raise MigrationError(
                f"Reviewed paid operation {position} has no stable ID"
            )
        if operation_id in seen:
            raise MigrationError(
                f"Reviewed paid operation ID {operation_id!r} is repeated"
            )
        seen.add(operation_id)


def _dedupe_sizes(rows: Iterable[Any], identity: str) -> list[dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in sorted(rows, key=lambda item: int(getattr(item, "id", 0) or 0)):
        size = clean(getattr(row, "size", None))
        key = local_import.normalized_value(size)
        if not key:
            raise MigrationError(f"Reviewed model {identity} has a blank size")
        value = {
            "size": size,
            "measurement_json": copy.deepcopy(
                getattr(row, "measurement_json", None)
            ),
        }
        prior = result.get(key)
        if prior is not None:
            if prior["measurement_json"] != value["measurement_json"]:
                raise MigrationError(
                    f"Reviewed model {identity} has conflicting normalized size {size!r}"
                )
            continue
        result[key] = value
    return [result[key] for key in sorted(result)]


def _dedupe_colors(rows: Iterable[Any], identity: str) -> list[dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in sorted(rows, key=lambda item: int(getattr(item, "id", 0) or 0)):
        name = clean(getattr(row, "color_name", None))
        key = local_import.normalized_value(name)
        if not key:
            raise MigrationError(f"Reviewed model {identity} has a blank color")
        color_code = clean(getattr(row, "color_code", None)) or None
        value = {
            "color_name": name,
            "color_code": color_code,
        }
        prior = result.get(key)
        if prior is not None:
            if prior["color_code"] != value["color_code"]:
                raise MigrationError(
                    f"Reviewed model {identity} has conflicting normalized color {name!r}"
                )
            continue
        result[key] = value
    return [result[key] for key in sorted(result)]


def _legacy_product(model: Model, details: dict[str, Any]) -> str:
    general = details.get("general")
    if not isinstance(general, dict):
        general = {}
    values = [
        clean(general.get("legacy_product")),
        clean(getattr(model, "product_type", None)),
        clean(general.get("product_type")),
    ]
    nonblank: list[str] = []
    normalized: set[str] = set()
    for value in values:
        if not value:
            continue
        key = local_import.normalized_value(value)
        if key not in normalized:
            normalized.add(key)
            nonblank.append(value)
    if len(nonblank) > 1:
        raise MigrationError(
            "Reviewed legacy Product fields disagree for "
            f"{_identity_from_details(details, 'Reviewed model')}: {nonblank}"
        )
    return nonblank[0] if nonblank else ""


def reviewed_creation_name(
    model: Model,
    *,
    details: dict[str, Any],
    target_classification: str,
    protected_identity: bool,
) -> tuple[str, str]:
    """Apply the reviewed, non-guessing creation-name policy."""

    local_name = clean(getattr(model, "name", None))
    product = _legacy_product(model, details)
    code = clean(getattr(model, "code", None))
    if not code:
        raise MigrationError("Reviewed model code is blank")
    if target_classification == "create" and protected_identity:
        if not product:
            raise MigrationError(
                "Protected localhost row becoming a create has no exact legacy Product"
            )
        return product, "protected_create_exact_product"
    if local_name:
        return local_name, "reviewed_local_name"
    if product:
        return product, "blank_local_name_exact_product"
    return code, "productless_code_fallback"


def _target_name_from_url(file_url: object, identity: str) -> str:
    value = clean(file_url)
    if not value:
        raise MigrationError(f"Reviewed model {identity} has a blank image URL")
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise MigrationError(f"Reviewed model {identity} image URL is not a local storage URL")
    decoded_path = unquote(parsed.path)
    prefix = "/storage/model-files/"
    if not decoded_path.startswith(prefix):
        raise MigrationError(f"Reviewed model {identity} image URL is outside model storage")
    relative = PurePosixPath(decoded_path[len(prefix) :])
    if (
        len(relative.parts) != 1
        or relative.name in {"", ".", ".."}
        or not SAFE_FILE_NAME.fullmatch(relative.name)
        or relative.name.startswith(".")
    ):
        raise MigrationError(f"Reviewed model {identity} image target name is unsafe")
    return relative.name


def _validate_source_image(
    source: Path,
    *,
    target_name: str,
    max_image_bytes: int,
    label: str,
) -> MediaFile:
    if not source.is_file():
        raise MigrationError(f"{label} source file is missing: {source}")
    byte_count = source.stat().st_size
    if byte_count <= 0 or byte_count > max_image_bytes:
        raise MigrationError(f"{label} source byte count is invalid")
    digest = file_sha256(source)
    with source.open("rb") as handle:
        head = handle.read(32)
        handle.seek(max(0, byte_count - 32))
        tail = handle.read(32)
    content_type, _ = local_import.detect_image(head, tail)
    if content_type not in SUPPORTED_IMAGE_TYPES:
        raise MigrationError(f"{label} has an unsupported image type")
    try:
        from PIL import Image

        with Image.open(source) as opened:
            opened.verify()
    except Exception as exc:
        raise MigrationError(f"{label} failed complete image decode: {exc}") from exc
    return MediaFile(
        source=source,
        relative_path=f"media/{target_name}",
        target_name=target_name,
        bytes=byte_count,
        sha256=digest,
        content_type=content_type,
    )


def export_images(
    model: Model,
    *,
    identity: str,
    target_classification: str,
    source_media_root: Path,
    max_image_bytes: int,
    validated_files: dict[str, MediaFile],
    target_hashes: dict[str, str],
) -> list[dict[str, Any]]:
    if target_classification == "existing":
        return []
    images: list[dict[str, Any]] = []
    root = source_media_root.resolve()
    for image in sorted(model.images or [], key=lambda row: int(row.id or 0)):
        target_name = _target_name_from_url(image.file_url, identity)
        source = (root / target_name).resolve()
        if source.parent != root:
            raise MigrationError(f"Reviewed model {identity} image escapes the source root")
        relative_source = source.relative_to(root).as_posix()
        media = validated_files.get(relative_source)
        if media is None:
            media = _validate_source_image(
                source,
                target_name=target_name,
                max_image_bytes=max_image_bytes,
                label=f"Reviewed model {identity} image {image.id}",
            )
            validated_files[relative_source] = media
        elif media.target_name != target_name:
            raise MigrationError(f"Reviewed image source target changed for {relative_source}")
        prior_target_hash = target_hashes.get(target_name)
        if prior_target_hash is not None and prior_target_hash != media.sha256:
            raise MigrationError(f"Reviewed package image target collision for {target_name!r}")
        target_hashes[target_name] = media.sha256
        declared_content_type = clean(image.content_type)
        if declared_content_type and declared_content_type != media.content_type:
            raise MigrationError(
                f"Reviewed model {identity} image {image.id} content_type changed: "
                f"database={declared_content_type}, detected={media.content_type}"
            )
        file_data = image.file_data
        if file_data is not None and (
            len(file_data) != media.bytes
            or hashlib.sha256(file_data).hexdigest() != media.sha256
        ):
            raise MigrationError(
                f"Reviewed model {identity} image {image.id} file_data differs from storage"
            )
        file_name = clean(image.file_name) or target_name
        if len(file_name) > 255:
            raise MigrationError(f"Reviewed model {identity} image file_name is too long")
        image_type = clean(image.image_type) or "model"
        if len(image_type) > 32:
            raise MigrationError(f"Reviewed model {identity} image_type is too long")
        images.append(
            {
                "source_path": media.relative_path,
                "target_name": target_name,
                "file_url": f"/storage/model-files/{target_name}",
                "file_name": file_name,
                "content_type": media.content_type,
                "image_type": image_type,
                "is_primary": bool(image.is_primary),
                "bytes": media.bytes,
                "sha256": media.sha256,
            }
        )
    return images


def _optional_scalar(value: object, *, limit: int | None, label: str) -> str | None:
    result = clean(value) or None
    if result is not None and limit is not None and len(result) > limit:
        raise MigrationError(f"{label} exceeds the database limit")
    return result


def build_export(
    *,
    reviewed_models: dict[str, Model],
    receipts: dict[str, Any],
    production_snapshot: dict[str, Any],
    source_files: dict[str, str],
    source_media_root: Path,
    max_image_bytes: int,
) -> tuple[dict[str, Any], dict[str, Any], list[MediaFile]]:
    if max_image_bytes <= 0:
        raise MigrationError("max_image_bytes must be positive")
    source_identities = sorted(reviewed_models)
    production_identities = set(production_snapshot["identities"])
    exact_identities = sorted(set(source_identities) & production_identities)
    create_identities = sorted(set(source_identities) - production_identities)
    exact_set = set(exact_identities)
    protected_set = set(receipts["protected_identities"])
    protected_creates = sorted(protected_set & set(create_identities))
    quarantine_identity_set = {
        clean(row.get("identity"))
        for row in receipts["quarantines"]
        if clean(row.get("identity"))
    }
    if quarantine_identity_set & set(source_identities):
        raise MigrationError("Reviewed quarantine evidence overlaps the exported identities")

    snapshot_evidence = {
        "artifact_name": production_snapshot["artifact_name"],
        "artifact_sha256": production_snapshot["artifact_sha256"],
        "model_count": int(production_snapshot["model_count"]),
        "identity_set_sha256": object_sha256(sorted(production_identities)),
        "exact_package_identities_sha256": object_sha256(exact_identities),
        "create_package_identities_sha256": object_sha256(create_identities),
    }
    if snapshot_evidence["identity_set_sha256"] != production_snapshot["identity_set_sha256"]:
        raise MigrationError("Production snapshot identity fingerprint changed during export")

    validated_files: dict[str, MediaFile] = {}
    target_hashes: dict[str, str] = {}
    records: dict[str, dict[str, Any]] = {}
    receipt_keys_removed = 0
    name_policy_counts: dict[str, int] = {}
    omitted_existing_image_relations = 0
    for identity in source_identities:
        model = reviewed_models[identity]
        details, removed = _canonical_details(model.details_json)
        receipt_keys_removed += removed
        if _identity_from_details(details, f"Reviewed model {identity}") != identity:
            raise MigrationError(f"Reviewed model {identity} canonical identity changed")
        target_classification = "existing" if identity in exact_set else "create"
        name, name_policy = reviewed_creation_name(
            model,
            details=details,
            target_classification=target_classification,
            protected_identity=identity in protected_set,
        )
        name_policy_counts[name_policy] = name_policy_counts.get(name_policy, 0) + 1
        if target_classification == "existing":
            omitted_existing_image_relations += len(model.images or [])
        images = export_images(
            model,
            identity=identity,
            target_classification=target_classification,
            source_media_root=source_media_root,
            max_image_bytes=max_image_bytes,
            validated_files=validated_files,
            target_hashes=target_hashes,
        )
        try:
            sam_minutes = float(model.sam_minutes or 0)
        except (TypeError, ValueError) as exc:
            raise MigrationError(f"Reviewed model {identity} has invalid SAM") from exc
        if not math.isfinite(sam_minutes) or sam_minutes < 0:
            raise MigrationError(f"Reviewed model {identity} has invalid SAM")
        record = {
            "identity": identity,
            "target_classification": target_classification,
            "code": clean(model.code),
            "name": name,
            "category": _optional_scalar(
                model.category,
                limit=64,
                label=f"Reviewed model {identity} category",
            ),
            "description": _optional_scalar(
                model.description,
                limit=None,
                label=f"Reviewed model {identity} description",
            ),
            "product_type": _optional_scalar(
                model.product_type,
                limit=64,
                label=f"Reviewed model {identity} product_type",
            ),
            "season": _optional_scalar(
                model.season,
                limit=64,
                label=f"Reviewed model {identity} season",
            ),
            "sam_minutes": sam_minutes,
            "status": _optional_scalar(
                model.status,
                limit=32,
                label=f"Reviewed model {identity} status",
            )
            or "draft",
            "details_json": details,
            "sizes": _dedupe_sizes(model.sizes or [], identity),
            "colors": _dedupe_colors(model.colors or [], identity),
            "images": images,
        }
        if not record["code"] or len(record["code"]) > 64:
            raise MigrationError(f"Reviewed model {identity} code is blank or too long")
        if not record["name"] or len(record["name"]) > 255:
            raise MigrationError(f"Reviewed model {identity} name is blank or too long")
        records[identity] = record

    media_manifest = [
        {
            "source_path": media.relative_path,
            "target_name": media.target_name,
            "bytes": media.bytes,
            "sha256": media.sha256,
            "content_type": media.content_type,
        }
        for media in sorted(validated_files.values(), key=lambda row: row.relative_path)
    ]
    package = {
        "schema_version": SCHEMA_VERSION,
        "package_kind": PACKAGE_KIND,
        "source_key": SOURCE_KEY,
        "source_files": dict(sorted(source_files.items())),
        "production_snapshot": snapshot_evidence,
        "models": records,
        "quarantines": copy.deepcopy(receipts["quarantines"]),
    }
    summary = {
        "models": len(records),
        "existing_identities": len(exact_identities),
        "create_identities": len(create_identities),
        "protected_create_identities": len(protected_creates),
        "images": sum(len(record["images"]) for record in records.values()),
        "sizes": sum(len(record["sizes"]) for record in records.values()),
        "colors": sum(len(record["colors"]) for record in records.values()),
        "quarantine_identities": len(receipts["quarantines"]),
        "quarantine_records": int(receipts["quarantine_records"]),
        "unique_media_files": len(media_manifest),
        "unique_media_bytes": sum(int(row["bytes"]) for row in media_manifest),
        "existing_image_relations_omitted": omitted_existing_image_relations,
        "production_receipt_keys_removed": receipt_keys_removed,
        "name_policy_counts": dict(sorted(name_policy_counts.items())),
    }
    evidence = {
        "source_identity_set_sha256": object_sha256(source_identities),
        "records_sha256": object_sha256(records),
        "quarantines_sha256": object_sha256(package["quarantines"]),
        "media_manifest_sha256": object_sha256(media_manifest),
        "production_snapshot": snapshot_evidence,
        "summary": summary,
        "protected_create_identities": protected_creates,
        "media_manifest": media_manifest,
    }
    return package, evidence, sorted(
        validated_files.values(),
        key=lambda row: row.relative_path,
    )


def build_source_files(
    artifacts: Iterable[Artifact],
    *,
    original_source_files: dict[str, str],
    delta_source_files: dict[str, str],
    production_snapshot_artifact_name: str,
    production_snapshot_sha256: str,
) -> dict[str, str]:
    result: dict[str, str] = {}
    for artifact in artifacts:
        if artifact.key in result:
            raise MigrationError(f"Source artifact key {artifact.key!r} is repeated")
        result[artifact.key] = artifact.sha256
    artifact_name = clean(production_snapshot_artifact_name)
    if (
        not artifact_name
        or not SAFE_FILE_NAME.fullmatch(artifact_name)
        or Path(artifact_name).name != artifact_name
    ):
        raise MigrationError("Production catalog snapshot artifact name is unsafe")
    if artifact_name in result:
        raise MigrationError(
            f"Production catalog snapshot artifact key {artifact_name!r} is repeated"
        )
    result[artifact_name] = _checked_sha256(
        production_snapshot_sha256,
        "production catalog snapshot SHA-256",
    )
    for key, digest in original_source_files.items():
        result[f"original_source__{key}"] = digest
    for key, digest in delta_source_files.items():
        result[f"delta_source__{key}"] = digest
    return dict(sorted(result.items()))


def enforce_expectations(evidence: dict[str, Any], args: argparse.Namespace) -> None:
    summary = evidence["summary"]
    checks = {
        "--expect-models": (args.expect_models, summary["models"]),
        "--expect-existing-identities": (
            args.expect_existing_identities,
            summary["existing_identities"],
        ),
        "--expect-create-identities": (
            args.expect_create_identities,
            summary["create_identities"],
        ),
        "--expect-protected-create-identities": (
            args.expect_protected_create_identities,
            summary["protected_create_identities"],
        ),
        "--expect-images": (args.expect_images, summary["images"]),
        "--expect-sizes": (args.expect_sizes, summary["sizes"]),
        "--expect-colors": (args.expect_colors, summary["colors"]),
        "--expect-unique-media-files": (
            args.expect_unique_media_files,
            summary["unique_media_files"],
        ),
        "--expect-quarantine-identities": (
            args.expect_quarantine_identities,
            summary["quarantine_identities"],
        ),
        "--expect-quarantine-records": (
            args.expect_quarantine_records,
            summary["quarantine_records"],
        ),
        "--expect-production-models": (
            args.expect_production_models,
            evidence["production_snapshot"]["model_count"],
        ),
    }
    mismatches = [
        f"{flag}: expected {expected}, got {actual}"
        for flag, (expected, actual) in checks.items()
        if int(expected) != int(actual)
    ]
    hash_checks = {
        "--expect-source-identity-set-sha256": (
            args.expect_source_identity_set_sha256,
            evidence["source_identity_set_sha256"],
        ),
        "--expect-existing-identity-set-sha256": (
            args.expect_existing_identity_set_sha256,
            evidence["production_snapshot"]["exact_package_identities_sha256"],
        ),
        "--expect-create-identity-set-sha256": (
            args.expect_create_identity_set_sha256,
            evidence["production_snapshot"]["create_package_identities_sha256"],
        ),
    }
    for flag, (expected, actual) in hash_checks.items():
        checked = _checked_sha256(expected, flag)
        if checked != actual:
            mismatches.append(f"{flag}: expected {checked}, got {actual}")
    if mismatches:
        raise MigrationError("Export expectation mismatch: " + "; ".join(mismatches))


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )


def _write_atomic(path: Path, content: bytes, *, overwrite: bool) -> None:
    resolved = path.expanduser().resolve()
    if resolved.exists() and not overwrite:
        raise MigrationError(f"Output already exists: {resolved}")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    temporary = resolved.with_name(f".{resolved.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(content)
        temporary.replace(resolved)
    finally:
        if temporary.exists():
            temporary.unlink()


def stage_media(
    media_files: Iterable[MediaFile],
    *,
    package_media_root: Path,
) -> dict[str, Any]:
    root = package_media_root.expanduser().resolve()
    media_dir = (root / "media").resolve()
    if media_dir.parent != root:
        raise MigrationError("Package media directory escapes its root")
    media_dir.mkdir(parents=True, exist_ok=True)
    copied = 0
    reused = 0
    for media in media_files:
        target = (root / Path(media.relative_path)).resolve()
        if target.parent != media_dir or target.name != media.target_name:
            raise MigrationError(f"Package media target is unsafe: {media.relative_path}")
        if target.exists():
            if (
                not target.is_file()
                or target.stat().st_size != media.bytes
                or file_sha256(target) != media.sha256
            ):
                raise MigrationError(f"Existing staged media conflicts: {target}")
            reused += 1
            continue
        temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
        try:
            shutil.copyfile(media.source, temporary)
            if (
                temporary.stat().st_size != media.bytes
                or file_sha256(temporary) != media.sha256
            ):
                raise MigrationError(f"Staged media verification failed: {target}")
            temporary.replace(target)
            copied += 1
        finally:
            if temporary.exists():
                temporary.unlink()
    return {
        "files_present": copied + reused,
        "media_directory": "media",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export the final reviewed old-ERP localhost models."
    )
    for name in (
        "original-plan",
        "original-report",
        "correction-plan",
        "correction-report",
        "delta-plan",
        "delta-report",
        "name-plan",
        "name-report",
        "empty-ops-plan",
        "empty-ops-report",
    ):
        parser.add_argument(f"--{name}", required=True, type=Path)
        parser.add_argument(f"--{name}-sha256", required=True)
    parser.add_argument("--production-catalog-snapshot", required=True, type=Path)
    parser.add_argument("--production-catalog-snapshot-sha256", required=True)
    parser.add_argument("--expected-unresolved-quarantine-sha256", required=True)
    parser.add_argument("--source-media-root", required=True, type=Path)
    parser.add_argument("--package-media-root", required=True, type=Path)
    parser.add_argument("--package-output", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--overwrite-output", action="store_true")
    parser.add_argument("--local-db-port", type=int, default=DEFAULT_LOCAL_DB_PORT)
    parser.add_argument(
        "--max-image-bytes",
        type=int,
        default=DEFAULT_MAX_IMAGE_BYTES,
    )
    parser.add_argument("--expect-models", required=True, type=int)
    parser.add_argument("--expect-existing-identities", required=True, type=int)
    parser.add_argument("--expect-create-identities", required=True, type=int)
    parser.add_argument(
        "--expect-protected-create-identities",
        required=True,
        type=int,
    )
    parser.add_argument("--expect-images", required=True, type=int)
    parser.add_argument("--expect-sizes", required=True, type=int)
    parser.add_argument("--expect-colors", required=True, type=int)
    parser.add_argument("--expect-unique-media-files", required=True, type=int)
    parser.add_argument("--expect-quarantine-identities", required=True, type=int)
    parser.add_argument("--expect-quarantine-records", required=True, type=int)
    parser.add_argument("--expect-production-models", required=True, type=int)
    parser.add_argument("--expect-source-identity-set-sha256", required=True)
    parser.add_argument("--expect-existing-identity-set-sha256", required=True)
    parser.add_argument("--expect-create-identity-set-sha256", required=True)
    return parser.parse_args()


def _artifact_from_args(args: argparse.Namespace, cli_name: str, key: str) -> Artifact:
    attribute = cli_name.replace("-", "_")
    return load_artifact(
        key,
        getattr(args, attribute),
        getattr(args, f"{attribute}_sha256"),
    )


def main() -> None:
    args = parse_args()
    artifacts = {
        "original_plan": _artifact_from_args(
            args, "original-plan", "original_apply_plan"
        ),
        "original_report": _artifact_from_args(
            args, "original-report", "original_apply_report"
        ),
        "correction_plan": _artifact_from_args(
            args, "correction-plan", "correction_apply_plan"
        ),
        "correction_report": _artifact_from_args(
            args, "correction-report", "correction_apply_report"
        ),
        "delta_plan": _artifact_from_args(args, "delta-plan", "delta_apply_plan"),
        "delta_report": _artifact_from_args(
            args, "delta-report", "delta_apply_report"
        ),
        "name_plan": _artifact_from_args(
            args, "name-plan", "product_name_apply_plan"
        ),
        "name_report": _artifact_from_args(
            args, "name-report", "product_name_apply_report"
        ),
        "empty_ops_plan": _artifact_from_args(
            args, "empty-ops-plan", "empty_paid_operations_apply_plan"
        ),
        "empty_ops_report": _artifact_from_args(
            args, "empty-ops-report", "empty_paid_operations_apply_report"
        ),
    }
    receipts = validate_review_artifacts(
        **artifacts,
        expected_quarantine_sha256=args.expected_unresolved_quarantine_sha256,
        expected_quarantine_identities=args.expect_quarantine_identities,
        expected_quarantine_records=args.expect_quarantine_records,
    )
    production_snapshot = load_production_snapshot(
        args.production_catalog_snapshot,
        args.production_catalog_snapshot_sha256,
    )
    source_files = build_source_files(
        artifacts.values(),
        original_source_files=receipts["original_source_files"],
        delta_source_files=receipts["delta_source_files"],
        production_snapshot_artifact_name=production_snapshot["artifact_name"],
        production_snapshot_sha256=production_snapshot["artifact_sha256"],
    )

    package_output = args.package_output.expanduser().resolve()
    report_output = args.report.expanduser().resolve()
    package_media_root = args.package_media_root.expanduser().resolve()
    source_media_root = args.source_media_root.expanduser().resolve()
    protected_inputs = {
        artifact.path for artifact in artifacts.values()
    } | {args.production_catalog_snapshot.expanduser().resolve()}
    if package_output == report_output:
        raise MigrationError("--package-output and --report must differ")
    if package_output in protected_inputs or report_output in protected_inputs:
        raise MigrationError("Exporter outputs must not overwrite a frozen input")
    if package_media_root == source_media_root:
        raise MigrationError("Package media root must differ from the live local media root")
    if not source_media_root.is_dir():
        raise MigrationError(f"Source media root does not exist: {source_media_root}")
    if not args.overwrite_output:
        existing = [
            str(path)
            for path in (package_output, report_output)
            if path.exists()
        ]
        if existing:
            raise MigrationError("Output already exists: " + ", ".join(existing))

    db = SessionLocal()
    try:
        db.execute(text("SET TRANSACTION READ ONLY"))
        database_guard = local_import.local_database_guard(
            db,
            expected_port=args.local_db_port,
        )
        read_only = clean(
            db.execute(text("SHOW transaction_read_only")).scalar_one()
        ).casefold()
        if read_only != "on":
            raise MigrationError("Exporter database transaction is not read-only")
        reviewed = validate_reviewed_model_scope(
            load_reviewed_models(db),
            receipts=receipts,
        )
        package, evidence, media_files = build_export(
            reviewed_models=reviewed,
            receipts=receipts,
            production_snapshot=production_snapshot,
            source_files=source_files,
            source_media_root=source_media_root,
            max_image_bytes=args.max_image_bytes,
        )
        enforce_expectations(evidence, args)
    finally:
        db.rollback()
        db.close()

    staging = stage_media(
        media_files,
        package_media_root=package_media_root,
    )
    package_bytes = _canonical_json_bytes(package)
    package_sha = hashlib.sha256(package_bytes).hexdigest()
    report = {
        "schema_version": SCHEMA_VERSION,
        "kind": "reviewed_old_erp_local_export",
        "source_key": SOURCE_KEY,
        "production_touched": False,
        "database_mutated": False,
        "database_guard": database_guard,
        "source_files": source_files,
        "package_sha256": package_sha,
        "production_snapshot": evidence["production_snapshot"],
        "source_identity_set_sha256": evidence["source_identity_set_sha256"],
        "records_sha256": evidence["records_sha256"],
        "quarantines_sha256": evidence["quarantines_sha256"],
        "media_manifest_sha256": evidence["media_manifest_sha256"],
        "summary": evidence["summary"],
        "staging": staging,
        "invariants": {
            "localhost_database_read_only": True,
            "reviewed_receipt_identity_union_exact": True,
            "production_snapshot_hash_pinned": True,
            "existing_identity_images_omitted": True,
            "create_identity_images_fully_decoded_and_hash_pinned": True,
            "production_receipts_removed": True,
            "quarantines_are_reviewed_non_actionable_evidence": True,
            "no_database_ids_used_for_target_matching": True,
        },
    }
    _write_atomic(
        package_output,
        package_bytes,
        overwrite=args.overwrite_output,
    )
    _write_atomic(
        report_output,
        _canonical_json_bytes(report),
        overwrite=args.overwrite_output,
    )
    print(
        json.dumps(
            {
                "package": str(package_output),
                "package_sha256": package_sha,
                "report": str(report_output),
                "summary": evidence["summary"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
