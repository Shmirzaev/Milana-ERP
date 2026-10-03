"""The old-ERP import must not store a ``details_json`` the ERP cannot read back.

DB03-MODEL bounded every catalog write path. This module covers the offline
import script, which reaches ``Model.details_json`` through its own
``apply_details`` and therefore had no ceiling of its own.
"""

from __future__ import annotations

import copy
import json

import pytest

from app.models import Model
from scripts import import_old_erp_models_local as migration

# Read from the shared validator rather than restating the numbers, so this
# module fails if the ceilings are ever retuned in catalog.py.
from app.api.routes.catalog import (
    _MAX_MODEL_DETAILS_JSON_BYTES,
    _MAX_MODEL_DETAILS_JSON_DEPTH,
    _validate_model_details_json_bounds,
)

GUARDED_MESSAGE = "Imported Model.details_json is invalid"


def _provenance() -> dict:
    return {
        "source_key": migration.SOURCE_KEY,
        "source_files": {},
        "identity": "TEST|1",
        "master_records": [],
        "variant_records": [],
        "metadata_only_records": [],
        "details_and_sizes": {},
        "validated_images": {"models": {}, "variants": {}},
    }


def _model(details: object) -> Model:
    return Model(code="TEST", name="Test", details_json=copy.deepcopy(details))


def _oversized() -> str:
    return "x" * (_MAX_MODEL_DETAILS_JSON_BYTES + 1024)


def _too_deep() -> dict:
    nested: dict = {"leaf": True}
    for _ in range(_MAX_MODEL_DETAILS_JSON_DEPTH + 4):
        nested = {"next": nested}
    return nested


def test_shared_validator_is_reused_not_reimplemented() -> None:
    """The import script must delegate to the one shared guard.

    A second local copy of the ceilings would drift from the catalog write
    paths, which is exactly how the two sides diverged in the first place.
    """

    assert migration._validate_model_details_json_bounds is _validate_model_details_json_bounds


@pytest.mark.parametrize(
    ("invalid_kind", "invalid_value"),
    [
        pytest.param("oversized_bytes", _oversized(), id="oversized_bytes"),
        pytest.param("too_deep", _too_deep(), id="too_deep"),
        pytest.param("non_finite_number", float("nan"), id="non_finite_number"),
        pytest.param("non_finite_infinity", float("inf"), id="non_finite_infinity"),
        pytest.param("unserializable_value", object(), id="unserializable_value"),
    ],
)
def test_apply_details_refuses_unbounded_document_without_mutating(
    invalid_kind: str,
    invalid_value: object,
) -> None:
    original = {"general": {}}
    model = _model(original)

    with pytest.raises(migration.MigrationError, match=GUARDED_MESSAGE):
        migration.apply_details(
            model,
            {"legacy_product": invalid_value},
            _provenance(),
            created=True,
        )

    # A refused write must leave the row exactly as it was, so a failed import
    # cannot leave a half-applied document behind.
    assert model.details_json == original


def test_apply_details_refuses_oversized_legacy_document_even_when_unchanged() -> None:
    """The import is not grandfathered the way a catalog client edit is.

    ``apply_details`` builds the document itself from the legacy payload, so
    unlike an HTTP client that can only re-save what it read, there is no
    "the user did not change anything" case to protect. Re-running an import
    that would write nothing new is exactly how an unbounded legacy payload
    stays blessed forever, so the import validates unconditionally.
    """

    oversized = {"general": {}, "legacy_extension": _oversized()}
    model = _model(oversized)

    with pytest.raises(migration.MigrationError, match=GUARDED_MESSAGE):
        migration.apply_details(model, {}, _provenance(), created=False)

    assert model.details_json == oversized


def test_apply_details_refuses_nan_that_pydantic_would_silently_null() -> None:
    """A stored NaN is not merely unparseable, it silently changes meaning.

    ``json.dumps`` writes the non-standard ``NaN`` token, and Pydantic's JSON
    serializer coerces it to ``null`` on the way out, so the value a client
    reads back is not the value the import stored.
    """

    model = _model({"general": {}})

    with pytest.raises(migration.MigrationError, match=GUARDED_MESSAGE):
        migration.apply_details(
            model,
            {"legacy_measurement": float("nan")},
            _provenance(),
            created=True,
        )

    assert "legacy_measurement" not in model.details_json["general"]


def test_apply_details_accepts_bounded_document() -> None:
    model = _model({})

    migration.apply_details(
        model,
        {"legacy_product": "Tunic"},
        _provenance(),
        created=True,
    )

    assert model.details_json["general"]["legacy_product"] == "Tunic"
    assert model.details_json["old_erp_migration"]["identity"] == "TEST|1"
    # A guarded write is still readable by an ordinary strict JSON consumer.
    assert json.loads(json.dumps(model.details_json, allow_nan=False))["general"]


def test_apply_details_accepts_document_just_under_the_ceiling() -> None:
    """The guard must reject only what is genuinely over the line."""

    model = _model({})
    padding = "x" * (_MAX_MODEL_DETAILS_JSON_BYTES - 2048)

    migration.apply_details(model, {"legacy_product": padding}, _provenance(), created=True)

    assert len(json.dumps(model.details_json, ensure_ascii=False).encode("utf-8")) < _MAX_MODEL_DETAILS_JSON_BYTES
