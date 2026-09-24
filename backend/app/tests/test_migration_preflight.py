from __future__ import annotations

from sqlalchemy import JSON, Column, ForeignKey, Integer, MetaData, String, Table, create_engine, insert

from app.migrations.preflight import (
    PREDECESSOR_0055,
    PREDECESSOR_0130,
    TARGET_PRODUCTION_NO_0055,
    TARGET_PERMISSION_0130,
    preview_0130_permissions,
    read_only_preflight_0055,
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


def _engine_0055():
    engine = create_engine("sqlite://")
    metadata = MetaData()
    orders = Table(
        "production_orders", metadata,
        Column("id", Integer, primary_key=True),
        Column("production_no", String, nullable=False),
        Column("notes", String),
    )
    work_orders = Table(
        "work_orders", metadata,
        Column("id", Integer, primary_key=True),
        Column("production_order_id", ForeignKey("production_orders.id")),
        Column("status", String),
        *(Column(name, Integer) for name in (
            "actual_input_qty", "actual_output_qty", "passed_qty", "failed_qty", "rework_qty",
        )),
    )
    items = Table(
        "production_order_items", metadata,
        Column("id", Integer, primary_key=True),
        Column("production_order_id", ForeignKey("production_orders.id")),
    )
    packages = Table(
        "packages", metadata,
        Column("id", Integer, primary_key=True),
        Column("production_order_id", ForeignKey("production_orders.id")),
    )
    version = Table("alembic_version", metadata, Column("version_num", String, primary_key=True))
    metadata.create_all(engine)
    return engine, orders, work_orders, items, packages, version


def _waiting_work_row(order_id, *, work_id=11, status="waiting", **overrides):
    row = {
        "id": work_id,
        "production_order_id": order_id,
        "status": status,
        "actual_input_qty": 0,
        "actual_output_qty": 0,
        "passed_qty": 0,
        "failed_qty": 0,
        "rework_qty": 0,
    }
    row.update(overrides)
    return row


def test_0055_preflight_identifies_exact_direct_delete_ids_and_is_read_only():
    engine, orders, work_orders, items, packages, version = _engine_0055()
    with engine.begin() as connection:
        connection.execute(insert(version), {"version_num": PREDECESSOR_0055})
        connection.execute(insert(orders), [
            {"id": 1, "production_no": TARGET_PRODUCTION_NO_0055, "notes": "preserve in backup"},
            {"id": 2, "production_no": "PO-OTHER", "notes": None},
        ])
        connection.execute(insert(work_orders), [
            _waiting_work_row(1),
            _waiting_work_row(2, work_id=12),
        ])
        connection.execute(insert(items), [
            {"id": 21, "production_order_id": 1},
            {"id": 22, "production_order_id": 2},
        ])

    report = read_only_preflight_0055(engine)
    assert report["applicability"] == "ready_for_operator_review"
    assert report["matching_order_count"] == 1
    assert report["direct_deletes"]["production_orders"]["ids"] == [1]
    assert report["direct_deletes"]["work_orders"]["ids"] == [11]
    assert report["direct_deletes"]["production_order_items"]["ids"] == [21]
    assert len(report["direct_deletes"]["production_orders"]["snapshot_sha256"]) == 64
    assert report["external_references"] == []
    import json
    assert "preserve in backup" not in json.dumps(report)
    with engine.connect() as connection:
        assert len(connection.execute(orders.select()).all()) == 2
        assert len(connection.execute(work_orders.select()).all()) == 2
        assert len(connection.execute(items.select()).all()) == 2
    engine.dispose()


def test_0055_preflight_flags_guarded_activity_and_external_references():
    engine, orders, work_orders, items, packages, version = _engine_0055()
    with engine.begin() as connection:
        connection.execute(insert(version), {"version_num": PREDECESSOR_0055})
        connection.execute(insert(orders), {"id": 1, "production_no": TARGET_PRODUCTION_NO_0055})
        connection.execute(insert(work_orders), _waiting_work_row(1, actual_output_qty=3))
        connection.execute(insert(packages), {"id": 31, "production_order_id": 1})

    report = read_only_preflight_0055(engine)
    assert report["applicability"] == "manual_review_required"
    assert report["migration_guard_work_order_ids"] == [11]
    assert report["external_references"] == [{
        "table": "packages",
        "column": "production_order_id",
        "referred_table": "production_orders",
        "count": 1,
        "ondelete": None,
    }]
    engine.dispose()


def test_0055_preflight_flags_null_guard_values_the_migration_may_not_detect():
    engine, orders, work_orders, items, packages, version = _engine_0055()
    with engine.begin() as connection:
        connection.execute(insert(version), {"version_num": PREDECESSOR_0055})
        connection.execute(insert(orders), {"id": 1, "production_no": TARGET_PRODUCTION_NO_0055})
        connection.execute(insert(work_orders), _waiting_work_row(1, passed_qty=None))

    report = read_only_preflight_0055(engine)
    assert report["applicability"] == "manual_review_required"
    assert report["migration_guard_work_order_ids"] == []
    assert report["null_guard_work_order_ids"] == [11]
    engine.dispose()


def test_0055_preflight_no_target_and_revision_mismatch_do_not_claim_ready():
    engine, orders, work_orders, items, packages, version = _engine_0055()
    with engine.begin() as connection:
        connection.execute(insert(version), {"version_num": PREDECESSOR_0055})

    assert read_only_preflight_0055(engine)["applicability"] == "no_target"
    with engine.begin() as connection:
        connection.execute(version.update().values(version_num="0130_eco_fabric_transfers"))
        connection.execute(insert(orders), {"id": 1, "production_no": TARGET_PRODUCTION_NO_0055})
    report = read_only_preflight_0055(engine)
    assert report["applicability"] == "revision_mismatch_review_required"
    assert report["migration_pending"] is False
    engine.dispose()
