"""Reviewed production import must bound the ``Model.details_json`` it stores.

``3544b1f4`` put this guard on the reviewed import; ``DB03-MODEL`` landed the
shared validator it now has to reuse. The hole this file pins down is specific
to a *merging* importer: ``desired_existing_state`` combines the live catalog
document with the reviewed source document, so two documents that are each
inside the shared ceilings can merge into one that is outside them. Validating
only the inputs is therefore not enough -- the persisted document has to be
checked, and the plan has to refuse to compile rather than abort halfway.

No assertion here touches a database: the importer is driven with in-memory
fakes, exactly as the existing reviewed-import suite does.
"""

from __future__ import annotations

import ast
import copy
import inspect
import json
import math
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.api.routes import catalog
from scripts import migrate_reviewed_old_erp_models_production as migration


MAX_BYTES = catalog._MAX_MODEL_DETAILS_JSON_BYTES
MAX_DEPTH = catalog._MAX_MODEL_DETAILS_JSON_DEPTH


def serialized_bytes(details: object) -> int:
    """Byte size exactly as the shared validator measures it."""
    return len(
        json.dumps(details, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    )


def assert_within_shared_bounds(details: object) -> None:
    """Assert a document is legal on its own, for the 'legal inputs' half."""
    assert serialized_bytes(details) <= MAX_BYTES
    catalog._validate_model_details_json_bounds(details)


def receipt_plan() -> dict:
    return {
        "source_key": "reviewed-final",
        "package_sha256": "a" * 64,
        "plan_sha256": "b" * 64,
        "actions": [{"identity": "TJ2053|879"}],
        "active_release": {"active_release": "20260727_062443"},
    }


def fake_image() -> SimpleNamespace:
    return SimpleNamespace(
        id=19,
        file_url="/storage/model-files/existing.jpg",
        file_name="existing-original.jpg",
        content_type="image/jpeg",
        file_data=b"existing-image-row",
        image_type="model",
        is_primary=True,
    )


def fake_existing_model(details: dict) -> SimpleNamespace:
    return SimpleNamespace(
        id=77,
        code="PROD-CODE-UNCHANGED",
        name="PROD NAME UNCHANGED",
        category="Legacy category",
        description="Existing description",
        product_type="",
        season="Current season",
        sam_minutes=0.0,
        details_json=copy.deepcopy(details),
        sizes=[SimpleNamespace(id=1, size="S", measurement_json={"chest": 90})],
        colors=[SimpleNamespace(id=1, color_name="Blue", color_code="#00f")],
        images=[fake_image()],
    )


def source_record(*, target_classification: str, details: dict) -> dict:
    record = {
        "identity": "TJ2053|879",
        "target_classification": target_classification,
        "code": "TJ-2053-879",
        "name": "Туника",
        "category": "Legacy category",
        "description": "Legacy description",
        "product_type": "Туника",
        "season": "Summer",
        "sam_minutes": 12.5,
        "status": "draft",
        "details_json": copy.deepcopy(details),
        "sizes": [],
        "colors": [],
        "images": [],
    }
    record["record_sha256"] = migration.object_sha256(record)
    return record


def normalized_package(record: dict, *, live_model_count: int, live_identities: list[str]) -> dict:
    live_identities = sorted(live_identities)
    exact = [record["identity"]] if record["target_classification"] == "existing" else []
    create = [record["identity"]] if record["target_classification"] == "create" else []
    return {
        "source_key": "reviewed-final",
        "package_sha256": "d" * 64,
        "source_files": {"production-model-catalog.ndjson.gz": "a" * 64},
        "production_snapshot": {
            "artifact_name": "production-model-catalog.ndjson.gz",
            "artifact_sha256": "a" * 64,
            "model_count": live_model_count,
            "identity_set_sha256": migration.object_sha256(live_identities),
            "exact_package_identities_sha256": migration.object_sha256(exact),
            "create_package_identities_sha256": migration.object_sha256(create),
        },
        "models": {record["identity"]: copy.deepcopy(record)},
        "quarantines": [],
        "quarantines_sha256": migration.object_sha256([]),
    }


class FakePlanQuery:
    def scalar(self) -> int:
        return 0


class FakePlanDB:
    def get(self, _model_type, _row_id: int) -> object:
        return object()

    def query(self, _expression) -> FakePlanQuery:
        return FakePlanQuery()


def stub_compile_plan_dependencies(monkeypatch: pytest.MonkeyPatch, models: list) -> None:
    """Neutralise the database/inspection reads compile_plan performs."""
    monkeypatch.setattr(migration, "load_models", lambda _db: list(models))
    monkeypatch.setattr(migration, "_complete_catalog_snapshot", lambda _models: [])
    monkeypatch.setattr(migration, "all_public_table_counts", lambda _db: {})
    monkeypatch.setattr(migration, "immutable_public_table_snapshots", lambda _db: {})


# ---------------------------------------------------------------------------
# The named hole: every input is legal, the merge is not.
# ---------------------------------------------------------------------------


def test_merge_of_two_legal_documents_is_refused_before_apply(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each side fits the shared ceiling; together they do not.

    This is the specific hole ``DB03-IMPORT-REVIEWED`` names. The live catalog
    document and the reviewed source document are each individually writable by
    the API, so an input-only check passes both, and only the merged document
    that the migration actually stores is over 64 KiB.
    """
    live_details = {
        "general": {"model_no": "TJ-2053", "variant_no": "879"},
        "legacy_notes": "A" * 40_000,
    }
    source_details = {
        "general": {"model_no": "TJ-2053", "variant_no": "879"},
        "costing": {"fabric": "B" * 40_000},
    }

    # Both inputs are individually legal -- this is not an input-validation case.
    assert_within_shared_bounds(live_details)
    assert_within_shared_bounds(source_details)

    model = fake_existing_model(live_details)
    record = source_record(target_classification="existing", details=source_details)
    package = normalized_package(record, live_model_count=1, live_identities=[record["identity"]])
    monkeypatch.setattr(
        migration.local_import,
        "assert_no_duplicate_db_identities",
        lambda _models: ({record["identity"]: model}, {}),
    )
    stub_compile_plan_dependencies(monkeypatch, [model])

    # The merge really does produce an out-of-bounds document...
    merged = migration.desired_existing_state(model, record)["details_after"]
    assert serialized_bytes(merged) > MAX_BYTES
    with pytest.raises(Exception):
        catalog._validate_model_details_json_bounds(merged)

    # ...so the plan must refuse to compile at all, not compile and then abort.
    with pytest.raises(migration.MigrationError):
        migration.compile_plan(
            db=FakePlanDB(),
            package=package,
            package_media_root=tmp_path,
            database_guard={"alembic_revision": "reviewed"},
            active_release={"active_release": "20260727_062443"},
            target_media_root=tmp_path,
            creator_user_id=1,
        )


def test_legal_merge_still_compiles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The bound must not reject a merge that stays inside the ceilings."""
    model = fake_existing_model(
        {
            "general": {"model_no": "TJ-2053", "variant_no": "879"},
            "legacy_notes": "A" * 2_000,
        }
    )
    record = source_record(
        target_classification="existing",
        details={
            "general": {"model_no": "TJ-2053", "variant_no": "879"},
            "costing": {"fabric": "B" * 2_000},
        },
    )
    package = normalized_package(record, live_model_count=1, live_identities=[record["identity"]])
    monkeypatch.setattr(
        migration.local_import,
        "assert_no_duplicate_db_identities",
        lambda _models: ({record["identity"]: model}, {}),
    )
    stub_compile_plan_dependencies(monkeypatch, [model])

    plan = migration.compile_plan(
        db=FakePlanDB(),
        package=package,
        package_media_root=tmp_path,
        database_guard={"alembic_revision": "reviewed"},
        active_release={"active_release": "20260727_062443"},
        target_media_root=tmp_path,
        creator_user_id=1,
    )
    assert plan["summary"]["ready_for_apply"] is True
    assert plan["actions"][0]["action"] == "update_existing"
    assert serialized_bytes(plan["actions"][0]["details_after"]) <= MAX_BYTES


def test_preflight_also_covers_the_create_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A new model has no merge, but its document still has to be bounded.

    This covers the ``create_model`` branch of the pre-flight sweep, which the
    update-path tests above never reach.
    """
    deep: dict = {"leaf": 1}
    for _ in range(MAX_DEPTH + 2):
        deep = {"nest": deep}

    record = source_record(target_classification="create", details={"general": deep})
    package = normalized_package(record, live_model_count=0, live_identities=[])
    monkeypatch.setattr(
        migration.local_import,
        "assert_no_duplicate_db_identities",
        lambda _models: ({}, {}),
    )
    stub_compile_plan_dependencies(monkeypatch, [])

    with pytest.raises(migration.MigrationError):
        migration.compile_plan(
            db=FakePlanDB(),
            package=package,
            package_media_root=tmp_path,
            database_guard={"alembic_revision": "reviewed"},
            active_release={"active_release": "20260727_062443"},
            target_media_root=tmp_path,
            creator_user_id=1,
        )


# ---------------------------------------------------------------------------
# The persisted document, not merely the inputs.
# ---------------------------------------------------------------------------


def test_final_update_write_refuses_oversized_document() -> None:
    """``_append_receipt`` builds the document stored at the update write site."""
    oversized = {"general": {"note": "C" * (MAX_BYTES + 1)}}
    with pytest.raises(migration.MigrationError):
        migration._append_receipt(
            oversized,
            plan=receipt_plan(),
            identity="TJ2053|879",
            action="update_existing",
            action_index=1,
        )


def test_final_create_write_refuses_too_deep_document() -> None:
    """Depth is a property of the assembled document, so check it there too."""
    deep: dict = {"leaf": 1}
    for _ in range(MAX_DEPTH + 2):
        deep = {"nest": deep}
    assert depth_of(deep) > MAX_DEPTH

    with pytest.raises(migration.MigrationError):
        migration._append_receipt(
            deep,
            plan=receipt_plan(),
            identity="TJ2053|879",
            action="create_model",
            action_index=1,
        )


def depth_of(value: object) -> int:
    """Container nesting depth, counted the way the shared validator counts it."""
    if not isinstance(value, (dict, list)):
        return 0
    children = value.values() if isinstance(value, dict) else value
    return 1 + max((depth_of(child) for child in children), default=0)


def test_non_finite_number_is_refused_and_is_not_valid_stored_json() -> None:
    """NaN must be refused, not carried into a stored document.

    ``json.dumps`` emits a bare ``NaN`` token, which no JSON reader accepts, so
    the value cannot survive a round trip through the database. The guard has to
    catch it here rather than leave the coercion to the storage driver.
    """
    details = {"general": {"sam": float("nan")}}

    # The hazard is real and objective: strict JSON cannot represent this.
    with pytest.raises(ValueError):
        json.dumps(details, allow_nan=False)

    # Without the guard the NaN rides straight through into the stored document.
    unvalidated = copy.deepcopy(details)
    unvalidated[migration.RECEIPTS_KEY] = [{"identity": "TJ2053|879"}]
    assert math.isnan(unvalidated["general"]["sam"])

    with pytest.raises(migration.MigrationError):
        migration._append_receipt(
            details,
            plan=receipt_plan(),
            identity="TJ2053|879",
            action="update_existing",
            action_index=1,
        )


def test_infinity_is_refused_too() -> None:
    with pytest.raises(migration.MigrationError):
        migration._append_receipt(
            {"general": {"rate": float("inf")}},
            plan=receipt_plan(),
            identity="TJ2053|879",
            action="update_existing",
            action_index=1,
        )


def test_ordinary_document_passes_the_final_write() -> None:
    """A normal reviewed document is untouched by the guard."""
    details = {
        "general": {"model_no": "TJ-2053", "variant_no": "879"},
        "paid_operations": [{"id": "old-1", "rate": "100"}],
    }
    result = migration._append_receipt(
        details,
        plan=receipt_plan(),
        identity="TJ2053|879",
        action="create_model",
        action_index=1,
    )
    assert result["general"] == details["general"]
    assert len(result[migration.RECEIPTS_KEY]) == 1


# ---------------------------------------------------------------------------
# existing_details: grandfathering a pre-existing row, never a new one.
# ---------------------------------------------------------------------------


def already_applied_receipt() -> dict:
    """A receipt for the plan in :func:`receipt_plan`, as an earlier run left it.

    Hand-built rather than produced by ``_append_receipt``, because the document
    it belongs to is oversized and the guarded helper would refuse to build it.
    """
    plan = receipt_plan()
    return {
        "schema_version": migration.SCHEMA_VERSION,
        "target_environment": "production",
        "source_key": plan["source_key"],
        "package_sha256": plan["package_sha256"],
        "plan_sha256": plan["plan_sha256"],
        "identity": "TJ2053|879",
        "action": "update_existing",
        "action_index": 1,
        "action_count": len(plan["actions"]),
        "active_release": plan["active_release"]["active_release"],
        "applied_at": "2026-07-27T06:24:43+00:00",
    }


def test_unchanged_oversized_legacy_row_stays_editable() -> None:
    """An unchanged legacy document is grandfathered, as the API does.

    The shared validator's exemption exists so a row that predates the ceilings
    can still be re-saved. An idempotent re-run of the import finds its receipt
    already present, appends nothing, and therefore writes back exactly the
    bytes already stored -- that must not be blocked forever.
    """
    legacy = {
        "general": {"note": "D" * (MAX_BYTES + 1)},
        migration.RECEIPTS_KEY: [already_applied_receipt()],
    }
    assert serialized_bytes(legacy) > MAX_BYTES

    unchanged = migration._append_receipt(
        legacy,
        plan=receipt_plan(),
        identity="TJ2053|879",
        action="update_existing",
        action_index=1,
        existing_details=legacy,
    )
    assert unchanged == legacy


def test_a_fresh_receipt_on_an_oversized_row_is_still_a_change() -> None:
    """Grandfathering is for unchanged bytes, not for adding a new receipt.

    This is the distinction that keeps the exemption from becoming a loophole:
    appending a receipt changes the stored document, so the ceiling applies.
    """
    legacy = {
        "general": {"note": "D" * (MAX_BYTES + 1)},
        migration.RECEIPTS_KEY: [already_applied_receipt()],
    }
    other_plan = receipt_plan()
    other_plan["plan_sha256"] = "c" * 64

    with pytest.raises(migration.MigrationError):
        migration._append_receipt(
            legacy,
            plan=other_plan,
            identity="TJ2053|879",
            action="update_existing",
            action_index=1,
            existing_details=legacy,
        )


def test_changed_oversized_legacy_row_is_still_refused() -> None:
    """Grandfathering must not become a way to grow an oversized row."""
    legacy = {"general": {"note": "D" * (MAX_BYTES + 1)}}
    with pytest.raises(migration.MigrationError):
        migration._append_receipt(
            legacy,
            plan=receipt_plan(),
            identity="TJ2053|879",
            action="update_existing",
            action_index=1,
            existing_details={"general": {"note": "D" * 10}},
        )


def test_a_brand_new_row_is_never_grandfathered() -> None:
    """create_model has no stored row, so the exemption cannot apply."""
    oversized = {"general": {"note": "E" * (MAX_BYTES + 1)}}
    with pytest.raises(migration.MigrationError):
        migration._append_receipt(
            oversized,
            plan=receipt_plan(),
            identity="TJ2053|879",
            action="create_model",
            action_index=1,
        )


# ---------------------------------------------------------------------------
# Structural guarantee: the final write cannot bypass the guard.
# ---------------------------------------------------------------------------


def test_every_details_json_write_in_apply_plan_goes_through_the_guard() -> None:
    """Pin the two write sites named in the bug row to the guarded helper.

    ``apply_plan`` stores ``details_json`` at two places: the update assignment
    and the ``Model(...)`` constructor for a created row. Both must trace back to
    ``_append_receipt``; an unguarded direct assignment -- or a local holding an
    unguarded document -- would reintroduce the hole with no other test
    noticing.
    """
    tree = ast.parse(inspect.getsource(migration.apply_plan))

    guarded_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            func = node.value.func
            if isinstance(func, ast.Name) and func.id == "_append_receipt":
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        guarded_names.add(target.id)

    def is_guarded(value: ast.AST) -> bool:
        if isinstance(value, ast.Call):
            func = value.func
            return isinstance(func, ast.Name) and func.id == "_append_receipt"
        return isinstance(value, ast.Name) and value.id in guarded_names

    write_sites: list[ast.AST] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Attribute) and target.attr == "details_json":
                    write_sites.append(node.value)
        elif isinstance(node, ast.Call):
            for keyword in node.keywords:
                if keyword.arg == "details_json":
                    write_sites.append(keyword.value)

    assert len(write_sites) == 2, "expected exactly the update and create write sites"
    for value in write_sites:
        assert is_guarded(value), f"unguarded details_json write: {ast.dump(value)}"
    assert guarded_names == {"details"}, "the create path should bind the guarded document once"


def test_the_update_write_passes_existing_details_and_create_does_not() -> None:
    """The create path must not hand the validator a document to grandfather."""
    source = inspect.getsource(migration.apply_plan)
    assert "existing_details=model.details_json" in source
    create_call = source.split('action="create_model"')[0].rsplit("_append_receipt(", 1)[-1]
    assert "existing_details" not in create_call
