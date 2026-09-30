"""Correct the reviewed old-ERP model import on localhost only.

This is a deliberately separate, receipt-driven correction pass.  It consumes
the exact plan/report from ``import_old_erp_models_local`` plus a hash-pinned
complete-details manifest.  The default mode is a read-only dry run.

The pass is correction-only.  Source models or variants appended after the
reviewed receipt require their own validated supplemental import; they are
reported as blockers rather than silently omitted or created from incomplete
list metadata.

The correction may:

* change the name of a row created by the reviewed import to the exact legacy
  Product value, but only while its current name is still the original planned
  import value;
* add lossless legacy general/operation/recipe sections to provenance-linked
  models;
* add canonical paid operations only when that field is missing.

It never changes a pre-import model name or any model image, and it never
creates catalog or business rows.  Recipes remain raw metadata; no Item or BOM
row is created.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qs, urlparse

from sqlalchemy import text
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import flag_modified

from app.db.session import SessionLocal
from app.models import Model
from scripts import import_old_erp_models_local as original


SCHEMA_VERSION = 1
COMPLETE_SECTIONS_SCHEMA_VERSION = 1
APPLY_CONFIRMATION = "APPLY-REVIEWED-OLD-ERP-CORRECTION-TO-LOCALHOST"
DEFAULT_LOCAL_DB_PORT = original.DEFAULT_LOCAL_DB_PORT
SOURCE_KEY = original.SOURCE_KEY

GENERAL_FIELDS = (
    "Company",
    "Date",
    "Description",
    "Embroidery",
    "Name",
    "Parent Sew Model",
    "Planning Type",
    "Product",
    "Sew Model Code",
    "Style",
    "Thermal Print",
    "Variant",
)
GENERAL_TO_DETAILS = {
    "Company": "legacy_company",
    "Date": "legacy_source_date",
    "Description": "legacy_description",
    "Embroidery": "legacy_master_embroidery",
    "Name": "legacy_sew_model_name",
    "Parent Sew Model": "legacy_parent_sew_model",
    "Planning Type": "legacy_planning_type",
    "Product": "legacy_product",
    "Sew Model Code": "legacy_sew_model_code",
    "Style": "legacy_style",
    "Thermal Print": "legacy_master_thermal_print",
    "Variant": "legacy_model_variant",
}
LIST_METADATA_STRING_FIELDS = (
    "code",
    "company",
    "detail_url",
    "model_variant",
    "name",
    "product",
    "style",
)
GENERAL_TO_LIST_METADATA = {
    "Sew Model Code": "code",
    "Company": "company",
    "Name": "name",
    "Product": "product",
    "Style": "style",
    "Variant": "model_variant",
}
OPERATION_FIELDS = (
    "source_order",
    "name",
    "duration",
    "price",
    "currency",
    "stage",
    "control_change_direction",
    "final_operation",
)
RECIPE_FIELDS = (
    "source_order",
    "product",
    "quantity",
    "sewing_type_list",
)
STAGE_TO_SECTION = {
    "Tikuv": "sewing",
    "Кнопки": "sewing",
    "Упаковка": "packaging",
    "Склад": "packaging",
    "Чистка": "pressing",
    "Контроль": "sewing",
}
SECTION_CODE_PREFIX = {
    "sewing": "SEW",
    "pressing": "PRS",
    "packaging": "PKG",
}

MigrationError = original.MigrationError


def require_object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise MigrationError(f"{label} must be a JSON object")
    return value


def require_list(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise MigrationError(f"{label} must be a JSON array")
    return value


def require_int(value: object, label: str, *, positive: bool = False) -> int:
    if isinstance(value, bool):
        raise MigrationError(f"{label} must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise MigrationError(f"{label} must be an integer") from exc
    if parsed != value and not (isinstance(value, str) and str(parsed) == value.strip()):
        raise MigrationError(f"{label} must be an integer")
    if positive and parsed <= 0:
        raise MigrationError(f"{label} must be positive")
    return parsed


def validate_internal_plan_hash(plan: dict[str, Any]) -> str:
    claimed = original.clean(plan.get("plan_sha256")).lower()
    if not re.fullmatch(r"[0-9a-f]{64}", claimed):
        raise MigrationError("Prior apply plan has no valid internal plan_sha256")
    body = copy.deepcopy(plan)
    body.pop("plan_sha256", None)
    actual = original.object_sha256(body)
    if actual != claimed:
        raise MigrationError(
            f"Prior apply plan logical SHA-256 changed: expected {claimed}, got {actual}"
        )
    return claimed


def index_receipt_provenance_evidence(
    actions: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "model_records": {},
        "model_record_bases": {},
        "variant_records": {},
        "variant_record_identities": {},
        "details_and_sizes": {},
        "details_and_sizes_bases": {},
        "validated_images": {"models": {}, "variants": {}},
        "validated_image_scopes": {"models": {}, "variants": {}},
    }

    def add_exact(
        target: dict[Any, Any],
        key: Any,
        value: Any,
        label: str,
    ) -> None:
        if key in target and target[key] != value:
            raise MigrationError(
                f"Prior receipt has conflicting provenance evidence for {label} {key}"
            )
        target[key] = copy.deepcopy(value)

    def add_scope(
        target: dict[Any, list[str]],
        key: Any,
        scope: str,
    ) -> None:
        scopes = target.setdefault(key, [])
        if scope not in scopes:
            scopes.append(scope)
            scopes.sort()

    for action in actions:
        provenance = require_object(
            action.get("provenance"), "Prior action provenance"
        )
        identity = original.clean(provenance.get("identity"))
        identity_base, separator, _ = identity.partition("|")
        if not separator or not identity_base:
            raise MigrationError(
                f"Prior receipt has malformed provenance identity {identity!r}"
            )
        for field in ("master_records", "metadata_only_records"):
            for row in require_list(
                provenance.get(field), f"Prior provenance.{field}"
            ):
                row = require_object(row, f"Prior provenance.{field} row")
                old_model_id = require_int(
                    row.get("old_model_id"),
                    f"Prior provenance.{field}.old_model_id",
                    positive=True,
                )
                add_exact(
                    evidence["model_records"],
                    old_model_id,
                    row,
                    "old_model_id",
                )
                add_scope(
                    evidence["model_record_bases"],
                    old_model_id,
                    identity_base,
                )
        for row in require_list(
            provenance.get("variant_records"),
            "Prior provenance.variant_records",
        ):
            row = require_object(row, "Prior provenance.variant_records row")
            old_variant_id = require_int(
                row.get("old_variant_id"),
                "Prior provenance.variant_records.old_variant_id",
                positive=True,
            )
            add_exact(
                evidence["variant_records"],
                old_variant_id,
                row,
                "old_variant_id",
            )
            add_scope(
                evidence["variant_record_identities"],
                old_variant_id,
                identity,
            )
        for key, value in require_object(
            provenance.get("details_and_sizes"),
            "Prior provenance.details_and_sizes",
        ).items():
            old_model_id = require_int(
                key,
                "Prior provenance.details_and_sizes key",
                positive=True,
            )
            add_exact(
                evidence["details_and_sizes"],
                str(old_model_id),
                value,
                "details old_model_id",
            )
            add_scope(
                evidence["details_and_sizes_bases"],
                str(old_model_id),
                identity_base,
            )
        validated = require_object(
            provenance.get("validated_images"),
            "Prior provenance.validated_images",
        )
        for source_type in ("models", "variants"):
            for key, value in require_object(
                validated.get(source_type),
                f"Prior provenance.validated_images.{source_type}",
            ).items():
                source_id = require_int(
                    key,
                    f"Prior provenance.validated_images.{source_type} key",
                    positive=True,
                )
                add_exact(
                    evidence["validated_images"][source_type],
                    str(source_id),
                    value,
                    f"validated {source_type}",
                )
                add_scope(
                    evidence["validated_image_scopes"][source_type],
                    str(source_id),
                    identity_base if source_type == "models" else identity,
                )
    return evidence


def load_reviewed_receipt(
    plan_payload: object,
    report_payload: object,
    *,
    plan_file_sha256: str,
    report_file_sha256: str,
) -> dict[str, Any]:
    """Validate and index the exact successful original localhost apply receipt."""

    plan = require_object(plan_payload, "Prior apply plan")
    report = require_object(report_payload, "Prior apply report")
    logical_plan_sha = validate_internal_plan_hash(plan)
    if original.clean(plan.get("source_key")) != SOURCE_KEY:
        raise MigrationError("Prior apply plan source_key changed")
    if original.clean(plan.get("mode")) != "dry_run_plan":
        raise MigrationError("Prior apply plan is not the reviewed dry-run plan")
    if original.clean(report.get("mode")) != "apply":
        raise MigrationError("Prior apply report is not a successful apply receipt")
    if report.get("production_touched") is not False:
        raise MigrationError("Prior apply report does not prove production_touched=false")
    if original.clean(report.get("plan_sha256")).lower() != logical_plan_sha:
        raise MigrationError("Prior apply report does not match the prior apply plan")

    source_files = require_object(plan.get("source_files"), "Prior apply source_files")
    for key in (
        "models_source_sha256",
        "variants_source_sha256",
        "validated_models_sha256",
        "validated_variants_sha256",
        "sizes_sha256",
    ):
        digest = original.clean(source_files.get(key)).lower()
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise MigrationError(f"Prior apply source_files.{key} is not a SHA-256")

    actions = require_list(plan.get("actions"), "Prior apply actions")
    create_actions = [
        require_object(action, "Prior create action")
        for action in actions
        if isinstance(action, dict) and action.get("action") in {"create_variant", "create_standalone"}
    ]
    update_actions = [
        require_object(action, "Prior update action")
        for action in actions
        if isinstance(action, dict) and action.get("action") == "update_existing"
    ]
    if len(create_actions) + len(update_actions) != len(actions):
        raise MigrationError("Prior apply plan contains an unsupported action type")

    reconciliation = require_object(
        report.get("reconciliation"), "Prior apply reconciliation"
    )
    created_ids_raw = require_list(
        reconciliation.get("created_model_ids"),
        "Prior apply reconciliation.created_model_ids",
    )
    created_ids = [
        require_int(value, "Prior created model id", positive=True)
        for value in created_ids_raw
    ]
    if len(created_ids) != len(set(created_ids)):
        raise MigrationError("Prior apply report contains duplicate created model ids")
    if len(created_ids) != len(create_actions):
        raise MigrationError(
            "Prior apply create actions do not reconcile to created_model_ids"
        )
    if require_int(
        reconciliation.get("created_models"),
        "Prior apply reconciliation.created_models",
    ) != len(created_ids):
        raise MigrationError("Prior apply created_models count changed")

    created_by_id = {
        model_id: copy.deepcopy(action)
        for model_id, action in zip(created_ids, create_actions, strict=True)
    }
    existing_by_id: dict[int, dict[str, Any]] = {}
    for action in update_actions:
        model_id = require_int(
            action.get("target_model_id"),
            "Prior update target_model_id",
            positive=True,
        )
        if model_id in existing_by_id or model_id in created_by_id:
            raise MigrationError(f"Prior receipt maps model {model_id} more than once")
        existing_by_id[model_id] = copy.deepcopy(action)

    counts_before = require_object(
        reconciliation.get("counts_before"), "Prior apply counts_before"
    )
    counts_after = require_object(
        reconciliation.get("counts_after"), "Prior apply counts_after"
    )
    if require_int(counts_after.get("models"), "Prior models-after count") - require_int(
        counts_before.get("models"), "Prior models-before count"
    ) != len(created_ids):
        raise MigrationError("Prior apply model counts do not reconcile to created ids")
    for key in ("model_images", "model_sizes", "model_colors", "model_bom"):
        require_int(counts_before.get(key), f"Prior counts_before.{key}")
        require_int(counts_after.get(key), f"Prior counts_after.{key}")

    protected_before = original.clean(
        reconciliation.get("protected_names_images_sha256_before")
    ).lower()
    protected_after = original.clean(
        reconciliation.get("protected_names_images_sha256_after")
    ).lower()
    if not re.fullmatch(r"[0-9a-f]{64}", protected_before):
        raise MigrationError("Prior apply receipt has no protected pre-import digest")
    if protected_before != protected_after:
        raise MigrationError("Prior apply did not preserve pre-import names/images")

    plan_preconditions = require_object(
        plan.get("database_preconditions"), "Prior database_preconditions"
    )
    if (
        original.clean(
            plan_preconditions.get("protected_names_images_sha256")
        ).lower()
        != protected_before
    ):
        raise MigrationError("Prior plan/report protected digests disagree")

    all_by_id = {**existing_by_id, **created_by_id}
    provenance_evidence = index_receipt_provenance_evidence(
        all_by_id.values()
    )
    summary = require_object(plan.get("summary"), "Prior apply summary")
    prior_source_model_count = require_int(
        summary.get("source_model_rows"),
        "Prior apply summary.source_model_rows",
        positive=True,
    )
    prior_source_variant_count = require_int(
        summary.get("source_variant_rows"),
        "Prior apply summary.source_variant_rows",
        positive=True,
    )
    known_model_ids = set(provenance_evidence["model_records"])
    known_variant_ids = set(provenance_evidence["variant_records"])
    for raw_quarantine in require_list(
        plan.get("quarantines"), "Prior apply quarantines"
    ):
        quarantine = require_object(raw_quarantine, "Prior quarantine")
        known_model_ids.update(
            require_int(value, "Prior quarantine old_model_id", positive=True)
            for value in require_list(
                quarantine.get("old_model_ids"),
                "Prior quarantine.old_model_ids",
            )
        )
        known_variant_ids.update(
            require_int(value, "Prior quarantine old_variant_id", positive=True)
            for value in require_list(
                quarantine.get("old_variant_ids"),
                "Prior quarantine.old_variant_ids",
            )
        )
    if not known_model_ids or not known_variant_ids:
        raise MigrationError("Prior receipt has no usable source-id bounds")
    return {
        "logical_plan_sha256": logical_plan_sha,
        "plan_file_sha256": plan_file_sha256,
        "report_file_sha256": report_file_sha256,
        "source_files": copy.deepcopy(source_files),
        "created_by_id": created_by_id,
        "existing_by_id": existing_by_id,
        "all_by_id": all_by_id,
        "provenance_evidence": provenance_evidence,
        "prior_source_model_count": prior_source_model_count,
        "prior_source_variant_count": prior_source_variant_count,
        "prior_source_max_old_model_id": max(known_model_ids),
        "prior_source_max_old_variant_id": max(known_variant_ids),
        "created_ids": created_ids,
        "counts_before": copy.deepcopy(counts_before),
        "counts_after": copy.deepcopy(counts_after),
        "protected_preimport_sha256": protected_before,
    }


def validate_string_fields(row: dict[str, Any], fields: Iterable[str], label: str) -> None:
    for field in fields:
        if field not in row:
            raise MigrationError(f"{label} is missing {field!r}")
        if not isinstance(row[field], str):
            raise MigrationError(f"{label}.{field} must be a string")


def validate_complete_record(value: object, position: int) -> dict[str, Any]:
    record = require_object(value, f"Complete record {position}")
    old_model_id = require_int(
        record.get("old_model_id"),
        f"Complete record {position}.old_model_id",
        positive=True,
    )
    if not isinstance(record.get("source_url"), str):
        raise MigrationError(f"Complete record {old_model_id}.source_url must be a string")
    list_metadata = require_object(
        record.get("list_metadata"),
        f"Complete record {old_model_id}.list_metadata",
    )
    if require_int(
        list_metadata.get("old_model_id"),
        f"Complete record {old_model_id}.list_metadata.old_model_id",
        positive=True,
    ) != old_model_id:
        raise MigrationError(
            f"Complete record {old_model_id} list_metadata id changed"
        )
    validate_string_fields(
        list_metadata,
        LIST_METADATA_STRING_FIELDS,
        f"Complete record {old_model_id}.list_metadata",
    )
    if not isinstance(list_metadata.get("has_image"), bool):
        raise MigrationError(
            f"Complete record {old_model_id}.list_metadata.has_image "
            "must be boolean"
        )

    general = require_object(
        record.get("general"), f"Complete record {old_model_id}.general"
    )
    for field in GENERAL_FIELDS:
        if field not in general:
            raise MigrationError(
                f"Complete record {old_model_id}.general is missing {field!r}"
            )
        if field in {"Embroidery", "Thermal Print"}:
            if not isinstance(general[field], bool):
                raise MigrationError(
                    f"Complete record {old_model_id}.general.{field} must be boolean"
                )
        elif not isinstance(general[field], str):
            raise MigrationError(
                f"Complete record {old_model_id}.general.{field} must be a string"
            )
    for general_field, list_field in GENERAL_TO_LIST_METADATA.items():
        if general[general_field] != list_metadata[list_field]:
            raise MigrationError(
                f"Complete record {old_model_id} general/list metadata "
                f"disagree on {general_field!r}"
            )

    operations = require_list(
        record.get("operations"), f"Complete record {old_model_id}.operations"
    )
    for operation_position, raw_operation in enumerate(operations, start=1):
        operation = require_object(
            raw_operation,
            f"Complete record {old_model_id} operation {operation_position}",
        )
        for field in OPERATION_FIELDS:
            if field not in operation:
                raise MigrationError(
                    f"Complete record {old_model_id} operation "
                    f"{operation_position} is missing {field!r}"
                )
        require_int(
            operation["source_order"],
            f"Complete record {old_model_id} operation {operation_position}.source_order",
        )
        validate_string_fields(
            operation,
            (
                "name",
                "duration",
                "price",
                "currency",
                "stage",
                "control_change_direction",
            ),
            f"Complete record {old_model_id} operation {operation_position}",
        )
        if not isinstance(operation["final_operation"], bool):
            raise MigrationError(
                f"Complete record {old_model_id} operation "
                f"{operation_position}.final_operation must be boolean"
            )

    recipes = require_list(
        record.get("recipes"), f"Complete record {old_model_id}.recipes"
    )
    for recipe_position, raw_recipe in enumerate(recipes, start=1):
        recipe = require_object(
            raw_recipe,
            f"Complete record {old_model_id} recipe {recipe_position}",
        )
        for field in RECIPE_FIELDS:
            if field not in recipe:
                raise MigrationError(
                    f"Complete record {old_model_id} recipe "
                    f"{recipe_position} is missing {field!r}"
                )
        require_int(
            recipe["source_order"],
            f"Complete record {old_model_id} recipe {recipe_position}.source_order",
        )
        validate_string_fields(
            recipe,
            ("product", "quantity", "sewing_type_list"),
            f"Complete record {old_model_id} recipe {recipe_position}",
        )
    return copy.deepcopy(record)


def index_complete_manifest(
    payload: object,
    *,
    manifest_file_sha256: str,
) -> dict[str, Any]:
    manifest = require_object(payload, "Complete-details manifest")
    if require_int(manifest.get("version"), "Complete-details manifest.version") != 1:
        raise MigrationError("Unsupported complete-details manifest version")
    records_raw = manifest.get("records")
    if isinstance(records_raw, dict):
        records_list = list(records_raw.values())
    else:
        records_list = require_list(
            records_raw, "Complete-details manifest.records"
        )
    records: dict[int, dict[str, Any]] = {}
    for position, value in enumerate(records_list, start=1):
        record = validate_complete_record(value, position)
        old_model_id = int(record["old_model_id"])
        if old_model_id in records:
            raise MigrationError(
                f"Complete-details manifest repeats old_model_id {old_model_id}"
            )
        records[old_model_id] = record

    record_count = require_int(
        manifest.get("record_count"), "Complete-details manifest.record_count"
    )
    source_model_count = require_int(
        manifest.get("source_model_count"),
        "Complete-details manifest.source_model_count",
    )
    if record_count != len(records):
        raise MigrationError(
            "Complete-details manifest record_count does not match records"
        )
    if source_model_count < record_count:
        raise MigrationError(
            "Complete-details manifest source_model_count is smaller than record_count"
        )
    top_level_metadata = {
        key: copy.deepcopy(value)
        for key, value in manifest.items()
        if key != "records"
    }
    return {
        "records": records,
        "record_count": record_count,
        "source_model_count": source_model_count,
        "is_complete": source_model_count == record_count,
        "file_sha256": manifest_file_sha256,
        "metadata": top_level_metadata,
    }


def validate_complete_record_receipt_evidence(
    record: dict[str, Any],
    source_row: dict[str, Any],
) -> None:
    old_model_id = int(record["old_model_id"])
    if int(source_row.get("old_model_id") or 0) != old_model_id:
        raise MigrationError(
            f"Complete record {old_model_id} has mismatched receipt evidence"
        )
    parsed = urlparse(record["source_url"])
    query_ids = parse_qs(parsed.query, keep_blank_values=True).get("id") or []
    if (
        parsed.path != "/uzerp/prepareSewModel.htm"
        or query_ids != [str(old_model_id)]
    ):
        raise MigrationError(
            f"Complete record {old_model_id} source_url does not identify itself"
        )
    list_metadata = record["list_metadata"]
    for field in LIST_METADATA_STRING_FIELDS:
        if field not in source_row:
            raise MigrationError(
                f"Receipt evidence for old model {old_model_id} lacks {field!r}"
            )
        if list_metadata[field] != source_row[field]:
            raise MigrationError(
                f"Complete record {old_model_id} list_metadata.{field} "
                "differs from the frozen receipt"
            )
def canonical_paid_operation(raw_operation: dict[str, Any]) -> dict[str, Any]:
    """Map one validated old operation to the exact frontend storage shape."""

    stage = raw_operation["stage"]
    section = STAGE_TO_SECTION.get(stage)
    if section is None:
        raise MigrationError(f"Unsupported old-ERP operation stage {stage!r}")
    source_order = require_int(
        raw_operation["source_order"], "Old operation source_order"
    )
    fingerprint = {
        field: copy.deepcopy(raw_operation[field])
        for field in OPERATION_FIELDS
    }
    digest = original.object_sha256(fingerprint)
    prefix = SECTION_CODE_PREFIX[section]
    return {
        "id": f"old-erp-op-{digest[:24]}",
        "selected": True,
        "section": section,
        "code": f"OERP-{prefix}-{source_order:03d}-{digest[:16].upper()}",
        "name": raw_operation["name"],
        "rate": raw_operation["price"],
        "sourceOrder": source_order,
        "duration": raw_operation["duration"],
        "currency": raw_operation["currency"],
        "sourceStage": stage,
        "changeDirection": raw_operation["control_change_direction"],
        "finalOperation": raw_operation["final_operation"],
        "quantityMode": "batch",
        "customQuantity": 0,
        "copies": 1,
        "splitMode": "none",
        "splitQuantities": [],
    }


def canonical_paid_operations(
    records: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return a deterministic, content-deduplicated union of source operations."""

    by_id: dict[str, dict[str, Any]] = {}
    for record in sorted(records, key=lambda row: int(row["old_model_id"])):
        for raw_operation in record["operations"]:
            operation = canonical_paid_operation(raw_operation)
            existing = by_id.get(operation["id"])
            if existing is not None and existing != operation:
                raise MigrationError(
                    f"Deterministic paid-operation id collision: {operation['id']}"
                )
            by_id[operation["id"]] = operation
    return sorted(
        by_id.values(),
        key=lambda row: (
            int(row["sourceOrder"]),
            row["section"],
            row["name"],
            row["id"],
        ),
    )


def provenance_without_complete_sections(
    provenance: dict[str, Any],
) -> dict[str, Any]:
    result = copy.deepcopy(provenance)
    result.pop("complete_sections", None)
    return result


def validate_current_provenance(
    details: object,
    action: dict[str, Any],
    provenance_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current_details = require_object(details, "Current model details_json")
    provenance = require_object(
        current_details.get("old_erp_migration"),
        "Current model old_erp_migration provenance",
    )
    expected = require_object(
        action.get("provenance"), "Prior action provenance"
    )
    current_base = provenance_without_complete_sections(provenance)
    if provenance_evidence is None:
        if current_base != expected:
            raise MigrationError(
                "Current old_erp_migration provenance differs from the reviewed apply action"
            )
        return provenance

    if set(current_base) != set(expected):
        raise MigrationError(
            "Current old_erp_migration provenance differs from the reviewed apply action"
        )
    for field in ("source_key", "source_files", "identity"):
        if current_base.get(field) != expected.get(field):
            raise MigrationError(
                "Current old_erp_migration provenance differs from the reviewed apply action"
            )
    if original.clean(current_base.get("source_key")) != SOURCE_KEY:
        raise MigrationError("Current old_erp_migration provenance owner changed")
    identity = original.clean(current_base.get("identity"))
    identity_base, separator, _ = identity.partition("|")
    if not separator or not identity_base:
        raise MigrationError("Current provenance identity is malformed")

    def indexed_rows(
        value: object,
        *,
        field: str,
        id_field: str,
    ) -> dict[int, dict[str, Any]]:
        result: dict[int, dict[str, Any]] = {}
        for position, raw_row in enumerate(
            require_list(value, f"Current provenance.{field}"),
            start=1,
        ):
            row = require_object(
                raw_row, f"Current provenance.{field}[{position}]"
            )
            row_id = require_int(
                row.get(id_field),
                f"Current provenance.{field}[{position}].{id_field}",
                positive=True,
            )
            if row_id in result:
                raise MigrationError(
                    f"Current provenance.{field} repeats {id_field} {row_id}"
                )
            result[row_id] = row
        return result

    current_model_record_ids: set[int] = set()
    current_variant_record_ids: set[int] = set()
    for field, id_field, evidence_field, scope_field, required_scope in (
        (
            "master_records",
            "old_model_id",
            "model_records",
            "model_record_bases",
            identity_base,
        ),
        (
            "metadata_only_records",
            "old_model_id",
            "model_records",
            "model_record_bases",
            identity_base,
        ),
        (
            "variant_records",
            "old_variant_id",
            "variant_records",
            "variant_record_identities",
            identity,
        ),
    ):
        current_rows = indexed_rows(
            current_base.get(field),
            field=field,
            id_field=id_field,
        )
        expected_rows = indexed_rows(
            expected.get(field),
            field=f"expected.{field}",
            id_field=id_field,
        )
        for row_id, row in expected_rows.items():
            if current_rows.get(row_id) != row:
                raise MigrationError(
                    "Current old_erp_migration provenance differs from "
                    "the reviewed apply action"
                )
        evidence_rows = require_object(
            provenance_evidence.get(evidence_field),
            f"Receipt evidence.{evidence_field}",
        )
        evidence_scopes = require_object(
            provenance_evidence.get(scope_field),
            f"Receipt evidence.{scope_field}",
        )
        for row_id, row in current_rows.items():
            if evidence_rows.get(row_id) != row:
                raise MigrationError(
                    f"Current provenance {id_field} {row_id} lacks exact "
                    "hash-pinned receipt evidence"
                )
            allowed_scopes = require_list(
                evidence_scopes.get(row_id),
                f"Receipt evidence.{scope_field}.{row_id}",
            )
            if required_scope not in allowed_scopes:
                raise MigrationError(
                    f"Current provenance {id_field} {row_id} is not authorized "
                    f"for identity {identity}"
                )
        if id_field == "old_model_id":
            current_model_record_ids.update(current_rows)
        else:
            current_variant_record_ids.update(current_rows)

    current_details_rows = require_object(
        current_base.get("details_and_sizes"),
        "Current provenance.details_and_sizes",
    )
    expected_details_rows = require_object(
        expected.get("details_and_sizes"),
        "Expected provenance.details_and_sizes",
    )
    evidence_details_rows = require_object(
        provenance_evidence.get("details_and_sizes"),
        "Receipt evidence.details_and_sizes",
    )
    evidence_detail_scopes = require_object(
        provenance_evidence.get("details_and_sizes_bases"),
        "Receipt evidence.details_and_sizes_bases",
    )
    for key, value in expected_details_rows.items():
        if current_details_rows.get(key) != value:
            raise MigrationError(
                "Current old_erp_migration provenance differs from the reviewed apply action"
            )
    for key, value in current_details_rows.items():
        source_id = require_int(
            key, "Current provenance.details_and_sizes key", positive=True
        )
        if evidence_details_rows.get(str(source_id)) != value:
            raise MigrationError(
                f"Current details provenance {source_id} lacks exact "
                "hash-pinned receipt evidence"
            )
        if source_id not in current_model_record_ids:
            raise MigrationError(
                f"Current details provenance {source_id} has no linked model record"
            )
        allowed_bases = require_list(
            evidence_detail_scopes.get(str(source_id)),
            f"Receipt evidence.details_and_sizes_bases.{source_id}",
        )
        if identity_base not in allowed_bases:
            raise MigrationError(
                f"Current details provenance {source_id} is not authorized "
                f"for identity {identity}"
            )

    current_validated = require_object(
        current_base.get("validated_images"),
        "Current provenance.validated_images",
    )
    expected_validated = require_object(
        expected.get("validated_images"),
        "Expected provenance.validated_images",
    )
    evidence_validated = require_object(
        provenance_evidence.get("validated_images"),
        "Receipt evidence.validated_images",
    )
    evidence_validated_scopes = require_object(
        provenance_evidence.get("validated_image_scopes"),
        "Receipt evidence.validated_image_scopes",
    )
    for source_type in ("models", "variants"):
        current_rows = require_object(
            current_validated.get(source_type),
            f"Current provenance.validated_images.{source_type}",
        )
        expected_rows = require_object(
            expected_validated.get(source_type),
            f"Expected provenance.validated_images.{source_type}",
        )
        evidence_rows = require_object(
            evidence_validated.get(source_type),
            f"Receipt evidence.validated_images.{source_type}",
        )
        evidence_scopes = require_object(
            evidence_validated_scopes.get(source_type),
            f"Receipt evidence.validated_image_scopes.{source_type}",
        )
        for key, value in expected_rows.items():
            if current_rows.get(key) != value:
                raise MigrationError(
                    "Current old_erp_migration provenance differs from "
                    "the reviewed apply action"
                )
        for key, value in current_rows.items():
            source_id = require_int(
                key,
                f"Current provenance.validated_images.{source_type} key",
                positive=True,
            )
            if evidence_rows.get(str(source_id)) != value:
                raise MigrationError(
                    f"Current validated {source_type} provenance {source_id} "
                    "lacks exact hash-pinned receipt evidence"
                )
            linked_ids = (
                current_model_record_ids
                if source_type == "models"
                else current_variant_record_ids
            )
            if source_id not in linked_ids:
                raise MigrationError(
                    f"Current validated {source_type} provenance {source_id} "
                    "has no linked source record"
                )
            allowed_scopes = require_list(
                evidence_scopes.get(str(source_id)),
                f"Receipt evidence.validated_image_scopes."
                f"{source_type}.{source_id}",
            )
            required_scope = (
                identity_base if source_type == "models" else identity
            )
            if required_scope not in allowed_scopes:
                raise MigrationError(
                    f"Current validated {source_type} provenance {source_id} "
                    f"is not authorized for identity {identity}"
                )
    return provenance


def referenced_old_model_ids(provenance: dict[str, Any]) -> list[int]:
    ids: set[int] = set()
    for field in ("master_records", "metadata_only_records"):
        rows = require_list(
            provenance.get(field), f"old_erp_migration.{field}"
        )
        for position, value in enumerate(rows, start=1):
            row = require_object(value, f"old_erp_migration.{field}[{position}]")
            ids.add(
                require_int(
                    row.get("old_model_id"),
                    f"old_erp_migration.{field}[{position}].old_model_id",
                    positive=True,
                )
            )
    if not ids:
        raise MigrationError(
            "Reviewed old_erp_migration provenance references no old_model_id"
        )
    return sorted(ids)


def complete_sections_payload(
    records: Iterable[dict[str, Any]],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    ordered = sorted(records, key=lambda row: int(row["old_model_id"]))
    ids = [int(record["old_model_id"]) for record in ordered]
    return {
        "schema_version": COMPLETE_SECTIONS_SCHEMA_VERSION,
        "source_manifest_sha256": manifest["file_sha256"],
        "source_manifest_metadata": copy.deepcopy(manifest["metadata"]),
        "source_record_ids": ids,
        "general": {
            str(record["old_model_id"]): copy.deepcopy(record["general"])
            for record in ordered
        },
        "operations": {
            str(record["old_model_id"]): copy.deepcopy(record["operations"])
            for record in ordered
        },
        "recipes": {
            str(record["old_model_id"]): copy.deepcopy(record["recipes"])
            for record in ordered
        },
        "record_metadata": {
            str(record["old_model_id"]): {
                key: copy.deepcopy(value)
                for key, value in record.items()
                if key not in {"general", "operations", "recipes"}
            }
            for record in ordered
        },
    }


def merge_lossless_complete_sections(
    provenance: dict[str, Any],
    desired: dict[str, Any],
) -> bool:
    """Add exact source sections while refusing conflicting prior content."""

    current = provenance.get("complete_sections")
    if current is None:
        provenance["complete_sections"] = copy.deepcopy(desired)
        return True
    if not isinstance(current, dict):
        raise MigrationError("Existing complete_sections is not a JSON object")
    changed = False
    scalar_fields = (
        "schema_version",
        "source_manifest_sha256",
        "source_manifest_metadata",
    )
    for field in scalar_fields:
        if field not in current:
            current[field] = copy.deepcopy(desired[field])
            changed = True
        elif current[field] != desired[field]:
            raise MigrationError(
                f"Existing complete_sections.{field} conflicts with reviewed source"
            )

    desired_ids = list(desired["source_record_ids"])
    if "source_record_ids" not in current:
        current["source_record_ids"] = desired_ids
        changed = True
    else:
        current_ids = require_list(
            current["source_record_ids"],
            "Existing complete_sections.source_record_ids",
        )
        parsed_ids = [
            require_int(value, "Existing complete source id", positive=True)
            for value in current_ids
        ]
        if not set(parsed_ids).issubset(desired_ids):
            raise MigrationError(
                "Existing complete_sections references a different old model"
            )
        if parsed_ids != desired_ids:
            current["source_record_ids"] = desired_ids
            changed = True

    for field in ("general", "operations", "recipes", "record_metadata"):
        desired_rows = require_object(
            desired[field], f"Desired complete_sections.{field}"
        )
        current_rows = current.get(field)
        if current_rows is None:
            current[field] = copy.deepcopy(desired_rows)
            changed = True
            continue
        current_rows = require_object(
            current_rows, f"Existing complete_sections.{field}"
        )
        unexpected = sorted(set(current_rows) - set(desired_rows))
        if unexpected:
            raise MigrationError(
                f"Existing complete_sections.{field} has unrelated ids: "
                + ", ".join(unexpected[:10])
            )
        for key, value in desired_rows.items():
            if key not in current_rows:
                current_rows[key] = copy.deepcopy(value)
                changed = True
            elif current_rows[key] != value:
                raise MigrationError(
                    f"Existing complete_sections.{field}.{key} conflicts "
                    "with reviewed source"
                )
    return changed


def is_missing_general_value(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def present_source_value(value: object) -> bool:
    if isinstance(value, bool):
        return True
    if isinstance(value, str):
        return bool(value.strip())
    return value is not None


def unique_exact_values(values: Iterable[object]) -> list[Any]:
    result: list[Any] = []
    for value in values:
        if not any(existing == value for existing in result):
            result.append(copy.deepcopy(value))
    return result


def fill_missing_general(
    details: dict[str, Any],
    records: Iterable[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, list[Any]], dict[str, Any]]:
    general = details.get("general")
    if general is None:
        general = {}
        details["general"] = general
    if not isinstance(general, dict):
        raise MigrationError("Current details_json.general is not a JSON object")
    fills: dict[str, Any] = {}
    conflicts: dict[str, list[Any]] = {}
    preserved: dict[str, Any] = {}
    ordered_records = sorted(records, key=lambda row: int(row["old_model_id"]))
    for source_field, target_field in GENERAL_TO_DETAILS.items():
        values = unique_exact_values(
            record["general"][source_field]
            for record in ordered_records
            if present_source_value(record["general"][source_field])
        )
        if len(values) > 1:
            conflicts[target_field] = values
            continue
        if not values:
            continue
        incoming = values[0]
        if is_missing_general_value(general.get(target_field)):
            general[target_field] = copy.deepcopy(incoming)
            fills[target_field] = copy.deepcopy(incoming)
        elif general.get(target_field) != incoming:
            preserved[target_field] = copy.deepcopy(general.get(target_field))
    return fills, conflicts, preserved


def fill_missing_paid_operations(
    details: dict[str, Any],
    operations: list[dict[str, Any]],
) -> str:
    """Fill only a missing canonical field; never overwrite user/default rows."""

    if "paid_operations" in details:
        if details["paid_operations"] is None:
            details["paid_operations"] = copy.deepcopy(operations)
            return "filled_explicit_empty" if not operations else "filled"
        if details["paid_operations"] == operations:
            return "already_exact"
        return "preserved_existing_paid_operations"
    if "paidOperations" in details and details["paidOperations"] is not None:
        return "preserved_existing_paidOperations"
    details["paid_operations"] = copy.deepcopy(operations)
    return "filled_explicit_empty" if not operations else "filled"


def build_corrected_details(
    current_details: dict[str, Any],
    *,
    records: list[dict[str, Any]],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    details = copy.deepcopy(current_details)
    provenance = require_object(
        details.get("old_erp_migration"),
        "Current model old_erp_migration provenance",
    )
    complete_changed = merge_lossless_complete_sections(
        provenance,
        complete_sections_payload(records, manifest),
    )
    fills, conflicts, preserved_general = fill_missing_general(details, records)
    operations = canonical_paid_operations(records)
    paid_status = fill_missing_paid_operations(details, operations)
    return {
        "details_after": details,
        "complete_sections_changed": complete_changed,
        "general_fills": fills,
        "general_conflicts": conflicts,
        "preserved_general": preserved_general,
        "paid_operations_status": paid_status,
        "canonical_paid_operations_count": len(operations),
    }


def product_name_decision(
    *,
    created: bool,
    current_name: str,
    action: dict[str, Any],
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    if not created:
        return {
            "status": "protected_preexisting",
            "original_imported_name": None,
            "target_name": None,
        }
    original_name = action.get("name")
    if not isinstance(original_name, str):
        raise MigrationError("Prior create action name is not a string")
    raw_product = action.get("product_type")
    if raw_product is None:
        raw_product = ""
    if not isinstance(raw_product, str):
        raise MigrationError("Prior create action product_type is not a string")
    source_products = unique_exact_values(
        record["general"]["Product"]
        for record in records
        if present_source_value(record["general"]["Product"])
    )
    if raw_product.strip():
        target_name = raw_product
        if target_name not in source_products:
            raise MigrationError(
                f"Prior Product {target_name!r} has no exact complete-source evidence"
            )
    elif len(source_products) == 1:
        target_name = source_products[0]
    elif len(source_products) > 1:
        return {
            "status": "product_conflict",
            "original_imported_name": original_name,
            "target_name": None,
            "source_products": source_products,
        }
    else:
        return {
            "status": "no_product",
            "original_imported_name": original_name,
            "target_name": None,
            "source_products": [],
        }
    if len(target_name) > 255:
        raise MigrationError("Exact old Product exceeds the Model.name limit")
    if current_name == target_name:
        status = "already_correct"
    elif current_name == original_name:
        status = "update"
    else:
        status = "manual_drift"
    return {
        "status": status,
        "original_imported_name": original_name,
        "target_name": target_name,
        "source_products": source_products,
    }


def model_state_from_orm(model: Model) -> dict[str, Any]:
    return {
        "id": int(model.id),
        "code": model.code,
        "name": model.name,
        "product_type": model.product_type,
        "details_json": copy.deepcopy(model.details_json),
        "images": original.model_image_snapshot(model),
    }


def plan_model_correction(
    state: dict[str, Any],
    *,
    action: dict[str, Any],
    created: bool,
    complete_records: dict[int, dict[str, Any]],
    manifest: dict[str, Any],
    provenance_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    model_id = require_int(state.get("id"), "Current model id", positive=True)
    expected_code = (
        action.get("code") if created else action.get("expected_code")
    )
    if state.get("code") != expected_code:
        raise MigrationError(
            f"Current model {model_id} code changed from the reviewed apply value"
        )
    current_name = state.get("name")
    if not isinstance(current_name, str):
        raise MigrationError(f"Current model {model_id} name is not a string")
    current_details = require_object(
        state.get("details_json"), f"Current model {model_id} details_json"
    )
    provenance = validate_current_provenance(
        current_details,
        action,
        provenance_evidence,
    )
    source_ids = referenced_old_model_ids(provenance)
    missing = [source_id for source_id in source_ids if source_id not in complete_records]
    if missing:
        raise MigrationError(
            f"Current model {model_id} lacks complete records for old ids "
            + ", ".join(str(value) for value in missing)
        )
    records = [complete_records[source_id] for source_id in source_ids]
    details_result = build_corrected_details(
        current_details,
        records=records,
        manifest=manifest,
    )
    name_decision = product_name_decision(
        created=created,
        current_name=current_name,
        action=action,
        records=records,
    )
    new_name = (
        name_decision["target_name"]
        if name_decision["status"] == "update"
        else None
    )
    details_after = details_result.pop("details_after")
    details_changed = details_after != current_details
    image_snapshot = copy.deepcopy(state.get("images") or [])
    return {
        "model_id": model_id,
        "origin": "import_created" if created else "preexisting",
        "identity": action.get("identity"),
        "expected_code": expected_code,
        "expected_name": current_name,
        "expected_images_sha256": original.object_sha256(image_snapshot),
        "expected_details_sha256": original.object_sha256(current_details),
        "source_record_ids": source_ids,
        "name_decision": name_decision,
        "new_name": new_name,
        "details_changed": details_changed,
        "details_after_sha256": original.object_sha256(details_after),
        **details_result,
        "_details_after": details_after,
    }


def public_model_action(result: dict[str, Any]) -> dict[str, Any]:
    return {
        key: copy.deepcopy(value)
        for key, value in result.items()
        if key != "_details_after"
    }


def expected_action_provenance_ids(
    receipt: dict[str, Any],
) -> dict[int, list[int]]:
    result: dict[int, list[int]] = {}
    for model_id, action in receipt["all_by_id"].items():
        provenance = require_object(
            action.get("provenance"), f"Prior action {model_id} provenance"
        )
        result[int(model_id)] = referenced_old_model_ids(provenance)
    return result


def manifest_linkage_gaps(
    provenance_ids: dict[int, list[int]],
    complete_records: dict[int, dict[str, Any]],
) -> tuple[list[int], list[int], list[int]]:
    referenced = sorted(
        {
            source_id
            for values in provenance_ids.values()
            for source_id in values
        }
    )
    missing = sorted(set(referenced) - set(complete_records))
    unlinked = sorted(set(complete_records) - set(referenced))
    return referenced, missing, unlinked


def correction_source_scope(
    receipt: dict[str, Any],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    """Describe whether the detail manifest is still inside the prior receipt."""

    prior_model_count = require_int(
        receipt.get("prior_source_model_count"),
        "Receipt prior_source_model_count",
        positive=True,
    )
    prior_variant_count = require_int(
        receipt.get("prior_source_variant_count"),
        "Receipt prior_source_variant_count",
        positive=True,
    )
    prior_max_model_id = require_int(
        receipt.get("prior_source_max_old_model_id"),
        "Receipt prior_source_max_old_model_id",
        positive=True,
    )
    prior_max_variant_id = require_int(
        receipt.get("prior_source_max_old_variant_id"),
        "Receipt prior_source_max_old_variant_id",
        positive=True,
    )
    manifest_model_count = require_int(
        manifest.get("source_model_count"),
        "Complete manifest source_model_count",
    )
    records = require_object(
        manifest.get("records"),
        "Complete manifest indexed records",
    )
    appended_model_ids: list[int] = []
    for source_id in records:
        parsed_source_id = require_int(
            source_id,
            "Complete manifest old_model_id",
            positive=True,
        )
        if parsed_source_id > prior_max_model_id:
            appended_model_ids.append(parsed_source_id)
    appended_model_ids.sort()
    model_count_delta = manifest_model_count - prior_model_count
    return {
        "prior_receipt_source_model_count": prior_model_count,
        "complete_manifest_source_model_count": manifest_model_count,
        "source_model_count_delta": model_count_delta,
        "prior_receipt_max_old_model_id": prior_max_model_id,
        "appended_old_model_record_count": len(appended_model_ids),
        "appended_old_model_ids": appended_model_ids,
        "prior_receipt_source_variant_count": prior_variant_count,
        "prior_receipt_max_old_variant_id": prior_max_variant_id,
        "complete_manifest_has_authenticated_variant_scope": False,
        "is_exact_prior_receipt_scope": (
            model_count_delta == 0 and not appended_model_ids
        ),
    }


def source_scope_blocking_issue(
    source_scope: dict[str, Any],
) -> dict[str, Any] | None:
    if source_scope["is_exact_prior_receipt_scope"]:
        return None
    positive_delta = (
        int(source_scope["source_model_count_delta"]) > 0
        or bool(source_scope["appended_old_model_ids"])
    )
    return {
        "reason": (
            "supplemental_source_delta_requires_separate_import"
            if positive_delta
            else "complete_manifest_source_scope_mismatch"
        ),
        **copy.deepcopy(source_scope),
        "required_action": (
            "Use a separately reviewed, hash-pinned supplemental model/variant "
            "import. This correction pass cannot create appended catalog rows "
            "or authenticate appended variant rows."
        ),
    }


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


def validate_receipt_database_shape(
    models: list[Model],
    receipt: dict[str, Any],
) -> tuple[list[Model], list[Model]]:
    counts_after = receipt["counts_after"]
    if len(models) != int(counts_after["models"]):
        raise MigrationError(
            "Current model count changed from the reviewed apply receipt"
        )
    by_id = {int(model.id): model for model in models}
    if len(by_id) != len(models):
        raise MigrationError("Current model ids are not unique")
    expected_linked = set(receipt["all_by_id"])
    missing_linked = sorted(expected_linked - set(by_id))
    if missing_linked:
        raise MigrationError(
            "Reviewed migrated model rows disappeared: "
            + ", ".join(str(value) for value in missing_linked[:20])
        )
    created_ids = set(receipt["created_ids"])
    preexisting = [model for model in models if int(model.id) not in created_ids]
    created = [model for model in models if int(model.id) in created_ids]
    if len(preexisting) != int(receipt["counts_before"]["models"]):
        raise MigrationError(
            "Current pre-import model scope changed from the reviewed receipt"
        )
    protected_sha = original.object_sha256(original.protected_snapshot(preexisting))
    if protected_sha != receipt["protected_preimport_sha256"]:
        raise MigrationError(
            "A pre-import model code, name, or image changed from the reviewed receipt"
        )
    return preexisting, created


def compile_correction_plan(
    *,
    db,
    receipt: dict[str, Any],
    manifest: dict[str, Any],
    database_guard: dict[str, Any],
) -> dict[str, Any]:
    models = load_models(db)
    preexisting, created_models = validate_receipt_database_shape(models, receipt)
    counts = original.db_counts(db)
    if counts != receipt["counts_after"]:
        raise MigrationError(
            "Current catalog row counts changed from the reviewed apply receipt"
        )
    business_counts = original.count_business_tables(db)
    by_id = {int(model.id): model for model in models}
    provenance_ids: dict[int, list[int]] = {}
    provenance_errors: list[dict[str, Any]] = []
    for model_id, action in sorted(receipt["all_by_id"].items()):
        try:
            details = require_object(
                by_id[model_id].details_json,
                f"Current model {model_id} details_json",
            )
            provenance = validate_current_provenance(
                details,
                action,
                receipt["provenance_evidence"],
            )
            provenance_ids[model_id] = referenced_old_model_ids(provenance)
        except MigrationError as exc:
            provenance_errors.append({"model_id": model_id, "error": str(exc)})
    (
        all_referenced_ids,
        missing_manifest_ids,
        unlinked_manifest_ids,
    ) = manifest_linkage_gaps(
        provenance_ids,
        manifest["records"],
    )
    blocking_issues: list[dict[str, Any]] = []
    source_scope = correction_source_scope(receipt, manifest)
    source_scope_issue = source_scope_blocking_issue(source_scope)
    if source_scope_issue is not None:
        blocking_issues.append(source_scope_issue)
    if provenance_errors:
        blocking_issues.append(
            {
                "reason": "provenance_precondition_errors",
                "models": provenance_errors,
            }
        )
    if not manifest["is_complete"]:
        blocking_issues.append(
            {
                "reason": "complete_manifest_is_partial",
                "source_model_count": manifest["source_model_count"],
                "record_count": manifest["record_count"],
            }
        )
    if missing_manifest_ids:
        blocking_issues.append(
            {
                "reason": "referenced_old_model_records_missing",
                "old_model_ids": missing_manifest_ids,
            }
        )

    source_evidence_errors: dict[int, str] = {}
    receipt_source_rows = require_object(
        receipt["provenance_evidence"].get("model_records"),
        "Receipt model-record evidence",
    )
    for source_id in all_referenced_ids:
        record = manifest["records"].get(source_id)
        if record is None:
            continue
        source_row = receipt_source_rows.get(source_id)
        if not isinstance(source_row, dict):
            source_evidence_errors[source_id] = (
                "No frozen receipt source row exists"
            )
            continue
        try:
            validate_complete_record_receipt_evidence(record, source_row)
        except MigrationError as exc:
            source_evidence_errors[source_id] = str(exc)
    if source_evidence_errors:
        blocking_issues.append(
            {
                "reason": "complete_record_source_evidence_errors",
                "records": [
                    {"old_model_id": key, "error": value}
                    for key, value in sorted(source_evidence_errors.items())
                ],
            }
        )

    operation_errors_by_source: dict[int, str] = {}
    for source_id in all_referenced_ids:
        record = manifest["records"].get(source_id)
        if record is None or source_id in source_evidence_errors:
            continue
        try:
            canonical_paid_operations([record])
        except MigrationError as exc:
            operation_errors_by_source[source_id] = str(exc)
    if operation_errors_by_source:
        blocking_issues.append(
            {
                "reason": "unsupported_operation_mapping",
                "records": [
                    {"old_model_id": key, "error": value}
                    for key, value in sorted(operation_errors_by_source.items())
                ],
            }
        )

    actions: list[dict[str, Any]] = []
    manual_name_drifts: list[dict[str, Any]] = []
    product_name_conflicts: list[dict[str, Any]] = []
    planning_errors: list[dict[str, Any]] = []
    checked_results: list[dict[str, Any]] = []
    created_ids = set(receipt["created_ids"])
    for model_id, action in sorted(receipt["all_by_id"].items()):
        if model_id not in provenance_ids:
            continue
        source_ids = provenance_ids[model_id]
        if any(
            source_id in missing_manifest_ids
            or source_id in source_evidence_errors
            or source_id in operation_errors_by_source
            for source_id in source_ids
        ):
            continue
        try:
            result = plan_model_correction(
                model_state_from_orm(by_id[model_id]),
                action=action,
                created=model_id in created_ids,
                complete_records=manifest["records"],
                manifest=manifest,
                provenance_evidence=receipt["provenance_evidence"],
            )
        except MigrationError as exc:
            planning_errors.append({"model_id": model_id, "error": str(exc)})
            continue
        checked_results.append(result)
        if result["name_decision"]["status"] == "manual_drift":
            manual_name_drifts.append(
                {
                    "model_id": model_id,
                    "current_name": result["expected_name"],
                    "original_imported_name": result["name_decision"][
                        "original_imported_name"
                    ],
                    "target_name": result["name_decision"]["target_name"],
                }
            )
        elif result["name_decision"]["status"] == "product_conflict":
            product_name_conflicts.append(
                {
                    "model_id": model_id,
                    "current_name": result["expected_name"],
                    "original_imported_name": result["name_decision"][
                        "original_imported_name"
                    ],
                    "source_products": result["name_decision"]["source_products"],
                }
            )
        if result["new_name"] is not None or result["details_changed"]:
            actions.append(public_model_action(result))
    if planning_errors:
        blocking_issues.append(
            {"reason": "model_planning_errors", "models": planning_errors}
        )

    name_status_counts: dict[str, int] = {}
    paid_status_counts: dict[str, int] = {}
    for result in checked_results:
        name_status = result["name_decision"]["status"]
        name_status_counts[name_status] = name_status_counts.get(name_status, 0) + 1
        paid_status = result["paid_operations_status"]
        paid_status_counts[paid_status] = paid_status_counts.get(paid_status, 0) + 1

    source_operation_rows = sum(
        len(manifest["records"][source_id]["operations"])
        for source_id in all_referenced_ids
        if source_id in manifest["records"]
    )
    source_recipe_rows = sum(
        len(manifest["records"][source_id]["recipes"])
        for source_id in all_referenced_ids
        if source_id in manifest["records"]
    )
    protected_snapshot = original.protected_snapshot(preexisting)
    all_names_images = original.protected_snapshot(models)
    plan = {
        "schema_version": SCHEMA_VERSION,
        "mode": "dry_run",
        "source_key": SOURCE_KEY,
        "prior_receipt": {
            "plan_file_sha256": receipt["plan_file_sha256"],
            "report_file_sha256": receipt["report_file_sha256"],
            "logical_plan_sha256": receipt["logical_plan_sha256"],
            "source_files": copy.deepcopy(receipt["source_files"]),
        },
        "complete_details_manifest": {
            "file_sha256": manifest["file_sha256"],
            "source_model_count": manifest["source_model_count"],
            "record_count": manifest["record_count"],
            "is_complete": manifest["is_complete"],
        },
        "source_scope": source_scope,
        "database_guard": copy.deepcopy(database_guard),
        "database_preconditions": {
            "counts": counts,
            "business_counts": business_counts,
            "catalog_sha256": original.object_sha256(
                original.catalog_snapshot(models)
            ),
            "all_names_images_sha256": original.object_sha256(all_names_images),
            "protected_preimport_names_images_sha256": original.object_sha256(
                protected_snapshot
            ),
            "protected_preimport_model_count": len(preexisting),
            "import_created_model_count": len(created_models),
        },
        "summary": {
            "receipt_linked_models": len(receipt["all_by_id"]),
            "import_created_models": len(receipt["created_ids"]),
            "receipt_preexisting_models": len(receipt["existing_by_id"]),
            "protected_preimport_models": len(preexisting),
            "referenced_old_model_records": len(all_referenced_ids),
            "manifest_unlinked_records": len(unlinked_manifest_ids),
            "manifest_missing_records": len(missing_manifest_ids),
            "appended_source_model_records": source_scope[
                "appended_old_model_record_count"
            ],
            "source_model_count_delta": source_scope[
                "source_model_count_delta"
            ],
            "complete_manifest_has_authenticated_variant_scope": source_scope[
                "complete_manifest_has_authenticated_variant_scope"
            ],
            "source_evidence_error_records": len(source_evidence_errors),
            "source_operation_rows": source_operation_rows,
            "source_recipe_rows": source_recipe_rows,
            "planned_model_updates": len(actions),
            "planned_name_updates": sum(
                action["new_name"] is not None for action in actions
            ),
            "planned_details_updates": sum(
                bool(action["details_changed"]) for action in actions
            ),
            "manual_name_drifts_skipped": len(manual_name_drifts),
            "product_name_conflicts_skipped": len(product_name_conflicts),
            "name_status_counts": dict(sorted(name_status_counts.items())),
            "paid_operations_status_counts": dict(
                sorted(paid_status_counts.items())
            ),
            "blocking_issue_count": len(blocking_issues),
            "ready_for_apply": not blocking_issues,
        },
        "actions": sorted(actions, key=lambda row: int(row["model_id"])),
        "manual_name_drifts": manual_name_drifts,
        "product_name_conflicts": product_name_conflicts,
        "missing_manifest_old_model_ids": missing_manifest_ids,
        "unlinked_manifest_old_model_ids": unlinked_manifest_ids,
        "blocking_issues": blocking_issues,
        "invariants": {
            "preimport_names_codes_images_immutable": True,
            "all_model_images_immutable": True,
            "created_names_require_original_current_value": True,
            "details_metadata_additive_only": True,
            "recipes_are_raw_metadata_only": True,
            "correction_scope_is_receipt_linked_only": True,
            "supplemental_source_delta_is_never_silently_applied": True,
            "items_or_bom_created": False,
            "production_touched": False,
        },
    }
    plan["plan_sha256"] = original.object_sha256(plan)
    return plan


def plain_dump_has_required_catalog(path: Path) -> bool:
    marker_groups = (
        (
            b"CREATE TABLE public.models",
            b'CREATE TABLE "public"."models"',
        ),
        (
            b"CREATE TABLE public.alembic_version",
            b'CREATE TABLE "public"."alembic_version"',
        ),
        (
            b"COPY public.models",
            b'COPY "public"."models"',
            b"INSERT INTO public.models",
            b'INSERT INTO "public"."models"',
        ),
        (
            b"COPY public.alembic_version",
            b'COPY "public"."alembic_version"',
            b"INSERT INTO public.alembic_version",
            b'INSERT INTO "public"."alembic_version"',
        ),
    )
    found = [False] * len(marker_groups)
    longest = max(len(marker) for group in marker_groups for marker in group)
    carry = b""
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            haystack = carry + chunk
            for index, group in enumerate(marker_groups):
                if not found[index] and any(marker in haystack for marker in group):
                    found[index] = True
            if all(found):
                break
            carry = haystack[-longest:]
    with path.open("rb") as handle:
        handle.seek(max(0, path.stat().st_size - 65_536))
        footer = handle.read()
    return all(found) and b"PostgreSQL database dump complete" in footer


def pg_restore_toc_has_required_catalog(toc: bytes) -> bool:
    required_patterns = (
        rb"\bTABLE public models\b",
        rb"\bTABLE DATA public models\b",
        rb"\bTABLE public alembic_version\b",
        rb"\bTABLE DATA public alembic_version\b",
    )
    return all(re.search(pattern, toc) for pattern in required_patterns)


def verify_fresh_database_backup(
    path: Path | None,
    expected_sha256: str | None,
    *,
    max_age_hours: float,
) -> dict[str, Any]:
    if max_age_hours <= 0:
        raise MigrationError("--max-backup-age-hours must be positive")
    evidence = original.verify_backup(
        path, expected_sha256, "Fresh external database backup"
    )
    resolved = Path(evidence["path"])
    if int(evidence["bytes"]) <= 0:
        raise MigrationError("External database backup is empty")
    with resolved.open("rb") as backup_handle:
        header = backup_handle.read(16_384)
    plain_markers = (
        b"PostgreSQL database dump",
        b"Dumped from database version",
        b"Dumped by pg_dump version",
    )
    if all(marker in header for marker in plain_markers) and header.lstrip().startswith(
        b"--"
    ):
        if not plain_dump_has_required_catalog(resolved):
            raise MigrationError(
                "Plain database backup lacks a complete ERP models/alembic dump"
            )
        backup_format = "postgresql_plain_sql"
        validation = "strict_pg_dump_header_catalog_and_footer"
    else:
        pg_restore = shutil.which("pg_restore")
        if pg_restore is None:
            raise MigrationError(
                "Non-plain database backup validation requires pg_restore"
            )
        try:
            checked = subprocess.run(
                [pg_restore, "--list", str(resolved)],
                check=False,
                capture_output=True,
                timeout=120,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise MigrationError(
                f"Could not validate database backup with pg_restore: {exc}"
            ) from exc
        if checked.returncode != 0:
            raise MigrationError(
                "External database backup is not a readable pg_dump archive"
            )
        if not pg_restore_toc_has_required_catalog(checked.stdout):
            raise MigrationError(
                "Database archive lacks ERP models/alembic schema and data entries"
            )
        backup_format = (
            "postgresql_custom_archive"
            if header.startswith(b"PGDMP")
            else "postgresql_pg_restore_archive"
        )
        validation = "pg_restore_list"
    modified_at = datetime.fromtimestamp(
        resolved.stat().st_mtime, tz=timezone.utc
    )
    age_seconds = (datetime.now(timezone.utc) - modified_at).total_seconds()
    if age_seconds < -300:
        raise MigrationError("Database backup timestamp is unexpectedly in the future")
    if age_seconds > max_age_hours * 3600:
        raise MigrationError(
            f"Database backup is older than {max_age_hours:g} hours"
        )
    return {
        **evidence,
        "modified_at": modified_at.isoformat(),
        "age_seconds_at_verification": max(0, int(age_seconds)),
        "created_externally": True,
        "backup_format": backup_format,
        "format_validation": validation,
    }


def reject_output_input_aliases(
    *,
    plan_output: Path,
    report_output: Path,
    protected_inputs: Iterable[Path | None],
) -> None:
    outputs = {
        "--plan-output": plan_output.expanduser().resolve(),
        "--report": report_output.expanduser().resolve(),
    }
    protected = {
        path.expanduser().resolve()
        for path in protected_inputs
        if path is not None
    }
    for flag, output in outputs.items():
        if output in protected:
            raise MigrationError(
                f"{flag} must not overwrite a hash-pinned input or database backup"
            )


def enforce_reviewed_counts(args: argparse.Namespace, plan: dict[str, Any]) -> None:
    checks = {
        "--expect-name-updates": (
            args.expect_name_updates,
            plan["summary"]["planned_name_updates"],
        ),
        "--expect-details-updates": (
            args.expect_details_updates,
            plan["summary"]["planned_details_updates"],
        ),
        "--expect-manual-drifts": (
            args.expect_manual_drifts,
            plan["summary"]["manual_name_drifts_skipped"],
        ),
        "--expect-product-conflicts": (
            args.expect_product_conflicts,
            plan["summary"]["product_name_conflicts_skipped"],
        ),
        "--expect-missing-records": (
            args.expect_missing_records,
            plan["summary"]["manifest_missing_records"],
        ),
    }
    missing: list[str] = []
    for flag, (expected, actual) in checks.items():
        if expected is None:
            if args.apply:
                missing.append(flag)
            continue
        if int(expected) != int(actual):
            raise MigrationError(
                f"Reviewed count {flag} changed: expected {expected}, got {actual}"
            )
    if missing:
        raise MigrationError(
            "Apply requires every reviewed count assertion: " + ", ".join(missing)
        )


def acquire_local_apply_locks(db) -> None:
    # The guard is called first.  These transaction-scoped locks make the
    # compile/apply/current-value checks atomic relative to catalog writers.
    db.execute(text("SELECT pg_advisory_xact_lock(727202607)"))
    db.execute(
        text(
            "LOCK TABLE models, model_images, model_sizes, model_colors, model_bom "
            "IN SHARE ROW EXCLUSIVE MODE"
        )
    )


def apply_correction_plan(
    *,
    db,
    plan: dict[str, Any],
    receipt: dict[str, Any],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    if not plan["summary"]["ready_for_apply"]:
        raise MigrationError("Reviewed correction plan has blocking issues")
    models_before = load_models(db)
    by_id = {int(model.id): model for model in models_before}
    created_ids = set(receipt["created_ids"])
    preexisting_ids = set(by_id) - created_ids
    state_before = {
        model_id: model_state_from_orm(model)
        for model_id, model in by_id.items()
    }
    counts_before = original.db_counts(db)
    business_before = original.count_business_tables(db)
    name_updates = 0
    details_updates = 0
    for reviewed_action in plan["actions"]:
        model_id = int(reviewed_action["model_id"])
        model = by_id.get(model_id)
        if model is None:
            raise MigrationError(f"Reviewed target model {model_id} disappeared")
        prior_action = receipt["all_by_id"][model_id]
        current_result = plan_model_correction(
            model_state_from_orm(model),
            action=prior_action,
            created=model_id in created_ids,
            complete_records=manifest["records"],
            manifest=manifest,
            provenance_evidence=receipt["provenance_evidence"],
        )
        if public_model_action(current_result) != reviewed_action:
            raise MigrationError(
                f"Current-value preconditions changed for model {model_id}"
            )
        if reviewed_action["new_name"] is not None:
            if model_id in preexisting_ids:
                raise MigrationError(
                    f"Plan attempted to rename pre-import model {model_id}"
                )
            model.name = reviewed_action["new_name"]
            name_updates += 1
        if reviewed_action["details_changed"]:
            model.details_json = current_result["_details_after"]
            flag_modified(model, "details_json")
            details_updates += 1

    db.flush()
    db.expire_all()
    models_after = load_models(db)
    after_by_id = {int(model.id): model for model in models_after}
    if set(after_by_id) != set(state_before):
        raise MigrationError("Model row set changed during correction")
    counts_after = original.db_counts(db)
    if counts_after != counts_before:
        raise MigrationError("Catalog row counts changed during correction")
    business_after = original.count_business_tables(db)
    if business_after != business_before:
        raise MigrationError("A business-table row count changed during correction")

    expected_names = {
        int(action["model_id"]): action["new_name"]
        for action in plan["actions"]
        if action["new_name"] is not None
    }
    expected_details = {
        int(action["model_id"]): action["details_after_sha256"]
        for action in plan["actions"]
        if action["details_changed"]
    }
    for model_id, before in state_before.items():
        after = model_state_from_orm(after_by_id[model_id])
        if after["code"] != before["code"]:
            raise MigrationError(f"Model {model_id} code changed during correction")
        if after["images"] != before["images"]:
            raise MigrationError(f"Model {model_id} images changed during correction")
        expected_name = expected_names.get(model_id, before["name"])
        if after["name"] != expected_name:
            raise MigrationError(f"Model {model_id} name reconciliation failed")
        before_details_sha = original.object_sha256(before["details_json"])
        after_details_sha = original.object_sha256(after["details_json"])
        if model_id in expected_details:
            if after_details_sha != expected_details[model_id]:
                raise MigrationError(
                    f"Model {model_id} details reconciliation failed"
                )
        elif after_details_sha != before_details_sha:
            raise MigrationError(
                f"Unplanned details_json change on model {model_id}"
            )

    protected_after = [
        after_by_id[model_id] for model_id in sorted(preexisting_ids)
    ]
    protected_after_sha = original.object_sha256(
        original.protected_snapshot(protected_after)
    )
    if (
        protected_after_sha
        != plan["database_preconditions"][
            "protected_preimport_names_images_sha256"
        ]
    ):
        raise MigrationError(
            "Pre-import model name/code/image invariant failed"
        )
    return {
        "updated_models": len(plan["actions"]),
        "name_updates": name_updates,
        "details_updates": details_updates,
        "counts_before": counts_before,
        "counts_after": counts_after,
        "business_counts_before": business_before,
        "business_counts_after": business_after,
        "protected_preimport_names_images_sha256_before": plan[
            "database_preconditions"
        ]["protected_preimport_names_images_sha256"],
        "protected_preimport_names_images_sha256_after": protected_after_sha,
        "all_model_images_unchanged": True,
        "items_or_bom_created": False,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Plan/apply the receipt-linked complete-details correction to "
            "localhost only. Appended old-ERP models or variants require a "
            "separate validated supplemental import."
        )
    )
    parser.add_argument("--prior-apply-plan", required=True, type=Path)
    parser.add_argument("--prior-apply-plan-sha256", required=True)
    parser.add_argument("--prior-apply-report", required=True, type=Path)
    parser.add_argument("--prior-apply-report-sha256", required=True)
    parser.add_argument(
        "--complete-details-manifest",
        required=True,
        type=Path,
        help=(
            "Final combined version-1 manifest with source_model_count, "
            "record_count, completed_at, and records (not the progress file)"
        ),
    )
    parser.add_argument("--complete-details-sha256", required=True)
    parser.add_argument("--plan-output", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--overwrite-output", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-localhost")
    parser.add_argument("--expected-plan-sha256")
    parser.add_argument("--local-db-port", type=int, default=DEFAULT_LOCAL_DB_PORT)
    parser.add_argument("--database-backup", type=Path)
    parser.add_argument("--database-backup-sha256")
    parser.add_argument("--max-backup-age-hours", type=float, default=24.0)
    parser.add_argument("--expect-name-updates", type=int)
    parser.add_argument("--expect-details-updates", type=int)
    parser.add_argument("--expect-manual-drifts", type=int)
    parser.add_argument("--expect-product-conflicts", type=int)
    parser.add_argument("--expect-missing-records", type=int)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    original.preflight_output_paths(
        args.plan_output,
        args.report,
        overwrite=args.overwrite_output,
    )
    reject_output_input_aliases(
        plan_output=args.plan_output,
        report_output=args.report,
        protected_inputs=(
            args.prior_apply_plan,
            args.prior_apply_report,
            args.complete_details_manifest,
            args.database_backup,
        ),
    )
    if args.apply:
        if args.confirm_localhost != APPLY_CONFIRMATION:
            raise MigrationError(
                f"Apply requires --confirm-localhost {APPLY_CONFIRMATION}"
            )
        expected_plan_sha = original.clean(args.expected_plan_sha256).lower()
        if not re.fullmatch(r"[0-9a-f]{64}", expected_plan_sha):
            raise MigrationError(
                "Apply requires the reviewed --expected-plan-sha256"
            )
        backup_evidence = verify_fresh_database_backup(
            args.database_backup,
            args.database_backup_sha256,
            max_age_hours=args.max_backup_age_hours,
        )
    else:
        expected_plan_sha = ""
        backup_evidence = None

    prior_plan, _, prior_plan_file_sha = original.load_json_file(
        args.prior_apply_plan,
        args.prior_apply_plan_sha256,
        "Prior localhost apply plan",
    )
    prior_report, _, prior_report_file_sha = original.load_json_file(
        args.prior_apply_report,
        args.prior_apply_report_sha256,
        "Prior localhost apply report",
    )
    complete_payload, _, complete_file_sha = original.load_json_file(
        args.complete_details_manifest,
        args.complete_details_sha256,
        "Complete old-ERP model details manifest",
    )
    receipt = load_reviewed_receipt(
        prior_plan,
        prior_report,
        plan_file_sha256=prior_plan_file_sha,
        report_file_sha256=prior_report_file_sha,
    )
    manifest = index_complete_manifest(
        complete_payload,
        manifest_file_sha256=complete_file_sha,
    )

    with SessionLocal() as db:
        try:
            database_guard = original.local_database_guard(
                db, expected_port=args.local_db_port
            )
            if args.apply:
                acquire_local_apply_locks(db)
            plan = compile_correction_plan(
                db=db,
                receipt=receipt,
                manifest=manifest,
                database_guard=database_guard,
            )
            enforce_reviewed_counts(args, plan)
            if args.apply:
                if plan["plan_sha256"] != expected_plan_sha:
                    raise MigrationError(
                        "Reviewed correction plan SHA-256 changed: "
                        f"expected {expected_plan_sha}, got {plan['plan_sha256']}"
                    )
                if not plan["summary"]["ready_for_apply"]:
                    raise MigrationError(
                        "Correction plan has blocking issues"
                    )
            original.write_json(
                args.plan_output,
                plan,
                overwrite=args.overwrite_output,
            )
            if args.apply:
                reconciliation = apply_correction_plan(
                    db=db,
                    plan=plan,
                    receipt=receipt,
                    manifest=manifest,
                )
                db.commit()
                report = {
                    "schema_version": SCHEMA_VERSION,
                    "mode": "apply",
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "plan_sha256": plan["plan_sha256"],
                    "summary": plan["summary"],
                    "backup_evidence": backup_evidence,
                    "reconciliation": reconciliation,
                    "database_mutated": bool(plan["actions"]),
                    "media_mutated": False,
                    "production_touched": False,
                }
            else:
                db.rollback()
                report = {
                    "schema_version": SCHEMA_VERSION,
                    "mode": "dry_run",
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "plan_sha256": plan["plan_sha256"],
                    "summary": plan["summary"],
                    "apply_guards": {
                        "confirmation": APPLY_CONFIRMATION,
                        "expected_plan_sha256": plan["plan_sha256"],
                        "fresh_external_database_backup_required": True,
                        "reviewed_counts": {
                            "expect_name_updates": plan["summary"][
                                "planned_name_updates"
                            ],
                            "expect_details_updates": plan["summary"][
                                "planned_details_updates"
                            ],
                            "expect_manual_drifts": plan["summary"][
                                "manual_name_drifts_skipped"
                            ],
                            "expect_product_conflicts": plan["summary"][
                                "product_name_conflicts_skipped"
                            ],
                            "expect_missing_records": plan["summary"][
                                "manifest_missing_records"
                            ],
                        },
                    },
                    "database_mutated": False,
                    "media_mutated": False,
                    "production_touched": False,
                }
            original.write_json(
                args.report,
                report,
                overwrite=args.overwrite_output,
            )
        except Exception:
            db.rollback()
            raise
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
