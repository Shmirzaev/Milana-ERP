from __future__ import annotations

import json

from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, insert, select

from app.migrations.preflight_0101 import (
    PREDECESSOR_0101,
    REVISION_0101,
    read_only_preflight_0101,
)


def _engine(revision: str = PREDECESSOR_0101):
    engine = create_engine("sqlite://")
    metadata = MetaData()
    versions = Table("alembic_version", metadata, Column("version_num", String, primary_key=True))
    users = Table("users", metadata, Column("id", Integer, primary_key=True), Column("factory_code", String))
    departments = Table("departments", metadata, Column("id", Integer, primary_key=True), Column("code", String))
    employees = Table(
        "employees", metadata, Column("id", Integer, primary_key=True), Column("user_id", Integer),
        Column("department_id", Integer), Column("employee_no", String),
    )
    periods = Table(
        "payroll_periods", metadata, Column("id", Integer, primary_key=True), Column("period_no", String),
        Column("created_by", Integer),
    )
    records = Table(
        "payroll_records", metadata, Column("id", Integer, primary_key=True),
        Column("payroll_period_id", Integer), Column("employee_id", Integer), Column("scanned_by", Integer),
        Column("scan_uid", String), Column("dedupe_key", String),
    )
    labels = Table(
        "payroll_qr_labels", metadata, Column("id", Integer, primary_key=True),
        Column("payroll_record_id", Integer), Column("sewing_flow_id", Integer),
        Column("production_order_id", Integer), Column("issued_by", Integer), Column("label_uid", String),
    )
    adjustments = Table(
        "payroll_adjustments", metadata, Column("id", Integer, primary_key=True),
        Column("employee_id", Integer), Column("created_by", Integer),
    )
    flows = Table(
        "sewing_flows", metadata, Column("id", Integer, primary_key=True), Column("factory_code", String),
    )
    bundles = Table(
        "bundles", metadata, Column("id", Integer, primary_key=True), Column("production_order_id", Integer),
        Column("status", String), Column("sewing_factory_code", String),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(insert(versions), {"version_num": revision})
        connection.execute(insert(users), [
            {"id": 1, "factory_code": "BST"}, {"id": 2, "factory_code": "BAD"},
            {"id": 3, "factory_code": None},
        ])
        connection.execute(insert(departments), [
            {"id": 10, "code": "ECT"}, {"id": 11, "code": "UNKNOWN"},
        ])
        connection.execute(insert(employees), [
            {"id": 1, "user_id": 1, "department_id": 10, "employee_no": "E-1"},
            {"id": 2, "user_id": 3, "department_id": 10, "employee_no": "E-2"},
            {"id": 3, "user_id": None, "department_id": None, "employee_no": "DUP"},
            {"id": 4, "user_id": None, "department_id": 11, "employee_no": "DUP"},
            {"id": 5, "user_id": 2, "department_id": None, "employee_no": "E-5"},
        ])
        connection.execute(insert(periods), [
            {"id": 100, "period_no": "P-MIX", "created_by": 1},
            {"id": 101, "period_no": "P-DUP", "created_by": 1},
            {"id": 102, "period_no": "P-DUP", "created_by": 1},
            {"id": 103, "period_no": "P-MIL", "created_by": None},
        ])
        connection.execute(insert(records), [
            {"id": 10, "payroll_period_id": 100, "employee_id": 1, "scanned_by": None,
             "scan_uid": "scan-duplicate", "dedupe_key": "dedupe-duplicate"},
            {"id": 11, "payroll_period_id": 100, "employee_id": 2, "scanned_by": None,
             "scan_uid": "scan-11", "dedupe_key": "dedupe-11"},
            {"id": 12, "payroll_period_id": None, "employee_id": None, "scanned_by": 2,
             "scan_uid": None, "dedupe_key": None},
            {"id": 13, "payroll_period_id": None, "employee_id": None, "scanned_by": None,
             "scan_uid": None, "dedupe_key": None},
            {"id": 14, "payroll_period_id": None, "employee_id": 1, "scanned_by": None,
             "scan_uid": "scan-duplicate", "dedupe_key": "dedupe-duplicate"},
        ])
        connection.execute(insert(labels), [
            {"id": 20, "payroll_record_id": 10, "sewing_flow_id": None,
             "production_order_id": 77, "issued_by": 1, "label_uid": "label-bst"},
            {"id": 21, "payroll_record_id": None, "sewing_flow_id": None,
             "production_order_id": 77, "issued_by": 1, "label_uid": "label-ambiguous"},
            {"id": 22, "payroll_record_id": None, "sewing_flow_id": None,
             "production_order_id": 78, "issued_by": None, "label_uid": "label-single"},
            {"id": 23, "payroll_record_id": None, "sewing_flow_id": None,
             "production_order_id": None, "issued_by": None, "label_uid": "label-mil"},
            {"id": 24, "payroll_record_id": None, "sewing_flow_id": None,
             "production_order_id": None, "issued_by": 1, "label_uid": "label-bst"},
        ])
        connection.execute(insert(adjustments), [
            {"id": 30, "employee_id": 2, "created_by": None},
            {"id": 31, "employee_id": None, "created_by": 2},
            {"id": 32, "employee_id": None, "created_by": None},
        ])
        connection.execute(insert(flows), [])
        connection.execute(insert(bundles), [
            {"id": 70, "production_order_id": 77, "status": "active", "sewing_factory_code": "BST"},
            {"id": 71, "production_order_id": 77, "status": "active", "sewing_factory_code": "ECO"},
            {"id": 72, "production_order_id": 78, "status": "active", "sewing_factory_code": "ECO"},
            {"id": 73, "production_order_id": 78, "status": "cancelled", "sewing_factory_code": "BST"},
        ])
    return engine


def test_0101_projection_mirrors_priority_and_identifies_migration_blockers():
    engine = _engine()
    report = read_only_preflight_0101(engine)

    assert report["revision"] == REVISION_0101
    assert report["expected_predecessor"] == PREDECESSOR_0101
    assert report["applicability"] == "blockers_found_review_required"
    predicted = report["factory_code_predictions"]
    assert [(row["id"], row["factory_code_after"], row["source"])
            for row in predicted["employees"]["predictions"]] == [
        (1, "BST", "employee_user"), (2, "ECO", "employee_department_mapping"),
        (3, "MIL", "employee_fallback_mil"), (4, "MIL", "employee_department_default_mil"),
        (5, "BAD", "employee_user"),
    ]
    assert [(row["id"], row["factory_code_after"])
            for row in predicted["payroll_records"]["predictions"]] == [
        (10, "BST"), (11, "ECO"), (12, "BAD"), (13, "MIL"), (14, "BST"),
    ]
    assert [(row["id"], row["factory_code_after"])
            for row in predicted["payroll_periods"]["predictions"]] == [
        (100, "BST"), (101, "BST"), (102, "BST"), (103, "MIL"),
    ]
    assert report["mixed_payroll_periods"]["periods"][0]["payroll_period_id"] == 100
    assert report["mixed_payroll_periods"]["periods"][0]["payroll_record_ids"] == [10, 11]
    assert report["invalid_factory_codes"]["employees"]["ids"] == [5]
    assert report["invalid_factory_codes"]["payroll_records"]["ids"] == [12]
    assert report["default_to_mil"]["employees"]["ids"] == [3, 4]
    assert report["duplicate_new_unique_keys"]["employees"]["employee_no"]["groups"] == [{
        "factory_code": "MIL", "count": 2, "ids": [3, 4], "ids_sha256": report[
            "duplicate_new_unique_keys"]["employees"]["employee_no"]["groups"][0]["ids_sha256"],
    }]
    assert report["duplicate_new_unique_keys"]["payroll_records"]["scan_uid"]["groups"][0]["ids"] == [10, 14]
    assert report["duplicate_new_unique_keys"]["payroll_records"]["dedupe_key"]["groups"][0]["ids"] == [10, 14]
    assert report["duplicate_new_unique_keys"]["payroll_periods"]["period_no"]["groups"][0]["ids"] == [101, 102]
    assert report["ambiguous_bundle_factory_attribution"]["count"] == 1
    assert report["ambiguous_bundle_factory_attribution"]["labels"][0]["id"] == 21
    labels = {row["id"]: row["factory_code_after"] for row in predicted["payroll_qr_labels"]["predictions"]}
    assert labels == {20: "BST", 21: "BST", 22: "ECO", 23: "MIL", 24: "BST"}
    assert report["duplicate_new_unique_keys"]["payroll_qr_labels"]["label_uid"]["groups"][0]["ids"] == [20, 24]
    assert [(row["id"], row["factory_code_after"])
            for row in predicted["payroll_adjustments"]["predictions"]] == [
        (30, "ECO"), (31, "BAD"), (32, "MIL"),
    ]

    serialized = json.dumps(report, sort_keys=True)
    assert "E-1" not in serialized and "DUP" not in serialized
    assert "scan-duplicate" not in serialized and "dedupe-duplicate" not in serialized
    assert "label-ambiguous" not in serialized
    assert "payroll_amount" not in serialized
    assert all(len(table["snapshot_sha256"]) == 64 for table in predicted.values())

    # The read-only SQLite mode leaves all predecessor tables and rows intact.
    with engine.connect() as connection:
        employees = Table("employees", MetaData(), autoload_with=connection)
        employee_ids = connection.execute(select(employees.c.id).order_by(employees.c.id)).scalars().all()
        assert employee_ids == [1, 2, 3, 4, 5]
        assert "factory_code" not in employees.c
    engine.dispose()


def test_0101_fails_closed_on_revision_mismatch_before_business_table_inspection():
    engine = create_engine("sqlite://")
    metadata = MetaData()
    versions = Table("alembic_version", metadata, Column("version_num", String, primary_key=True))
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(insert(versions), {"version_num": REVISION_0101})

    report = read_only_preflight_0101(engine)

    assert report["applicability"] == "revision_mismatch_review_required"
    assert report["database_revisions"] == [REVISION_0101]
    assert report["affected_rows_inspected"] is False
    assert "factory_code_predictions" not in report
    engine.dispose()


def test_0101_snapshot_hashes_are_repeatable_and_report_never_says_safe():
    engine = _engine()
    first = read_only_preflight_0101(engine)
    second = read_only_preflight_0101(engine)

    assert first["factory_code_predictions"]["payroll_records"]["snapshot_sha256"] == second[
        "factory_code_predictions"]["payroll_records"]["snapshot_sha256"]
    assert first["mixed_payroll_periods"]["snapshot_sha256"] == second[
        "mixed_payroll_periods"]["snapshot_sha256"]
    assert first["applicability"] != "safe"
    assert "not evidence that the migration is safe" in first["limitations"]
    engine.dispose()
