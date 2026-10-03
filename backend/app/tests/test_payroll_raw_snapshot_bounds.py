import json

import pytest
from fastapi import HTTPException

from app.api.routes.payroll import _normalize_record_payload
from app.models import AuditLog, PayrollQrLabel, PayrollRecord
from app.schemas.payroll import PayrollRecordIn
from app.tests.conftest import TestSessionLocal


MAX_PAYROLL_SNAPSHOT_BYTES = 16 * 1024
MAX_PAYROLL_SNAPSHOT_DEPTH = 16


def _employee(client, auth_headers):
    response = client.post("/api/employees", headers=auth_headers, json={"full_name": "Snapshot worker"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


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
    assert _normalize_record_payload(PayrollRecordIn(quantity="1", rate_per_piece="1", work=snapshot))["raw_work_json"] == snapshot


def test_payroll_raw_snapshot_depth_limit_is_inclusive():
    assert _normalize_record_payload(PayrollRecordIn(quantity="1", rate_per_piece="1", work=_nested_arrays(MAX_PAYROLL_SNAPSHOT_DEPTH)))["raw_work_json"]

    with pytest.raises(HTTPException) as exc_info:
        _normalize_record_payload(PayrollRecordIn(quantity="1", rate_per_piece="1", work=_nested_arrays(MAX_PAYROLL_SNAPSHOT_DEPTH + 1)))
    assert exc_info.value.status_code == 422


def test_single_oversized_employee_snapshot_rejects_without_record_or_audit_write(client, auth_headers):
    employee_id = _employee(client, auth_headers)
    before = _write_counts()

    response = client.post(
        "/api/payroll/records",
        headers=auth_headers,
        json={"employee_id": employee_id, "quantity": "1", "rate_per_piece": "1", "employee": {"legacy_extension": "x" * MAX_PAYROLL_SNAPSHOT_BYTES}},
    )

    assert response.status_code == 422, response.text
    assert _write_counts() == before


def test_bulk_oversized_work_snapshot_rejects_without_partial_writes(client, auth_headers):
    employee_id = _employee(client, auth_headers)
    before = _write_counts()

    response = client.post(
        "/api/payroll/records/bulk",
        headers=auth_headers,
        json={"records": [
            {"employee_id": employee_id, "quantity": "1", "rate_per_piece": "1", "work": {"legacy_extension": "x" * MAX_PAYROLL_SNAPSHOT_BYTES}},
            {"employee_id": employee_id, "quantity": "1", "rate_per_piece": "2", "work": {"extension": "valid-second-row"}},
        ]},
    )

    assert response.status_code == 422, response.text
    assert _write_counts() == before


def test_compact_mw2_normalization_preserves_reference_fields_and_open_keys():
    compact = "MW2*12*PO-12*34*B-34*2*MODEL-A*sewing*SEW*Sleeve*5*250*UZS*1*56*SO-56*78*90*LBL-1*L*11*LINE-A*Sewing line*22*CP-22"
    normalized = _normalize_record_payload(
        PayrollRecordIn(quantity="1", rate_per_piece="1", work=compact, employee={"employee_id": 9, "extension_key": "kept"})
    )

    assert normalized["raw_employee_json"] == {"employee_id": 9, "extension_key": "kept"}
    assert normalized["raw_work_json"]["production_no"] == "PO-12"
    assert normalized["raw_work_json"]["sales_order_no"] == "SO-56"
    assert normalized["raw_work_json"]["label_id"] == "LBL-1"
    assert normalized["raw_work_json"]["cutting_passport_no"] == "CP-22"


def test_nonobject_legacy_snapshot_still_normalizes_to_absent():
    normalized = _normalize_record_payload(PayrollRecordIn(quantity="1", rate_per_piece="1", employee=["legacy"], work="[1,2,3]"))

    assert normalized["raw_employee_json"] is None
    assert normalized["raw_work_json"] is None


@pytest.mark.parametrize("field", ["employee", "work"])
@pytest.mark.parametrize("snapshot", [
    {"extension": "я" * (MAX_PAYROLL_SNAPSHOT_BYTES // 2)},
    _nested_arrays(MAX_PAYROLL_SNAPSHOT_DEPTH + 1),
    {"extension": float("inf")},
])
def test_payroll_snapshot_rejects_utf8_depth_and_nonfinite_values(client, auth_headers, field, snapshot):
    employee_id = _employee(client, auth_headers)
    before = _write_counts()
    response = client.post("/api/payroll/records", headers={**auth_headers, "Content-Type": "application/json"},
                           content=json.dumps({"employee_id": employee_id, "quantity": "1", "rate_per_piece": "1", field: snapshot}))
    assert response.status_code == 422, response.text
    assert _write_counts() == before


@pytest.mark.parametrize("bulk", [False, True])
def test_payroll_snapshot_rechecks_after_trusted_label_enrichment(client, auth_headers, bulk):
    employee_id = _employee(client, auth_headers)
    uid = "SNAPSHOT-ENRICHMENT"
    with TestSessionLocal.begin() as db:
        db.add(PayrollQrLabel(factory_code="MIL", label_uid=uid, quantity=1, rate_per_piece=1,
                             currency="UZS", status="available", sewing_line_name="Line one"))
    work = {"extension": "x" * (MAX_PAYROLL_SNAPSHOT_BYTES - len('{"extension":""}'))}
    assert len(json.dumps(work, separators=(",", ":")).encode("utf-8")) == MAX_PAYROLL_SNAPSHOT_BYTES
    record = {"employee_id": employee_id, "scan_uid": uid, "quantity": "1", "rate_per_piece": "1", "work": work}
    payload = {"records": [
        {"employee_id": employee_id, "quantity": "1", "rate_per_piece": "2"}, record,
    ]} if bulk else record
    before = _write_counts()
    response = client.post("/api/payroll/records/bulk" if bulk else "/api/payroll/records",
                           headers=auth_headers, json=payload)
    assert response.status_code == 422, response.text
    assert _write_counts() == before
    with TestSessionLocal() as db:
        assert db.query(PayrollQrLabel).filter_by(label_uid=uid).one().status == "available"
