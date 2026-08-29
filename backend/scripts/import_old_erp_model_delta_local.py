"""Plan and apply the reviewed append-only old-ERP model delta to localhost.

This pass is intentionally separate from ``import_old_erp_models_local``.  The
original import is bound to four immutable full-manifest hashes, so extending
those files would invalidate provenance already stored on thousands of local
catalog rows.

The supplemental pass:

* validates the successful original localhost receipt;
* proves that the current old-ERP lists are an exact append of the frozen
  3,065-model / 5,153-variant sources;
* accepts only reviewed source IDs 3125..3131 and 5581..5590;
* creates missing canonical variant Models with the exact legacy Product as
  the display name when present;
* enriches exact duplicates without changing their code, name, or image row,
  while allowing only a provenance-proven delta-created row that still has
  the importer-assigned legacy Name to be corrected to Product;
* accounts for all 23 prior unlinked quarantine records, enriching only a
  proven exact target and requiring explicit hash review for unresolved rows;
* stores complete legacy metadata and independent delta provenance;
* requires hash-pinned, fully decoded image evidence;
* is a read-only dry run unless every apply guard is supplied.

The script creates or updates only Models, ModelSizes, ModelColors, and
ModelImages.  It never creates BOM, item, stock, order, package, shipment, or
other business data.
"""

from __future__ import annotations

import argparse
import copy
import re
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qs, urlparse

from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import flag_modified

from app.db.session import SessionLocal
from app.models import Model, ModelColor, ModelImage, ModelSize
from scripts import correct_old_erp_models_local as correction
from scripts import import_old_erp_models_local as original


SCHEMA_VERSION = 1
SOURCE_KEY = "old-erp-sewing-model-delta-2026-07-27"
DETAILS_KEY = "old_erp_delta_migration"
QUARANTINE_SOURCE_KEY = "old-erp-sewing-model-quarantine-reconciliation-2026-07-27"
QUARANTINE_DETAILS_KEY = "old_erp_quarantine_reconciliation"
APPLY_CONFIRMATION = "APPLY-REVIEWED-OLD-ERP-MODEL-DELTA-TO-LOCALHOST"
DEFAULT_LOCAL_DB_PORT = original.DEFAULT_LOCAL_DB_PORT

EXPECTED_DELTA_MODEL_IDS = tuple(range(3125, 3132))
EXPECTED_DELTA_VARIANT_IDS = tuple(range(5581, 5591))
EXPECTED_PARENT_BY_VARIANT = {
    5581: 3125,
    5582: 3126,
    5583: 1803,
    5584: 1803,
    5585: 3127,
    5586: 3128,
    5587: 3129,
    5588: 3129,
    5589: 3130,
    5590: 1803,
}
EXPECTED_EXPLICIT_DUPLICATE_MODEL_ID = 3131
EXPECTED_EXPLICIT_DUPLICATE_IDENTITY = "TJ2187|5256"

# These are the exact complete-detail records that were not linked to any
# successful original-import action.  Nineteen appear directly in a reviewed
# quarantine entry.  Four were metadata rows assigned to an identity that was
# later quarantined, so the original plan omitted them from both actions and
# quarantine rows.  Keeping the complete mapping here makes that omission
# impossible to repeat silently.
EXPECTED_QUARANTINE_IDENTITY_BY_MODEL: dict[int, str | None] = {
    63: "TJ2017|1",
    430: "B3189|",
    837: "T4697|",
    1061: "T4697|",
    1204: "XJ3001|",
    1234: "B3189|",
    1262: "TJ2017|1",
    1269: "XJ3001|",
    1270: "TJ2026|2",
    1296: "TJ2017|1",
    1334: "SJ4002|1",
    1345: "PJ1003|1",
    1386: "XJ3016|1",
    1400: "TJ2016|1",
    1404: "XJ3024V|264",
    1425: "TJ2000|425",
    1441: "TJ2000|425",
    1462: "PJ1030|474",
    1464: "XJ3024V|264",
    1467: "SJ4022|556",
    1523: "PJ1030|474",
    1560: "SJ4022|556",
    1683: None,
}
EXPECTED_HIDDEN_QUARANTINE_METADATA = {
    1262: "TJ2017|1",
    1270: "TJ2026|2",
    1296: "TJ2017|1",
    1400: "TJ2016|1",
}

MODEL_COMPARE_FIELDS = (
    "code",
    "company",
    "detail_url",
    "model_variant",
    "name",
    "old_model_id",
    "product",
    "style",
)
VARIANT_COMPARE_FIELDS = (
    "color",
    "design",
    "detail_url",
    "embroidery",
    "old_variant_id",
    "sew_model_code",
    "sew_model_name",
    "thermal_print",
    "variant_code",
)
VARIANT_IMAGE_FLAGS = {
    "main_image": "has_main_image",
    "thermal_image": "has_thermal_image",
    "embroidery_image": "has_embroidery_image",
    "design_image": "has_design_image",
}
VARIANT_IMAGE_TYPES = {
    "main_image": "material",
    "thermal_image": "pattern",
    "embroidery_image": "pattern",
    "design_image": "pattern",
}
VARIANT_IMAGE_ROLES = {
    "main_image": "delta_variant_main",
    "thermal_image": "delta_variant_thermal",
    "embroidery_image": "delta_variant_embroidery",
    "design_image": "delta_variant_design",
}

MigrationError = original.MigrationError


def require_object(value: object, label: str) -> dict[str, Any]:
    return correction.require_object(value, label)


def require_list(value: object, label: str) -> list[Any]:
    return correction.require_list(value, label)


def require_int(value: object, label: str, *, positive: bool = False) -> int:
    return correction.require_int(value, label, positive=positive)


def sha256_value(value: object, label: str) -> str:
    result = original.clean(value).lower()
    if not re.fullmatch(r"[0-9a-f]{64}", result):
        raise MigrationError(f"{label} is not a SHA-256")
    return result


def _project(row: dict[str, Any], fields: Iterable[str]) -> dict[str, Any]:
    return {field: copy.deepcopy(row.get(field)) for field in fields}


def flatten_current_list(
    payload: object,
    *,
    label: str,
    id_field: str,
) -> dict[int, dict[str, Any]]:
    """Validate one paginated current-list capture and return indexed rows."""

    manifest = require_object(payload, label)
    if require_int(manifest.get("version"), f"{label}.version") != 1:
        raise MigrationError(f"{label} has an unsupported version")
    pages = require_list(manifest.get("pages"), f"{label}.pages")
    page_count = require_int(manifest.get("page_count"), f"{label}.page_count", positive=True)
    record_count = require_int(
        manifest.get("record_count"),
        f"{label}.record_count",
        positive=True,
    )
    if page_count != len(pages):
        raise MigrationError(f"{label} page_count does not match pages")

    flattened: list[dict[str, Any]] = []
    seen_pages: set[int] = set()
    for position, raw_page in enumerate(pages, start=1):
        page = require_object(raw_page, f"{label}.pages[{position}]")
        page_number = require_int(
            page.get("page"),
            f"{label}.pages[{position}].page",
            positive=True,
        )
        if page_number in seen_pages:
            raise MigrationError(f"{label} repeats page {page_number}")
        seen_pages.add(page_number)
        for row_position, raw_row in enumerate(
            require_list(page.get("rows"), f"{label}.pages[{position}].rows"),
            start=1,
        ):
            flattened.append(
                require_object(
                    raw_row,
                    f"{label}.pages[{position}].rows[{row_position}]",
                )
            )
    if seen_pages != set(range(1, page_count + 1)):
        raise MigrationError(f"{label} page sequence is incomplete")
    if len(flattened) != record_count:
        raise MigrationError(f"{label} record_count does not match flattened rows")
    return original.index_rows(flattened, id_field, label)


def prove_append_only(
    *,
    prior_models: dict[int, dict[str, Any]],
    prior_variants: dict[int, dict[str, Any]],
    current_models: dict[int, dict[str, Any]],
    current_variants: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    """Prove exact common-row equality and the reviewed 7/10 append scope."""

    for source_id, prior in sorted(prior_models.items()):
        current = current_models.get(source_id)
        if current is None:
            raise MigrationError(f"Current models list removed old_model_id {source_id}")
        if _project(prior, MODEL_COMPARE_FIELDS) != _project(current, MODEL_COMPARE_FIELDS):
            raise MigrationError(
                f"Current models list changed prior non-image data for old_model_id {source_id}"
            )
    for source_id, prior in sorted(prior_variants.items()):
        current = current_variants.get(source_id)
        if current is None:
            raise MigrationError(f"Current variants list removed old_variant_id {source_id}")
        if _project(prior, VARIANT_COMPARE_FIELDS) != _project(
            current,
            VARIANT_COMPARE_FIELDS,
        ):
            raise MigrationError(
                "Current variants list changed prior non-image data for "
                f"old_variant_id {source_id}"
            )

    delta_model_ids = sorted(set(current_models) - set(prior_models))
    delta_variant_ids = sorted(set(current_variants) - set(prior_variants))
    if delta_model_ids != list(EXPECTED_DELTA_MODEL_IDS):
        raise MigrationError(
            "Reviewed delta model IDs changed: "
            f"expected {list(EXPECTED_DELTA_MODEL_IDS)}, got {delta_model_ids}"
        )
    if delta_variant_ids != list(EXPECTED_DELTA_VARIANT_IDS):
        raise MigrationError(
            "Reviewed delta variant IDs changed: "
            f"expected {list(EXPECTED_DELTA_VARIANT_IDS)}, got {delta_variant_ids}"
        )
    if min(delta_model_ids) <= max(prior_models):
        raise MigrationError("Reviewed model delta is not append-only by source ID")
    if min(delta_variant_ids) <= max(prior_variants):
        raise MigrationError("Reviewed variant delta is not append-only by source ID")

    return {
        "models": {source_id: copy.deepcopy(current_models[source_id]) for source_id in delta_model_ids},
        "variants": {
            source_id: copy.deepcopy(current_variants[source_id])
            for source_id in delta_variant_ids
        },
        "summary": {
            "prior_model_rows": len(prior_models),
            "current_model_rows": len(current_models),
            "delta_model_rows": len(delta_model_ids),
            "prior_variant_rows": len(prior_variants),
            "current_variant_rows": len(current_variants),
            "delta_variant_rows": len(delta_variant_ids),
            "delta_model_ids": delta_model_ids,
            "delta_variant_ids": delta_variant_ids,
            "common_non_image_rows_unchanged": True,
        },
    }


def canonical_quarantine_identity(raw_identity: object) -> str | None:
    """Convert a reviewed original-plan quarantine label to a DB identity."""

    identity = original.clean(raw_identity)
    if identity.startswith("MALFORMED-MASTER-"):
        return None
    if "|" in identity:
        base, variant = original.identity_parts(identity)
        canonical = original.identity_key(base, variant)
        if canonical != identity:
            raise MigrationError(
                f"Prior quarantine identity is not canonical: {identity!r}"
            )
        return canonical
    base = original.base_key(identity)
    if not base:
        raise MigrationError(f"Prior quarantine identity is unusable: {identity!r}")
    return original.identity_key(base, "")


def build_quarantine_evidence(
    *,
    prior_plan: dict[str, Any],
    receipt: dict[str, Any],
    prior_models: dict[int, dict[str, Any]],
    prior_variants: dict[int, dict[str, Any]],
    prior_sizes: dict[int, dict[str, Any]],
    complete_manifest: dict[str, Any],
) -> dict[str, Any]:
    """Account for every prior complete record omitted by reviewed actions.

    The original importer intentionally quarantined conflicting images and
    other conflicting variant evidence.  This pass may attach those records
    only to a DB row whose canonical ``details_json.general`` identity is an
    exact match.  Base-family siblings are evidence of a family, not evidence
    of the missing variant, and are therefore never selected.
    """

    raw_quarantines = require_list(
        prior_plan.get("quarantines"),
        "Prior apply quarantines",
    )
    reviewed_quarantine_sha = sha256_value(
        prior_plan.get("quarantine_sha256"),
        "Prior apply quarantine_sha256",
    )
    actual_quarantine_sha = original.object_sha256(raw_quarantines)
    if actual_quarantine_sha != reviewed_quarantine_sha:
        raise MigrationError("Prior apply quarantine list hash changed")

    linked_source_ids = {
        require_int(value, "Receipt linked old_model_id", positive=True)
        for value in require_object(
            receipt["provenance_evidence"].get("model_records"),
            "Receipt model-record evidence",
        )
    }
    unlinked_ids = sorted(set(prior_models) - linked_source_ids)
    expected_unlinked = sorted(EXPECTED_QUARANTINE_IDENTITY_BY_MODEL)
    if unlinked_ids != expected_unlinked:
        raise MigrationError(
            "Prior unlinked complete-record scope changed: "
            f"expected {expected_unlinked}, got {unlinked_ids}"
        )
    if set(prior_sizes) != set(prior_models):
        raise MigrationError("Prior sizes/details source no longer covers every frozen model")

    quarantine_by_identity: dict[str | None, list[dict[str, Any]]] = defaultdict(list)
    direct_identity_by_model: dict[int, str | None] = {}
    for position, raw in enumerate(raw_quarantines, start=1):
        row = require_object(raw, f"Prior apply quarantine {position}")
        identity = canonical_quarantine_identity(row.get("identity"))
        model_ids = [
            require_int(
                value,
                f"Prior apply quarantine {position}.old_model_ids",
                positive=True,
            )
            for value in require_list(
                row.get("old_model_ids"),
                f"Prior apply quarantine {position}.old_model_ids",
            )
        ]
        variant_ids = [
            require_int(
                value,
                f"Prior apply quarantine {position}.old_variant_ids",
                positive=True,
            )
            for value in require_list(
                row.get("old_variant_ids"),
                f"Prior apply quarantine {position}.old_variant_ids",
            )
        ]
        if any(source_id not in prior_models for source_id in model_ids):
            raise MigrationError(
                f"Prior quarantine {position} references an unknown model source"
            )
        if any(source_id not in prior_variants for source_id in variant_ids):
            raise MigrationError(
                f"Prior quarantine {position} references an unknown variant source"
            )
        if not original.clean(row.get("reason")):
            raise MigrationError(f"Prior quarantine {position} has no reason")
        require_list(
            row.get("conflicts"),
            f"Prior apply quarantine {position}.conflicts",
        )
        public_row = copy.deepcopy(row)
        public_row["canonical_identity"] = identity
        quarantine_by_identity[identity].append(public_row)
        for source_id in model_ids:
            if source_id not in EXPECTED_QUARANTINE_IDENTITY_BY_MODEL:
                continue
            if source_id in direct_identity_by_model:
                raise MigrationError(
                    f"Unlinked old_model_id {source_id} appears in multiple quarantines"
                )
            direct_identity_by_model[source_id] = identity

    if set(EXPECTED_HIDDEN_QUARANTINE_METADATA) & set(direct_identity_by_model):
        raise MigrationError(
            "Metadata-to-quarantine omissions unexpectedly became direct quarantines"
        )
    expected_direct_ids = (
        set(EXPECTED_QUARANTINE_IDENTITY_BY_MODEL)
        - set(EXPECTED_HIDDEN_QUARANTINE_METADATA)
    )
    if set(direct_identity_by_model) != expected_direct_ids:
        raise MigrationError("Direct unlinked quarantine coverage changed")
    for source_id, identity in sorted(direct_identity_by_model.items()):
        if EXPECTED_QUARANTINE_IDENTITY_BY_MODEL[source_id] != identity:
            raise MigrationError(
                f"Unlinked old_model_id {source_id} changed quarantine identity"
            )

    # Prove the four historical metadata rows still point only at their
    # reviewed quarantined identity.  They are not inferred from a sibling DB
    # row or from a merely similar name.
    for source_id, identity in sorted(EXPECTED_HIDDEN_QUARANTINE_METADATA.items()):
        if identity not in quarantine_by_identity:
            raise MigrationError(
                f"Hidden metadata old_model_id {source_id} lost quarantine {identity}"
            )
        base, variant = original.identity_parts(identity)
        row = prior_models[source_id]
        code_key = original.base_key(row.get("code"))
        if code_key not in {base, f"{base}{variant}"}:
            raise MigrationError(
                f"Hidden metadata old_model_id {source_id} no longer proves {identity}"
            )
        if code_key == base and original.variant_key(row.get("model_variant")) != variant:
            raise MigrationError(
                f"Hidden metadata old_model_id {source_id} variant evidence changed"
            )

    complete_records = complete_manifest["records"]
    grouped_ids: dict[str | None, list[int]] = defaultdict(list)
    for source_id, identity in sorted(EXPECTED_QUARANTINE_IDENTITY_BY_MODEL.items()):
        record = complete_records.get(source_id)
        if record is None:
            raise MigrationError(
                f"Complete-details manifest lacks unlinked old_model_id {source_id}"
            )
        correction.validate_complete_record_receipt_evidence(
            record,
            prior_models[source_id],
        )
        if identity is not None and identity not in quarantine_by_identity:
            raise MigrationError(
                f"Unlinked old_model_id {source_id} has no reviewed quarantine identity"
            )
        grouped_ids[identity].append(source_id)

    groups: list[dict[str, Any]] = []
    for identity, model_ids in sorted(
        grouped_ids.items(),
        key=lambda pair: (pair[0] is None, pair[0] or ""),
    ):
        entries = quarantine_by_identity.get(identity) or []
        variant_ids = sorted(
            {
                require_int(value, "Quarantine old_variant_id", positive=True)
                for entry in entries
                for value in require_list(
                    entry.get("old_variant_ids"),
                    "Quarantine old_variant_ids",
                )
            }
        )
        groups.append(
            {
                "identity": identity,
                "old_model_ids": sorted(model_ids),
                "old_variant_ids": variant_ids,
                "master_rows": [
                    copy.deepcopy(prior_models[source_id])
                    for source_id in sorted(model_ids)
                ],
                "variant_rows": [
                    copy.deepcopy(prior_variants[source_id])
                    for source_id in variant_ids
                ],
                "size_rows": {
                    source_id: copy.deepcopy(prior_sizes[source_id])
                    for source_id in sorted(model_ids)
                },
                "complete_records": [
                    copy.deepcopy(complete_records[source_id])
                    for source_id in sorted(model_ids)
                ],
                "quarantine_entries": copy.deepcopy(entries),
            }
        )

    logical_identities = sorted(
        identity for identity in grouped_ids if identity is not None
    )
    return {
        "reviewed_quarantine_sha256": reviewed_quarantine_sha,
        "groups": groups,
        "summary": {
            "unlinked_complete_records": len(unlinked_ids),
            "logical_quarantine_identities": len(logical_identities),
            "malformed_unlinked_records": len(grouped_ids.get(None) or []),
            "hidden_metadata_to_quarantine_records": len(
                EXPECTED_HIDDEN_QUARANTINE_METADATA
            ),
            "unlinked_old_model_ids": unlinked_ids,
            "logical_identities": logical_identities,
            "all_unlinked_records_accounted_for": True,
        },
    }


def detail_variant_id(row: dict[str, Any], label: str) -> int | None:
    source_order = require_int(row.get("source_order"), f"{label}.source_order")
    name = original.clean(row.get("name"))
    detail_url = original.clean(row.get("detail_url"))
    if source_order == 0 and not name and not detail_url:
        return None
    if source_order <= 0:
        raise MigrationError(f"{label} has a non-positive source order")
    parsed = urlparse(detail_url)
    values = parse_qs(parsed.query, keep_blank_values=True).get("id") or []
    if len(values) != 1 or not values[0].isdigit():
        raise MigrationError(f"{label} has an invalid detail_url")
    source_id = int(values[0])
    if original.variant_key(name) != str(source_id):
        raise MigrationError(f"{label} name and detail_url identify different variants")
    return source_id


def resolve_reviewed_parents(
    *,
    current_models: dict[int, dict[str, Any]],
    delta_variants: dict[int, dict[str, Any]],
) -> dict[int, dict[str, Any]]:
    """Resolve every reviewed variant to one exact source master."""

    result: dict[int, dict[str, Any]] = {}
    for old_variant_id, variant in sorted(delta_variants.items()):
        expected_parent_id = EXPECTED_PARENT_BY_VARIANT.get(old_variant_id)
        if expected_parent_id is None:
            raise MigrationError(f"Variant {old_variant_id} has no reviewed parent")
        parent = current_models.get(expected_parent_id)
        if parent is None:
            raise MigrationError(
                f"Variant {old_variant_id} reviewed parent {expected_parent_id} is missing"
            )
        candidates = [
            row
            for row in current_models.values()
            if original.base_key(row.get("code"))
            == original.base_key(variant.get("sew_model_code"))
            and original.normalized_value(row.get("name"))
            == original.normalized_value(variant.get("sew_model_name"))
        ]
        if len(candidates) != 1 or int(candidates[0]["old_model_id"]) != expected_parent_id:
            raise MigrationError(
                f"Variant {old_variant_id} no longer has one exact code/name parent"
            )
        result[old_variant_id] = copy.deepcopy(parent)
    return result


def validate_complete_delta_records(
    *,
    complete_manifest: dict[str, Any],
    current_models: dict[int, dict[str, Any]],
    delta_variants: dict[int, dict[str, Any]],
    parents: dict[int, dict[str, Any]],
) -> dict[int, dict[str, Any]]:
    if not complete_manifest["is_complete"]:
        raise MigrationError("Complete-details manifest is partial")
    if complete_manifest["source_model_count"] != len(current_models):
        raise MigrationError(
            "Complete-details manifest does not cover the current models capture"
        )
    records = complete_manifest["records"]
    required_record_ids = set(EXPECTED_DELTA_MODEL_IDS) | {
        int(parent["old_model_id"]) for parent in parents.values()
    }
    missing = sorted(required_record_ids - set(records))
    if missing:
        raise MigrationError(
            f"Complete-details manifest lacks reviewed parent/model IDs {missing}"
        )

    delta_records: dict[int, dict[str, Any]] = {}
    for old_model_id in sorted(required_record_ids):
        record = copy.deepcopy(records[old_model_id])
        current = current_models[old_model_id]
        list_metadata = require_object(
            record.get("list_metadata"),
            f"Complete record {old_model_id}.list_metadata",
        )
        if _project(list_metadata, (*MODEL_COMPARE_FIELDS, "has_image")) != _project(
            current,
            (*MODEL_COMPARE_FIELDS, "has_image"),
        ):
            raise MigrationError(
                f"Complete record {old_model_id} differs from current list evidence"
            )
        delta_records[old_model_id] = record

    expected_children: dict[int, set[int]] = defaultdict(set)
    for old_variant_id, parent in parents.items():
        parent_id = int(parent["old_model_id"])
        if parent_id in EXPECTED_DELTA_MODEL_IDS:
            expected_children[parent_id].add(old_variant_id)

    for old_model_id in EXPECTED_DELTA_MODEL_IDS:
        extension = require_object(
            delta_records[old_model_id].get("new_source_extension"),
            f"Complete record {old_model_id}.new_source_extension",
        )
        seen_children: set[int] = set()
        for position, raw_variant in enumerate(
            require_list(
                extension.get("variants"),
                f"Complete record {old_model_id}.new_source_extension.variants",
            ),
            start=1,
        ):
            variant_row = require_object(
                raw_variant,
                f"Complete record {old_model_id} variant {position}",
            )
            source_id = detail_variant_id(
                variant_row,
                f"Complete record {old_model_id} variant {position}",
            )
            if source_id is None:
                continue
            current_variant = delta_variants.get(source_id)
            if current_variant is None:
                raise MigrationError(
                    f"Complete record {old_model_id} references non-delta variant {source_id}"
                )
            if original.clean(variant_row.get("name")) != original.clean(
                current_variant.get("variant_code")
            ):
                raise MigrationError(
                    f"Complete record {old_model_id} variant {source_id} code changed"
                )
            for field in ("color", "design"):
                if original.clean(variant_row.get(field)) != original.clean(
                    current_variant.get(field)
                ):
                    raise MigrationError(
                        f"Complete record {old_model_id} variant {source_id} {field} changed"
                    )
            if bool(variant_row.get("has_image")) != bool(
                current_variant.get("has_main_image")
            ):
                raise MigrationError(
                    f"Complete record {old_model_id} variant {source_id} image flag changed"
                )
            seen_children.add(source_id)
        if seen_children != expected_children.get(old_model_id, set()):
            raise MigrationError(
                f"Complete record {old_model_id} variant scope changed: "
                f"expected {sorted(expected_children.get(old_model_id, set()))}, "
                f"got {sorted(seen_children)}"
            )
    return delta_records


def _media_source_files(
    manifest: dict[str, Any],
    *,
    current_models_sha256: str,
    current_variants_sha256: str,
    complete_details_sha256: str,
) -> None:
    source_files = require_object(
        manifest.get("source_files"),
        "Delta image manifest.source_files",
    )
    expected = {
        "models": current_models_sha256,
        "variants": current_variants_sha256,
        "complete_details": complete_details_sha256,
    }
    for key, digest in expected.items():
        row = require_object(
            source_files.get(key),
            f"Delta image manifest.source_files.{key}",
        )
        if sha256_value(
            row.get("sha256"),
            f"Delta image manifest.source_files.{key}.sha256",
        ) != digest:
            raise MigrationError(
                f"Delta image manifest refers to a different {key} source"
            )


def _image_manifest_object(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": row.get("relative_path"),
        "sha256": row.get("decoded_sha256"),
        "bytes": row.get("decoded_bytes"),
        "detected_mime": row.get("actual_media_type"),
    }


def validate_delta_media(
    payload: object,
    *,
    media_root: Path,
    max_image_bytes: int,
    current_models_sha256: str,
    current_variants_sha256: str,
    complete_details_sha256: str,
) -> dict[str, Any]:
    manifest = require_object(payload, "Delta image manifest")
    if require_int(manifest.get("version"), "Delta image manifest.version") != 1:
        raise MigrationError("Unsupported delta image manifest version")
    _media_source_files(
        manifest,
        current_models_sha256=current_models_sha256,
        current_variants_sha256=current_variants_sha256,
        complete_details_sha256=complete_details_sha256,
    )
    model_ids = [
        require_int(value, "Delta image manifest.delta_model_ids", positive=True)
        for value in require_list(
            manifest.get("delta_model_ids"),
            "Delta image manifest.delta_model_ids",
        )
    ]
    variant_ids = [
        require_int(value, "Delta image manifest.delta_variant_ids", positive=True)
        for value in require_list(
            manifest.get("delta_variant_ids"),
            "Delta image manifest.delta_variant_ids",
        )
    ]
    if model_ids != list(EXPECTED_DELTA_MODEL_IDS):
        raise MigrationError("Delta image manifest model IDs changed")
    if variant_ids != list(EXPECTED_DELTA_VARIANT_IDS):
        raise MigrationError("Delta image manifest variant IDs changed")

    model_rows: dict[int, dict[str, Any]] = {}
    for position, raw in enumerate(
        require_list(manifest.get("model_images"), "Delta image manifest.model_images"),
        start=1,
    ):
        row = require_object(raw, f"Delta image manifest.model_images[{position}]")
        source_id = require_int(
            row.get("old_model_id"),
            f"Delta image manifest.model_images[{position}].old_model_id",
            positive=True,
        )
        if source_id in model_rows:
            raise MigrationError(f"Delta image manifest repeats model image {source_id}")
        model_rows[source_id] = row

    absence_rows: dict[int, dict[str, Any]] = {}
    for position, raw in enumerate(
        require_list(
            manifest.get("model_image_absences"),
            "Delta image manifest.model_image_absences",
        ),
        start=1,
    ):
        row = require_object(
            raw,
            f"Delta image manifest.model_image_absences[{position}]",
        )
        source_id = require_int(
            row.get("old_model_id"),
            f"Delta image manifest.model_image_absences[{position}].old_model_id",
            positive=True,
        )
        if source_id in absence_rows:
            raise MigrationError(f"Delta image manifest repeats absence {source_id}")
        if row.get("detail_page_model_image_present") is not False:
            raise MigrationError(f"Model {source_id} absence is not explicit")
        if not original.clean(row.get("reason")):
            raise MigrationError(f"Model {source_id} absence has no reviewed reason")
        absence_rows[source_id] = row

    if set(model_rows) != set(EXPECTED_DELTA_MODEL_IDS) - {
        EXPECTED_EXPLICIT_DUPLICATE_MODEL_ID
    }:
        raise MigrationError("Delta image manifest model image coverage changed")
    if set(absence_rows) != {EXPECTED_EXPLICIT_DUPLICATE_MODEL_ID}:
        raise MigrationError("Delta image manifest reviewed absence scope changed")

    variant_rows: dict[int, dict[str, Any]] = {}
    for position, raw in enumerate(
        require_list(
            manifest.get("variant_images"),
            "Delta image manifest.variant_images",
        ),
        start=1,
    ):
        row = require_object(raw, f"Delta image manifest.variant_images[{position}]")
        source_id = require_int(
            row.get("old_variant_id"),
            f"Delta image manifest.variant_images[{position}].old_variant_id",
            positive=True,
        )
        if source_id in variant_rows:
            raise MigrationError(f"Delta image manifest repeats variant image {source_id}")
        variant_rows[source_id] = row
    if set(variant_rows) != set(EXPECTED_DELTA_VARIANT_IDS):
        raise MigrationError("Delta image manifest variant image coverage changed")

    model_specs: dict[int, dict[str, Any]] = {}
    variant_specs: dict[int, dict[str, Any]] = {}
    for source_id, row in sorted(model_rows.items()):
        spec = original.validate_image_object(
            _image_manifest_object(row),
            media_root=media_root,
            role="delta_model",
            max_bytes=max_image_bytes,
            decode=True,
        )
        if spec is None:
            raise MigrationError(f"Model {source_id} validated image disappeared")
        model_specs[source_id] = spec
    for source_id, row in sorted(variant_rows.items()):
        spec = original.validate_image_object(
            _image_manifest_object(row),
            media_root=media_root,
            role="delta_variant_main",
            max_bytes=max_image_bytes,
            decode=True,
        )
        if spec is None:
            raise MigrationError(f"Variant {source_id} validated image disappeared")
        variant_specs[source_id] = spec

    return {
        "models": model_specs,
        "variants": variant_specs,
        "model_evidence": copy.deepcopy(model_rows),
        "variant_evidence": copy.deepcopy(variant_rows),
        "absences": copy.deepcopy(absence_rows),
        "summary": {
            "validated_model_images": len(model_specs),
            "reviewed_model_image_absences": len(absence_rows),
            "validated_variant_images": len(variant_specs),
            "all_decoded_files_hash_verified": True,
        },
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


def delta_provenance(model: Model) -> dict[str, Any] | None:
    details = model.details_json if isinstance(model.details_json, dict) else {}
    value = details.get(DETAILS_KEY)
    return value if isinstance(value, dict) else None


def is_delta_created(model: Model) -> bool:
    value = delta_provenance(model)
    return bool(
        value
        and original.clean(value.get("source_key")) == SOURCE_KEY
        and value.get("created_by_delta") is True
    )


def validate_prior_database_scope(
    models: list[Model],
    receipt: dict[str, Any],
) -> tuple[list[Model], list[Model]]:
    delta_created = [model for model in models if is_delta_created(model)]
    prior_scope = [model for model in models if not is_delta_created(model)]
    correction.validate_receipt_database_shape(prior_scope, receipt)
    by_id = {int(model.id): model for model in prior_scope}
    for model_id, action in sorted(receipt["all_by_id"].items()):
        model = by_id.get(int(model_id))
        if model is None:
            raise MigrationError(f"Prior receipt target {model_id} disappeared")
        correction.validate_current_provenance(
            model.details_json,
            action,
            receipt["provenance_evidence"],
        )
    return prior_scope, delta_created


def sizes_from_record(record: dict[str, Any]) -> list[dict[str, Any]]:
    extension = require_object(
        record.get("new_source_extension"),
        f"Complete record {record['old_model_id']}.new_source_extension",
    )
    result: dict[str, dict[str, Any]] = {}
    for position, raw in enumerate(
        require_list(
            extension.get("sizes"),
            f"Complete record {record['old_model_id']} sizes",
        ),
        start=1,
    ):
        row = require_object(raw, f"Complete record {record['old_model_id']} size {position}")
        source_order = require_int(
            row.get("source_order"),
            f"Complete record {record['old_model_id']} size {position}.source_order",
            positive=True,
        )
        size = original.clean(row.get("size"))
        if not size:
            raise MigrationError(
                f"Complete record {record['old_model_id']} size {source_order} is blank"
            )
        key = original.normalized_value(size)
        if key in result:
            raise MigrationError(
                f"Complete record {record['old_model_id']} repeats size {size!r}"
            )
        result[key] = {"size": size, "measurement_json": None}
    return sorted(result.values(), key=lambda row: original.normalized_value(row["size"]))


def reviewed_sizes_for_parent(
    *,
    parent_id: int,
    record: dict[str, Any],
    evidence: dict[str, Any],
) -> list[dict[str, Any]]:
    """Use current-detail sizes for appended parents and frozen sizes otherwise."""

    if isinstance(record.get("new_source_extension"), dict):
        return sizes_from_record(record)
    prior_row = evidence["prior_models"].get(parent_id)
    prior_sizes = evidence["prior_sizes"].get(parent_id)
    if prior_row is None or prior_sizes is None:
        raise MigrationError(
            f"Reviewed parent {parent_id} has no authenticated size evidence"
        )
    return original.sizes_from_masters(
        [prior_row],
        {parent_id: prior_sizes},
    )


def general_patch(
    record: dict[str, Any],
    *,
    model_no: str,
    variant_no: str,
) -> dict[str, Any]:
    general = require_object(
        record.get("general"),
        f"Complete record {record['old_model_id']}.general",
    )
    result: dict[str, Any] = {
        "model_no": model_no,
        "variant_no": variant_no,
    }
    for source_field, target_field in correction.GENERAL_TO_DETAILS.items():
        value = general.get(source_field)
        if isinstance(value, bool):
            result[target_field] = value
        elif original.clean(value):
            result[target_field] = original.clean(value)
    return result


def sanitized_complete_record(
    record: dict[str, Any],
    *,
    media_evidence: dict[str, Any] | None,
) -> dict[str, Any]:
    result = copy.deepcopy(record)
    raw_extension = result.get("new_source_extension")
    if raw_extension is None:
        return result
    extension = require_object(
        raw_extension,
        f"Complete record {record['old_model_id']}.new_source_extension",
    )
    raw_data_url = original.clean(extension.pop("primary_image_data_url", ""))
    extension["primary_image_capture"] = {
        "raw_capture_sha256": original.object_sha256(raw_data_url) if raw_data_url else None,
        "raw_capture_was_truncated": raw_data_url.endswith("[Truncated]"),
        "validated_media": copy.deepcopy(media_evidence),
    }
    result["new_source_extension"] = extension
    return result


def provenance_payload(
    *,
    identity: str,
    master_row: dict[str, Any],
    variant_row: dict[str, Any] | None,
    complete_record: dict[str, Any],
    source_files: dict[str, str],
    media_evidence: dict[str, Any] | None,
    variant_media_evidence: dict[str, Any] | None,
    created_by_delta: bool,
) -> dict[str, Any]:
    return {
        "source_key": SOURCE_KEY,
        "source_files": dict(sorted(source_files.items())),
        "identity": identity,
        "created_by_delta": created_by_delta,
        "master_record": copy.deepcopy(master_row),
        "variant_record": copy.deepcopy(variant_row),
        "complete_record": sanitized_complete_record(
            complete_record,
            media_evidence=media_evidence,
        ),
        "validated_images": {
            "model": copy.deepcopy(media_evidence),
            "variant": copy.deepcopy(variant_media_evidence),
        },
    }


def merge_delta_provenance(
    details: dict[str, Any],
    incoming: dict[str, Any],
) -> None:
    current = details.get(DETAILS_KEY)
    if current is None:
        details[DETAILS_KEY] = copy.deepcopy(incoming)
        return
    if not isinstance(current, dict):
        raise MigrationError(f"Existing {DETAILS_KEY} is not an object")
    if original.clean(current.get("source_key")) != SOURCE_KEY:
        raise MigrationError(f"Existing {DETAILS_KEY} has an unexpected owner")
    if current != incoming:
        raise MigrationError(
            f"Existing {DETAILS_KEY} disagrees with reviewed delta evidence"
        )


def details_after(
    current_details: object,
    *,
    patch: dict[str, Any],
    provenance: dict[str, Any],
    paid_operations: list[dict[str, Any]],
) -> dict[str, Any]:
    details = copy.deepcopy(current_details) if isinstance(current_details, dict) else {}
    general = details.get("general")
    if not isinstance(general, dict):
        general = {}
    for key, value in patch.items():
        if value in (None, ""):
            continue
        if general.get(key) in (None, ""):
            general[key] = copy.deepcopy(value)
    details["general"] = general
    if (
        not isinstance(details.get("paid_operations"), list)
        and not isinstance(details.get("paidOperations"), list)
    ):
        details["paid_operations"] = copy.deepcopy(paid_operations)
    merge_delta_provenance(details, provenance)
    return details


def merge_quarantine_provenance(
    details: dict[str, Any],
    incoming: dict[str, Any],
) -> None:
    current = details.get(QUARANTINE_DETAILS_KEY)
    if current is None:
        details[QUARANTINE_DETAILS_KEY] = copy.deepcopy(incoming)
        return
    if not isinstance(current, dict):
        raise MigrationError(f"Existing {QUARANTINE_DETAILS_KEY} is not an object")
    if original.clean(current.get("source_key")) != QUARANTINE_SOURCE_KEY:
        raise MigrationError(
            f"Existing {QUARANTINE_DETAILS_KEY} has an unexpected owner"
        )
    if current != incoming:
        raise MigrationError(
            f"Existing {QUARANTINE_DETAILS_KEY} disagrees with reviewed evidence"
        )


def exact_complete_consensus(
    records: list[dict[str, Any]],
    field: str,
) -> tuple[str, list[str]]:
    values = correction.unique_exact_values(
        original.meaningful(record["general"].get(field))
        for record in records
        if original.meaningful(record["general"].get(field))
    )
    if len(values) == 1:
        return str(values[0]), []
    if len(values) > 1:
        return "", [str(value) for value in values]
    return "", []


def quarantine_provenance_payload(
    *,
    group: dict[str, Any],
    complete_manifest: dict[str, Any],
    source_files: dict[str, str],
    reviewed_quarantine_sha256: str,
) -> dict[str, Any]:
    records = require_list(
        group.get("complete_records"),
        "Quarantine group complete_records",
    )
    return {
        "source_key": QUARANTINE_SOURCE_KEY,
        "source_files": dict(sorted(source_files.items())),
        "reviewed_quarantine_sha256": reviewed_quarantine_sha256,
        "identity": group.get("identity"),
        "old_model_ids": copy.deepcopy(group["old_model_ids"]),
        "old_variant_ids": copy.deepcopy(group["old_variant_ids"]),
        "master_records": copy.deepcopy(group["master_rows"]),
        "variant_records": copy.deepcopy(group["variant_rows"]),
        "sizes_and_details": {
            str(source_id): copy.deepcopy(value)
            for source_id, value in sorted(group["size_rows"].items())
        },
        "quarantine_entries": copy.deepcopy(group["quarantine_entries"]),
        "complete_sections": correction.complete_sections_payload(
            records,
            complete_manifest,
        ),
        "name_and_images_preserved": True,
    }


def plan_quarantine_existing_action(
    model: Model,
    *,
    group: dict[str, Any],
    complete_manifest: dict[str, Any],
    source_files: dict[str, str],
    reviewed_quarantine_sha256: str,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Fill only missing fields on one exact, already-existing identity."""

    identity = original.clean(group.get("identity"))
    if not identity or original.db_identity(model) != identity:
        raise MigrationError(
            f"Quarantine target {model.id} does not prove identity {identity!r}"
        )
    if not isinstance(model.details_json, dict):
        raise MigrationError(
            f"Exact quarantine target {model.id} details_json is not an object"
        )

    records = [
        require_object(value, "Quarantine complete record")
        for value in require_list(
            group.get("complete_records"),
            "Quarantine complete records",
        )
    ]
    details = copy.deepcopy(model.details_json)
    general_fills, general_conflicts, preserved_general = (
        correction.fill_missing_general(details, records)
    )
    operations = correction.canonical_paid_operations(records)
    paid_operations_status = correction.fill_missing_paid_operations(
        details,
        operations,
    )
    provenance = quarantine_provenance_payload(
        group=group,
        complete_manifest=complete_manifest,
        source_files=source_files,
        reviewed_quarantine_sha256=reviewed_quarantine_sha256,
    )
    merge_quarantine_provenance(details, provenance)

    scalar_fills: dict[str, str] = {}
    scalar_conflicts: dict[str, list[str]] = {}
    for source_field, target_field in (
        ("Product", "product_type"),
        ("Description", "description"),
    ):
        value, conflicts = exact_complete_consensus(records, source_field)
        if conflicts:
            scalar_conflicts[target_field] = conflicts
        elif value and not original.meaningful(getattr(model, target_field)):
            scalar_fills[target_field] = value

    sizes = original.sizes_from_masters(
        group["master_rows"],
        group["size_rows"],
    )
    color, color_conflicts = original.consensus(
        row.get("color") for row in group["variant_rows"]
    )
    add_sizes = _missing_sizes(model, sizes)
    add_colors = _missing_colors(model, [color] if color else [])
    decision = {
        "target_model_id": int(model.id),
        "identity": identity,
        "old_model_ids": copy.deepcopy(group["old_model_ids"]),
        "old_variant_ids": copy.deepcopy(group["old_variant_ids"]),
        "general_fills": general_fills,
        "general_conflicts": general_conflicts,
        "preserved_general": preserved_general,
        "scalar_conflicts": scalar_conflicts,
        "color_conflicts": color_conflicts,
        "paid_operations_status": paid_operations_status,
        "canonical_paid_operations_count": len(operations),
        "name_and_images_preserved": True,
    }
    if (
        details == model.details_json
        and not scalar_fills
        and not add_sizes
        and not add_colors
    ):
        decision["status"] = "exact_target_already_enriched"
        return None, decision
    decision["status"] = "enrich_exact_target"
    return (
        {
            "action": "update_existing",
            "action_scope": "quarantine_reconciliation",
            "identity": identity,
            "target_model_id": int(model.id),
            "expected_code": model.code,
            "expected_name": model.name,
            "expected_images": original.model_image_snapshot(model),
            "expected_details_sha256": original.object_sha256(model.details_json),
            "scalar_fills": scalar_fills,
            "details_after": details,
            "add_sizes": add_sizes,
            "add_colors": add_colors,
            "preserve_existing_name_and_images": True,
        },
        decision,
    )


def _missing_sizes(model: Model, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    existing = {original.normalized_value(row.size) for row in model.sizes or []}
    return [
        copy.deepcopy(row)
        for row in rows
        if original.normalized_value(row["size"]) not in existing
    ]


def _missing_colors(model: Model, rows: list[str]) -> list[str]:
    existing = {original.normalized_value(row.color_name) for row in model.colors or []}
    return [
        value for value in rows if original.normalized_value(value) not in existing
    ]


def create_name_evidence(
    *,
    record: dict[str, Any],
    master_row: dict[str, Any],
    code: str,
) -> dict[str, Any]:
    general = require_object(
        record.get("general"),
        f"Complete record {record['old_model_id']}.general",
    )
    legacy_name = (
        original.meaningful(general.get("Name"))
        or original.meaningful(master_row.get("name"))
        or code
    )
    exact_product = original.meaningful(general.get("Product"))
    desired_name = exact_product or legacy_name
    if len(legacy_name) > 255:
        raise MigrationError("Legacy Name exceeds the Model.name limit")
    if len(desired_name) > 255:
        raise MigrationError("Exact old-ERP Product exceeds the Model.name limit")
    return {
        "legacy_imported_name": legacy_name,
        "exact_product": exact_product or None,
        "desired_name": desired_name,
        "name_source": "product" if exact_product else "legacy_name_fallback",
    }


def existing_delta_name_decision(
    model: Model,
    *,
    record: dict[str, Any],
    master_row: dict[str, Any],
    created_by_delta: bool,
) -> dict[str, Any]:
    evidence = create_name_evidence(
        record=record,
        master_row=master_row,
        code=model.code,
    )
    decision = {
        **evidence,
        "current_name": model.name,
        "new_name": None,
    }
    if not created_by_delta:
        decision["status"] = "protected_existing"
        return decision
    if evidence["exact_product"] is None:
        decision["status"] = "no_product_legacy_name_preserved"
        return decision
    if model.name == evidence["desired_name"]:
        decision["status"] = "already_exact_product"
        return decision
    if model.name == evidence["legacy_imported_name"]:
        decision["status"] = "correct_imported_legacy_name_to_product"
        decision["new_name"] = evidence["desired_name"]
        return decision
    decision["status"] = "manual_name_drift_preserved"
    return decision


def plan_existing_action(
    model: Model,
    *,
    identity: str,
    record: dict[str, Any],
    master_row: dict[str, Any],
    variant_row: dict[str, Any] | None,
    raw_model_no: str,
    variant_no: str,
    source_files: dict[str, str],
    media_evidence: dict[str, Any] | None,
    variant_media_evidence: dict[str, Any] | None,
    created_by_delta: bool,
    sizes: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    general = require_object(
        record.get("general"),
        f"Complete record {record['old_model_id']}.general",
    )
    colors = []
    if variant_row is not None and original.meaningful(variant_row.get("color")):
        colors = [original.meaningful(variant_row.get("color"))]
    provenance = provenance_payload(
        identity=identity,
        master_row=master_row,
        variant_row=variant_row,
        complete_record=record,
        source_files=source_files,
        media_evidence=media_evidence,
        variant_media_evidence=variant_media_evidence,
        created_by_delta=created_by_delta,
    )
    paid_operations = correction.canonical_paid_operations([record])
    planned_details = details_after(
        model.details_json,
        patch=general_patch(
            record,
            model_no=raw_model_no,
            variant_no=variant_no,
        ),
        provenance=provenance,
        paid_operations=paid_operations,
    )
    scalar_fills: dict[str, str] = {}
    product = original.meaningful(general.get("Product"))
    description = original.meaningful(general.get("Description"))
    if not original.meaningful(model.product_type) and product:
        scalar_fills["product_type"] = product
    if not original.meaningful(model.description) and description:
        scalar_fills["description"] = description
    add_sizes = _missing_sizes(model, sizes)
    add_colors = _missing_colors(model, colors)
    name_decision = existing_delta_name_decision(
        model,
        record=record,
        master_row=master_row,
        created_by_delta=created_by_delta,
    )
    if (
        planned_details == model.details_json
        and not scalar_fills
        and not add_sizes
        and not add_colors
        and name_decision["new_name"] is None
    ):
        return None, name_decision
    return (
        {
            "action": "update_existing",
            "action_scope": "append_only_delta",
            "identity": identity,
            "target_model_id": int(model.id),
            "expected_code": model.code,
            "expected_name": model.name,
            "new_name": name_decision["new_name"],
            "name_decision": copy.deepcopy(name_decision),
            "expected_images": original.model_image_snapshot(model),
            "expected_details_sha256": original.object_sha256(model.details_json),
            "scalar_fills": scalar_fills,
            "details_after": planned_details,
            "add_sizes": add_sizes,
            "add_colors": add_colors,
            "preserve_existing_images": True,
            "preserve_existing_name": name_decision["new_name"] is None,
        },
        name_decision,
    )


def inherited_parent_image(
    *,
    parent_id: int,
    db_group: list[Model],
    receipt: dict[str, Any],
    target_media_dir: Path,
) -> dict[str, Any]:
    expected = require_object(
        require_object(
            receipt["provenance_evidence"].get("validated_images"),
            "Receipt validated images",
        ).get("models"),
        "Receipt validated model images",
    ).get(str(parent_id))
    if not isinstance(expected, dict):
        raise MigrationError(f"Prior parent model {parent_id} has no validated image")
    expected_sha = sha256_value(
        expected.get("sha256"),
        f"Prior parent model {parent_id} image SHA-256",
    )
    matches: list[tuple[int, ModelImage]] = []
    for model in db_group:
        for image in model.images or []:
            if original.clean(image.image_type) != "model":
                continue
            if original.db_model_image_sha(image, target_media_dir) == expected_sha:
                matches.append((int(image.id), image))
    if not matches:
        raise MigrationError(
            f"No local DB image matches prior parent model {parent_id} evidence"
        )
    _, selected = sorted(matches, key=lambda pair: (original.clean(pair[1].file_url), pair[0]))[0]
    return {
        "kind": "existing_relation",
        "role": "model",
        "file_url": selected.file_url,
        "file_name": selected.file_name,
        "content_type": selected.content_type,
        "image_type": "model",
        "is_primary": True,
    }


def create_action(
    *,
    identity: str,
    code: str,
    record: dict[str, Any],
    master_row: dict[str, Any],
    variant_row: dict[str, Any],
    raw_model_no: str,
    variant_no: str,
    source_files: dict[str, str],
    model_image: dict[str, Any],
    variant_image: dict[str, Any],
    media_evidence: dict[str, Any] | None,
    variant_media_evidence: dict[str, Any],
    sizes: list[dict[str, Any]],
) -> dict[str, Any]:
    general = require_object(
        record.get("general"),
        f"Complete record {record['old_model_id']}.general",
    )
    provenance = provenance_payload(
        identity=identity,
        master_row=master_row,
        variant_row=variant_row,
        complete_record=record,
        source_files=source_files,
        media_evidence=media_evidence,
        variant_media_evidence=variant_media_evidence,
        created_by_delta=True,
    )
    paid_operations = correction.canonical_paid_operations([record])
    details = details_after(
        {},
        patch=general_patch(
            record,
            model_no=raw_model_no,
            variant_no=variant_no,
        ),
        provenance=provenance,
        paid_operations=paid_operations,
    )
    model_spec = copy.deepcopy(model_image)
    model_spec["image_type"] = "model"
    model_spec["is_primary"] = True
    variant_spec = copy.deepcopy(variant_image)
    variant_spec["image_type"] = "material"
    variant_spec["is_primary"] = False
    color = original.meaningful(variant_row.get("color"))
    name_evidence = create_name_evidence(
        record=record,
        master_row=master_row,
        code=code,
    )
    return {
        "action": "create_variant",
        "action_scope": "append_only_delta",
        "identity": identity,
        "code": code,
        "name": name_evidence["desired_name"],
        "name_evidence": name_evidence,
        "description": original.meaningful(general.get("Description")) or None,
        "product_type": original.meaningful(general.get("Product")) or None,
        "status": "draft",
        "details_after": details,
        "sizes": copy.deepcopy(sizes),
        "colors": [color] if color else [],
        "images": [model_spec, variant_spec],
    }


def compile_plan(
    *,
    db,
    receipt: dict[str, Any],
    evidence: dict[str, Any],
    media: dict[str, Any],
    database_guard: dict[str, Any],
    target_media_dir: Path,
) -> dict[str, Any]:
    models = load_models(db)
    prior_scope, delta_created = validate_prior_database_scope(models, receipt)
    db_exact, db_bases = original.assert_no_duplicate_db_identities(models)

    reviewed_identities = {
        old_variant_id: original.identity_key(
            row.get("sew_model_code"),
            row.get("variant_code"),
        )
        for old_variant_id, row in evidence["delta"]["variants"].items()
    }
    for model in delta_created:
        identity = original.db_identity(model)
        provenance = delta_provenance(model)
        if identity not in set(reviewed_identities.values()):
            raise MigrationError(
                f"Delta-created model {model.id} has an unreviewed identity {identity!r}"
            )
        if not provenance or provenance.get("identity") != identity:
            raise MigrationError(f"Delta-created model {model.id} provenance changed")

    existing_codes = {original.base_key(model.code): int(model.id) for model in models}
    planned_codes: dict[str, str] = {}
    actions: list[dict[str, Any]] = []
    duplicate_targets: list[dict[str, Any]] = []

    for old_variant_id, variant_row in sorted(evidence["delta"]["variants"].items()):
        identity = reviewed_identities[old_variant_id]
        parent = evidence["parents"][old_variant_id]
        parent_id = int(parent["old_model_id"])
        record = evidence["records"][parent_id]
        reviewed_sizes = reviewed_sizes_for_parent(
            parent_id=parent_id,
            record=record,
            evidence=evidence,
        )
        base, variant_no = original.identity_parts(identity)
        db_group = db_bases.get(base) or []
        if db_group:
            raw_model_no = original.canonical_db_base_display(db_group)
        else:
            raw_model_no = original.display_base(variant_row.get("sew_model_code"))
        if not raw_model_no:
            raise MigrationError(f"Variant {old_variant_id} lost its display base")

        target = db_exact.get(identity)
        model_evidence = media["model_evidence"].get(parent_id)
        variant_evidence = media["variant_evidence"][old_variant_id]
        if target is not None:
            created_by_delta = is_delta_created(target)
            action, name_decision = plan_existing_action(
                target,
                identity=identity,
                record=record,
                master_row=parent,
                variant_row=variant_row,
                raw_model_no=raw_model_no,
                variant_no=variant_no,
                source_files=evidence["source_files"],
                media_evidence=model_evidence,
                variant_media_evidence=variant_evidence,
                created_by_delta=created_by_delta,
                sizes=reviewed_sizes,
            )
            duplicate_targets.append(
                {
                    "source_type": "variant",
                    "source_id": old_variant_id,
                    "identity": identity,
                    "target_model_id": int(target.id),
                    "name_preserved": name_decision["new_name"] is None,
                    "images_preserved": True,
                    "name_and_images_preserved": (
                        name_decision["new_name"] is None
                    ),
                    "name_decision": name_decision,
                }
            )
            if action is not None:
                actions.append(action)
            continue

        if parent_id in media["models"]:
            parent_image = media["models"][parent_id]
        else:
            parent_image = inherited_parent_image(
                parent_id=parent_id,
                db_group=db_group,
                receipt=receipt,
                target_media_dir=target_media_dir,
            )
        variant_image = media["variants"][old_variant_id]
        code = f"{raw_model_no}-{variant_no}"
        code_key = original.base_key(code)
        if code_key in existing_codes:
            raise MigrationError(
                f"Planned variant {old_variant_id} code collides with model "
                f"{existing_codes[code_key]}"
            )
        if code_key in planned_codes:
            raise MigrationError(
                f"Planned codes collide: {planned_codes[code_key]} and {code}"
            )
        planned_codes[code_key] = code
        actions.append(
            create_action(
                identity=identity,
                code=code,
                record=record,
                master_row=parent,
                variant_row=variant_row,
                raw_model_no=raw_model_no,
                variant_no=variant_no,
                source_files=evidence["source_files"],
                model_image=parent_image,
                variant_image=variant_image,
                media_evidence=model_evidence,
                variant_media_evidence=variant_evidence,
                sizes=reviewed_sizes,
            )
        )

    explicit_master = evidence["delta"]["models"][
        EXPECTED_EXPLICIT_DUPLICATE_MODEL_ID
    ]
    parsed = original.parse_explicit_variant(explicit_master.get("code"))
    if parsed is None:
        raise MigrationError("Reviewed explicit duplicate lost its variant identity")
    explicit_identity = original.identity_key(*parsed)
    if explicit_identity != EXPECTED_EXPLICIT_DUPLICATE_IDENTITY:
        raise MigrationError(
            f"Reviewed explicit duplicate identity changed to {explicit_identity}"
        )
    explicit_target = db_exact.get(explicit_identity)
    if explicit_target is None:
        raise MigrationError(
            "Reviewed explicit duplicate target disappeared; refusing to create it"
        )
    explicit_record = evidence["records"][EXPECTED_EXPLICIT_DUPLICATE_MODEL_ID]
    explicit_action, explicit_name_decision = plan_existing_action(
        explicit_target,
        identity=explicit_identity,
        record=explicit_record,
        master_row=explicit_master,
        variant_row=None,
        raw_model_no=original.clean(
            original.model_general(explicit_target).get("model_no")
            or original.model_general(explicit_target).get("modelNo")
        ),
        variant_no=original.clean(
            original.model_general(explicit_target).get("variant_no")
            or original.model_general(explicit_target).get("variantNo")
        ),
        source_files=evidence["source_files"],
        media_evidence=None,
        variant_media_evidence=None,
        created_by_delta=False,
        sizes=sizes_from_record(explicit_record),
    )
    duplicate_targets.append(
        {
            "source_type": "explicit_model",
            "source_id": EXPECTED_EXPLICIT_DUPLICATE_MODEL_ID,
            "identity": explicit_identity,
            "target_model_id": int(explicit_target.id),
            "name_preserved": True,
            "images_preserved": True,
            "name_and_images_preserved": True,
            "name_decision": explicit_name_decision,
        }
    )
    if explicit_action is not None:
        actions.append(explicit_action)

    quarantine_resolutions: list[dict[str, Any]] = []
    unresolved_quarantines: list[dict[str, Any]] = []
    for group in evidence["quarantine"]["groups"]:
        identity = group.get("identity")
        public_scope = {
            "identity": identity,
            "old_model_ids": copy.deepcopy(group["old_model_ids"]),
            "old_variant_ids": copy.deepcopy(group["old_variant_ids"]),
            "quarantine_entries": copy.deepcopy(group["quarantine_entries"]),
        }
        if identity is None:
            unresolved_quarantines.append(
                {
                    **public_scope,
                    "reason": "blank_or_unusable_master_identity",
                    "exact_target_model_ids": [],
                    "base_family_candidate_model_ids": [],
                    "code_only_candidate_model_ids": [],
                    "name_only_candidate_model_ids": [],
                }
            )
            continue

        target = db_exact.get(identity)
        base, _ = original.identity_parts(identity)
        base_candidates = sorted(
            int(model.id) for model in (db_bases.get(base) or [])
        )
        source_code_keys = {
            original.base_key(row.get("code"))
            for row in group["master_rows"]
            if original.base_key(row.get("code"))
        }
        source_name_keys = {
            original.normalized_value(row.get("name"))
            for row in group["master_rows"]
            if original.meaningful(row.get("name"))
        }
        code_only_candidates = sorted(
            int(model.id)
            for model in models
            if original.base_key(model.code) in source_code_keys
        )
        name_only_candidates = sorted(
            int(model.id)
            for model in models
            if original.normalized_value(model.name) in source_name_keys
        )
        if target is None:
            unresolved_quarantines.append(
                {
                    **public_scope,
                    "reason": "exact_identity_target_absent",
                    "exact_target_model_ids": [],
                    "base_family_candidate_model_ids": base_candidates,
                    "code_only_candidate_model_ids": code_only_candidates,
                    "name_only_candidate_model_ids": name_only_candidates,
                    "unsafe_sibling_or_text_only_attachment_rejected": True,
                }
            )
            continue

        action, resolution = plan_quarantine_existing_action(
            target,
            group=group,
            complete_manifest=evidence["complete_manifest"],
            source_files=evidence["source_files"],
            reviewed_quarantine_sha256=evidence["quarantine"][
                "reviewed_quarantine_sha256"
            ],
        )
        resolution.update(
            {
                "exact_target_model_ids": [int(target.id)],
                "base_family_candidate_model_ids": base_candidates,
                "code_only_candidate_model_ids": code_only_candidates,
                "name_only_candidate_model_ids": name_only_candidates,
            }
        )
        quarantine_resolutions.append(resolution)
        if action is not None:
            actions.append(action)

    target_action_ids: dict[int, str] = {}
    for action in actions:
        if action["action"] != "update_existing":
            continue
        target_id = int(action["target_model_id"])
        prior_scope_name = target_action_ids.get(target_id)
        if prior_scope_name is not None:
            raise MigrationError(
                f"Existing model {target_id} received both {prior_scope_name} "
                f"and {action.get('action_scope')} actions"
            )
        target_action_ids[target_id] = original.clean(action.get("action_scope"))

    actions = sorted(
        actions,
        key=lambda row: (
            row["identity"],
            0 if row["action"] == "update_existing" else 1,
        ),
    )
    create_actions = [row for row in actions if row["action"] == "create_variant"]
    update_actions = [row for row in actions if row["action"] == "update_existing"]
    delta_update_actions = [
        row
        for row in update_actions
        if row.get("action_scope") == "append_only_delta"
    ]
    quarantine_update_actions = [
        row
        for row in update_actions
        if row.get("action_scope") == "quarantine_reconciliation"
    ]
    planned_images = sum(len(row.get("images") or []) for row in create_actions)
    planned_sizes = sum(
        len(row.get("sizes") or row.get("add_sizes") or []) for row in actions
    )
    planned_colors = sum(
        len(row.get("colors") or row.get("add_colors") or []) for row in actions
    )
    planned_name_corrections = [
        row
        for row in update_actions
        if original.meaningful(row.get("new_name"))
    ]
    existing_name_status_counts: dict[str, int] = defaultdict(int)
    for row in duplicate_targets:
        decision = row.get("name_decision")
        if isinstance(decision, dict):
            existing_name_status_counts[
                original.clean(decision.get("status"))
            ] += 1
    counts = original.db_counts(db)
    business_counts = original.count_business_tables(db)
    protected = original.protected_snapshot(models)
    unresolved_quarantine_sha256 = original.object_sha256(unresolved_quarantines)
    summary = {
        **copy.deepcopy(evidence["delta"]["summary"]),
        **copy.deepcopy(evidence["quarantine"]["summary"]),
        "canonical_delta_variant_identities": len(reviewed_identities),
        "create_models": len(create_actions),
        "update_existing_models": len(update_actions),
        "delta_update_existing_models": len(delta_update_actions),
        "quarantine_update_existing_models": len(quarantine_update_actions),
        "quarantine_resolved_identities": len(quarantine_resolutions),
        "quarantine_unresolved_identities": len(unresolved_quarantines),
        "quarantine_unresolved_records": sum(
            len(row["old_model_ids"]) for row in unresolved_quarantines
        ),
        "unresolved_quarantines_require_explicit_acceptance": bool(
            unresolved_quarantines
        ),
        "exact_duplicate_sources": len(duplicate_targets),
        "explicit_duplicate_target_model_id": int(explicit_target.id),
        "planned_model_images": planned_images,
        "planned_model_sizes": planned_sizes,
        "planned_model_colors": planned_colors,
        "create_models_named_from_product": sum(
            1
            for row in create_actions
            if require_object(
                row.get("name_evidence"),
                "Create action name_evidence",
            ).get("name_source")
            == "product"
        ),
        "planned_delta_created_name_corrections": len(
            planned_name_corrections
        ),
        "existing_delta_name_status_counts": dict(
            sorted(existing_name_status_counts.items())
        ),
        "already_delta_created_models": len(delta_created),
        **copy.deepcopy(media["summary"]),
    }
    plan = {
        "schema_version": SCHEMA_VERSION,
        "source_key": SOURCE_KEY,
        "mode": "dry_run_plan",
        "source_files": dict(sorted(evidence["source_files"].items())),
        "append_only_proof": copy.deepcopy(evidence["delta"]["summary"]),
        "prior_quarantine_proof": {
            "reviewed_quarantine_sha256": evidence["quarantine"][
                "reviewed_quarantine_sha256"
            ],
            **copy.deepcopy(evidence["quarantine"]["summary"]),
        },
        "database_guard": copy.deepcopy(database_guard),
        "database_preconditions": {
            "counts": counts,
            "business_counts": business_counts,
            "catalog_sha256": original.object_sha256(original.catalog_snapshot(models)),
            "protected_names_images_sha256": original.object_sha256(protected),
            "creator_user_id": receipt["creator_user_id"],
        },
        "summary": summary,
        "duplicate_targets": duplicate_targets,
        "quarantine_resolutions": quarantine_resolutions,
        "unresolved_quarantines": unresolved_quarantines,
        "unresolved_quarantine_sha256": unresolved_quarantine_sha256,
        "actions": actions,
        "invariants": {
            "existing_model_codes_immutable": True,
            "existing_model_image_rows_immutable": True,
            "existing_names_immutable_except_reviewed_delta_created_corrections": True,
            "delta_created_name_correction_requires_exact_legacy_name": True,
            "delta_created_name_correction_uses_exact_product": True,
            "explicit_duplicate_must_not_be_created": True,
            "explicit_duplicate_name_and_images_immutable": True,
            "quarantine_target_requires_exact_canonical_identity": True,
            "quarantine_sibling_or_text_only_attachment_forbidden": True,
            "every_unlinked_complete_record_accounted_for": True,
            "no_bom_items_stock_orders_packages_shipments": True,
            "production_touched": False,
        },
    }
    plan["plan_sha256"] = original.object_sha256(plan)
    return plan


def enforce_reviewed_counts(
    args: argparse.Namespace,
    plan: dict[str, Any],
) -> None:
    summary = plan["summary"]
    pre = plan["database_preconditions"]["counts"]
    checks = {
        "--expect-delta-models": (args.expect_delta_models, summary["delta_model_rows"]),
        "--expect-delta-variants": (
            args.expect_delta_variants,
            summary["delta_variant_rows"],
        ),
        "--expect-create-models": (args.expect_create_models, summary["create_models"]),
        "--expect-update-existing": (
            args.expect_update_existing,
            summary["update_existing_models"],
        ),
        "--expect-name-corrections": (
            args.expect_name_corrections,
            summary["planned_delta_created_name_corrections"],
        ),
        "--expect-quarantine-updates": (
            args.expect_quarantine_updates,
            summary["quarantine_update_existing_models"],
        ),
        "--expect-unresolved-quarantine-identities": (
            args.expect_unresolved_quarantine_identities,
            summary["quarantine_unresolved_identities"],
        ),
        "--expect-unresolved-quarantine-records": (
            args.expect_unresolved_quarantine_records,
            summary["quarantine_unresolved_records"],
        ),
        "--expect-duplicate-sources": (
            args.expect_duplicate_sources,
            summary["exact_duplicate_sources"],
        ),
        "--expect-added-images": (
            args.expect_added_images,
            summary["planned_model_images"],
        ),
        "--expect-added-sizes": (
            args.expect_added_sizes,
            summary["planned_model_sizes"],
        ),
        "--expect-added-colors": (
            args.expect_added_colors,
            summary["planned_model_colors"],
        ),
        "--expect-db-models": (args.expect_db_models, pre["models"]),
        "--expect-db-images": (args.expect_db_images, pre["model_images"]),
        "--expect-db-sizes": (args.expect_db_sizes, pre["model_sizes"]),
        "--expect-db-colors": (args.expect_db_colors, pre["model_colors"]),
        "--expect-db-bom": (args.expect_db_bom, pre["model_bom"]),
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
    revision = original.clean(plan["database_guard"].get("alembic_revision"))
    if args.expect_db_revision is None:
        if args.apply:
            missing.append("--expect-db-revision")
    elif original.clean(args.expect_db_revision) != revision:
        raise MigrationError(
            f"Reviewed DB revision changed: expected {args.expect_db_revision}, got {revision}"
        )
    if missing:
        raise MigrationError(
            "Apply requires every reviewed count assertion: " + ", ".join(missing)
        )


def _add_sizes(db, model: Model, rows: list[dict[str, Any]]) -> int:
    existing = {original.normalized_value(row.size) for row in model.sizes or []}
    added = 0
    for row in rows:
        key = original.normalized_value(row["size"])
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


def _add_colors(db, model: Model, rows: list[str]) -> int:
    existing = {original.normalized_value(row.color_name) for row in model.colors or []}
    added = 0
    for value in rows:
        key = original.normalized_value(value)
        if key in existing:
            continue
        db.add(
            ModelColor(
                model_id=int(model.id),
                color_name=value,
                color_code=None,
            )
        )
        existing.add(key)
        added += 1
    return added


def apply_plan(
    *,
    db,
    plan: dict[str, Any],
    media_root: Path,
    target_media_dir: Path,
) -> dict[str, Any]:
    models_before = load_models(db)
    before_by_id = {int(model.id): model for model in models_before}
    counts_before = original.db_counts(db)
    business_before = original.count_business_tables(db)
    expected = plan["database_preconditions"]
    if counts_before != expected["counts"]:
        raise MigrationError("Database catalog counts changed after reviewed plan")
    if business_before != expected["business_counts"]:
        raise MigrationError("Business table counts changed after reviewed plan")
    if (
        original.object_sha256(original.catalog_snapshot(models_before))
        != expected["catalog_sha256"]
    ):
        raise MigrationError("Database catalog content changed after reviewed plan")
    protected_before = original.protected_snapshot(models_before)
    protected_before_sha = original.object_sha256(protected_before)
    if protected_before_sha != expected["protected_names_images_sha256"]:
        raise MigrationError("Protected names/images changed after reviewed plan")

    reviewed_name_corrections: dict[int, str] = {}
    explicit_duplicate_target_id = int(
        plan["summary"]["explicit_duplicate_target_model_id"]
    )
    for action in plan["actions"]:
        if action.get("action") != "update_existing":
            continue
        new_name = action.get("new_name")
        if new_name is None:
            continue
        if not isinstance(new_name, str) or not new_name:
            raise MigrationError("Reviewed name correction is not a nonblank string")
        target_id = int(action["target_model_id"])
        if target_id == explicit_duplicate_target_id:
            raise MigrationError("Explicit duplicate name correction is forbidden")
        if action.get("action_scope") != "append_only_delta":
            raise MigrationError("Only append-only delta rows may receive a name correction")
        decision = require_object(
            action.get("name_decision"),
            f"Name correction decision for model {target_id}",
        )
        if (
            decision.get("status")
            != "correct_imported_legacy_name_to_product"
            or decision.get("legacy_imported_name") != action.get("expected_name")
            or decision.get("current_name") != action.get("expected_name")
            or decision.get("exact_product") != new_name
            or decision.get("desired_name") != new_name
            or decision.get("new_name") != new_name
        ):
            raise MigrationError(
                f"Name correction evidence changed for model {target_id}"
            )
        if target_id in reviewed_name_corrections:
            raise MigrationError(
                f"Model {target_id} received multiple name corrections"
            )
        reviewed_name_corrections[target_id] = new_name

    preflight = original.media_preflight(plan, target_media_dir)
    required_bytes = int(preflight["source_bytes_to_create"])
    safety_margin = max(512 * 1024 * 1024, required_bytes // 10) if required_bytes else 0
    if shutil.disk_usage(target_media_dir).free < required_bytes + safety_margin:
        raise MigrationError("Insufficient local disk space for reviewed delta images")

    created_files: list[Path] = []
    result = {
        "created_models": 0,
        "updated_existing_models": 0,
        "added_images": 0,
        "added_sizes": 0,
        "added_colors": 0,
        "corrected_delta_created_names": 0,
        "corrected_delta_created_name_model_ids": [],
        "created_model_ids": [],
    }
    try:
        created_files = original.materialize_source_images(
            plan,
            media_root=media_root,
            target_dir=target_media_dir,
        )
        creator_id = int(expected.get("creator_user_id") or 0) or None
        for action in plan["actions"]:
            if action["action"] == "update_existing":
                model = db.get(Model, int(action["target_model_id"]))
                if model is None:
                    raise MigrationError(
                        f"Existing target {action['target_model_id']} disappeared"
                    )
                if model.code != action["expected_code"] or model.name != action["expected_name"]:
                    raise MigrationError(
                        f"Protected code/name changed for model {model.id}"
                    )
                if original.model_image_snapshot(model) != action["expected_images"]:
                    raise MigrationError(f"Protected images changed for model {model.id}")
                if (
                    original.object_sha256(model.details_json)
                    != action["expected_details_sha256"]
                ):
                    raise MigrationError(f"Details changed for model {model.id}")
                new_name = action.get("new_name")
                if new_name is not None:
                    if not is_delta_created(model):
                        raise MigrationError(
                            f"Model {model.id} is not a provenance-proven delta creation"
                        )
                    if reviewed_name_corrections.get(int(model.id)) != new_name:
                        raise MigrationError(
                            f"Model {model.id} lacks reviewed name-correction evidence"
                        )
                    model.name = new_name
                    result["corrected_delta_created_names"] += 1
                    result["corrected_delta_created_name_model_ids"].append(
                        int(model.id)
                    )
                for field, value in action["scalar_fills"].items():
                    if original.meaningful(getattr(model, field)):
                        raise MigrationError(
                            f"Planned blank field {field} became nonblank for model {model.id}"
                        )
                    setattr(model, field, value)
                model.details_json = copy.deepcopy(action["details_after"])
                flag_modified(model, "details_json")
                result["added_sizes"] += _add_sizes(db, model, action["add_sizes"])
                result["added_colors"] += _add_colors(db, model, action["add_colors"])
                result["updated_existing_models"] += 1
                continue

            if action["action"] != "create_variant":
                raise MigrationError(f"Unsupported delta action {action['action']!r}")
            model = Model(
                code=action["code"],
                name=action["name"],
                category=None,
                description=action.get("description"),
                brand_id=None,
                collection_id=None,
                product_type=action.get("product_type"),
                season=None,
                details_json=copy.deepcopy(action["details_after"]),
                status=action["status"],
                created_by=creator_id,
                sam_minutes=0,
            )
            db.add(model)
            db.flush()
            result["added_sizes"] += _add_sizes(db, model, action["sizes"])
            result["added_colors"] += _add_colors(db, model, action["colors"])
            result["added_images"] += original.add_images(db, model, action["images"])
            result["created_models"] += 1
            result["created_model_ids"].append(int(model.id))

        db.flush()
        db.expire_all()
        models_after = load_models(db)
        after_by_id = {int(model.id): model for model in models_after}
        protected_existing_after = original.protected_snapshot(
            after_by_id[model_id] for model_id in sorted(before_by_id)
        )
        expected_protected_after = copy.deepcopy(protected_before)
        expected_by_id = {
            int(row["id"]): row for row in expected_protected_after
        }
        for model_id, new_name in reviewed_name_corrections.items():
            row = expected_by_id.get(model_id)
            if row is None:
                raise MigrationError(
                    f"Reviewed name-correction model {model_id} was not pre-existing"
                )
            row["name"] = new_name
        protected_after_sha = original.object_sha256(protected_existing_after)
        expected_protected_after_sha = original.object_sha256(
            expected_protected_after
        )
        if protected_after_sha != expected_protected_after_sha:
            raise MigrationError(
                "Existing model code/name/image reconciliation exceeded the "
                "reviewed delta-created name corrections"
            )
        if (
            result["corrected_delta_created_names"]
            != len(reviewed_name_corrections)
        ):
            raise MigrationError("Delta-created name correction count failed")
        business_after = original.count_business_tables(db)
        if business_after != business_before:
            raise MigrationError("A business table count changed during delta apply")
        counts_after = original.db_counts(db)
        if counts_after["models"] - counts_before["models"] != result["created_models"]:
            raise MigrationError("Created Model reconciliation failed")
        if (
            counts_after["model_images"] - counts_before["model_images"]
            != result["added_images"]
        ):
            raise MigrationError("Created ModelImage reconciliation failed")
        if (
            counts_after["model_sizes"] - counts_before["model_sizes"]
            != result["added_sizes"]
        ):
            raise MigrationError("Created ModelSize reconciliation failed")
        if (
            counts_after["model_colors"] - counts_before["model_colors"]
            != result["added_colors"]
        ):
            raise MigrationError("Created ModelColor reconciliation failed")
        if counts_after["model_bom"] != counts_before["model_bom"]:
            raise MigrationError("ModelBOM count changed")
        db.commit()
        result.update(
            {
                "created_files": [str(path) for path in created_files],
                "counts_before": counts_before,
                "counts_after": counts_after,
                "business_counts_before": business_before,
                "business_counts_after": business_after,
                "protected_names_images_sha256_before": protected_before_sha,
                "protected_names_images_sha256_after": protected_after_sha,
                "expected_protected_names_images_sha256_after": (
                    expected_protected_after_sha
                ),
            }
        )
        return result
    except Exception:
        db.rollback()
        for path in reversed(created_files):
            try:
                if path.is_file() and path.parent.resolve() == target_media_dir.resolve():
                    path.unlink()
            except OSError:
                pass
        raise


def prepare_evidence(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any], Path]:
    prior_plan, _, prior_plan_sha = original.load_json_file(
        args.prior_apply_plan,
        args.prior_apply_plan_sha256,
        "Prior localhost apply plan",
    )
    prior_report, _, prior_report_sha = original.load_json_file(
        args.prior_apply_report,
        args.prior_apply_report_sha256,
        "Prior localhost apply report",
    )
    receipt = correction.load_reviewed_receipt(
        prior_plan,
        prior_report,
        plan_file_sha256=prior_plan_sha,
        report_file_sha256=prior_report_sha,
    )
    receipt["creator_user_id"] = require_int(
        require_object(
            prior_plan.get("database_preconditions"),
            "Prior apply database_preconditions",
        ).get("creator_user_id"),
        "Prior apply creator_user_id",
        positive=True,
    )
    prior_models_payload, _, prior_models_sha = original.load_json_file(
        args.prior_models_source,
        args.prior_models_source_sha256,
        "Prior frozen models source",
    )
    prior_variants_payload, _, prior_variants_sha = original.load_json_file(
        args.prior_variants_source,
        args.prior_variants_source_sha256,
        "Prior frozen variants source",
    )
    prior_sizes_payload, _, prior_sizes_sha = original.load_json_file(
        args.prior_sizes_source,
        args.prior_sizes_source_sha256,
        "Prior frozen sizes/details source",
    )
    if prior_models_sha != receipt["source_files"]["models_source_sha256"]:
        raise MigrationError("Prior models source does not match successful receipt")
    if prior_variants_sha != receipt["source_files"]["variants_source_sha256"]:
        raise MigrationError("Prior variants source does not match successful receipt")
    if prior_sizes_sha != receipt["source_files"]["sizes_sha256"]:
        raise MigrationError("Prior sizes/details source does not match successful receipt")
    prior_models = original.index_rows(
        require_list(prior_models_payload, "Prior models source"),
        "old_model_id",
        "Prior models source",
    )
    prior_variants = original.index_rows(
        require_list(prior_variants_payload, "Prior variants source"),
        "old_variant_id",
        "Prior variants source",
    )
    embedded_prior_models_sha = original.clean(
        require_object(
            prior_sizes_payload,
            "Prior frozen sizes/details source",
        ).get("source_models_sha256")
    ).lower()
    if embedded_prior_models_sha != prior_models_sha:
        raise MigrationError(
            "Prior sizes/details source refers to a different models source"
        )
    prior_sizes = original.load_sizes(prior_sizes_payload)
    if len(prior_models) != receipt["prior_source_model_count"]:
        raise MigrationError("Prior models source count differs from receipt")
    if len(prior_variants) != receipt["prior_source_variant_count"]:
        raise MigrationError("Prior variants source count differs from receipt")

    current_models_payload, _, current_models_sha = original.load_json_file(
        args.current_models_metadata,
        args.current_models_sha256,
        "Current models metadata",
    )
    current_variants_payload, _, current_variants_sha = original.load_json_file(
        args.current_variants_metadata,
        args.current_variants_sha256,
        "Current variants metadata",
    )
    current_models = flatten_current_list(
        current_models_payload,
        label="Current models metadata",
        id_field="old_model_id",
    )
    current_variants = flatten_current_list(
        current_variants_payload,
        label="Current variants metadata",
        id_field="old_variant_id",
    )
    delta = prove_append_only(
        prior_models=prior_models,
        prior_variants=prior_variants,
        current_models=current_models,
        current_variants=current_variants,
    )
    parents = resolve_reviewed_parents(
        current_models=current_models,
        delta_variants=delta["variants"],
    )

    complete_payload, complete_path, complete_sha = original.load_json_file(
        args.complete_details_manifest,
        args.complete_details_sha256,
        "Complete-details manifest",
    )
    complete = correction.index_complete_manifest(
        complete_payload,
        manifest_file_sha256=complete_sha,
    )
    records = validate_complete_delta_records(
        complete_manifest=complete,
        current_models=current_models,
        delta_variants=delta["variants"],
        parents=parents,
    )
    quarantine = build_quarantine_evidence(
        prior_plan=prior_plan,
        receipt=receipt,
        prior_models=prior_models,
        prior_variants=prior_variants,
        prior_sizes=prior_sizes,
        complete_manifest=complete,
    )

    media_payload, media_path, media_sha = original.load_json_file(
        args.delta_images_manifest,
        args.delta_images_sha256,
        "Delta image manifest",
    )
    media_root = (
        args.media_root.expanduser().resolve()
        if args.media_root
        else media_path.parent.resolve()
    )
    if not media_root.is_dir():
        raise MigrationError(f"Delta media root does not exist: {media_root}")
    media = validate_delta_media(
        media_payload,
        media_root=media_root,
        max_image_bytes=args.max_image_bytes,
        current_models_sha256=current_models_sha,
        current_variants_sha256=current_variants_sha,
        complete_details_sha256=complete_sha,
    )
    source_files = {
        "prior_apply_plan_sha256": prior_plan_sha,
        "prior_apply_report_sha256": prior_report_sha,
        "prior_models_source_sha256": prior_models_sha,
        "prior_variants_source_sha256": prior_variants_sha,
        "prior_sizes_source_sha256": prior_sizes_sha,
        "current_models_metadata_sha256": current_models_sha,
        "current_variants_metadata_sha256": current_variants_sha,
        "complete_details_sha256": complete_sha,
        "delta_images_manifest_sha256": media_sha,
    }
    evidence = {
        "receipt": receipt,
        "prior_models": prior_models,
        "prior_variants": prior_variants,
        "prior_sizes": prior_sizes,
        "current_models": current_models,
        "current_variants": current_variants,
        "delta": delta,
        "parents": parents,
        "records": records,
        "quarantine": quarantine,
        "complete_manifest": complete,
        "source_files": source_files,
        "paths": {
            "complete": complete_path,
            "media_manifest": media_path,
        },
    }
    return evidence, media, media_root


def reject_output_aliases(args: argparse.Namespace) -> None:
    correction.reject_output_input_aliases(
        plan_output=args.plan_output,
        report_output=args.report,
        protected_inputs=(
            args.prior_apply_plan,
            args.prior_apply_report,
            args.prior_models_source,
            args.prior_variants_source,
            args.prior_sizes_source,
            args.current_models_metadata,
            args.current_variants_metadata,
            args.complete_details_manifest,
            args.delta_images_manifest,
            args.database_backup,
            args.media_backup,
        ),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plan/apply the reviewed append-only old-ERP model delta locally."
    )
    parser.add_argument("--prior-apply-plan", required=True, type=Path)
    parser.add_argument("--prior-apply-plan-sha256", required=True)
    parser.add_argument("--prior-apply-report", required=True, type=Path)
    parser.add_argument("--prior-apply-report-sha256", required=True)
    parser.add_argument("--prior-models-source", required=True, type=Path)
    parser.add_argument("--prior-models-source-sha256", required=True)
    parser.add_argument("--prior-variants-source", required=True, type=Path)
    parser.add_argument("--prior-variants-source-sha256", required=True)
    parser.add_argument("--prior-sizes-source", required=True, type=Path)
    parser.add_argument("--prior-sizes-source-sha256", required=True)
    parser.add_argument("--current-models-metadata", required=True, type=Path)
    parser.add_argument("--current-models-sha256", required=True)
    parser.add_argument("--current-variants-metadata", required=True, type=Path)
    parser.add_argument("--current-variants-sha256", required=True)
    parser.add_argument("--complete-details-manifest", required=True, type=Path)
    parser.add_argument("--complete-details-sha256", required=True)
    parser.add_argument("--delta-images-manifest", required=True, type=Path)
    parser.add_argument("--delta-images-sha256", required=True)
    parser.add_argument("--media-root", type=Path)
    parser.add_argument(
        "--target-media-dir",
        type=Path,
        default=original.repo_local_media_dir(),
    )
    parser.add_argument("--max-image-bytes", type=int, default=25 * 1024 * 1024)
    parser.add_argument("--plan-output", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--overwrite-output", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-localhost")
    parser.add_argument("--expected-plan-sha256")
    parser.add_argument("--accept-unresolved-quarantine-sha256")
    parser.add_argument("--local-db-port", type=int, default=DEFAULT_LOCAL_DB_PORT)
    parser.add_argument("--database-backup", type=Path)
    parser.add_argument("--database-backup-sha256")
    parser.add_argument("--media-backup", type=Path)
    parser.add_argument("--media-backup-sha256")
    parser.add_argument("--max-backup-age-hours", type=float, default=24.0)
    parser.add_argument("--expect-delta-models", type=int)
    parser.add_argument("--expect-delta-variants", type=int)
    parser.add_argument("--expect-create-models", type=int)
    parser.add_argument("--expect-update-existing", type=int)
    parser.add_argument("--expect-name-corrections", type=int)
    parser.add_argument("--expect-quarantine-updates", type=int)
    parser.add_argument("--expect-unresolved-quarantine-identities", type=int)
    parser.add_argument("--expect-unresolved-quarantine-records", type=int)
    parser.add_argument("--expect-duplicate-sources", type=int)
    parser.add_argument("--expect-added-images", type=int)
    parser.add_argument("--expect-added-sizes", type=int)
    parser.add_argument("--expect-added-colors", type=int)
    parser.add_argument("--expect-db-models", type=int)
    parser.add_argument("--expect-db-images", type=int)
    parser.add_argument("--expect-db-sizes", type=int)
    parser.add_argument("--expect-db-colors", type=int)
    parser.add_argument("--expect-db-bom", type=int)
    parser.add_argument("--expect-db-revision")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    original.preflight_output_paths(
        args.plan_output,
        args.report,
        overwrite=args.overwrite_output,
    )
    reject_output_aliases(args)
    if args.max_image_bytes <= 0:
        raise MigrationError("--max-image-bytes must be positive")
    if args.apply:
        if args.confirm_localhost != APPLY_CONFIRMATION:
            raise MigrationError(
                f"Apply requires --confirm-localhost {APPLY_CONFIRMATION}"
            )
        expected_plan_sha = sha256_value(
            args.expected_plan_sha256,
            "--expected-plan-sha256",
        )
        database_backup = correction.verify_fresh_database_backup(
            args.database_backup,
            args.database_backup_sha256,
            max_age_hours=args.max_backup_age_hours,
        )
        media_backup = original.verify_backup(
            args.media_backup,
            args.media_backup_sha256,
            "media backup",
        )
    else:
        expected_plan_sha = ""
        database_backup = None
        media_backup = None

    evidence, media, media_root = prepare_evidence(args)
    target_media_dir = original.verify_media_target(args.target_media_dir)
    db = SessionLocal()
    try:
        database_guard = original.local_database_guard(
            db,
            expected_port=args.local_db_port,
        )
        if args.apply:
            correction.acquire_local_apply_locks(db)
        plan = compile_plan(
            db=db,
            receipt=evidence["receipt"],
            evidence=evidence,
            media=media,
            database_guard=database_guard,
            target_media_dir=target_media_dir,
        )
        enforce_reviewed_counts(args, plan)
        accepted_unresolved_quarantine_sha256 = None
        if args.apply and plan["unresolved_quarantines"]:
            accepted_unresolved_quarantine_sha256 = sha256_value(
                args.accept_unresolved_quarantine_sha256,
                "--accept-unresolved-quarantine-sha256",
            )
            if (
                accepted_unresolved_quarantine_sha256
                != plan["unresolved_quarantine_sha256"]
            ):
                raise MigrationError(
                    "Reviewed unresolved-quarantine SHA-256 changed: "
                    f"expected {accepted_unresolved_quarantine_sha256}, "
                    f"got {plan['unresolved_quarantine_sha256']}"
                )
        if args.apply and plan["plan_sha256"] != expected_plan_sha:
            raise MigrationError(
                "Live delta plan differs from reviewed plan: "
                f"expected {expected_plan_sha}, got {plan['plan_sha256']}"
            )
        media_check = original.media_preflight(plan, target_media_dir)
        if args.apply:
            reconciliation = apply_plan(
                db=db,
                plan=plan,
                media_root=media_root,
                target_media_dir=target_media_dir,
            )
            mode = "apply"
        else:
            db.rollback()
            reconciliation = None
            mode = "dry_run"
        report = {
            "schema_version": SCHEMA_VERSION,
            "source_key": SOURCE_KEY,
            "mode": mode,
            "production_touched": False,
            "plan_sha256": plan["plan_sha256"],
            "source_files": copy.deepcopy(plan["source_files"]),
            "summary": copy.deepcopy(plan["summary"]),
            "append_only_proof": copy.deepcopy(plan["append_only_proof"]),
            "prior_quarantine_proof": copy.deepcopy(
                plan["prior_quarantine_proof"]
            ),
            "duplicate_targets": copy.deepcopy(plan["duplicate_targets"]),
            "quarantine_resolutions": copy.deepcopy(
                plan["quarantine_resolutions"]
            ),
            "unresolved_quarantines": copy.deepcopy(
                plan["unresolved_quarantines"]
            ),
            "unresolved_quarantine_sha256": plan[
                "unresolved_quarantine_sha256"
            ],
            "accepted_unresolved_quarantine_sha256": (
                accepted_unresolved_quarantine_sha256
            ),
            "media_preflight": media_check,
            "database_backup": database_backup,
            "media_backup": media_backup,
            "reconciliation": reconciliation,
        }
        original.write_json(
            args.plan_output,
            plan,
            overwrite=args.overwrite_output,
        )
        original.write_json(
            args.report,
            report,
            overwrite=args.overwrite_output,
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
