from copy import deepcopy

import pytest

from app.models import Model
from scripts.import_model_catalog import upsert_details


RECORD = {
    "modelNo": "XJ3062",
    "variantNo": "1",
    "fabric": "Cotton",
    "sourceRows": [2, 3],
}


def _upsert(model: Model, *, record: dict = RECORD, preserve_existing: bool = False) -> None:
    upsert_details(
        model,
        record,
        source_key="catalog-2026",
        workbook="catalog.xlsx",
        preserve_existing=preserve_existing,
    )


def test_catalog_details_preserve_unrelated_extensions_and_existing_general_values() -> None:
    model = Model(details_json={
        "general": {"model_no": "Owner model", "legacy_field": True},
        "legacy_extension": {"keep": [1, 2]},
        "source": {"import_key": "other"},
    })
    previous = deepcopy(model.details_json)

    _upsert(model, preserve_existing=True)

    assert previous == {
        "general": {"model_no": "Owner model", "legacy_field": True},
        "legacy_extension": {"keep": [1, 2]},
        "source": {"import_key": "other"},
    }
    assert model.details_json["general"]["model_no"] == "Owner model"
    assert model.details_json["general"]["variant_no"] == "1"
    assert model.details_json["legacy_extension"] == previous["legacy_extension"]
    assert model.details_json["source"] == previous["source"]
    assert {entry["import_key"] for entry in model.details_json["sources"]} == {"other", "catalog-2026"}


@pytest.mark.parametrize("invalid_kind", ["oversized", "deep"])
def test_catalog_details_reject_changed_unbounded_legacy_without_mutation(invalid_kind: str) -> None:
    extension: object = "x" * (70 * 1024) if invalid_kind == "oversized" else {"leaf": True}
    if invalid_kind == "deep":
        for _ in range(20):
            extension = {"next": extension}
    previous = {"legacy_extension": extension}
    model = Model(details_json=deepcopy(previous))

    with pytest.raises(ValueError, match="details_json cannot exceed"):
        _upsert(model)

    assert model.details_json == previous


def test_exact_repeat_import_keeps_oversized_legacy_document_and_timestamp() -> None:
    source = {
        "import_key": "catalog-2026",
        "workbook": "catalog.xlsx",
        "excel_rows": [2, 3],
        "imported_at": "2026-01-01T00:00:00+00:00",
    }
    previous = {
        "general": {"model_no": "XJ3062", "variant_no": "1", "variant_fabric": "Cotton"},
        "source": deepcopy(source),
        "sources": [deepcopy(source)],
        "legacy_extension": "x" * (70 * 1024),
    }
    model = Model(details_json=deepcopy(previous))
    original_details = model.details_json

    _upsert(model)

    assert model.details_json == previous
    assert model.details_json is original_details


def test_catalog_details_reject_oversized_manifest_rows_before_assignment() -> None:
    model = Model(details_json={})
    original_details = model.details_json

    with pytest.raises(ValueError, match="details_json cannot exceed"):
        _upsert(model, record={**RECORD, "sourceRows": list(range(40_000))})

    assert model.details_json is original_details
