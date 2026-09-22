from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.db.session import SessionLocal
from app.models import AuditLog, PayrollQrLabel
from app.schemas.payroll import PayrollQrLabelEditIn, PayrollQrLabelIssueIn


MAX_STORED_AMOUNT = Decimal("9999999999.9999")


def _label(**overrides) -> dict:
    return {
        "label_uid": f"PAY-BOUND-{uuid4().hex.upper()}",
        "operation_name": "Bounded sewing operation",
        "quantity": "2.34567",
        "rate_per_piece": "25.12567",
        **overrides,
    }


def _write_counts() -> tuple[int, int]:
    with SessionLocal() as db:
        return db.query(PayrollQrLabel).count(), db.query(AuditLog).count()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("quantity", "-0.0001"),
        ("quantity", "NaN"),
        ("quantity", "Infinity"),
        ("quantity", "10000000000"),
        ("rate_per_piece", "-0.0001"),
        ("rate_per_piece", "NaN"),
        ("rate_per_piece", "Infinity"),
        ("rate_per_piece", "10000000000"),
    ],
)
def test_qr_issue_numeric_fields_reject_negative_non_finite_and_overflow(field, value):
    with pytest.raises(ValidationError):
        PayrollQrLabelIssueIn(**_label(**{field: value}))


@pytest.mark.parametrize("value", ["NaN", "Infinity", "10000000000"])
def test_qr_edit_rate_rejects_non_finite_and_overflow(value):
    with pytest.raises(ValidationError):
        PayrollQrLabelEditIn(operation_name="Sewing", rate_per_piece=value)


def test_qr_numeric_fields_preserve_zero_extra_precision_and_exact_maximum():
    zero = PayrollQrLabelIssueIn(label_uid="ZERO")
    assert zero.quantity == Decimal("0")
    assert zero.rate_per_piece == Decimal("0")

    precise = PayrollQrLabelIssueIn(**_label())
    assert precise.quantity == Decimal("2.34567")
    assert precise.rate_per_piece == Decimal("25.12567")

    maximum = PayrollQrLabelIssueIn(**_label(
        quantity=str(MAX_STORED_AMOUNT),
        rate_per_piece=str(MAX_STORED_AMOUNT),
    ))
    assert maximum.quantity == MAX_STORED_AMOUNT
    assert maximum.rate_per_piece == MAX_STORED_AMOUNT


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("quantity", "-0.0001"),
        ("quantity", "10000000000"),
        ("rate_per_piece", "Infinity"),
        ("rate_per_piece", "10000000000"),
    ],
)
def test_invalid_qr_issue_has_no_label_or_audit_side_effects(
    client,
    auth_headers,
    field,
    value,
):
    before = _write_counts()

    response = client.post(
        "/api/payroll/qr-labels/issue",
        headers=auth_headers,
        json={"labels": [_label(**{field: value})]},
    )

    assert response.status_code == 422, response.text
    assert _write_counts() == before


def test_qr_issue_preserves_exact_max_and_historical_extra_precision(
    client,
    auth_headers,
):
    payload = _label(
        quantity=str(MAX_STORED_AMOUNT),
        rate_per_piece="2.34567",
    )

    response = client.post(
        "/api/payroll/qr-labels/issue",
        headers=auth_headers,
        json={"labels": [payload]},
    )

    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        label = db.query(PayrollQrLabel).filter_by(label_uid=payload["label_uid"]).one()
        assert label.quantity == MAX_STORED_AMOUNT
        assert label.rate_per_piece == Decimal("2.3457")


def test_invalid_qr_edit_preserves_label_and_audit(client, auth_headers):
    payload = _label(quantity=2, rate_per_piece=25)
    issued = client.post(
        "/api/payroll/qr-labels/issue",
        headers=auth_headers,
        json={"labels": [payload]},
    )
    assert issued.status_code == 200, issued.text
    with SessionLocal() as db:
        label = db.query(PayrollQrLabel).filter_by(label_uid=payload["label_uid"]).one()
        label_id = int(label.id)
        previous_rate = label.rate_per_piece
    before = _write_counts()

    response = client.patch(
        f"/api/payroll/qr-labels/{label_id}",
        headers=auth_headers,
        json={"operation_name": "Changed", "rate_per_piece": "10000000000"},
    )

    assert response.status_code == 422, response.text
    assert _write_counts() == before
    with SessionLocal() as db:
        label = db.get(PayrollQrLabel, label_id)
        assert label is not None
        assert label.operation_name == payload["operation_name"]
        assert label.rate_per_piece == previous_rate


def test_invalid_qr_numeric_input_preserves_authentication_precedence(client):
    before = _write_counts()

    response = client.post(
        "/api/payroll/qr-labels/issue",
        json={"labels": [_label(quantity="10000000000")]},
    )

    assert response.status_code == 401, response.text
    assert _write_counts() == before
