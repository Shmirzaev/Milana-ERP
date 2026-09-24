from __future__ import annotations

import json

from sqlalchemy import Column, Integer, JSON, MetaData, String, Table, create_engine, insert

from app.migrations.preflight_0126 import (
    GRANTS_0126,
    PREDECESSOR_0126,
    read_only_preflight_0126,
)


def _engine(*, with_roles: bool = True):
    engine = create_engine("sqlite://")
    metadata = MetaData()
    version = Table("alembic_version", metadata, Column("version_num", String, primary_key=True))
    roles = None
    if with_roles:
        roles = Table(
            "roles", metadata,
            Column("id", Integer, primary_key=True),
            Column("name", String, nullable=False),
            Column("permissions", JSON),
        )
    metadata.create_all(engine)
    return engine, roles, version


def test_0126_preflight_predicts_exact_case_insensitive_append_without_writes():
    engine, roles, version = _engine()
    existing = ["payroll.view", "sewing.records"]
    with engine.begin() as connection:
        connection.execute(insert(version), {"version_num": PREDECESSOR_0126})
        connection.execute(insert(roles), [
            {"id": 2, "name": "Payroll", "permissions": existing},
            {"id": 1, "name": "payroll", "permissions": []},
            {"id": 3, "name": "sewing", "permissions": []},
        ])

    report = read_only_preflight_0126(engine)
    assert report["applicability"] == "multiple_matches_review_required"
    assert report["matching_role_count"] == report["changed_role_count"] == 2
    assert report["roles"][0]["role_id"] == 1
    assert report["roles"][0]["after"] == list(GRANTS_0126)
    assert report["roles"][1]["before"] == existing
    assert report["roles"][1]["after"] == ["payroll.view", "sewing.records", "sewing.flows", "sewing.bundles"]
    assert all(len(role["before_sha256"]) == 64 for role in report["roles"])
    with engine.connect() as connection:
        persisted = connection.execute(roles.select().where(roles.c.id == 2)).mappings().one()
    assert persisted["permissions"] == existing
    engine.dispose()


def test_0126_preflight_reports_malformed_json_as_blocker():
    engine, roles, version = _engine()
    with engine.begin() as connection:
        connection.execute(insert(version), {"version_num": PREDECESSOR_0126})
        connection.execute(insert(roles), {"id": 1, "name": "payroll", "permissions": "not-an-array"})

    report = read_only_preflight_0126(engine)
    assert report["applicability"] == "blocked_by_migration_input"
    assert report["blocked_role_count"] == 1
    assert "after" not in report["roles"][0]
    engine.dispose()


def test_0126_preflight_refuses_to_inspect_on_revision_drift():
    engine, _roles, version = _engine(with_roles=False)
    with engine.begin() as connection:
        connection.execute(insert(version), {"version_num": "0124_material_length"})

    assert read_only_preflight_0126(engine) == {
        "revision": "0126_payroll_sewing_access",
        "expected_predecessor": PREDECESSOR_0126,
        "database_revision": "0124_material_length",
        "migration_pending": False,
        "applicability": "revision_mismatch_review_required",
        "affected_rows_inspected": False,
    }
    engine.dispose()


def test_0126_applied_revision_does_not_claim_historical_grants():
    engine, _roles, version = _engine(with_roles=False)
    with engine.begin() as connection:
        connection.execute(insert(version), {"version_num": "0130_eco_fabric_transfers"})

    report = read_only_preflight_0126(engine)
    assert report["applicability"] == "migration_already_applied"
    assert report["affected_rows_inspected"] is False
    assert "roles" not in json.dumps(report)
    engine.dispose()
