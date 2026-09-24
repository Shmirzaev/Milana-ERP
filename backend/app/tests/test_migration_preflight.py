from __future__ import annotations

from sqlalchemy import JSON, Column, Integer, MetaData, String, Table, create_engine, insert

from app.migrations.preflight import (
    PREDECESSOR_0130,
    TARGET_PERMISSION_0130,
    preview_0130_permissions,
    read_only_preflight_0130,
)


def _engine():
    engine = create_engine("sqlite://")
    metadata = MetaData()
    users = Table("users", metadata,
                  Column("id", Integer, primary_key=True),
                  Column("email", String, nullable=False),
                  Column("extra_permissions", JSON),
                  Column("access_policy", JSON))
    version = Table("alembic_version", metadata, Column("version_num", String, primary_key=True))
    metadata.create_all(engine)
    return engine, users, version


def test_0130_preflight_reports_exact_before_after_and_recovery_snapshot():
    engine, users, version = _engine()
    with engine.begin() as connection:
        connection.execute(insert(users), {
            "id": 9,
            "email": "Mubina@MilanaPremium.uz",
            "extra_permissions": ["sales.view"],
            "access_policy": {"MIL": {"allow": [], "deny": [TARGET_PERMISSION_0130]}},
        })
        connection.execute(insert(version),
                           {"version_num": PREDECESSOR_0130})

    with engine.connect() as connection:
        report = preview_0130_permissions(connection)

    assert report["matching_account_count"] == 1
    assert report["changed_account_count"] == 1
    account = report["accounts"][0]
    assert account["user_id"] == 9
    assert account["before"]["extra_permissions"] == ["sales.view"]
    assert account["before"]["access_policy"]["MIL"]["deny"] == [TARGET_PERMISSION_0130]
    assert TARGET_PERMISSION_0130 in account["after"]["extra_permissions"]
    assert TARGET_PERMISSION_0130 in account["after"]["access_policy"]["MIL"]["allow"]
    assert account["after"]["access_policy"]["MIL"]["deny"] == []
    assert len(account["before_sha256"]) == 64
    assert len(account["after_sha256"]) == 64
    engine.dispose()


def test_read_only_preflight_marks_predecessor_and_does_not_write():
    engine, users, version = _engine()
    with engine.begin() as connection:
        connection.execute(insert(users), {"id": 1, "email": "mubina@milanapremium.uz",
                                           "extra_permissions": [], "access_policy": None})
        connection.execute(insert(version), {"version_num": PREDECESSOR_0130})

    report = read_only_preflight_0130(engine)
    with engine.connect() as connection:
        persisted = connection.execute(users.select()).mappings().one()
    assert report["applicability"] == "ready_for_review"
    assert report["migration_pending"] is True
    assert persisted["extra_permissions"] == []
    assert persisted["access_policy"] is None
    engine.dispose()


def test_0130_preflight_never_echoes_target_email():
    engine, users, version = _engine()
    with engine.begin() as connection:
        connection.execute(insert(users), {"id": 1, "email": "mubina@milanapremium.uz",
                                           "extra_permissions": [], "access_policy": None})
        connection.execute(insert(version),
                           {"version_num": "0130_eco_fabric_transfers"})
    import json
    report_text = json.dumps(read_only_preflight_0130(engine))
    assert "mubina@milanapremium.uz" not in report_text
    engine.dispose()


def test_null_mil_policy_is_reported_as_migration_blocker():
    engine, users, version = _engine()
    with engine.begin() as connection:
        connection.execute(insert(users), {"id": 4, "email": "mubina@milanapremium.uz",
                                           "extra_permissions": [], "access_policy": {"MIL": None}})
        connection.execute(insert(version), {"version_num": PREDECESSOR_0130})

    report = read_only_preflight_0130(engine)
    assert report["applicability"] == "blocked_by_migration_input"
    assert report["blocked_account_count"] == 1
    assert "TypeError" in report["accounts"][0]["blocker"]
    assert report["accounts"][0]["before"]["access_policy"] == {"MIL": None}
    engine.dispose()
