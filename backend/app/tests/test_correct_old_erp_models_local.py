from __future__ import annotations

import copy

import pytest

from scripts import correct_old_erp_models_local as correction


def complete_record(
    old_model_id: int = 35,
    *,
    product: str = "Туника",
    name: str = "4112",
    operations: list[dict] | None = None,
    recipes: list[dict] | None = None,
) -> dict:
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
            "name": name,
            "product": product,
            "style": "Classic",
        },
        "general": {
            "Company": "Milana",
            "Date": "01/02/2025 03:04:05",
            "Description": "Exact legacy description",
            "Embroidery": False,
            "Name": name,
            "Parent Sew Model": "TJ2200",
            "Planning Type": "Order",
            "Product": product,
            "Sew Model Code": "TJ2205",
            "Style": "Classic",
            "Thermal Print": True,
            "Variant": "1",
        },
        "operations": copy.deepcopy(operations or []),
        "recipes": copy.deepcopy(recipes or []),
        "new_source_extension": {"lossless": ["value"]},
        "extracted_at": "2026-07-27T03:59:24.856Z",
    }


def raw_operation(
    *,
    stage: str = "Tikuv",
    source_order: int = 7,
) -> dict:
    return {
        "source_order": source_order,
        "name": "exact old operation",
        "duration": "1.50",
        "price": "00120.00",
        "currency": "UZB",
        "stage": stage,
        "control_change_direction": "Old → New",
        "final_operation": True,
    }


def raw_recipe() -> dict:
    return {
        "source_order": 1,
        "product": "Fabric A",
        "quantity": "1.2500",
        "sewing_type_list": "Main",
    }


def indexed_manifest(*records: dict, source_model_count: int | None = None) -> dict:
    rows = list(records)
    payload = {
        "version": 1,
        "source_model_count": (
            len(rows) if source_model_count is None else source_model_count
        ),
        "record_count": len(rows),
        "completed_at": "2026-07-27T04:00:00Z",
        "records": rows,
    }
    return correction.index_complete_manifest(
        payload,
        manifest_file_sha256="f" * 64,
    )


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


def action(
    *,
    created: bool = True,
    old_model_ids: tuple[int, ...] = (35,),
    imported_name: str = "4112",
    product: str = "Туника",
) -> dict:
    common = {
        "action": "create_variant" if created else "update_existing",
        "identity": "TJ2205|1",
        "provenance": provenance(*old_model_ids),
    }
    if created:
        return {
            **common,
            "code": "TJ-2205-1",
            "name": imported_name,
            "product_type": product,
        }
    return {
        **common,
        "target_model_id": 9,
        "expected_code": "TJ-2205-1",
        "expected_name": "Protected duplicate",
    }


def model_state(
    current_action: dict,
    *,
    model_id: int = 2315,
    name: str = "4112",
    general: dict | None = None,
    paid_operations: object = ...,
) -> dict:
    details = {
        "general": copy.deepcopy(general or {"model_no": "TJ-2205", "variant_no": "1"}),
        "old_erp_migration": copy.deepcopy(current_action["provenance"]),
    }
    if paid_operations is not ...:
        details["paid_operations"] = copy.deepcopy(paid_operations)
    code = (
        current_action["code"]
        if current_action["action"] != "update_existing"
        else current_action["expected_code"]
    )
    return {
        "id": model_id,
        "code": code,
        "name": name,
        "product_type": current_action.get("product_type"),
        "details_json": details,
        "images": [
            {
                "id": 90,
                "file_url": "/storage/model-files/protected.jpg",
                "file_data_sha256": "c" * 64,
                "is_primary": True,
            }
        ],
    }


@pytest.mark.parametrize(
    ("stage", "section"),
    [
        ("Tikuv", "sewing"),
        ("Кнопки", "sewing"),
        ("Упаковка", "packaging"),
        ("Склад", "packaging"),
        ("Чистка", "pressing"),
        ("Контроль", "sewing"),
    ],
)
def test_paid_operation_maps_every_source_field_exactly(
    stage: str,
    section: str,
) -> None:
    raw = raw_operation(stage=stage)
    mapped = correction.canonical_paid_operation(raw)

    assert mapped["section"] == section
    assert mapped["name"] == raw["name"]
    assert mapped["rate"] == "00120.00"
    assert mapped["sourceOrder"] == 7
    assert mapped["duration"] == "1.50"
    assert mapped["currency"] == "UZB"
    assert mapped["sourceStage"] == stage
    assert mapped["changeDirection"] == "Old → New"
    assert mapped["finalOperation"] is True
    assert mapped["selected"] is True
    assert mapped["quantityMode"] == "batch"
    assert mapped["customQuantity"] == 0
    assert mapped["copies"] == 1
    assert mapped["splitMode"] == "none"
    assert mapped["splitQuantities"] == []
    assert mapped["id"].startswith("old-erp-op-")
    assert mapped["code"].startswith("OERP-")
    assert correction.canonical_paid_operation(raw) == mapped


def test_paid_operation_union_is_deterministic_and_deduplicated() -> None:
    operation = raw_operation()
    first = complete_record(35, operations=[operation])
    second = complete_record(36, operations=[copy.deepcopy(operation)])

    assert correction.canonical_paid_operations([second, first]) == [
        correction.canonical_paid_operation(operation)
    ]


@pytest.mark.parametrize("imported_name", ["4112", "", "Legacy tunic"])
def test_import_created_name_uses_exact_product_for_every_mismatch_kind(
    imported_name: str,
) -> None:
    prior_action = action(imported_name=imported_name)
    state = model_state(prior_action, name=imported_name)
    record = complete_record(product="Туника")
    result = correction.plan_model_correction(
        state,
        action=prior_action,
        created=True,
        complete_records={35: record},
        manifest=indexed_manifest(record),
    )

    assert result["name_decision"]["status"] == "update"
    assert result["new_name"] == "Туника"
    assert state["name"] == imported_name


def test_manual_name_drift_is_skipped_and_reportable() -> None:
    prior_action = action(imported_name="4112")
    state = model_state(prior_action, name="Human-edited name")
    record = complete_record()
    result = correction.plan_model_correction(
        state,
        action=prior_action,
        created=True,
        complete_records={35: record},
        manifest=indexed_manifest(record),
    )

    assert result["name_decision"] == {
        "status": "manual_drift",
        "original_imported_name": "4112",
        "target_name": "Туника",
        "source_products": ["Туника"],
    }
    assert result["new_name"] is None


def test_complete_source_supplies_product_missing_from_original_plan() -> None:
    prior_action = action(imported_name="", product="")
    state = model_state(prior_action, name="")
    record = complete_record(product="Туника")
    result = correction.plan_model_correction(
        state,
        action=prior_action,
        created=True,
        complete_records={35: record},
        manifest=indexed_manifest(record),
    )

    assert result["name_decision"]["status"] == "update"
    assert result["new_name"] == "Туника"


def test_conflicting_complete_products_are_preserved_raw_without_renaming() -> None:
    prior_action = action(
        old_model_ids=(35, 36),
        imported_name="",
        product="",
    )
    state = model_state(prior_action, name="")
    first = complete_record(35, product="Туника")
    second = complete_record(36, product="Футболка")
    result = correction.plan_model_correction(
        state,
        action=prior_action,
        created=True,
        complete_records={35: first, 36: second},
        manifest=indexed_manifest(first, second),
    )

    assert result["name_decision"]["status"] == "product_conflict"
    assert result["name_decision"]["source_products"] == [
        "Туника",
        "Футболка",
    ]
    assert result["new_name"] is None
    sections = result["_details_after"]["old_erp_migration"]["complete_sections"]
    assert sections["general"]["35"]["Product"] == "Туника"
    assert sections["general"]["36"]["Product"] == "Футболка"


def test_preexisting_duplicate_never_changes_name_or_images() -> None:
    prior_action = action(created=False)
    state = model_state(
        prior_action,
        model_id=9,
        name="Protected duplicate",
    )
    state_before = copy.deepcopy(state)
    record = complete_record(35, operations=[raw_operation()], recipes=[raw_recipe()])
    result = correction.plan_model_correction(
        state,
        action=prior_action,
        created=False,
        complete_records={35: record},
        manifest=indexed_manifest(record),
    )

    assert result["origin"] == "preexisting"
    assert result["name_decision"]["status"] == "protected_preexisting"
    assert result["new_name"] is None
    assert state == state_before
    assert result["expected_images_sha256"] == correction.original.object_sha256(
        state_before["images"]
    )
    assert result["_details_after"]["paid_operations"][0]["rate"] == "00120.00"


def test_explicit_zero_operations_suppresses_frontend_defaults() -> None:
    prior_action = action()
    state = model_state(prior_action)
    record = complete_record(35, operations=[])
    result = correction.plan_model_correction(
        state,
        action=prior_action,
        created=True,
        complete_records={35: record},
        manifest=indexed_manifest(record),
    )

    assert result["paid_operations_status"] == "filled_explicit_empty"
    assert result["_details_after"]["paid_operations"] == []


def test_existing_paid_operations_are_preserved_while_raw_source_is_added() -> None:
    prior_action = action()
    manual_operations = [{"id": "manual", "name": "Do not overwrite"}]
    state = model_state(
        prior_action,
        paid_operations=manual_operations,
    )
    record = complete_record(35, operations=[raw_operation()])
    result = correction.plan_model_correction(
        state,
        action=prior_action,
        created=True,
        complete_records={35: record},
        manifest=indexed_manifest(record),
    )
    details = result["_details_after"]

    assert result["paid_operations_status"] == "preserved_existing_paid_operations"
    assert details["paid_operations"] == manual_operations
    assert details["old_erp_migration"]["complete_sections"]["operations"]["35"] == [
        raw_operation()
    ]


def test_complete_sections_are_lossless_and_recipes_remain_metadata_only() -> None:
    prior_action = action()
    state = model_state(prior_action)
    record = complete_record(
        35,
        operations=[raw_operation()],
        recipes=[raw_recipe()],
    )
    result = correction.plan_model_correction(
        state,
        action=prior_action,
        created=True,
        complete_records={35: record},
        manifest=indexed_manifest(record),
    )
    sections = result["_details_after"]["old_erp_migration"]["complete_sections"]

    assert sections["source_record_ids"] == [35]
    assert sections["general"]["35"] == record["general"]
    assert sections["operations"]["35"] == record["operations"]
    assert sections["recipes"]["35"] == record["recipes"]
    assert sections["record_metadata"]["35"] == {
        key: value
        for key, value in record.items()
        if key not in {"general", "operations", "recipes"}
    }
    assert "bom" not in result["_details_after"]
    assert "items" not in result["_details_after"]


def test_second_correction_pass_is_idempotent() -> None:
    prior_action = action()
    record = complete_record(
        35,
        operations=[raw_operation()],
        recipes=[raw_recipe()],
    )
    manifest = indexed_manifest(record)
    first_state = model_state(prior_action)
    first = correction.plan_model_correction(
        first_state,
        action=prior_action,
        created=True,
        complete_records={35: record},
        manifest=manifest,
    )
    second_state = {
        **first_state,
        "name": first["new_name"],
        "details_json": copy.deepcopy(first["_details_after"]),
    }
    second = correction.plan_model_correction(
        second_state,
        action=prior_action,
        created=True,
        complete_records={35: record},
        manifest=manifest,
    )

    assert second["name_decision"]["status"] == "already_correct"
    assert second["new_name"] is None
    assert second["details_changed"] is False
    assert second["complete_sections_changed"] is False
    assert second["paid_operations_status"] == "already_exact"
    assert second["_details_after"] == first["_details_after"]


def test_general_values_fill_only_missing_fields() -> None:
    prior_action = action()
    state = model_state(
        prior_action,
        general={
            "model_no": "TJ-2205",
            "variant_no": "1",
            "legacy_company": "Manual company",
        },
    )
    record = complete_record()
    result = correction.plan_model_correction(
        state,
        action=prior_action,
        created=True,
        complete_records={35: record},
        manifest=indexed_manifest(record),
    )
    general = result["_details_after"]["general"]

    assert general["legacy_company"] == "Manual company"
    assert result["preserved_general"]["legacy_company"] == "Manual company"
    assert general["legacy_description"] == "Exact legacy description"
    assert general["legacy_sew_model_name"] == "4112"
    assert general["legacy_master_embroidery"] is False
    assert general["legacy_master_thermal_print"] is True


def test_every_provenance_reference_must_exist_and_gaps_are_listed() -> None:
    provenance_ids = {2315: [35, 36], 9: [35]}
    record = complete_record(35)
    referenced, missing, unlinked = correction.manifest_linkage_gaps(
        provenance_ids,
        {35: record, 99: complete_record(99)},
    )

    assert referenced == [35, 36]
    assert missing == [36]
    assert unlinked == [99]

    prior_action = action(old_model_ids=(35, 36))
    state = model_state(prior_action)
    with pytest.raises(correction.MigrationError, match="old ids 36"):
        correction.plan_model_correction(
            state,
            action=prior_action,
            created=True,
            complete_records={35: record},
            manifest=indexed_manifest(record),
        )


def test_progress_wrapper_is_not_accepted_as_final_combined_manifest() -> None:
    with pytest.raises(
        correction.MigrationError,
        match=r"manifest\.record_count must be an integer",
    ):
        correction.index_complete_manifest(
            {
                "version": 1,
                "source_model_count": 3072,
                "completed_count": 3072,
                "failure_count": 0,
                "records": [complete_record()],
            },
            manifest_file_sha256="f" * 64,
        )


def test_source_scope_refuses_appended_models_and_unauthenticated_variants() -> None:
    appended_ids = list(range(3125, 3132))
    manifest = indexed_manifest(
        *(complete_record(old_model_id) for old_model_id in appended_ids),
        source_model_count=3072,
    )
    receipt = {
        "prior_source_model_count": 3065,
        "prior_source_variant_count": 5153,
        "prior_source_max_old_model_id": 3124,
        "prior_source_max_old_variant_id": 5580,
    }

    scope = correction.correction_source_scope(receipt, manifest)
    issue = correction.source_scope_blocking_issue(scope)

    assert scope == {
        "prior_receipt_source_model_count": 3065,
        "complete_manifest_source_model_count": 3072,
        "source_model_count_delta": 7,
        "prior_receipt_max_old_model_id": 3124,
        "appended_old_model_record_count": 7,
        "appended_old_model_ids": appended_ids,
        "prior_receipt_source_variant_count": 5153,
        "prior_receipt_max_old_variant_id": 5580,
        "complete_manifest_has_authenticated_variant_scope": False,
        "is_exact_prior_receipt_scope": False,
    }
    assert issue is not None
    assert issue["reason"] == (
        "supplemental_source_delta_requires_separate_import"
    )
    assert "cannot create appended catalog rows" in issue["required_action"]
    assert correction.source_scope_blocking_issue(
        {
            **scope,
            "source_model_count_delta": 0,
            "appended_old_model_record_count": 0,
            "appended_old_model_ids": [],
            "is_exact_prior_receipt_scope": True,
        }
    ) is None


def test_provenance_drift_fails_closed() -> None:
    prior_action = action()
    state = model_state(prior_action)
    state["details_json"]["old_erp_migration"]["identity"] = "OTHER|1"
    record = complete_record()

    with pytest.raises(correction.MigrationError, match="provenance differs"):
        correction.plan_model_correction(
            state,
            action=prior_action,
            created=True,
            complete_records={35: record},
            manifest=indexed_manifest(record),
        )


def test_hash_pinned_additive_provenance_is_allowed_but_tampering_is_not() -> None:
    prior_action = action(old_model_ids=(35,))
    evidence_action = action(old_model_ids=(36,))
    evidence_action["provenance"]["details_and_sizes"] = {
        "36": {"sizes": [{"size": "M"}]}
    }
    evidence_action["provenance"]["validated_images"]["models"] = {
        "36": {"sha256": "d" * 64}
    }
    evidence = correction.index_receipt_provenance_evidence(
        [prior_action, evidence_action]
    )
    state = model_state(prior_action)
    extra_row = copy.deepcopy(evidence_action["provenance"]["master_records"][0])
    state["details_json"]["old_erp_migration"]["metadata_only_records"].append(
        extra_row
    )
    state["details_json"]["old_erp_migration"]["details_and_sizes"]["36"] = {
        "sizes": [{"size": "M"}]
    }
    state["details_json"]["old_erp_migration"]["validated_images"]["models"][
        "36"
    ] = {"sha256": "d" * 64}
    first = complete_record(35)
    second = complete_record(36)

    result = correction.plan_model_correction(
        state,
        action=prior_action,
        created=True,
        complete_records={35: first, 36: second},
        manifest=indexed_manifest(first, second),
        provenance_evidence=evidence,
    )
    assert result["source_record_ids"] == [35, 36]

    with pytest.raises(correction.MigrationError, match="old ids 36"):
        correction.plan_model_correction(
            state,
            action=prior_action,
            created=True,
            complete_records={35: first},
            manifest=indexed_manifest(first),
            provenance_evidence=evidence,
        )

    state["details_json"]["old_erp_migration"]["metadata_only_records"][0][
        "name"
    ] = "tampered"
    with pytest.raises(
        correction.MigrationError,
        match="lacks exact hash-pinned receipt evidence",
    ):
        correction.plan_model_correction(
            state,
            action=prior_action,
            created=True,
            complete_records={35: first, 36: second},
            manifest=indexed_manifest(first, second),
            provenance_evidence=evidence,
        )


def test_genuine_source_record_cannot_be_reassigned_across_model_bases() -> None:
    prior_action = action(old_model_ids=(35,))
    unrelated_action = action(old_model_ids=(36,))
    unrelated_action["identity"] = "OTHER|2"
    unrelated_action["provenance"]["identity"] = "OTHER|2"
    evidence = correction.index_receipt_provenance_evidence(
        [prior_action, unrelated_action]
    )
    state = model_state(prior_action)
    state["details_json"]["old_erp_migration"]["metadata_only_records"].append(
        copy.deepcopy(unrelated_action["provenance"]["master_records"][0])
    )
    first = complete_record(35)
    second = complete_record(36)

    with pytest.raises(
        correction.MigrationError,
        match="not authorized for identity",
    ):
        correction.plan_model_correction(
            state,
            action=prior_action,
            created=True,
            complete_records={35: first, 36: second},
            manifest=indexed_manifest(first, second),
            provenance_evidence=evidence,
        )


def test_unknown_source_stage_fails_closed() -> None:
    with pytest.raises(
        correction.MigrationError,
        match="Unsupported old-ERP operation stage",
    ):
        correction.canonical_paid_operation(raw_operation(stage="Unknown"))


def test_outputs_cannot_alias_hash_pinned_inputs_or_backup(tmp_path) -> None:
    frozen_plan = tmp_path / "prior-plan.json"
    frozen_plan.write_text("{}", encoding="utf-8")
    backup = tmp_path / "local.dump"
    backup.write_bytes(b"PGDMP")

    with pytest.raises(correction.MigrationError, match="must not overwrite"):
        correction.reject_output_input_aliases(
            plan_output=frozen_plan,
            report_output=tmp_path / "report.json",
            protected_inputs=(frozen_plan, backup),
        )
    with pytest.raises(correction.MigrationError, match="must not overwrite"):
        correction.reject_output_input_aliases(
            plan_output=tmp_path / "plan.json",
            report_output=backup,
            protected_inputs=(frozen_plan, backup),
        )


def test_complete_record_must_match_frozen_receipt_identity() -> None:
    record = complete_record(35)
    receipt_row = {
        "old_model_id": 35,
        **{
            field: record["list_metadata"][field]
            for field in correction.LIST_METADATA_STRING_FIELDS
        },
        "primary_image": {"path": "legacy.jpg"},
    }
    correction.validate_complete_record_receipt_evidence(record, receipt_row)

    swapped = complete_record(36, name="Different model", product="Халат")
    swapped["old_model_id"] = 35
    swapped["list_metadata"]["old_model_id"] = 35
    swapped["source_url"] = record["source_url"]
    swapped["list_metadata"]["detail_url"] = record["list_metadata"]["detail_url"]
    with pytest.raises(
        correction.MigrationError,
        match="differs from the frozen receipt",
    ):
        correction.validate_complete_record_receipt_evidence(
            swapped,
            receipt_row,
        )


def test_backup_guard_rejects_empty_and_accepts_strict_plain_pg_dump(
    tmp_path,
) -> None:
    empty = tmp_path / "empty.sql"
    empty.write_bytes(b"")
    with pytest.raises(correction.MigrationError, match="backup is empty"):
        correction.verify_fresh_database_backup(
            empty,
            correction.original.file_sha256(empty),
            max_age_hours=24,
        )

    plain = tmp_path / "erp.sql"
    header_only = (
        b"--\n"
        b"-- PostgreSQL database dump\n"
        b"--\n"
        b"-- Dumped from database version 16.2\n"
        b"-- Dumped by pg_dump version 16.2\n"
        b"SET statement_timeout = 0;\n"
    )
    plain.write_bytes(header_only)
    with pytest.raises(correction.MigrationError, match="lacks a complete ERP"):
        correction.verify_fresh_database_backup(
            plain,
            correction.original.file_sha256(plain),
            max_age_hours=24,
        )

    plain.write_bytes(
        header_only
        + b"CREATE TABLE public.models (id integer);\n"
        + b"CREATE TABLE public.alembic_version (version_num text);\n"
        + b"COPY public.models (id) FROM stdin;\n1\n\\.\n"
        + b"COPY public.alembic_version (version_num) FROM stdin;\n0069\n\\.\n"
        + b"-- PostgreSQL database dump complete\n"
    )
    evidence = correction.verify_fresh_database_backup(
        plain,
        correction.original.file_sha256(plain),
        max_age_hours=24,
    )
    assert evidence["backup_format"] == "postgresql_plain_sql"
    assert (
        evidence["format_validation"]
        == "strict_pg_dump_header_catalog_and_footer"
    )
