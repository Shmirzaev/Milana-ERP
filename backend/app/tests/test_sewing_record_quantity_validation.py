import pytest
from pydantic import ValidationError

from app.models import AuditLog, Notification, SewingRecord, SewingReplacementRequest, WasteRecord
from app.schemas.production import SewingRecordIn
from app.tests.conftest import TestSessionLocal


def _payload(**changes):
    payload = {
        "work_order_id": 1,
        "input_qty": 100,
        "sewn_qty": 100,
        "passed_qty": 95,
        "failed_qty": 3,
        "rejected_qty": 2,
    }
    payload.update(changes)
    return payload


@pytest.mark.parametrize(
    "changes",
    [
        {"input_qty": -1},
        {"sewn_qty": 101},
        {"passed_qty": 96, "failed_qty": 3, "rejected_qty": 2},
        {"passed_qty": -1},
        {"failed_qty": -1},
        {"rework_qty": -1},
        {"rejected_qty": -1},
        {"input_qty": 2**31},
        {"sewn_qty": 2**31},
        {"passed_qty": 2**31},
        {"failed_qty": 2**31},
        {"rework_qty": 2**31},
        {"rejected_qty": 2**31},
        {"input_qty": 0, "sewn_qty": 1, "passed_qty": 2, "failed_qty": 0, "rejected_qty": 0},
    ],
)
def test_invalid_sewing_quantities_are_rejected_before_record_creation(changes):
    with pytest.raises(ValidationError):
        SewingRecordIn(**_payload(**changes))


def test_valid_partial_output_with_rejections_is_conserved():
    record = SewingRecordIn(**_payload(input_qty=100, sewn_qty=60, passed_qty=55, failed_qty=2, rejected_qty=3))

    assert record.sewn_qty == 60
    assert record.passed_qty + record.failed_qty + record.rejected_qty == 60


def test_zero_input_keeps_upstream_inference_compatibility():
    record = SewingRecordIn(**_payload(input_qty=0, sewn_qty=10, passed_qty=8, failed_qty=1, rejected_qty=1))

    assert record.input_qty == 0


def test_int4_boundary_is_accepted():
    record = SewingRecordIn(**_payload(
        input_qty=2**31 - 1,
        sewn_qty=2**31 - 1,
        passed_qty=2**31 - 1,
        failed_qty=0,
        rework_qty=2**31 - 1,
        rejected_qty=0,
    ))

    assert record.sewn_qty == 2**31 - 1


def test_invalid_sewing_api_request_has_no_business_side_effects(client, auth_headers):
    with TestSessionLocal() as db:
        before = {
            "records": db.query(SewingRecord).count(),
            "replacements": db.query(SewingReplacementRequest).count(),
            "waste": db.query(WasteRecord).count(),
            "notifications": db.query(Notification).count(),
            "audits": db.query(AuditLog).count(),
        }

    response = client.post(
        "/api/sewing/records",
        headers=auth_headers,
        json=_payload(passed_qty=101, failed_qty=0, rejected_qty=0),
    )

    assert response.status_code == 422, response.text
    with TestSessionLocal() as db:
        after = {
            "records": db.query(SewingRecord).count(),
            "replacements": db.query(SewingReplacementRequest).count(),
            "waste": db.query(WasteRecord).count(),
            "notifications": db.query(Notification).count(),
            "audits": db.query(AuditLog).count(),
        }
    assert after == before
