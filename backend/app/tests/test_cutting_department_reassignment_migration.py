from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "0109_reassign_121_122_to_ect.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("migration_0109", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _safe_row(**changes):
    row = {
        "production_type": "branded_stock",
        "production_status": "planning",
        "operation": "cutting",
        "department_code": "CUT",
        "work_status": "waiting",
        "start_time": None,
        "end_time": None,
        "actual_input_qty": 0,
        "actual_output_qty": 0,
        "passed_qty": 0,
        "failed_qty": 0,
        "rework_qty": 0,
        "production_batch_count": 0,
        "cutting_record_count": 0,
        "bundle_count": 0,
        "sewing_record_count": 0,
        "packaging_record_count": 0,
        "package_count": 0,
        "sewing_assignment_count": 0,
        "replacement_request_count": 0,
    }
    row.update(changes)
    return row


def test_migration_targets_only_the_two_requested_production_orders():
    migration = _load_migration()

    assert migration.TARGET_PRODUCTION_NUMBERS == (
        "PO-2026-000121",
        "PO-2026-000122",
    )
    assert migration.SOURCE_DEPARTMENT_CODE == "CUT"
    assert migration.TARGET_DEPARTMENT_CODE == "ECT"
    assert migration._unsafe_reason(_safe_row()) is None


def test_migration_resolves_sewing_assignments_through_work_orders():
    source = MIGRATION.read_text(encoding="utf-8")

    assert "JOIN work_orders sawo ON sawo.id = sassign.work_order_id" in source
    assert "sassign.production_order_id" not in source


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"production_status": "cutting"}, "production status"),
        ({"department_code": "ECT"}, "cutting department"),
        ({"work_status": "in_progress"}, "work order status"),
        ({"start_time": "2026-08-26T00:00:00Z"}, "start/end timestamps"),
        ({"passed_qty": 1}, "recorded quantities"),
        ({"cutting_record_count": 1}, "production evidence"),
        ({"bundle_count": 1}, "production evidence"),
        ({"package_count": 1}, "production evidence"),
    ],
)
def test_migration_refuses_started_or_changed_work(changes, expected):
    migration = _load_migration()

    assert expected in migration._unsafe_reason(_safe_row(**changes))


def test_migration_audit_hash_is_deterministic():
    migration = _load_migration()
    old_value = {"department_code": "CUT", "production_no": "PO-2026-000121"}
    new_value = {"department_code": "ECT", "production_no": "PO-2026-000121"}

    first = migration._entry_hash(
        previous="prior",
        entity_id=535,
        old_value=old_value,
        new_value=new_value,
    )
    second = migration._entry_hash(
        previous="prior",
        entity_id=535,
        old_value=dict(reversed(list(old_value.items()))),
        new_value=dict(reversed(list(new_value.items()))),
    )

    assert first == second
    assert len(first) == 64
