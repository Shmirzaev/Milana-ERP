from __future__ import annotations

import copy
from collections import defaultdict
from types import SimpleNamespace

import pytest

from scripts import import_old_erp_model_delta_local as delta
from scripts import import_old_erp_models_local as original


def list_model(old_model_id: int, code: str, variant: str = "1") -> dict:
    return {
        "old_model_id": old_model_id,
        "code": code,
        "company": "",
        "detail_url": f"prepareSewModel.htm?id={old_model_id}",
        "has_image": False,
        "model_variant": variant,
        "name": code,
        "product": "",
        "style": "",
    }


def complete_record(old_model_id: int, row: dict) -> dict:
    return {
        "old_model_id": old_model_id,
        "source_url": (
            "https://10.100.50.199:8443/uzerp/"
            f"prepareSewModel.htm?id={old_model_id}"
        ),
        "list_metadata": copy.deepcopy(row),
        "general": {
            "Company": "",
            "Date": "01/02/2025 03:04:05",
            "Description": "Legacy description",
            "Embroidery": False,
            "Name": row["name"],
            "Parent Sew Model": "",
            "Planning Type": "",
            "Product": "Legacy product",
            "Sew Model Code": row["code"],
            "Style": "",
            "Thermal Print": False,
            "Variant": row["model_variant"],
        },
        "operations": [],
        "recipes": [],
        "new_source_extension": None,
        "extracted_at": "2026-07-27T03:59:49.183Z",
    }


def reviewed_quarantine_fixture() -> tuple[
    dict,
    dict,
    dict[int, dict],
    dict[int, dict],
    dict[int, dict],
    dict,
]:
    codes = {
        63: "TJ2017",
        430: "B-3189",
        837: "T-4697",
        1061: "T-4697",
        1204: "XJ-3001",
        1234: "B-3189",
        1262: "TJ-2017",
        1269: "XJ-3001",
        1270: "TJ-2026/2",
        1296: "TJ-2017/1",
        1334: "SJ-4002-v1",
        1345: "PJ-1003-v001",
        1386: "XJ-3016-v01",
        1400: "TJ-2016/1",
        1404: "XJ-3024v-v264",
        1425: "TJ-2000-v425",
        1441: "TJ-2000-V425",
        1462: "PJ-1030-v474",
        1464: "XJ-3024V-v264",
        1467: "SJ-4022-v556",
        1523: "PJ-1030-V474",
        1560: "sj-4022-v556",
        1683: "",
    }
    prior_models = {
        source_id: list_model(source_id, code)
        for source_id, code in codes.items()
    }
    prior_sizes = {
        source_id: {"sizes": [], "scalar": {}, "raw": {"old_model_id": source_id}}
        for source_id in prior_models
    }
    grouped_direct: dict[str | None, list[int]] = defaultdict(list)
    for source_id, identity in delta.EXPECTED_QUARANTINE_IDENTITY_BY_MODEL.items():
        if source_id not in delta.EXPECTED_HIDDEN_QUARANTINE_METADATA:
            grouped_direct[identity].append(source_id)

    identities = sorted(
        {
            identity
            for identity in delta.EXPECTED_QUARANTINE_IDENTITY_BY_MODEL.values()
            if identity is not None
        }
    )
    prior_variants: dict[int, dict] = {}
    quarantines = []
    for position, identity in enumerate(identities, start=1):
        old_variant_ids = [] if identity.endswith("|") else [position]
        if old_variant_ids:
            prior_variants[position] = {
                "old_variant_id": position,
                "color": "Blue",
            }
        quarantines.append(
            {
                "identity": identity[:-1] if identity.endswith("|") else identity,
                "reason": "reviewed_source_conflict",
                "old_model_ids": sorted(grouped_direct.get(identity) or []),
                "old_variant_ids": old_variant_ids,
                "conflicts": [{"role": "image", "values": ["a", "b"]}],
            }
        )
    quarantines.append(
        {
            "identity": "MALFORMED-MASTER-1683",
            "reason": "blank_or_unusable_master_code",
            "old_model_ids": [1683],
            "old_variant_ids": [],
            "conflicts": [],
        }
    )
    plan = {
        "quarantines": quarantines,
        "quarantine_sha256": original.object_sha256(quarantines),
    }
    receipt = {"provenance_evidence": {"model_records": {}}}
    manifest = {
        "records": {
            source_id: complete_record(source_id, row)
            for source_id, row in prior_models.items()
        }
    }
    return (
        plan,
        receipt,
        prior_models,
        prior_variants,
        prior_sizes,
        manifest,
    )


def test_append_only_proof_accepts_only_reviewed_delta_ids() -> None:
    prior_models = {1: list_model(1, "OLD")}
    prior_variants = {
        1: {
            "old_variant_id": 1,
            "color": "",
            "design": "",
            "detail_url": "id=1",
            "embroidery": "",
            "sew_model_code": "OLD",
            "sew_model_name": "OLD",
            "thermal_print": "",
            "variant_code": "1",
        }
    }
    current_models = copy.deepcopy(prior_models)
    for source_id in delta.EXPECTED_DELTA_MODEL_IDS:
        current_models[source_id] = list_model(source_id, f"N{source_id}")
    current_variants = copy.deepcopy(prior_variants)
    for source_id in delta.EXPECTED_DELTA_VARIANT_IDS:
        current_variants[source_id] = {
            **copy.deepcopy(prior_variants[1]),
            "old_variant_id": source_id,
            "variant_code": str(source_id),
        }

    proof = delta.prove_append_only(
        prior_models=prior_models,
        prior_variants=prior_variants,
        current_models=current_models,
        current_variants=current_variants,
    )
    assert proof["summary"]["delta_model_rows"] == 7
    assert proof["summary"]["delta_variant_rows"] == 10
    current_models[1]["name"] = "changed"
    with pytest.raises(delta.MigrationError, match="changed prior non-image data"):
        delta.prove_append_only(
            prior_models=prior_models,
            prior_variants=prior_variants,
            current_models=current_models,
            current_variants=current_variants,
        )


def test_quarantine_identity_normalization_is_fail_closed() -> None:
    assert delta.canonical_quarantine_identity("B3189") == "B3189|"
    assert delta.canonical_quarantine_identity("TJ2017|1") == "TJ2017|1"
    assert delta.canonical_quarantine_identity("MALFORMED-MASTER-1683") is None
    with pytest.raises(delta.MigrationError, match="not canonical"):
        delta.canonical_quarantine_identity("tj2017|01")


def test_all_23_unlinked_records_are_explicitly_accounted_for() -> None:
    plan, receipt, models, variants, sizes, manifest = (
        reviewed_quarantine_fixture()
    )
    evidence = delta.build_quarantine_evidence(
        prior_plan=plan,
        receipt=receipt,
        prior_models=models,
        prior_variants=variants,
        prior_sizes=sizes,
        complete_manifest=manifest,
    )
    assert evidence["summary"]["unlinked_complete_records"] == 23
    assert evidence["summary"]["logical_quarantine_identities"] == 13
    assert evidence["summary"]["malformed_unlinked_records"] == 1
    assert evidence["summary"]["all_unlinked_records_accounted_for"] is True
    assert {
        source_id
        for group in evidence["groups"]
        for source_id in group["old_model_ids"]
    } == set(delta.EXPECTED_QUARANTINE_IDENTITY_BY_MODEL)


def test_unlinked_scope_change_is_rejected_instead_of_silently_omitted() -> None:
    plan, receipt, models, variants, sizes, manifest = (
        reviewed_quarantine_fixture()
    )
    receipt["provenance_evidence"]["model_records"][63] = models[63]
    with pytest.raises(delta.MigrationError, match="unlinked complete-record scope"):
        delta.build_quarantine_evidence(
            prior_plan=plan,
            receipt=receipt,
            prior_models=models,
            prior_variants=variants,
            prior_sizes=sizes,
            complete_manifest=manifest,
        )


def exact_target_and_group() -> tuple[SimpleNamespace, dict, dict]:
    source_row = list_model(63, "TJ2017")
    record = complete_record(63, source_row)
    model = SimpleNamespace(
        id=99,
        code="Protected code",
        name="Protected name",
        product_type="",
        description="",
        details_json={"general": {"model_no": "TJ2017", "variant_no": "1"}},
        images=[],
        sizes=[],
        colors=[],
    )
    group = {
        "identity": "TJ2017|1",
        "old_model_ids": [63],
        "old_variant_ids": [32, 94],
        "master_rows": [source_row],
        "variant_rows": [
            {"old_variant_id": 32, "color": "Blue"},
            {"old_variant_id": 94, "color": "Red"},
        ],
        "size_rows": {
            63: {
                "sizes": [{"size": "M", "measurement_json": None}],
                "scalar": {},
                "raw": {"old_model_id": 63, "sizes": ["M"]},
            }
        },
        "complete_records": [record],
        "quarantine_entries": [
            {
                "identity": "TJ2017|1",
                "canonical_identity": "TJ2017|1",
                "reason": "variant_source_conflict",
                "old_model_ids": [63],
                "old_variant_ids": [32, 94],
                "conflicts": [{"role": "main_image", "values": ["a", "b"]}],
            }
        ],
    }
    manifest = {
        "file_sha256": "f" * 64,
        "metadata": {"version": 1, "source_model_count": 3072},
    }
    return model, group, manifest


def test_exact_quarantine_target_enrichment_preserves_name_and_images() -> None:
    model, group, manifest = exact_target_and_group()
    action, decision = delta.plan_quarantine_existing_action(
        model,
        group=group,
        complete_manifest=manifest,
        source_files={"complete_details_sha256": "f" * 64},
        reviewed_quarantine_sha256="a" * 64,
    )
    assert action is not None
    assert action["action_scope"] == "quarantine_reconciliation"
    assert action["expected_code"] == "Protected code"
    assert action["expected_name"] == "Protected name"
    assert action["expected_images"] == []
    assert action["scalar_fills"] == {
        "description": "Legacy description",
        "product_type": "Legacy product",
    }
    assert [row["size"] for row in action["add_sizes"]] == ["M"]
    assert action["add_colors"] == []
    assert decision["color_conflicts"] == ["Blue", "Red"]
    assert (
        action["details_after"][delta.QUARANTINE_DETAILS_KEY][
            "name_and_images_preserved"
        ]
        is True
    )


def test_exact_quarantine_target_enrichment_is_idempotent() -> None:
    model, group, manifest = exact_target_and_group()
    first, _ = delta.plan_quarantine_existing_action(
        model,
        group=group,
        complete_manifest=manifest,
        source_files={"complete_details_sha256": "f" * 64},
        reviewed_quarantine_sha256="a" * 64,
    )
    assert first is not None
    model.details_json = copy.deepcopy(first["details_after"])
    model.product_type = first["scalar_fills"]["product_type"]
    model.description = first["scalar_fills"]["description"]
    model.sizes = [SimpleNamespace(size="M")]
    second, decision = delta.plan_quarantine_existing_action(
        model,
        group=group,
        complete_manifest=manifest,
        source_files={"complete_details_sha256": "f" * 64},
        reviewed_quarantine_sha256="a" * 64,
    )
    assert second is None
    assert decision["status"] == "exact_target_already_enriched"


def test_quarantine_enrichment_rejects_a_sibling_identity() -> None:
    model, group, manifest = exact_target_and_group()
    model.details_json["general"]["variant_no"] = "2"
    with pytest.raises(delta.MigrationError, match="does not prove identity"):
        delta.plan_quarantine_existing_action(
            model,
            group=group,
            complete_manifest=manifest,
            source_files={"complete_details_sha256": "f" * 64},
            reviewed_quarantine_sha256="a" * 64,
        )


def delta_create_fixture() -> tuple[dict, dict, dict, dict]:
    master = list_model(3125, "PJ1203")
    master["name"] = "4579/4048"
    record = complete_record(3125, master)
    record["general"]["Name"] = "4579/4048"
    record["general"]["Product"] = "Туника"
    variant = {
        "old_variant_id": 5581,
        "color": "Blue",
        "variant_code": "5581",
    }
    source_files = {"complete_details_sha256": "f" * 64}
    return master, record, variant, source_files


def make_delta_create_action() -> tuple[dict, dict, dict, dict, dict]:
    master, record, variant, source_files = delta_create_fixture()
    action = delta.create_action(
        identity="PJ1203|5581",
        code="PJ-1203-5581",
        record=record,
        master_row=master,
        variant_row=variant,
        raw_model_no="PJ-1203",
        variant_no="5581",
        source_files=source_files,
        model_image={"kind": "source", "role": "model"},
        variant_image={"kind": "source", "role": "variant"},
        media_evidence=None,
        variant_media_evidence={"sha256": "a" * 64},
        sizes=[],
    )
    return action, master, record, variant, source_files


def test_create_variant_uses_exact_product_before_legacy_name() -> None:
    action, _, _, _, _ = make_delta_create_action()
    assert action["name"] == "Туника"
    assert action["name_evidence"] == {
        "legacy_imported_name": "4579/4048",
        "exact_product": "Туника",
        "desired_name": "Туника",
        "name_source": "product",
    }


def test_created_variant_falls_back_to_legacy_name_only_without_product() -> None:
    master, record, _, _ = delta_create_fixture()
    record["general"]["Product"] = ""
    evidence = delta.create_name_evidence(
        record=record,
        master_row=master,
        code="PJ-1203-5581",
    )
    assert evidence["desired_name"] == "4579/4048"
    assert evidence["name_source"] == "legacy_name_fallback"


def test_empty_source_paid_operations_is_written_as_explicit_empty_list() -> None:
    details = delta.details_after(
        {},
        patch={},
        provenance={"source_key": delta.SOURCE_KEY},
        paid_operations=[],
    )
    assert "paid_operations" in details
    assert details["paid_operations"] == []


@pytest.mark.parametrize("field", ["paid_operations", "paidOperations"])
def test_existing_paid_operations_list_is_preserved_exactly(field: str) -> None:
    existing = [{"id": "keep-me", "name": "Existing operation"}]
    details = delta.details_after(
        {field: copy.deepcopy(existing)},
        patch={},
        provenance={"source_key": delta.SOURCE_KEY},
        paid_operations=[],
    )
    assert details[field] == existing
    if field == "paidOperations":
        assert "paid_operations" not in details


def applied_delta_model(name: str) -> tuple[SimpleNamespace, dict, dict, dict, dict]:
    created, master, record, variant, source_files = make_delta_create_action()
    model = SimpleNamespace(
        id=9001,
        code=created["code"],
        name=name,
        product_type=created["product_type"],
        description=created["description"],
        details_json=copy.deepcopy(created["details_after"]),
        images=[],
        sizes=[],
        colors=[SimpleNamespace(color_name="Blue")],
    )
    return model, master, record, variant, source_files


def test_applied_delta_legacy_name_gets_one_guarded_product_correction() -> None:
    model, master, record, variant, source_files = applied_delta_model(
        "4579/4048"
    )
    action, decision = delta.plan_existing_action(
        model,
        identity="PJ1203|5581",
        record=record,
        master_row=master,
        variant_row=variant,
        raw_model_no="PJ-1203",
        variant_no="5581",
        source_files=source_files,
        media_evidence=None,
        variant_media_evidence={"sha256": "a" * 64},
        created_by_delta=True,
        sizes=[],
    )
    assert action is not None
    assert action["new_name"] == "Туника"
    assert action["expected_name"] == "4579/4048"
    assert action["expected_images"] == []
    assert action["scalar_fills"] == {}
    assert action["add_sizes"] == []
    assert action["add_colors"] == []
    assert decision["status"] == "correct_imported_legacy_name_to_product"


def test_preexisting_duplicate_keeps_its_paid_operations_list() -> None:
    master, record, _, source_files = delta_create_fixture()
    existing = [{"id": "duplicate-existing-op", "name": "Keep exactly"}]
    model = SimpleNamespace(
        id=6658,
        code="Protected duplicate code",
        name="Protected duplicate name",
        product_type="",
        description="",
        details_json={
            "general": {"model_no": "PJ1203", "variant_no": "5581"},
            "paid_operations": copy.deepcopy(existing),
        },
        images=[],
        sizes=[],
        colors=[],
    )
    action, decision = delta.plan_existing_action(
        model,
        identity="PJ1203|5581",
        record=record,
        master_row=master,
        variant_row=None,
        raw_model_no="PJ1203",
        variant_no="5581",
        source_files=source_files,
        media_evidence=None,
        variant_media_evidence=None,
        created_by_delta=False,
        sizes=[],
    )
    assert action is not None
    assert action["details_after"]["paid_operations"] == existing
    assert action["new_name"] is None
    assert action["expected_name"] == "Protected duplicate name"
    assert action["expected_images"] == []
    assert decision["status"] == "protected_existing"


@pytest.mark.parametrize(
    ("current_name", "created_by_delta", "expected_status"),
    [
        ("Manual user name", True, "manual_name_drift_preserved"),
        ("4579/4048", False, "protected_existing"),
        ("Туника", True, "already_exact_product"),
    ],
)
def test_name_correction_preserves_manual_existing_and_duplicate_names(
    current_name: str,
    created_by_delta: bool,
    expected_status: str,
) -> None:
    model, master, record, variant, source_files = applied_delta_model(
        current_name
    )
    if not created_by_delta:
        decision = delta.existing_delta_name_decision(
            model,
            record=record,
            master_row=master,
            created_by_delta=False,
        )
        assert decision["status"] == expected_status
        assert decision["new_name"] is None
        return
    action, decision = delta.plan_existing_action(
        model,
        identity="PJ1203|5581",
        record=record,
        master_row=master,
        variant_row=variant,
        raw_model_no="PJ-1203",
        variant_no="5581",
        source_files=source_files,
        media_evidence=None,
        variant_media_evidence={"sha256": "a" * 64},
        created_by_delta=created_by_delta,
        sizes=[],
    )
    assert action is None
    assert decision["status"] == expected_status
    assert decision["new_name"] is None
