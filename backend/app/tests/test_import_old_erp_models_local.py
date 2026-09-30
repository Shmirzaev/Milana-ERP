from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest

from scripts import import_old_erp_models_local as migration


def test_canonical_identity_preserves_non_confusable_unicode() -> None:
    assert migration.base_key(" ХJ-3062 ") == "XJ3062"
    assert migration.base_key("Ф-2544") == "Ф2544"
    assert migration.base_key("РJ_1000") == "PJ1000"
    assert migration.variant_key("V-0001") == "1"
    assert migration.variant_key(" v_01 ") == "1"
    assert migration.identity_key("ХJ-3062", "V-05579") == "XJ3062|5579"


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("PJ-1023V V-5330", ("PJ-1023V", "5330")),
        ("TJ2160V-4105", ("TJ2160", "4105")),
        ("XJ-3074-V3849", ("XJ-3074", "3849")),
        ("xj3112 v-5143", ("xj3112", "5143")),
        ("D-5001", None),
        ("", None),
    ],
)
def test_explicit_variant_parser_does_not_invent_variant_one(
    source: str,
    expected: tuple[str, str] | None,
) -> None:
    assert migration.parse_explicit_variant(source) == expected


def test_deterministic_display_code_normalization() -> None:
    assert migration.display_base("xj3164") == "XJ-3164"
    assert migration.display_base(" ХJ_3062 ") == "XJ-3062"
    assert migration.display_base("D-5001") == "D-5001"
    assert migration.display_base("Ф2544") == "Ф-2544"


def test_validated_mirror_can_only_change_image_fields() -> None:
    raw = {
        1: {
            "old_model_id": 1,
            "code": "XJ1000",
            "name": "Name",
            "primary_image": {"path": "raw.jpg", "sha256": "a"},
        }
    }
    validated = {
        1: {
            "old_model_id": 1,
            "code": "XJ1000",
            "name": "Name",
            "primary_image": {"path": "repaired.jpg", "sha256": "b"},
        }
    }
    migration.verify_validated_mirror(
        raw,
        validated,
        image_fields=migration.MODEL_IMAGE_FIELDS,
        label="models",
    )
    validated[1]["name"] = "Changed"
    with pytest.raises(migration.MigrationError, match="non-image data"):
        migration.verify_validated_mirror(
            raw,
            validated,
            image_fields=migration.MODEL_IMAGE_FIELDS,
            label="models",
        )


def test_duplicate_variant_conflict_is_quarantinable_by_role() -> None:
    group = {
        "children": [
            {
                "old_variant_id": 1,
                "color": "Blue",
                "design": "",
                "sew_model_name": "Tunic",
                "thermal_print": "-",
                "embroidery": "-",
                "main_image": {"sha256": "a" * 64},
                "thermal_image": None,
                "embroidery_image": None,
                "design_image": None,
            },
            {
                "old_variant_id": 2,
                "color": "Red",
                "design": "",
                "sew_model_name": "Tunic",
                "thermal_print": "-",
                "embroidery": "-",
                "main_image": {"sha256": "b" * 64},
                "thermal_image": None,
                "embroidery_image": None,
                "design_image": None,
            },
        ],
        "explicit": [],
    }
    conflicts = migration.source_conflicts_for_variant(group)
    assert {row["role"] for row in conflicts} == {"color", "main_image"}


def test_standalone_self_referential_name_is_not_a_conflict() -> None:
    rows = [
        {
            "old_model_id": 1,
            "code": "D-5001",
            "name": "D5001",
            "product": "Dress",
            "style": "",
            "company": "",
            "primary_image": {"sha256": "a" * 64},
        },
        {
            "old_model_id": 2,
            "code": "D5001",
            "name": "",
            "product": "Dress",
            "style": "",
            "company": "",
            "primary_image": {"sha256": "a" * 64},
        },
    ]
    assert migration.source_conflicts_for_standalone(rows) == []
    rows[1]["primary_image"] = {"sha256": "b" * 64}
    conflicts = migration.source_conflicts_for_standalone(rows)
    assert [row["role"] for row in conflicts] == ["standalone_primary_image"]


def test_output_files_must_be_distinct(tmp_path) -> None:
    same = tmp_path / "result.json"
    with pytest.raises(migration.MigrationError, match="must be different"):
        migration.preflight_output_paths(same, same, overwrite=False)


def test_sizes_manifest_accepts_progress_records_wrapper() -> None:
    payload = {
        "version": 1,
        "source_models_sha256": "a" * 64,
        "records": {
            "42": {
                "old_model_id": 42,
                "scalar": {"description": "Legacy description"},
                "sizes": ["S", {"size": "M", "measurement_json": {"chest": 90}}],
                "checks": {"size_button_count": 1},
            }
        },
    }
    indexed = migration.load_sizes(payload)
    assert list(indexed) == [42]
    assert [row["size"] for row in indexed[42]["sizes"]] == ["S", "M"]
    assert indexed[42]["raw"]["checks"] == {"size_button_count": 1}


def test_new_variant_protected_fields_come_from_exact_parent_not_db_group() -> None:
    parent = {
        "old_model_id": 10,
        "code": "XJ1000",
        "name": "Exact parent name",
        "primary_image": {
            "sha256": "a" * 64,
            "source_path": "images/model.jpg",
        },
    }
    arbitrary_db_image = SimpleNamespace(
        id=1,
        image_type="model",
        is_primary=True,
        file_url="/storage/model-files/arbitrary.jpg",
        file_data=None,
    )
    arbitrary_db_model = SimpleNamespace(
        id=1,
        name="Do not inherit",
        images=[arbitrary_db_image],
    )
    name, image, warnings = migration.source_protected_defaults(
        group={
            "explicit": [],
            "child_parent_ids": {10},
        },
        sources={"models": {10: parent}, "sizes": {}},
        db_group=[arbitrary_db_model],
        target_media_dir=None,
    )
    assert name == "Exact parent name"
    assert image is not None
    assert image["sha256"] == "a" * 64
    assert image["image_type"] == "model"
    assert warnings == []


def test_conflicting_exact_parent_pictures_are_omitted_without_unique_evidence() -> None:
    parents = {
        10: {
            "old_model_id": 10,
            "code": "XJ1000",
            "name": "Same name",
            "primary_image": {
                "sha256": "a" * 64,
                "source_path": "images/a.jpg",
            },
        },
        11: {
            "old_model_id": 11,
            "code": "XJ1000",
            "name": "Same name",
            "primary_image": {
                "sha256": "b" * 64,
                "source_path": "images/b.jpg",
            },
        },
    }
    name, image, warnings = migration.source_protected_defaults(
        group={
            "explicit": [],
            "child_parent_ids": {10, 11},
        },
        sources={"models": parents, "sizes": {}},
        db_group=[],
        target_media_dir=None,
    )
    assert name == "Same name"
    assert image is None
    assert warnings == ["exact_parent_master_picture_omitted_no_unique_evidence"]


def test_conflicting_parent_picture_uses_only_unique_db_content_match(tmp_path) -> None:
    matching_content = b"reviewed-current-picture"
    matching_sha = hashlib.sha256(matching_content).hexdigest()
    other_sha = "b" * 64
    (tmp_path / "current.jpg").write_bytes(matching_content)
    parents = {
        10: {
            "old_model_id": 10,
            "code": "TJ2010",
            "name": "Same name",
            "primary_image": {
                "sha256": matching_sha,
                "source_path": "images/matching.jpg",
            },
        },
        11: {
            "old_model_id": 11,
            "code": "TJ2010",
            "name": "Same name",
            "primary_image": {
                "sha256": other_sha,
                "source_path": "images/other.jpg",
            },
        },
    }
    db_image = SimpleNamespace(
        id=1,
        image_type="model",
        is_primary=True,
        file_url="/storage/model-files/current.jpg",
        file_data=None,
    )
    db_model = SimpleNamespace(id=1, images=[db_image])
    _, image, warnings = migration.source_protected_defaults(
        group={"explicit": [], "child_parent_ids": {10, 11}},
        sources={"models": parents, "sizes": {}},
        db_group=[db_model],
        target_media_dir=tmp_path,
    )
    assert image is not None
    assert image["sha256"] == matching_sha
    assert warnings == ["exact_parent_master_picture_resolved_by_unique_db_hash_match"]


def test_metadata_fills_missing_fields_without_overriding_primary_master() -> None:
    primary = {
        "old_model_id": 1,
        "code": "TJ2026",
        "name": "Exact parent",
        "product": "Primary product",
    }
    metadata = {
        "old_model_id": 2,
        "code": "TJ2026",
        "name": "",
        "product": "Metadata product must not override",
    }
    fields, warnings = migration.consensus_with_metadata_fallback(
        [primary],
        [metadata],
        {
            2: {
                "scalar": {
                    "description": "Metadata description",
                    "date": "2020-01-02",
                }
            }
        },
    )
    assert fields["product"] == "Primary product"
    assert fields["description"] == "Metadata description"
    assert fields["source_date"] == "2020-01-02"
    assert warnings == []
    no_name_fields, _ = migration.consensus_with_metadata_fallback(
        [{**primary, "name": "TJ2026", "product": ""}],
        [{**metadata, "name": "Metadata must not name the variant"}],
        {},
    )
    assert "name" not in no_name_fields


def test_source_group_metadata_precedes_current_db_base_membership() -> None:
    source_row = {
        "old_model_id": 10,
        "code": "TJ2026",
        "name": "TJ2026",
        "product": "Tunic",
        "style": "",
        "company": "",
        "primary_image": None,
    }
    db_model = SimpleNamespace(id=90, code="TJ-2026-1")
    classification, metadata, quarantined = migration.classify_nonvariant_masters(
        sources={"models": {10: source_row}},
        parent_ids=set(),
        variant_groups={
            "TJ2026|1": {"explicit": []},
            "TJ2026|2": {"explicit": []},
        },
        db_exact={"TJ2026|1": db_model},
        db_bases={"TJ2026": [db_model]},
    )
    assert metadata == {"old_base:TJ2026": [source_row]}
    assert classification["counts"]["metadata_old_group"] == 1
    assert "metadata_db_group" not in classification["counts"]
    assert quarantined == []


def test_source_variant_metadata_precedes_new_exact_db_code() -> None:
    source_row = {
        "old_model_id": 11,
        "code": "TJ2026-170",
        "name": "TJ2026-170",
        "product": "Tunic",
        "style": "",
        "company": "",
        "primary_image": None,
    }
    db_model = SimpleNamespace(id=91, code="TJ2026-170")
    classification, metadata, quarantined = migration.classify_nonvariant_masters(
        sources={"models": {11: source_row}},
        parent_ids=set(),
        variant_groups={"TJ2026|170": {"explicit": []}},
        db_exact={"TJ2026|170": db_model},
        db_bases={"TJ2026": [db_model]},
    )
    assert metadata == {"variant:TJ2026|170": [source_row]}
    assert classification["counts"]["metadata_old_variant"] == 1
    assert quarantined == []


def test_imported_standalone_keeps_its_primary_source_role() -> None:
    source_row = {
        "old_model_id": 42,
        "code": "D-5001",
        "name": "Dress",
        "product": "Dress",
        "style": "",
        "company": "",
        "primary_image": None,
    }
    db_model = SimpleNamespace(
        id=92,
        code="D-5001",
        details_json={
            "general": {"model_no": "D-5001"},
            "old_erp_migration": {
                "source_key": migration.SOURCE_KEY,
                "identity": "D5001|",
                "master_records": [{"old_model_id": 42}],
                "metadata_only_records": [],
            },
        },
    )
    classification, metadata, quarantined = migration.classify_nonvariant_masters(
        sources={"models": {42: source_row}},
        parent_ids=set(),
        variant_groups={},
        db_exact={"D5001|": db_model},
        db_bases={"D5001": [db_model]},
    )
    assert metadata == {}
    assert classification["standalone"] == {"D5001": [source_row]}
    assert classification["counts"]["safe_standalone_identities"] == 1
    assert quarantined == []


def test_existing_metadata_plan_keeps_only_missing_values_and_real_provenance_delta() -> None:
    provenance = {
        "source_key": migration.SOURCE_KEY,
        "source_files": {
            "models_source_sha256": "a" * 64,
            "variants_source_sha256": "b" * 64,
            "validated_models_sha256": "c" * 64,
            "validated_variants_sha256": "d" * 64,
        },
        "identity": "TJ2026|170",
        "master_records": [{"old_model_id": 1}],
        "variant_records": [],
        "metadata_only_records": [],
        "validated_images": {"models": {}, "variants": {}},
        "details_and_sizes": {},
    }
    model = SimpleNamespace(
        details_json={
            "general": {
                "model_no": "TJ2026",
                "variant_no": "170",
                "legacy_product": "Tunic",
            },
            "old_erp_migration": provenance,
        }
    )
    assert migration.missing_details_patch(
        model,
        {
            "model_no": "TJ2026",
            "variant_no": "170",
            "legacy_product": "Tunic",
            "legacy_source_date": "2020-01-02",
        },
    ) == {"legacy_source_date": "2020-01-02"}
    assert migration.provenance_would_change(model, provenance) is False
    changed = {**provenance, "metadata_only_records": [{"old_model_id": 2}]}
    assert migration.provenance_would_change(model, changed) is True

    converged_details = {
        **model.details_json,
        "general": {
            **model.details_json["general"],
            "legacy_source_date": "2020-01-02",
        },
    }
    migration.merge_provenance(converged_details, changed)
    converged = SimpleNamespace(
        product_type="Tunic",
        description=None,
        details_json=converged_details,
    )
    assert migration.scalar_fills(converged, {"product": "Tunic"}) == {}
    assert migration.missing_details_patch(
        converged,
        {"legacy_source_date": "2020-01-02"},
    ) == {}
    assert migration.provenance_would_change(converged, changed) is False
