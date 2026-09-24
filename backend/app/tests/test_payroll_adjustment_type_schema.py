from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models import AuditLog, PayrollAdjustment
from app.schemas.payroll import PayrollAdjustmentIn
from app.tests.conftest import TestSessionLocal


def _counts() -> tuple[int, int]:
    with TestSessionLocal() as db:
        return db.query(PayrollAdjustment).count(), db.query(AuditLog).count()


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        ("bonus", "bonus"),
        (" BONUS ", "bonus"),
        ("deduction", "deduction"),
        ("\tDeDuCtIoN\n", "deduction"),
        (None, None),
        (" \t ", None),
    ],
)
def test_payroll_adjustment_schema_normalizes_legacy_adjustment_type_inputs(raw_value, expected):
    payload = PayrollAdjustmentIn(
        employee_id=1,
        amount=1,
        reason="Schema contract",
        adjustment_type=raw_value,
    )

    assert payload.adjustment_type == expected


@pytest.mark.parametrize("raw_value", ["advance", "BONUS_REFUND", 1, True])
def test_payroll_adjustment_schema_rejects_values_outside_finite_vocabulary(raw_value):
    with pytest.raises(ValidationError):
        PayrollAdjustmentIn(
            employee_id=1,
            amount=1,
            reason="Schema contract",
            adjustment_type=raw_value,
        )


def _create_employee(client, auth_headers) -> int:
    response = client.post(
        "/api/employees",
        json={"full_name": f"Adjustment Type {uuid4().hex[:8]}", "position": "Operator", "status": "active"},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_payroll_adjustment_api_preserves_normalization_and_implicit_type_rules(client, auth_headers):
    employee_id = _create_employee(client, auth_headers)

    normalized = client.post(
        "/api/payroll/adjustments",
        json={
            "employee_id": employee_id,
            "adjustment_type": "  DeDuCtIoN  ",
            "amount": 25,
            "reason": "Normalized deduction",
        },
        headers=auth_headers,
    )
    assert normalized.status_code == 201, normalized.text
    assert normalized.json()["adjustment_type"] == "deduction"
    assert float(normalized.json()["signed_amount"]) == -25

    blank_positive = client.post(
        "/api/payroll/adjustments",
        json={"employee_id": employee_id, "adjustment_type": "  ", "amount": 10, "reason": "Blank defaults"},
        headers=auth_headers,
    )
    assert blank_positive.status_code == 201, blank_positive.text
    assert blank_positive.json()["adjustment_type"] == "bonus"
    assert float(blank_positive.json()["signed_amount"]) == 10

    inferred_negative = client.post(
        "/api/payroll/adjustments",
        json={"employee_id": employee_id, "amount": -5, "reason": "Inferred deduction"},
        headers=auth_headers,
    )
    assert inferred_negative.status_code == 201, inferred_negative.text
    assert inferred_negative.json()["adjustment_type"] == "deduction"
    assert float(inferred_negative.json()["signed_amount"]) == -5


def test_invalid_adjustment_type_rejects_before_reference_lookup_and_writes(client, auth_headers):
    before = _counts()

    response = client.post(
        "/api/payroll/adjustments",
        json={
            "payroll_period_id": 2_147_483_647,
            "employee_id": 2_147_483_647,
            "adjustment_type": "unsupported",
            "amount": 10,
            "reason": "No write",
        },
        headers=auth_headers,
    )

    assert response.status_code == 422, response.text
    assert any(error["loc"][-1] == "adjustment_type" for error in response.json()["detail"])
    assert _counts() == before


def test_invalid_adjustment_type_preserves_authentication_precedence(client):
    before = _counts()

    response = client.post(
        "/api/payroll/adjustments",
        json={"employee_id": 2_147_483_647, "adjustment_type": "unsupported", "amount": 10, "reason": "No write"},
    )

    assert response.status_code == 401, response.text
    assert _counts() == before


def test_negative_bonus_adjustment_remains_rejected_without_writes(client, auth_headers):
    employee_id = _create_employee(client, auth_headers)
    before = _counts()

    response = client.post(
        "/api/payroll/adjustments",
        json={"employee_id": employee_id, "adjustment_type": " BONUS ", "amount": -10, "reason": "Invalid sign"},
        headers=auth_headers,
    )

    assert response.status_code == 400, response.text
    assert "Negative adjustments must use adjustment_type=deduction" in response.json()["detail"]
    assert _counts() == before
