from __future__ import annotations

import copy
import gzip
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from scripts import export_reviewed_old_erp_models_local as exporter


def _artifact(key: str, payload: dict, file_sha: str) -> exporter.Artifact:
    return exporter.Artifact(
        key=key,
        path=Path(f"{key}.json"),
        sha256=file_sha,
        payload=copy.deepcopy(payload),
    )


def _plan(
    *,
    source_key: str,
    actions: list[dict],
    source_files: dict | None = None,
    **extra,
) -> dict:
    payload = {
        "schema_version": 1,
        "source_key": source_key,
        "actions": copy.deepcopy(actions),
        **copy.deepcopy(extra),
    }
    if source_files is not None:
        payload["source_files"] = copy.deepcopy(source_files)
    payload["plan_sha256"] = exporter.object_sha256(payload)
    return payload


def _report(
    plan: dict,
    *,
    source_files: dict | None = None,
    **extra,
) -> dict:
    payload = {
        "schema_version": 1,
        "mode": "apply",
        "production_touched": False,
        "plan_sha256": plan["plan_sha256"],
        **copy.deepcopy(extra),
    }
    if source_files is not None:
        payload["source_files"] = copy.deepcopy(source_files)
    return payload


def _review_artifacts() -> dict:
    original_file_sha = "1" * 64
    original_report_file_sha = "2" * 64
    original_source = {"models": "a" * 64}
    original_plan_payload = _plan(
        source_key="original",
        actions=[{"identity": "AA1|", "action": "update_existing"}],
        source_files=original_source,
    )
    original_report_payload = _report(original_plan_payload)
    correction_plan_payload = _plan(
        source_key="original",
        actions=[{"identity": "AA1|", "action": "correct"}],
        prior_receipt={
            "plan_file_sha256": original_file_sha,
            "report_file_sha256": original_report_file_sha,
            "source_files": original_source,
        },
    )
    correction_report_payload = _report(correction_plan_payload)

    quarantine = [
        {
            "identity": "QQ9|1",
            "old_model_ids": [9, 10],
            "old_variant_ids": [90],
            "reason": "reviewed_conflict",
        }
    ]
    quarantine_sha = exporter.object_sha256(quarantine)
    delta_source = {
        "prior_apply_plan_sha256": original_file_sha,
        "prior_apply_report_sha256": original_report_file_sha,
        "current": "b" * 64,
    }
    delta_extra = {
        "unresolved_quarantines": quarantine,
        "unresolved_quarantine_sha256": quarantine_sha,
        "summary": {
            "quarantine_unresolved_identities": 1,
            "quarantine_unresolved_records": 2,
        },
    }
    delta_plan_payload = _plan(
        source_key="delta",
        actions=[{"identity": "BB2|7", "action": "create_variant"}],
        source_files=delta_source,
        **delta_extra,
    )
    delta_report_payload = _report(
        delta_plan_payload,
        source_files=delta_source,
        accepted_unresolved_quarantine_sha256=quarantine_sha,
        **delta_extra,
    )

    def followup_pair(action_identity: str | None) -> tuple[dict, dict]:
        actions = (
            [{"identity": action_identity, "action": "update_existing"}]
            if action_identity
            else []
        )
        plan = _plan(
            source_key="delta",
            actions=actions,
            source_files=delta_source,
            **delta_extra,
        )
        report = _report(
            plan,
            source_files=delta_source,
            accepted_unresolved_quarantine_sha256=quarantine_sha,
            **delta_extra,
        )
        return plan, report

    name_plan_payload, name_report_payload = followup_pair("BB2|7")
    empty_plan_payload, empty_report_payload = followup_pair(None)
    return {
        "original_plan": _artifact(
            "original_plan", original_plan_payload, original_file_sha
        ),
        "original_report": _artifact(
            "original_report",
            original_report_payload,
            original_report_file_sha,
        ),
        "correction_plan": _artifact(
            "correction_plan", correction_plan_payload, "3" * 64
        ),
        "correction_report": _artifact(
            "correction_report", correction_report_payload, "4" * 64
        ),
        "delta_plan": _artifact("delta_plan", delta_plan_payload, "5" * 64),
        "delta_report": _artifact(
            "delta_report", delta_report_payload, "6" * 64
        ),
        "name_plan": _artifact("name_plan", name_plan_payload, "7" * 64),
        "name_report": _artifact(
            "name_report", name_report_payload, "8" * 64
        ),
        "empty_ops_plan": _artifact(
            "empty_ops_plan", empty_plan_payload, "9" * 64
        ),
        "empty_ops_report": _artifact(
            "empty_ops_report", empty_report_payload, "c" * 64
        ),
        "expected_quarantine_sha256": quarantine_sha,
        "expected_quarantine_identities": 1,
        "expected_quarantine_records": 2,
    }


def _details(model_no: str, variant_no: str, *, product: str = "") -> dict:
    return {
        "general": {
            "model_no": model_no,
            "variant_no": variant_no,
            "legacy_product": product,
        },
        "paid_operations": [],
    }


def _model(
    *,
    model_id: int,
    code: str,
    name: str,
    details: dict,
    image: SimpleNamespace | None = None,
    sizes: list[SimpleNamespace] | None = None,
    colors: list[SimpleNamespace] | None = None,
    product_type: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=model_id,
        code=code,
        name=name,
        category=None,
        description=None,
        product_type=product_type,
        season=None,
        sam_minutes=0,
        status="draft",
        details_json=copy.deepcopy(details),
        images=[image] if image is not None else [],
        sizes=copy.deepcopy(sizes or []),
        colors=copy.deepcopy(colors or []),
    )


def test_review_receipts_bind_identity_union_and_exact_quarantine() -> None:
    kwargs = _review_artifacts()
    reviewed = exporter.validate_review_artifacts(**kwargs)

    assert reviewed["reviewed_identities"] == ["AA1|", "BB2|7"]
    assert reviewed["protected_identities"] == ["AA1|"]
    assert reviewed["quarantine_records"] == 2
    assert reviewed["quarantine_sha256"] == kwargs[
        "expected_quarantine_sha256"
    ]

    tampered = _review_artifacts()
    tampered["delta_report"].payload["unresolved_quarantines"][0][
        "old_model_ids"
    ].append(11)
    with pytest.raises(exporter.MigrationError, match="quarantine evidence changed"):
        exporter.validate_review_artifacts(**tampered)


def test_production_snapshot_is_hash_pinned_and_rejects_duplicate_identity(
    tmp_path: Path,
) -> None:
    snapshot = tmp_path / "catalog.ndjson.gz"
    rows = [
        {"type": "model", "details_json": _details("BB2", "7")},
        {"type": "image", "model_id": 1},
        {"type": "model", "details_json": _details("AA1", "")},
    ]
    with gzip.open(snapshot, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    digest = exporter.file_sha256(snapshot)

    loaded = exporter.load_production_snapshot(snapshot, digest)

    assert loaded["model_count"] == 2
    assert loaded["identities"] == ["AA1|", "BB2|7"]
    assert loaded["identity_set_sha256"] == exporter.object_sha256(
        ["AA1|", "BB2|7"]
    )
    with pytest.raises(exporter.MigrationError, match="SHA-256 changed"):
        exporter.load_production_snapshot(snapshot, "f" * 64)

    duplicate = tmp_path / "duplicate.ndjson.gz"
    with gzip.open(duplicate, "wt", encoding="utf-8") as handle:
        for _ in range(2):
            handle.write(
                json.dumps(
                    {"type": "model", "details_json": _details("AA1", "")}
                )
                + "\n"
            )
    with pytest.raises(exporter.MigrationError, match="repeats canonical identity"):
        exporter.load_production_snapshot(
            duplicate,
            exporter.file_sha256(duplicate),
        )


def test_source_files_bind_production_snapshot_under_its_exact_artifact_name() -> None:
    source_files = exporter.build_source_files(
        [
            exporter.Artifact(
                key="review_receipt",
                path=Path("receipt.json"),
                sha256="a" * 64,
                payload={},
            )
        ],
        original_source_files={"models": "b" * 64},
        delta_source_files={"delta": "c" * 64},
        production_snapshot_artifact_name="production-catalog.ndjson.gz",
        production_snapshot_sha256="d" * 64,
    )
    production_snapshot = {
        "artifact_name": "production-catalog.ndjson.gz",
        "artifact_sha256": "d" * 64,
        "model_count": 2,
        "identity_set_sha256": exporter.object_sha256(["AA1|", "BB2|7"]),
        "exact_package_identities_sha256": exporter.object_sha256(["AA1|"]),
        "create_package_identities_sha256": exporter.object_sha256(["BB2|7"]),
    }

    assert source_files[production_snapshot["artifact_name"]] == (
        production_snapshot["artifact_sha256"]
    )
    assert "production_catalog_snapshot" not in source_files
    validated = exporter.production_import._validate_production_snapshot(
        production_snapshot,
        source_files=source_files,
    )
    assert validated["artifact_name"] == "production-catalog.ndjson.gz"


def test_receipts_are_removed_recursively_and_normalized_children_dedupe() -> None:
    details = {
        "general": {"model_no": "AA1", "variant_no": ""},
        exporter.PRODUCTION_RECEIPTS_KEY: [{"receipt": 1}],
        "nested": {
            exporter.PRODUCTION_RECEIPTS_KEY: [{"receipt": 2}],
        },
        "paidOperations": [],
    }
    canonical, removed = exporter._canonical_details(details)
    assert removed == 2
    assert exporter.PRODUCTION_RECEIPTS_KEY not in canonical
    assert exporter.PRODUCTION_RECEIPTS_KEY not in canonical["nested"]
    assert "paidOperations" not in canonical
    assert canonical["paid_operations"] == []

    sizes = [
        SimpleNamespace(id=2, size=" s ", measurement_json={"chest": 90}),
        SimpleNamespace(id=3, size="S", measurement_json={"chest": 90}),
    ]
    colors = [
        SimpleNamespace(id=2, color_name=" Blue ", color_code="#00f"),
        SimpleNamespace(id=3, color_name="blue", color_code="#00f"),
    ]
    assert exporter._dedupe_sizes(sizes, "AA1|") == [
        {"size": "s", "measurement_json": {"chest": 90}}
    ]
    assert exporter._dedupe_colors(colors, "AA1|") == [
        {"color_name": "Blue", "color_code": "#00f"}
    ]

    sizes[1].measurement_json = {"chest": 91}
    with pytest.raises(exporter.MigrationError, match="conflicting normalized size"):
        exporter._dedupe_sizes(sizes, "AA1|")


def test_paid_operations_preserve_repeated_semantics_with_distinct_ids() -> None:
    first = {
        "id": "old-erp-op-7",
        "name": "Rezina qoyish",
        "rate": "250",
        "sourceOrder": 7,
    }
    second = {
        "id": "old-erp-op-29",
        "name": "Rezina qoyish",
        "rate": "250",
        "sourceOrder": 29,
    }
    details = {
        "general": {"model_no": "AA1", "variant_no": ""},
        "paid_operations": [first, second],
    }

    canonical, _ = exporter._canonical_details(details)

    assert canonical["paid_operations"] == [first, second]
    duplicate_id = copy.deepcopy(details)
    duplicate_id["paid_operations"][1]["id"] = "old-erp-op-7"
    with pytest.raises(exporter.MigrationError, match="ID .* is repeated"):
        exporter._canonical_details(duplicate_id)


def test_creation_name_policy_preserves_reviewed_names_and_uses_safe_fallbacks() -> None:
    protected = _model(
        model_id=1,
        code="AA1",
        name="Local suffix name",
        details=_details("AA1", "", product="Exact Product"),
        product_type="Exact Product",
    )
    name, policy = exporter.reviewed_creation_name(
        protected,
        details=protected.details_json,
        target_classification="create",
        protected_identity=True,
    )
    assert (name, policy) == (
        "Exact Product",
        "protected_create_exact_product",
    )

    reviewed = _model(
        model_id=2,
        code="BB2-7",
        name="Accepted reviewed name",
        details=_details("BB2", "7", product="Different Product"),
        product_type="Different Product",
    )
    assert exporter.reviewed_creation_name(
        reviewed,
        details=reviewed.details_json,
        target_classification="create",
        protected_identity=False,
    ) == ("Accepted reviewed name", "reviewed_local_name")

    productless = _model(
        model_id=3,
        code="CC3",
        name="",
        details=_details("CC3", ""),
    )
    assert exporter.reviewed_creation_name(
        productless,
        details=productless.details_json,
        target_classification="create",
        protected_identity=False,
    ) == ("CC3", "productless_code_fallback")


def test_build_export_omits_existing_images_and_validates_create_media(
    tmp_path: Path,
) -> None:
    source_media = tmp_path / "source"
    source_media.mkdir()
    image_path = source_media / "reviewed.png"
    Image.new("RGB", (3, 2), color=(10, 20, 30)).save(image_path)
    image = SimpleNamespace(
        id=10,
        file_url="/storage/model-files/reviewed.png",
        file_name="legacy.png",
        content_type="image/png",
        file_data=None,
        image_type="model",
        is_primary=True,
    )
    existing = _model(
        model_id=1,
        code="AA1",
        name="Existing local name",
        details=_details("AA1", ""),
        image=image,
    )
    create = _model(
        model_id=2,
        code="BB2-7",
        name="",
        details=_details("BB2", "7", product="Exact Product"),
        image=image,
        sizes=[SimpleNamespace(id=1, size="M", measurement_json=None)],
        colors=[SimpleNamespace(id=1, color_name="Red", color_code=None)],
        product_type="Exact Product",
    )
    production_identities = ["AA1|", "PROD9|"]
    production_snapshot = {
        "artifact_name": "production.ndjson.gz",
        "artifact_sha256": "d" * 64,
        "model_count": len(production_identities),
        "identities": production_identities,
        "identity_set_sha256": exporter.object_sha256(production_identities),
    }
    receipts = {
        "protected_identities": ["BB2|7"],
        "quarantines": [
            {
                "identity": "QQ9|",
                "old_model_ids": [9],
                "old_variant_ids": [],
            }
        ],
        "quarantine_records": 1,
    }

    package, evidence, media = exporter.build_export(
        reviewed_models={"AA1|": existing, "BB2|7": create},
        receipts=receipts,
        production_snapshot=production_snapshot,
        source_files={"receipt": "e" * 64},
        source_media_root=source_media,
        max_image_bytes=1024 * 1024,
    )

    assert list(package["models"]) == ["AA1|", "BB2|7"]
    assert package["models"]["AA1|"]["target_classification"] == "existing"
    assert package["models"]["AA1|"]["images"] == []
    assert package["models"]["BB2|7"]["target_classification"] == "create"
    assert package["models"]["BB2|7"]["name"] == "Exact Product"
    assert package["models"]["BB2|7"]["images"][0]["source_path"] == (
        "media/reviewed.png"
    )
    assert evidence["summary"]["existing_image_relations_omitted"] == 1
    assert evidence["summary"]["images"] == 1
    assert evidence["summary"]["protected_create_identities"] == 1
    assert len(media) == 1
    assert media[0].sha256 == hashlib.sha256(image_path.read_bytes()).hexdigest()

    package_again, evidence_again, _ = exporter.build_export(
        reviewed_models={"BB2|7": create, "AA1|": existing},
        receipts=receipts,
        production_snapshot=production_snapshot,
        source_files={"receipt": "e" * 64},
        source_media_root=source_media,
        max_image_bytes=1024 * 1024,
    )
    assert exporter._canonical_json_bytes(package_again) == (
        exporter._canonical_json_bytes(package)
    )
    assert evidence_again["records_sha256"] == evidence["records_sha256"]


def test_export_rejects_unsafe_or_corrupt_create_image(tmp_path: Path) -> None:
    source_media = tmp_path / "source"
    source_media.mkdir()
    corrupt = source_media / "corrupt.png"
    corrupt.write_bytes(b"\x89PNG\r\n\x1a\nnot-a-complete-image")
    image = SimpleNamespace(
        id=1,
        file_url="/storage/model-files/corrupt.png",
        file_name=None,
        content_type="image/png",
        file_data=None,
        image_type=None,
        is_primary=False,
    )
    model = _model(
        model_id=1,
        code="AA1",
        name="Name",
        details=_details("AA1", ""),
        image=image,
    )
    with pytest.raises(exporter.MigrationError, match="failed complete image decode"):
        exporter.export_images(
            model,
            identity="AA1|",
            target_classification="create",
            source_media_root=source_media,
            max_image_bytes=1024,
            validated_files={},
            target_hashes={},
        )

    image.file_url = "/storage/model-files/../escape.png"
    with pytest.raises(exporter.MigrationError, match="target name is unsafe"):
        exporter.export_images(
            model,
            identity="AA1|",
            target_classification="create",
            source_media_root=source_media,
            max_image_bytes=1024,
            validated_files={},
            target_hashes={},
        )


def test_localhost_guard_refuses_production_before_query(monkeypatch) -> None:
    monkeypatch.setattr(exporter.local_import.settings, "ENV", "production")
    with pytest.raises(exporter.MigrationError, match="refuses production"):
        exporter.local_import.local_database_guard(
            SimpleNamespace(),
            expected_port=exporter.DEFAULT_LOCAL_DB_PORT,
        )
