from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.db.session import SessionLocal
from app.models import AuditLog, Item, PurchaseRequest, PurchaseRequestLine
from app.schemas.purchasing import PurchaseRequestLineIn


def _line(**values):
    return PurchaseRequestLineIn.model_validate({"item_id": 1, **values})


@pytest.mark.parametrize(
    "field",
    ["required_quantity", "requested_quantity", "available_quantity", "shortage_quantity"],
)
def test_purchase_request_quantities_accept_finite_database_boundaries(field):
    maximum = Decimal("9999999999.9999")
    assert getattr(_line(**{field: maximum}), field) == maximum
    assert getattr(_line(**{field: -maximum}), field) == -maximum


@pytest.mark.parametrize(
    "field",
    ["required_quantity", "requested_quantity", "available_quantity", "shortage_quantity"],
)
@pytest.mark.parametrize("value", ["Infinity", "-Infinity", "NaN", "10000000000", "-10000000000"])
def test_purchase_request_quantities_reject_nonfinite_or_unrepresentable_values(field, value):
    with pytest.raises(ValidationError):
        _line(**{field: value})


def test_purchase_request_quantity_api_rejects_before_writes_and_keeps_auth_precedence(
    client, auth_headers
):
    with SessionLocal() as db:
        item_unit = db.query(Item.unit).filter(Item.id == 1).scalar()

    def payload(**line_values):
        return {
            "status": "draft",
            "lines": [{"item_id": 1, "unit": item_unit, **line_values}],
        }

    with SessionLocal() as db:
        before = (
            db.query(PurchaseRequest).count(),
            db.query(PurchaseRequestLine).count(),
            db.query(AuditLog).count(),
        )

    valid = client.post(
        "/api/purchasing/requests",
        json=payload(required_quantity="12.34567", requested_quantity="10.25"),
        headers=auth_headers,
    )
    assert valid.status_code == 201, valid.text
    assert valid.json()["lines"][0]["required_quantity"] == pytest.approx(12.3457)
    assert valid.json()["lines"][0]["requested_quantity"] == pytest.approx(10.25)

    with SessionLocal() as db:
        after_valid = (
            db.query(PurchaseRequest).count(),
            db.query(PurchaseRequestLine).count(),
            db.query(AuditLog).count(),
        )
    assert after_valid == (before[0] + 1, before[1] + 1, before[2] + 1)

    for field in ("required_quantity", "requested_quantity", "available_quantity", "shortage_quantity"):
        response = client.post(
            "/api/purchasing/requests",
            json=payload(**{field: "Infinity"}),
            headers=auth_headers,
        )
        assert response.status_code == 422, (field, response.text)

        response = client.post(
            "/api/purchasing/requests",
            json=payload(**{field: "10000000000"}),
            headers=auth_headers,
        )
        assert response.status_code == 422, (field, response.text)

    assert client.post(
        "/api/purchasing/requests",
        json=payload(required_quantity="Infinity"),
    ).status_code == 401

    derived_overflow = client.post(
        "/api/purchasing/requests",
        json=payload(
            required_quantity="9999999999.9999",
            available_quantity="-9999999999.9999",
        ),
        headers=auth_headers,
    )
    assert derived_overflow.status_code == 400, derived_overflow.text

    # The existing business rule still reports a negative requested quantity from the service.
    negative_requested = client.post(
        "/api/purchasing/requests",
        json=payload(requested_quantity=-1),
        headers=auth_headers,
    )
    assert negative_requested.status_code == 400, negative_requested.text

    with SessionLocal() as db:
        after_invalid = (
            db.query(PurchaseRequest).count(),
            db.query(PurchaseRequestLine).count(),
            db.query(AuditLog).count(),
        )
    assert after_invalid == after_valid
