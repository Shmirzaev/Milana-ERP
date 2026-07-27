from __future__ import annotations

import copy
import hashlib
import re
import tarfile
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from scripts import migrate_reviewed_old_erp_models_production as migration


def paid_operation(
    operation_id: str,
    name: str,
    *,
    stage: str = "Tikuv",
    rate: str = "100",
) -> dict:
    return {
        "id": operation_id,
        "name": name,
        "stage": stage,
        "rate": rate,
        "currency": "UZB",
    }


def source_record(
    *,
    target_classification: str = "create",
    details: dict | None = None,
    sizes: list[dict] | None = None,
    colors: list[dict] | None = None,
    images: list[dict] | None = None,
) -> dict:
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
        "details_json": copy.deepcopy(
            details
            or {
                "general": {
                    "model_no": "TJ-2053",
                    "variant_no": "879",
                }
            }
        ),
        "sizes": copy.deepcopy(sizes or []),
        "colors": copy.deepcopy(colors or []),
        "images": copy.deepcopy(images or []),
    }
    record["record_sha256"] = migration.object_sha256(record)
    return record


def package_payload(record: dict, *, quarantines: list[dict] | None = None) -> dict:
    exported = {key: copy.deepcopy(value) for key, value in record.items() if key != "record_sha256"}
    artifact_name = "production-model-catalog.ndjson.gz"
    artifact_sha256 = "a" * 64
    identity = exported["identity"]
    exact_identities = [identity] if exported["target_classification"] == "existing" else []
    create_identities = [identity] if exported["target_classification"] == "create" else []
    return {
        "schema_version": 1,
        "package_kind": migration.PACKAGE_KIND,
        "source_key": "reviewed-final",
        "source_files": {artifact_name: artifact_sha256},
        "production_snapshot": {
            "artifact_name": artifact_name,
            "artifact_sha256": artifact_sha256,
            "model_count": 0,
            "identity_set_sha256": migration.object_sha256([]),
            "exact_package_identities_sha256": migration.object_sha256(exact_identities),
            "create_package_identities_sha256": migration.object_sha256(create_identities),
        },
        "models": {"TJ2053|879": exported},
        "quarantines": copy.deepcopy(quarantines or []),
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


def fake_existing_model(
    *,
    details: dict,
    category: str | None = None,
    description: str | None = "Keep current description",
    product_type: str | None = "",
    season: str | None = "Current season",
    sam_minutes: float = 0,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=77,
        code="PROD-CODE-UNCHANGED",
        name="PROD NAME UNCHANGED",
        category=category,
        description=description,
        product_type=product_type,
        season=season,
        sam_minutes=sam_minutes,
        details_json=copy.deepcopy(details),
        sizes=[SimpleNamespace(id=1, size="S", measurement_json={"chest": 90})],
        colors=[SimpleNamespace(id=1, color_name="Blue", color_code="#00f")],
        images=[fake_image()],
    )


def fingerprint_arguments(**overrides) -> dict:
    values = {
        "configured_host": migration.PRODUCTION_DATABASE_VM,
        "configured_port": migration.PRODUCTION_DATABASE_PORT,
        "configured_database": "erp",
        "observed_database": "erp",
        "observed_user": "erp_user",
        "observed_server_address": migration.PRODUCTION_DATABASE_VM,
        "observed_server_port": migration.PRODUCTION_DATABASE_PORT,
        "in_recovery": False,
        "transaction_read_only": "off",
        "expected_host": migration.PRODUCTION_DATABASE_VM,
        "expected_server_address": migration.PRODUCTION_DATABASE_VM,
        "expected_port": migration.PRODUCTION_DATABASE_PORT,
        "expected_database": "erp",
        "expected_user": "erp_user",
    }
    values.update(overrides)
    return values


class FakePlanQuery:
    def scalar(self) -> int:
        return 0


class FakePlanDB:
    def get(self, _model_type, _row_id: int) -> object:
        return object()

    def query(self, _expression) -> FakePlanQuery:
        return FakePlanQuery()


class FakeSnapshotResult:
    def __init__(self, rows: list[tuple]) -> None:
        self.rows = rows
        self.yield_size: int | None = None
        self.closed = False

    def all(self) -> list[tuple]:
        return self.rows

    def yield_per(self, size: int):
        self.yield_size = size
        return iter(self.rows)

    def close(self) -> None:
        self.closed = True

    def __iter__(self):
        return iter(self.rows)


class FakeSnapshotDB:
    def __init__(
        self,
        *,
        table_names: list[str],
        primary_keys: dict[str, list[str]],
        rows: dict[str, list[str]],
    ) -> None:
        self.table_names = table_names
        self.primary_keys = primary_keys
        self.rows = rows
        self.sql: list[str] = []
        self.streaming_results: list[FakeSnapshotResult] = []

    def execute(self, statement, parameters=None) -> FakeSnapshotResult:
        sql = str(statement)
        self.sql.append(sql)
        if "FROM pg_catalog.pg_tables" in sql:
            return FakeSnapshotResult([(name,) for name in self.table_names])
        if "FROM pg_catalog.pg_index" in sql:
            table = str(parameters["qualified_table"]).split(".", 1)[1]
            return FakeSnapshotResult([(column,) for column in self.primary_keys.get(table, [])])
        match = re.search(r'FROM "([a-z][a-z0-9_]*)"', sql)
        assert match is not None, sql
        result = FakeSnapshotResult([(row,) for row in self.rows.get(match.group(1), [])])
        self.streaming_results.append(result)
        return result


def normalized_package(
    record: dict,
    quarantines: list[dict],
    *,
    live_model_count: int = 0,
    live_identities: list[str] | None = None,
) -> dict:
    live_identities = sorted(live_identities or [])
    exact_identities = sorted(
        identity for identity in [record["identity"]] if record["target_classification"] == "existing"
    )
    create_identities = sorted(
        identity for identity in [record["identity"]] if record["target_classification"] == "create"
    )
    return {
        "source_key": "reviewed-final",
        "package_sha256": "d" * 64,
        "source_files": {
            "production-model-catalog.ndjson.gz": "a" * 64,
        },
        "production_snapshot": {
            "artifact_name": "production-model-catalog.ndjson.gz",
            "artifact_sha256": "a" * 64,
            "model_count": live_model_count,
            "identity_set_sha256": migration.object_sha256(live_identities),
            "exact_package_identities_sha256": migration.object_sha256(exact_identities),
            "create_package_identities_sha256": migration.object_sha256(create_identities),
        },
        "models": {record["identity"]: copy.deepcopy(record)},
        "quarantines": copy.deepcopy(quarantines),
        "quarantines_sha256": migration.object_sha256(quarantines),
    }


def test_database_fingerprint_requires_exact_production_primary() -> None:
    guard = migration.validate_database_fingerprint(**fingerprint_arguments())
    assert guard["server_address"] == migration.PRODUCTION_DATABASE_VM
    assert guard["in_recovery"] is False

    with pytest.raises(migration.MigrationError, match="production PostgreSQL VM"):
        migration.validate_database_fingerprint(
            **fingerprint_arguments(
                configured_host="127.0.0.1",
                observed_server_address="127.0.0.1",
                expected_host="127.0.0.1",
                expected_server_address="127.0.0.1",
            )
        )
    with pytest.raises(migration.MigrationError, match="recovery/replica"):
        migration.validate_database_fingerprint(**fingerprint_arguments(in_recovery=True))
    with pytest.raises(migration.MigrationError, match="read-write"):
        migration.validate_database_fingerprint(**fingerprint_arguments(transaction_read_only="on"))


def test_database_fingerprint_accepts_postgres_inet_cidr_for_production_bare_ip() -> None:
    guard = migration.validate_database_fingerprint(
        **fingerprint_arguments(
            observed_server_address=f"{migration.PRODUCTION_DATABASE_VM}/32",
        )
    )

    assert guard["url_host"] == migration.PRODUCTION_DATABASE_VM
    assert guard["server_address"] == migration.PRODUCTION_DATABASE_VM


@pytest.mark.parametrize(
    ("observed_server_address", "message"),
    [
        ("172.16.10.4/32", "not the reviewed server"),
        ("172.16.10.3/not-a-prefix", "valid IP address or CIDR interface"),
        ("172.16.10.999/32", "valid IP address or CIDR interface"),
        ("[172.16.10.3/32", "valid IP address or CIDR interface"),
    ],
)
def test_database_fingerprint_rejects_wrong_or_malformed_cidr(
    observed_server_address: str,
    message: str,
) -> None:
    with pytest.raises(migration.MigrationError, match=message):
        migration.validate_database_fingerprint(
            **fingerprint_arguments(observed_server_address=observed_server_address)
        )


def test_active_release_evidence_is_release_and_backend_vm_pinned() -> None:
    payload = {
        "kind": "milana_active_release",
        "active_release": "20260727_062443",
        "backend_image": "sha256:reviewed",
        "backend_vm": migration.PRODUCTION_BACKEND_VM,
        "captured_at": "2026-07-27T06:30:00Z",
    }
    evidence = migration.validate_active_release_evidence(
        payload,
        evidence_sha256="b" * 64,
        expected_release="20260727_062443",
    )
    assert evidence["active_release"] == "20260727_062443"

    with pytest.raises(migration.MigrationError, match="Active release changed"):
        migration.validate_active_release_evidence(
            payload,
            evidence_sha256="b" * 64,
            expected_release="different",
        )
    with pytest.raises(migration.MigrationError, match="production backend VM"):
        migration.validate_active_release_evidence(
            {**payload, "backend_vm": "127.0.0.1"},
            evidence_sha256="b" * 64,
            expected_release="20260727_062443",
        )


def test_package_validates_all_image_metadata_without_requiring_unused_files(
    tmp_path: Path,
) -> None:
    missing_image = {
        "source_path": "media/not-staged.png",
        "target_name": "old_erp_model_reviewed.png",
        "file_url": "/storage/model-files/old_erp_model_reviewed.png",
        "file_name": "legacy-name.png",
        "content_type": "image/png",
        "image_type": "model",
        "is_primary": True,
        "bytes": 123,
        "sha256": "c" * 64,
    }
    package = migration.validate_package(
        package_payload(source_record(images=[missing_image])),
        package_sha256="d" * 64,
        media_root=tmp_path,
        max_image_bytes=1024,
    )
    assert package["summary"]["images"] == 1
    assert package["models"]["TJ2053|879"]["images"][0]["sha256"] == "c" * 64

    ignored = migration.validate_planned_source_files(
        [
            {
                "action": "update_existing",
                "images": package["models"]["TJ2053|879"]["images"],
            }
        ],
        media_root=tmp_path,
    )
    assert ignored["image_relations"] == 0

    with pytest.raises(migration.MigrationError, match="source file is missing"):
        migration.validate_planned_source_files(
            [
                {
                    "action": "create_model",
                    "images": package["models"]["TJ2053|879"]["images"],
                }
            ],
            media_root=tmp_path,
        )


def test_create_action_images_are_decoded_and_hash_pinned(tmp_path: Path) -> None:
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    source = media_dir / "reviewed.png"
    Image.new("RGB", (2, 2), color=(20, 40, 60)).save(source)
    image = {
        "source_path": "media/reviewed.png",
        "target_name": "old_erp_model_reviewed.png",
        "file_url": "/storage/model-files/old_erp_model_reviewed.png",
        "file_name": "legacy-product-photo.png",
        "content_type": "image/png",
        "image_type": "model",
        "is_primary": True,
        "bytes": source.stat().st_size,
        "sha256": migration.file_sha256(source),
    }
    package = migration.validate_package(
        package_payload(source_record(images=[image])),
        package_sha256="d" * 64,
        media_root=tmp_path,
        max_image_bytes=1024 * 1024,
    )
    action = {
        "action": "create_model",
        "images": package["models"]["TJ2053|879"]["images"],
    }
    evidence = migration.validate_planned_source_files(
        [action],
        media_root=tmp_path,
    )
    assert evidence["image_relations"] == 1
    assert evidence["unique_source_files"] == 1
    assert evidence["unique_source_bytes"] == source.stat().st_size

    source.write_bytes(b"changed after review")
    with pytest.raises(migration.MigrationError, match="byte count changed"):
        migration.validate_planned_source_files([action], media_root=tmp_path)


def test_package_rejects_receipts_and_malformed_quarantines(tmp_path: Path) -> None:
    record = source_record()
    record["details_json"][migration.RECEIPTS_KEY] = []
    with pytest.raises(migration.MigrationError, match="production receipts"):
        migration.validate_package(
            package_payload(record),
            package_sha256="d" * 64,
            media_root=tmp_path,
            max_image_bytes=1024,
        )

    payload = package_payload(source_record())
    payload["quarantines"] = ["not reconstructable"]
    with pytest.raises(migration.MigrationError, match="list of objects"):
        migration.validate_package(
            payload,
            package_sha256="d" * 64,
            media_root=tmp_path,
            max_image_bytes=1024,
        )


def test_package_requires_frozen_snapshot_and_target_classification(
    tmp_path: Path,
) -> None:
    payload = package_payload(source_record())
    del payload["models"]["TJ2053|879"]["target_classification"]
    with pytest.raises(migration.MigrationError, match="target_classification"):
        migration.validate_package(
            payload,
            package_sha256="d" * 64,
            media_root=tmp_path,
            max_image_bytes=1024,
        )

    payload = package_payload(source_record())
    payload["production_snapshot"]["unexpected"] = True
    with pytest.raises(migration.MigrationError, match="fields changed"):
        migration.validate_package(
            payload,
            package_sha256="d" * 64,
            media_root=tmp_path,
            max_image_bytes=1024,
        )

    payload = package_payload(source_record())
    payload["production_snapshot"]["artifact_sha256"] = "b" * 64
    with pytest.raises(migration.MigrationError, match="source_files"):
        migration.validate_package(
            payload,
            package_sha256="d" * 64,
            media_root=tmp_path,
            max_image_bytes=1024,
        )


def test_existing_classification_requires_explicit_empty_images(
    tmp_path: Path,
) -> None:
    image = {
        "source_path": "media/not-used.png",
        "target_name": "not-used.png",
        "file_url": "/storage/model-files/not-used.png",
        "file_name": "not-used.png",
        "content_type": "image/png",
        "image_type": "model",
        "is_primary": True,
        "bytes": 10,
        "sha256": "a" * 64,
    }
    payload = package_payload(source_record(target_classification="existing", images=[image]))
    with pytest.raises(migration.MigrationError, match="explicit empty images"):
        migration.validate_package(
            payload,
            package_sha256="d" * 64,
            media_root=tmp_path,
            max_image_bytes=1024,
        )


def test_frozen_classification_shift_fails_before_action_planning() -> None:
    record = source_record(target_classification="existing")
    package = normalized_package(
        record,
        [],
        live_model_count=0,
        live_identities=[],
    )
    with pytest.raises(migration.MigrationError, match="classification changed"):
        migration.verify_frozen_target_classification(
            package=package,
            models=[],
            db_exact={},
        )


def test_reviewed_source_quarantines_are_evidence_not_blocking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reviewed = [
        {
            "identity": "UNRESOLVED|1",
            "source_record_ids": list(range(1, 24)),
            "reason": "reviewed_source_conflict",
        }
    ]
    package = normalized_package(source_record(), reviewed)
    monkeypatch.setattr(migration, "load_models", lambda _db: [])
    monkeypatch.setattr(
        migration.local_import,
        "assert_no_duplicate_db_identities",
        lambda _models: ({}, {}),
    )
    monkeypatch.setattr(
        migration,
        "all_public_table_counts",
        lambda _db: {},
    )
    monkeypatch.setattr(
        migration,
        "immutable_public_table_snapshots",
        lambda _db: {},
    )

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
    assert plan["summary"]["quarantines"] == 0
    assert plan["summary"]["reviewed_source_quarantines"] == 1
    assert plan["reviewed_source_quarantines"] == reviewed
    assert plan["reviewed_source_quarantines_sha256"] == (migration.object_sha256(reviewed))


def test_runtime_paid_operation_conflict_is_blocking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing_operation = paid_operation("old-1", "Operation", rate="100")
    source_operation = paid_operation("old-1", "Operation", rate="999")
    model = fake_existing_model(
        details={
            "general": {"model_no": "TJ-2053", "variant_no": "879"},
            "paid_operations": [existing_operation],
        }
    )
    record = source_record(
        target_classification="existing",
        details={
            "general": {"model_no": "TJ-2053", "variant_no": "879"},
            "paid_operations": [source_operation],
        },
    )
    package = normalized_package(
        record,
        [],
        live_model_count=1,
        live_identities=[record["identity"]],
    )
    monkeypatch.setattr(migration, "load_models", lambda _db: [model])
    monkeypatch.setattr(
        migration.local_import,
        "assert_no_duplicate_db_identities",
        lambda _models: ({record["identity"]: model}, {}),
    )
    monkeypatch.setattr(
        migration,
        "_complete_catalog_snapshot",
        lambda _models: [],
    )
    monkeypatch.setattr(
        migration,
        "all_public_table_counts",
        lambda _db: {},
    )
    monkeypatch.setattr(
        migration,
        "immutable_public_table_snapshots",
        lambda _db: {},
    )

    plan = migration.compile_plan(
        db=FakePlanDB(),
        package=package,
        package_media_root=tmp_path,
        database_guard={"alembic_revision": "reviewed"},
        active_release={"active_release": "20260727_062443"},
        target_media_root=tmp_path,
        creator_user_id=1,
    )
    assert plan["summary"]["ready_for_apply"] is False
    assert plan["summary"]["quarantines"] == 1
    assert plan["quarantines"][0]["reason"] == "paid_operation_conflict"
    assert plan["actions"] == []


def test_paid_operations_are_exact_or_additive_only() -> None:
    exact = paid_operation("old-1", "Exact operation")
    missing = paid_operation("old-2", "Missing operation", rate="220")
    existing = {
        "paid_operations": [copy.deepcopy(exact)],
        "unrelated": {"keep": True},
    }
    merged = migration.merge_paid_operations(
        existing,
        {"paid_operations": [copy.deepcopy(exact), copy.deepcopy(missing)]},
    )
    assert merged["conflicts"] == []
    assert merged["exact"] == 1
    assert merged["added"] == [missing]
    assert merged["details"]["paid_operations"] == [exact, missing]
    assert existing["paid_operations"] == [exact]

    empty = migration.merge_paid_operations({}, {"paid_operations": []})
    assert empty["details"] == {"paid_operations": []}


def test_paid_operation_disagreement_blocks_instead_of_overwriting() -> None:
    existing = paid_operation("old-1", "Operation", rate="100")
    source = paid_operation("old-1", "Operation", rate="999")
    merged = migration.merge_paid_operations(
        {"paid_operations": [existing]},
        {"paid_operations": [source]},
    )
    assert merged["added"] == []
    assert merged["conflicts"][0]["reason"] == "same_operation_content_conflict"
    assert merged["details"]["paid_operations"] == [existing]

    model = fake_existing_model(
        details={
            "general": {"model_no": "TJ-2053", "variant_no": "879"},
            "paid_operations": [existing],
        }
    )
    record = source_record(
        details={
            "general": {"model_no": "TJ-2053", "variant_no": "879"},
            "paid_operations": [source],
        }
    )
    action, quarantine = migration.plan_existing_model(model, record)
    assert action is None
    assert quarantine["reason"] == "paid_operation_conflict"
    assert quarantine["existing_name_preserved"] is True
    assert quarantine["existing_images_preserved"] is True


def test_source_paid_operations_must_have_unambiguous_identity() -> None:
    duplicate_id = migration.merge_paid_operations(
        {},
        {
            "paid_operations": [
                paid_operation("same-id", "First"),
                paid_operation("same-id", "Different"),
            ]
        },
    )
    assert duplicate_id["conflicts"][0]["reason"] == ("source_duplicate_operation_id_conflict")

    unidentified = migration.merge_paid_operations(
        {},
        {"paid_operations": [{"rate": "100", "currency": "UZB"}]},
    )
    assert unidentified["conflicts"][0]["reason"] == ("unidentifiable_source_operation")


def test_distinct_operation_ids_preserve_repeated_semantics_losslessly() -> None:
    first = {
        **paid_operation("old-7", "Rezina qoyish"),
        "sourceOrder": 7,
    }
    repeated = {
        **paid_operation("old-29", "Rezina qoyish"),
        "sourceOrder": 29,
    }
    merged = migration.merge_paid_operations(
        {},
        {"paid_operations": [first, repeated]},
    )
    assert merged["conflicts"] == []
    assert merged["added"] == [first, repeated]
    assert merged["details"]["paid_operations"] == [first, repeated]

    rerun = migration.merge_paid_operations(
        merged["details"],
        {"paid_operations": [first, repeated]},
    )
    assert rerun["conflicts"] == []
    assert rerun["added"] == []
    assert rerun["exact"] == 2
    assert rerun["details"] == merged["details"]


def test_id_bearing_operation_never_collapses_into_different_existing_id() -> None:
    existing = paid_operation("manual-id", "Repeated operation")
    source = paid_operation("old-erp-id", "Repeated operation")
    merged = migration.merge_paid_operations(
        {"paid_operations": [existing]},
        {"paid_operations": [source]},
    )
    assert merged["conflicts"] == []
    assert merged["added"] == [source]
    assert merged["details"]["paid_operations"] == [existing, source]


def test_id_bearing_semantic_fallback_uses_only_unique_idless_existing() -> None:
    existing = {key: value for key, value in paid_operation("remove-me", "Unique operation").items() if key != "id"}
    source = paid_operation("old-erp-id", "Unique operation")
    merged = migration.merge_paid_operations(
        {"paid_operations": [existing]},
        {"paid_operations": [source]},
    )
    assert merged["conflicts"] == []
    assert merged["added"] == []
    assert merged["exact"] == 1
    assert merged["details"]["paid_operations"] == [existing]


def test_repeated_ids_block_when_idless_semantic_fallback_is_unassignable() -> None:
    idless_existing = {
        key: value for key, value in paid_operation("remove-me", "Repeated operation").items() if key != "id"
    }
    first = paid_operation("old-1", "Repeated operation")
    second = paid_operation("old-2", "Repeated operation")
    merged = migration.merge_paid_operations(
        {"paid_operations": [idless_existing]},
        {"paid_operations": [first, second]},
    )
    assert merged["added"] == []
    assert {row["reason"] for row in merged["conflicts"]} == {"ambiguous_id_bearing_semantic_fallback"}
    assert merged["details"]["paid_operations"] == [idless_existing]


def test_existing_model_preserves_code_name_images_and_nonblank_information() -> None:
    exact = paid_operation("old-1", "Exact")
    missing = paid_operation("old-2", "Missing")
    model = fake_existing_model(
        details={
            "general": {"model_no": "TJ-2053", "variant_no": "879"},
            "nested": {"authoritative": "production", "blank": ""},
            "paid_operations": [exact],
        }
    )
    record = source_record(
        details={
            "general": {"model_no": "TJ-2053", "variant_no": "879"},
            "nested": {
                "authoritative": "legacy must not overwrite",
                "blank": "filled",
                "missing": "added",
            },
            "paid_operations": [exact, missing],
        },
        sizes=[
            {"size": "S", "measurement_json": {"legacy": "ignored duplicate"}},
            {"size": "M", "measurement_json": {"chest": 96}},
        ],
        colors=[
            {"color_name": "blue", "color_code": "#999"},
            {"color_name": "Red", "color_code": "#f00"},
        ],
    )
    action, quarantine = migration.plan_existing_model(model, record)
    assert quarantine is None
    assert action["expected_code"] == "PROD-CODE-UNCHANGED"
    assert action["expected_name"] == "PROD NAME UNCHANGED"
    assert action["expected_images"] == migration.local_import.model_image_snapshot(model)
    assert "images" not in action
    assert action["scalar_fills"] == {
        "category": "Legacy category",
        "product_type": "Туника",
        "sam_minutes": 12.5,
    }
    assert action["details_after"]["nested"] == {
        "authoritative": "production",
        "blank": "filled",
        "missing": "added",
    }
    assert action["paid_operations"]["added"] == 1
    assert action["add_sizes"] == [{"size": "M", "measurement_json": {"chest": 96}}]
    assert action["add_colors"] == [{"color_name": "Red", "color_code": "#f00"}]


def test_existing_update_is_idempotent_after_receipt() -> None:
    exact = paid_operation("old-1", "Exact")
    missing = paid_operation("old-2", "Missing")
    record = source_record(
        details={
            "general": {"model_no": "TJ-2053", "variant_no": "879"},
            "missing_detail": "filled once",
            "paid_operations": [exact, missing],
        },
        sizes=[{"size": "S", "measurement_json": None}, {"size": "M"}],
        colors=[{"color_name": "Blue"}, {"color_name": "Red"}],
    )
    model = fake_existing_model(
        details={
            "general": {"model_no": "TJ-2053", "variant_no": "879"},
            "paid_operations": [exact],
        },
        description="Existing description",
    )
    first = migration.desired_existing_state(model, record)
    for field, value in first["scalar_fills"].items():
        setattr(model, field, value)
    plan = {
        "source_key": "reviewed-final",
        "package_sha256": "a" * 64,
        "plan_sha256": "b" * 64,
        "actions": [{"identity": record["identity"]}],
        "active_release": {"active_release": "20260727_062443"},
    }
    model.details_json = migration._append_receipt(
        first["details_after"],
        plan=plan,
        identity=record["identity"],
        action="update_existing",
        action_index=1,
    )
    model.sizes.append(SimpleNamespace(id=2, size="M", measurement_json=None))
    model.colors.append(SimpleNamespace(id=2, color_name="Red", color_code=None))

    second = migration.desired_existing_state(model, record)
    assert second["scalar_fills"] == {}
    assert second["details_changed"] is False
    assert second["paid_operations"]["added"] == 0
    assert second["operation_conflicts"] == []
    assert second["add_sizes"] == []
    assert second["add_colors"] == []

    same_receipt = migration._append_receipt(
        model.details_json,
        plan=plan,
        identity=record["identity"],
        action="update_existing",
        action_index=1,
    )
    assert same_receipt == model.details_json
    assert len(same_receipt[migration.RECEIPTS_KEY]) == 1


def test_new_image_rows_preserve_reviewed_metadata() -> None:
    image = {
        "kind": "source",
        "source_path": "media/content-addressed.png",
        "target_name": "content-addressed.png",
        "file_url": "/storage/model-files/content-addressed.png",
        "file_name": "legacy-human-name.png",
        "content_type": "image/png",
        "image_type": "model",
        "is_primary": True,
        "bytes": 99,
        "sha256": "a" * 64,
    }

    class FakeDB:
        def __init__(self) -> None:
            self.rows: list = []

        def add(self, row) -> None:
            self.rows.append(row)

    db = FakeDB()
    assert migration._add_images(db, SimpleNamespace(id=123), [image]) == 1
    row = db.rows[0]
    assert row.model_id == 123
    assert row.file_url == image["file_url"]
    assert row.file_name == "legacy-human-name.png"
    assert row.content_type == "image/png"
    assert row.image_type == "model"
    assert row.is_primary is True
    assert row.file_data is None


def test_immutable_table_snapshots_hash_all_non_catalog_row_content() -> None:
    table_names = [
        "alembic_version",
        "event_log",
        "model_bom",
        "model_colors",
        "model_images",
        "model_sizes",
        "models",
    ]
    db = FakeSnapshotDB(
        table_names=table_names,
        primary_keys={
            "alembic_version": ["version_num"],
            "model_bom": ["id"],
        },
        rows={
            "alembic_version": ['{"version_num": "abc123"}'],
            "event_log": ['{"event": "created", "value": 1}'],
            "model_bom": ['{"id": 1, "model_id": 7, "quantity_per_piece": 1.25}'],
        },
    )
    snapshots = migration.immutable_public_table_snapshots(db)
    assert set(snapshots) == {
        "alembic_version",
        "event_log",
        "model_bom",
    }
    assert snapshots["alembic_version"]["row_count"] == 1
    assert snapshots["model_bom"]["primary_key_columns"] == ["id"]
    assert all(result.yield_size == 1000 for result in db.streaming_results)
    assert all(result.closed for result in db.streaming_results)
    assert any('ORDER BY to_jsonb(table_row)::text COLLATE "C"' in sql for sql in db.sql)

    changed_db = FakeSnapshotDB(
        table_names=table_names,
        primary_keys=db.primary_keys,
        rows={
            **db.rows,
            "model_bom": ['{"id": 1, "model_id": 7, "quantity_per_piece": 9.99}'],
        },
    )
    changed = migration.immutable_public_table_snapshots(changed_db)
    assert changed["model_bom"]["content_sha256"] != snapshots["model_bom"]["content_sha256"]
    assert changed["alembic_version"]["content_sha256"] == snapshots["alembic_version"]["content_sha256"]


def test_public_table_snapshot_rejects_unsafe_dynamic_identifiers() -> None:
    db = FakeSnapshotDB(
        table_names=["safe_table", "unsafe-table"],
        primary_keys={},
        rows={},
    )
    with pytest.raises(migration.MigrationError, match="Unsafe public table"):
        migration.immutable_public_table_snapshots(db)


def test_canonical_table_row_hash_is_deterministic_and_content_sensitive() -> None:
    rows = [('{"id":1,"value":"same"}',), ('{"id":2,"value":"same"}',)]
    first = migration._hash_canonical_table_rows("audit_logs", rows)
    second = migration._hash_canonical_table_rows("audit_logs", rows)
    changed = migration._hash_canonical_table_rows(
        "audit_logs",
        [('{"id":1,"value":"same"}',), ('{"id":2,"value":"changed"}',)],
    )
    assert first == second
    assert first["row_count"] == 2
    assert first["content_sha256"] != changed["content_sha256"]


def test_media_root_backup_lock_and_rollback_guards(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "model_files"
    target.mkdir()
    (target / "existing.bin").write_bytes(b"existing")
    monkeypatch.setattr(migration.settings, "MODEL_FILES_DIR", str(target))
    assert migration.verify_production_media_root(target, target) == target.resolve()
    wrong = tmp_path / "wrong"
    wrong.mkdir()
    with pytest.raises(migration.MigrationError, match="reviewed"):
        migration.verify_production_media_root(wrong, wrong)

    inventory = migration.media_inventory(target)
    archive_path = tmp_path / "model_files.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        archive.add(target, arcname="model_files")
    backup = migration.verify_media_backup(
        archive_path,
        migration.file_sha256(archive_path),
        max_age_hours=1,
        expected_inventory=inventory,
    )
    assert backup["inventory"]["files_sha256"] == inventory["files_sha256"]

    class FakeLockDB:
        def __init__(self) -> None:
            self.statements: list[str] = []

        def execute(self, statement) -> None:
            self.statements.append(str(statement))

    lock_db = FakeLockDB()
    migration.acquire_production_locks(lock_db)
    assert "pg_advisory_xact_lock" in lock_db.statements[0]
    assert "LOCK TABLE models" in lock_db.statements[1]

    created = target / "newly-created.bin"
    created.write_bytes(b"new")
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"outside")
    migration.cleanup_created_files(
        [created, outside],
        target_root=target,
        commit_started=False,
    )
    assert not created.exists()
    assert outside.exists()

    after_commit = target / "after-commit.bin"
    after_commit.write_bytes(b"must remain")
    migration.cleanup_created_files(
        [after_commit],
        target_root=target,
        commit_started=True,
    )
    assert after_commit.exists()


def test_durable_outputs_and_apply_count_guards(tmp_path: Path) -> None:
    output = tmp_path / "reviewed-plan.json"
    payload = {"production_targeted": True, "production_touched": False}
    migration.write_durable_json(output, payload, overwrite=False)
    assert output.read_text(encoding="utf-8").endswith("\n")
    with pytest.raises(migration.MigrationError, match="already exists"):
        migration.write_durable_json(output, payload, overwrite=False)

    args = Namespace(
        apply=True,
        expect_source_models=None,
        expect_update_existing=None,
        expect_create_models=None,
        expect_add_images=None,
        expect_add_sizes=None,
        expect_add_colors=None,
        expect_paid_operations_added=None,
        expect_quarantines=None,
        expect_reviewed_source_quarantines=None,
    )
    plan = {
        "summary": {
            "source_models": 6404,
            "update_existing": 767,
            "create_models": 5637,
            "add_images": 9580,
            "add_sizes": 0,
            "add_colors": 0,
            "paid_operations_added": 22867,
            "quarantines": 0,
            "reviewed_source_quarantines": 14,
        }
    }
    with pytest.raises(migration.MigrationError, match="every reviewed count"):
        migration.enforce_expected_counts(args, plan)


def test_package_hash_helper_is_stable() -> None:
    value = {"b": [2, 1], "a": {"x": True}}
    assert migration.object_sha256(value) == hashlib.sha256(b'{"a":{"x":true},"b":[2,1]}').hexdigest()
