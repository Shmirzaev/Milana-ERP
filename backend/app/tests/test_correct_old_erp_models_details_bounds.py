"""Bounds on ``Model.details_json`` written by the old-ERP correction script.

The correction pass re-derives ``details_json`` in pure functions and then
persists it, so these tests drive ``plan_model_correction`` -- the single
choke point every write goes through -- with in-memory fixtures only.  No
database is created, read or mutated here.
"""

from __future__ import annotations

import copy
import math

import pytest

from scripts import correct_old_erp_models_local as correction


# The ceilings live in the API write path, which the correction script shares
# so the two can never drift apart.
from app.api.routes.catalog import (  # noqa: E402
    _MAX_MODEL_DETAILS_JSON_BYTES,
    _MAX_MODEL_DETAILS_JSON_DEPTH,
    _validate_model_details_json_bounds,
)

MAX_BYTES = _MAX_MODEL_DETAILS_JSON_BYTES
MAX_DEPTH = _MAX_MODEL_DETAILS_JSON_DEPTH


def nested_legacy_value(depth: int = 20) -> dict:
    value = {"leaf": True}
    for _ in range(depth):
        value = {"next": value}
    return value


def provenance(*old_model_ids: int) -> dict:
    return {
        "source_key": correction.SOURCE_KEY,
        "source_files": {
            "models_source_sha256": "a" * 64,
            "variants_source_sha256": "b" * 64,
        },
        "identity": "TJ2205|1",
        "master_records": [
            {"old_model_id": old_model_id, "name": "raw"}
            for old_model_id in old_model_ids
        ],
        "variant_records": [],
        "metadata_only_records": [],
        "validated_images": {"models": {}, "variants": {}},
        "details_and_sizes": {},
    }


def action() -> dict:
    return {
        "action": "create_variant",
        "identity": "TJ2205|1",
        "provenance": provenance(35),
        "code": "TJ-2205-1",
        "name": "4112",
        "product_type": "Туника",
    }


def complete_record(old_model_id: int = 35) -> dict:
    return {
        "old_model_id": old_model_id,
        "source_url": (
            "https://10.100.50.199:8443/uzerp/"
            f"prepareSewModel.htm?id={old_model_id}"
        ),
        "list_metadata": {
            "old_model_id": old_model_id,
            "code": "TJ2205",
            "company": "Milana",
            "detail_url": f"prepareSewModel.htm?id={old_model_id}",
            "has_image": True,
            "model_variant": "1",
            "name": "4112",
            "product": "Туника",
            "style": "Classic",
        },
        "general": {
            "Company": "Milana",
            "Date": "01/02/2025 03:04:05",
            "Description": "Exact legacy description",
            "Embroidery": False,
            "Name": "4112",
            "Parent Sew Model": "TJ2200",
            "Planning Type": "Order",
            "Product": "Туника",
            "Sew Model Code": "TJ2205",
            "Style": "Classic",
            "Thermal Print": True,
            "Variant": "1",
        },
        "operations": [],
        "recipes": [],
        "new_source_extension": {"lossless": ["value"]},
        "extracted_at": "2026-07-27T03:59:24.856Z",
    }


def indexed_manifest(*records: dict) -> dict:
    rows = list(records)
    return correction.index_complete_manifest(
        {
            "version": 1,
            "source_model_count": len(rows),
            "record_count": len(rows),
            "completed_at": "2026-07-27T04:00:00Z",
            "records": rows,
        },
        manifest_file_sha256="f" * 64,
    )


def model_state(current_action: dict, **legacy_extension: object) -> dict:
    return {
        "id": 2315,
        "code": "TJ-2205-1",
        "name": "4112",
        "product_type": "Туника",
        "details_json": {
            "general": {"model_no": "TJ-2205", "variant_no": "1"},
            "old_erp_migration": copy.deepcopy(current_action["provenance"]),
            **legacy_extension,
        },
        "images": [],
    }


def state_from_details(details: dict) -> dict:
    """A model state whose stored ``details_json`` is exactly ``details``."""
    state = model_state(action())
    state["details_json"] = copy.deepcopy(details)
    return state


def plan(state: dict, record: dict) -> dict:
    return correction.plan_model_correction(
        state,
        action=action(),
        created=True,
        complete_records={35: record},
        manifest=indexed_manifest(record),
    )


# --------------------------------------------------------------------------
# Reproductions: a correction that CHANGES details_json must not be able to
# store a document the API write path would refuse.
# --------------------------------------------------------------------------


def test_changed_correction_rejects_oversized_details_json() -> None:
    record = complete_record()
    state = model_state(action(), legacy_extension="x" * (MAX_BYTES + 1024))
    state_before = copy.deepcopy(state)

    with pytest.raises(correction.MigrationError, match="details_json cannot exceed"):
        plan(state, record)

    assert state == state_before


def test_changed_correction_rejects_too_deep_details_json() -> None:
    record = complete_record()
    state = model_state(action(), legacy_extension=nested_legacy_value())
    state_before = copy.deepcopy(state)

    with pytest.raises(correction.MigrationError, match="details_json cannot exceed"):
        plan(state, record)

    assert state == state_before


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_changed_correction_rejects_non_finite_details_json(value: float) -> None:
    """A non-finite value is not JSON, so it must never reach the column.

    ``json.dumps`` happily emits a bare ``NaN`` token, so nothing else in this
    offline pass would notice the document had become unreadable.
    """
    record = complete_record()
    state = model_state(action(), legacy_extension=value)
    state_before = copy.deepcopy(state)

    with pytest.raises(correction.MigrationError, match="finite JSON-compatible"):
        plan(state, record)

    # ``repr`` so a NaN compares equal to itself here, as JSON never can.
    assert repr(state["details_json"]["legacy_extension"]) == repr(
        state_before["details_json"]["legacy_extension"]
    )
    assert math.isnan(value) or math.isinf(value)


def test_oversized_detail_is_actually_over_the_shared_ceiling() -> None:
    """Guards the reproduction itself: the fixture must exceed the shared limit."""
    payload = json_bytes_of({"legacy_extension": "x" * (MAX_BYTES + 1024)})

    assert len(payload) > MAX_BYTES


def json_bytes_of(value: object) -> bytes:
    import json

    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")


def test_nested_fixture_is_actually_deeper_than_the_shared_ceiling() -> None:
    def depth_of(value: object) -> int:
        if isinstance(value, dict):
            return 1 + max((depth_of(child) for child in value.values()), default=0)
        if isinstance(value, list):
            return 1 + max((depth_of(child) for child in value), default=0)
        return 0

    assert depth_of(nested_legacy_value()) > MAX_DEPTH


# --------------------------------------------------------------------------
# The guard must be the shared one, not a second copy that can drift.
# --------------------------------------------------------------------------


def test_correction_reuses_the_shared_catalog_validator(monkeypatch) -> None:
    """Fail if the script stops calling the validator the API write path uses."""
    import app.api.routes.catalog as catalog

    calls: list[tuple[object, object]] = []

    def spy(details: object, *, existing_details: object = None) -> None:
        calls.append((details, existing_details))
        _validate_model_details_json_bounds(details, existing_details=existing_details)

    monkeypatch.setattr(catalog, "_validate_model_details_json_bounds", spy)
    record = complete_record()

    plan(model_state(action()), record)

    assert len(calls) == 1, "correction must delegate to the shared validator"


def test_correction_reports_a_bound_failure_as_a_migration_error() -> None:
    """The script's own error type, not a bare web-framework HTTPException.

    ``compile_correction_plan`` collects ``MigrationError`` per model into the
    plan's blocking issues; any other exception type escapes that collection.
    """
    from fastapi import HTTPException

    record = complete_record()
    state = model_state(action(), legacy_extension="x" * (MAX_BYTES + 1024))

    with pytest.raises(correction.MigrationError) as excinfo:
        plan(state, record)

    assert not isinstance(excinfo.value, HTTPException)
    assert "Corrected Model.details_json is invalid" in str(excinfo.value)


# --------------------------------------------------------------------------
# Grandfathering and no-behaviour-change guards.
# --------------------------------------------------------------------------


def test_unchanged_oversized_and_deep_legacy_document_is_grandfathered() -> None:
    """A row that predates the ceilings and is not changed stays planable.

    A second pass over an already-corrected row changes nothing, so the
    oversized/deep legacy extension it carries is passed through untouched
    rather than blocking the pass.
    """
    record = complete_record()
    first = plan(model_state(action()), record)
    legacy_details = copy.deepcopy(first["_details_after"])
    legacy_details["legacy_extension"] = {
        "large": "x" * (MAX_BYTES + 1024),
        "deep": nested_legacy_value(),
    }

    second = plan(state_from_details(legacy_details), record)

    assert second["details_changed"] is False
    assert second["_details_after"] == legacy_details


def test_changed_correction_still_rejects_a_grown_legacy_document() -> None:
    """The grandfather is not a loophole: growing such a row is still refused."""
    record = complete_record()
    first = plan(model_state(action()), record)
    legacy_details = copy.deepcopy(first["_details_after"])
    legacy_details["legacy_extension"] = {"large": "x" * (MAX_BYTES + 1024)}
    # Drop a value the pass refills, so the next plan really does change the
    # document instead of being a no-op over the legacy extension.
    legacy_details["general"].pop("legacy_company")

    with pytest.raises(correction.MigrationError, match="details_json cannot exceed"):
        plan(state_from_details(legacy_details), record)


def test_ordinary_correction_still_plans_within_bounds() -> None:
    """No behaviour change for a normal correction."""
    record = complete_record()

    result = plan(model_state(action()), record)

    assert result["details_changed"] is True
    # Raises nothing: the produced document is inside the shared ceilings.
    _validate_model_details_json_bounds(result["_details_after"])
    assert result["new_name"] == "Туника"
