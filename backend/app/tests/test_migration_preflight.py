from __future__ import annotations

from sqlalchemy import JSON, Column, ForeignKey, Integer, MetaData, String, Table, create_engine, insert, text

from app.migrations.preflight import (
    PREDECESSOR_0055,
    PREDECESSOR_0130,
    PREDECESSOR_0091,
    PREDECESSOR_0092,
    REVISION_0091,
    REVISION_0092,
    TARGET_PRODUCTION_NO_0055,
    TARGET_PERMISSION_0130,
    preview_0130_permissions,
    read_only_preflight_0091_0092,
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
    assert report["affected_rows_inspected"] is False
    engine.dispose()


def test_0055_revision_mismatch_does_not_reflect_unrelated_schema():
    engine = create_engine("sqlite://")
    metadata = MetaData()
    version = Table("alembic_version", metadata, Column("version_num", String, primary_key=True))
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(insert(version), {"version_num": "unrelated_revision"})

    report = read_only_preflight_0055(engine)
    assert report["applicability"] == "revision_mismatch_review_required"
    assert report["affected_rows_inspected"] is False
    engine.dispose()


def _engine_role_overwrites(revision: str):
    engine = create_engine("sqlite://")
    metadata = MetaData()
    roles = Table(
        "roles", metadata,
        Column("id", Integer, primary_key=True),
        Column("name", String, nullable=False),
        Column("permissions", JSON, nullable=False),
    )
    version = Table("alembic_version", metadata, Column("version_num", String, primary_key=True))
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(insert(version), {"version_num": revision})
    return engine, roles


def test_0091_0092_preflight_is_read_only_and_reports_case_insensitive_targets():
    engine, roles = _engine_role_overwrites(PREDECESSOR_0091)
    with engine.begin() as connection:
        connection.execute(insert(roles), [
            {"id": 1, "name": "Payroll", "permissions": ["payroll.custom"]},
            {"id": 2, "name": "PAYROLL", "permissions": ["payroll.legacy"]},
            {"id": 3, "name": "sEwInG", "permissions": ["sewing.custom"]},
            {"id": 4, "name": "superpayroll", "permissions": ["admin.all"]},
        ])

    report = read_only_preflight_0091_0092(engine)
    payroll, sewing = report["stages"]
    assert report["database_revision"] == PREDECESSOR_0091
    assert report["migration_plan"] == "both_stages_pending"
    assert report["selected_revisions"] == [REVISION_0091, REVISION_0092]
    assert payroll["revision"] == REVISION_0091
    assert payroll["applicability"] == "multiple_matches_review_required"
    assert payroll["matching_role_count"] == 2
    assert [role["role_id"] for role in payroll["roles"]] == [1, 2]
    assert [role["before_permissions"] for role in payroll["roles"]] == [
        ["payroll.custom"], ["payroll.legacy"],
    ]
    assert all(role["after_permissions"] == [
        "payroll.view", "payroll.manage", "payroll.scan", "sewing.daily_reports.view",
    ] for role in payroll["roles"])
    assert all(role["restoration_snapshot"]["permissions"] == role["before_permissions"]
               for role in payroll["roles"])
    assert all(len(role["restoration_sha256"]) == 64 for role in payroll["roles"])
    assert sewing["applicability"] == "awaiting_predecessor"
    assert sewing["roles"][0]["before_permissions"] == ["sewing.custom"]
    assert sewing["roles"][0]["after_permissions"] == [
        "sewing.workspace", "sewing.records", "sewing.bundles", "sewing.flows", "traceability.view",
    ]

    with engine.connect() as connection:
        persisted = connection.execute(roles.select().order_by(roles.c.id)).mappings().all()
    assert [row["permissions"] for row in persisted] == [
        ["payroll.custom"], ["payroll.legacy"], ["sewing.custom"], ["admin.all"],
    ]
    engine.dispose()


def test_0092_preflight_distinguishes_only_0092_pending_and_restores_exact_grants():
    engine, roles = _engine_role_overwrites(PREDECESSOR_0092)
    payroll_permissions = ["payroll.view", "payroll.manage", "payroll.scan", "sewing.daily_reports.view"]
    sewing_permissions = ["sewing.custom", "sewing.records"]
    with engine.begin() as connection:
        connection.execute(insert(roles), [
            {"id": 7, "name": "payroll", "permissions": payroll_permissions},
            {"id": 8, "name": "SEWING", "permissions": sewing_permissions},
            {"id": 9, "name": "administrator", "permissions": ["admin.all"]},
        ])

    report = read_only_preflight_0091_0092(engine, revision="0092")
    assert report["migration_plan"] == "0092_only_pending"
    assert report["selected_revisions"] == [REVISION_0092]
    assert len(report["stages"]) == 1
    stage = report["stages"][0]
    assert stage["expected_predecessor"] == PREDECESSOR_0092
    assert stage["applicability"] == "ready_for_review"
    assert stage["roles"][0]["role_id"] == 8
    assert stage["roles"][0]["before_permissions"] == sewing_permissions
    assert stage["roles"][0]["restoration_snapshot"]["permissions"] == sewing_permissions
    assert stage["roles"][0]["after_permissions"] == [
        "sewing.workspace", "sewing.records", "sewing.bundles", "sewing.flows", "traceability.view",
    ]

    with engine.connect() as connection:
        persisted = connection.execute(roles.select().order_by(roles.c.id)).mappings().all()
    assert [row["permissions"] for row in persisted] == [payroll_permissions, sewing_permissions, ["admin.all"]]
    engine.dispose()


def test_0091_0092_preflight_reports_applied_and_mismatched_revisions_without_claiming_pending():
    engine, roles = _engine_role_overwrites(REVISION_0092)
    with engine.begin() as connection:
        connection.execute(insert(roles), {"id": 1, "name": "Payroll", "permissions": ["custom"]})
    applied_report = read_only_preflight_0091_0092(engine)
    assert applied_report["migration_plan"] == "both_stages_applied"
    assert [stage["applicability"] for stage in applied_report["stages"]] == [
        "migration_already_applied", "migration_already_applied",
    ]
    assert applied_report["stages"][0]["roles"][0]["observed_permissions"] == ["custom"]

    with engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num = '0130_eco_fabric_transfers'"))
    descendant_report = read_only_preflight_0091_0092(engine)
    assert descendant_report["migration_plan"] == "both_stages_applied"
    assert all(stage["applicability"] == "migration_already_applied"
               for stage in descendant_report["stages"])

    with engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num = 'unrelated_revision'"))
    mismatch_report = read_only_preflight_0091_0092(engine, revision="0091")
    assert mismatch_report["migration_plan"] == "revision_mismatch_review_required"
    assert mismatch_report["stages"][0]["applicability"] == "revision_mismatch_review_required"
    engine.dispose()
