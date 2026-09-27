import json

import pytest
from fastapi import HTTPException

from app.api.routes.payroll import (
    MAX_PAYROLL_SNAPSHOT_BYTES,
    MAX_PAYROLL_SNAPSHOT_DEPTH,
    _normalize_record_payload,
    _validate_payroll_snapshot,
)
from app.models import AuditLog, PayrollRecord
from app.schemas.payroll import PayrollRecordIn
from app.tests.conftest import TestSessionLocal


def _write_counts() -> tuple[int, int]:
    with TestSessionLocal() as db:
        return db.query(PayrollRecord).count(), db.query(AuditLog).count()


def _nested_arrays(levels: int):
    value = "leaf"
    for _ in range(levels - 1):
        value = [value]
    return {"open": value}


def test_payroll_raw_snapshot_bounds_allow_unknown_keys_and_exact_byte_limit():
    # Keep arbitrary legacy/extension keys; the limit is inclusive.
    prefix = '{"extension":"'
    suffix = '"}'
    snapshot = {"extension": "x" * (MAX_PAYROLL_SNAPSHOT_BYTES - len(prefix) - len(suffix))}

    encoded = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    assert len(encoded) == MAX_PAYROLL_SNAPSHOT_BYTES
    assert _validate_payroll_snapshot(snapshot, "work") is snapshot


def test_payroll_raw_snapshot_depth_limit_is_inclusive():
    assert _validate_payroll_snapshot(_nested_arrays(MAX_PAYROLL_SNAPSHOT_DEPTH), "work")

    with pytest.raises(HTTPException) as exc_info:
        _validate_payroll_snapshot(_nested_arrays(MAX_PAYROLL_SNAPSHOT_DEPTH + 1), "work")
    assert exc_info.value.status_code == 422


def test_single_oversized_employee_snapshot_rejects_without_record_or_audit_write(client, auth_headers):
    before = _write_counts()

    response = client.post(
        "/api/payroll/records",
        headers=auth_headers,
        json={"employee": {"legacy_extension": "x" * MAX_PAYROLL_SNAPSHOT_BYTES}},
    )

    assert response.status_code == 422, response.text
    assert _write_counts() == before


def test_bulk_oversized_work_snapshot_rejects_without_partial_writes(client, auth_headers):
    before = _write_counts()

    response = client.post(
        "/api/payroll/records/bulk",
        headers=auth_headers,
        json={"records": [
            {"employee_id": 1, "quantity": 1, "rate_per_piece": 1, "work": {"label_id": "valid-looking-first-row"}},
            {"work": {"legacy_extension": "x" * MAX_PAYROLL_SNAPSHOT_BYTES}},
        ]},
    )

    assert response.status_code == 422, response.text
    assert _write_counts() == before


def test_compact_mw2_normalization_preserves_reference_fields_and_open_keys():
    compact = "MW2*12*PO-12*34*B-34*2*MODEL-A*sewing*SEW*Sleeve*5*250*UZS*1*56*SO-56*78*90*LBL-1*L*11*LINE-A*Sewing line*22*CP-22"
    normalized = _normalize_record_payload(
        PayrollRecordIn(work=compact, employee={"employee_id": 9, "extension_key": "kept"})
    )

    assert normalized["raw_employee_json"] == {"employee_id": 9, "extension_key": "kept"}
    assert normalized["raw_work_json"]["production_no"] == "PO-12"
    assert normalized["raw_work_json"]["sales_order_no"] == "SO-56"
    assert normalized["raw_work_json"]["label_id"] == "LBL-1"
    assert normalized["raw_work_json"]["cutting_passport_no"] == "CP-22"


def test_nonobject_legacy_snapshot_still_normalizes_to_absent():
    normalized = _normalize_record_payload(
        PayrollRecordIn(employee=["legacy"], work="[1,2,3]", employee_id=1, quantity=1, rate_per_piece=1)
    )

    assert normalized["raw_employee_json"] is None
    assert normalized["raw_work_json"] is None
