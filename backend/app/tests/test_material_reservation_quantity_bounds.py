from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.db.session import SessionLocal
from app.models import AuditLog, MaterialReservation, StockMovement
from app.schemas.inventory import MaterialReservationConsumeIn, MaterialReservationIn


MAX_RESERVATION_QUANTITY = Decimal("9999999999.9999")


def _reservation_payload(quantity: str) -> dict:
    return {
        "production_order_id": 1,
        "item_id": 1,
        "stock_batch_id": 1,
        "reserved_quantity": quantity,
        "unit": "kg",
    }


def _write_counts() -> tuple[int, int, int]:
    with SessionLocal() as db:
        return (
            db.query(MaterialReservation).count(),
            db.query(StockMovement).count(),
            db.query(AuditLog).count(),
        )


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "10000000000"])
def test_reservation_create_quantity_rejects_non_finite_and_storage_overflow(value):
    with pytest.raises(ValidationError):
        MaterialReservationIn(**_reservation_payload(value))


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "10000000000"])
def test_reservation_consume_quantity_rejects_non_finite_and_storage_overflow(value):
    with pytest.raises(ValidationError):
        MaterialReservationConsumeIn(quantity=value)


def test_reservation_quantities_preserve_extra_precision_and_exact_maximum():
    precise = MaterialReservationIn(**_reservation_payload("2.34567"))
    assert precise.reserved_quantity == pytest.approx(2.34567)
    assert MaterialReservationConsumeIn(quantity="2.34567").quantity == pytest.approx(2.34567)

    maximum = MaterialReservationIn(**_reservation_payload(str(MAX_RESERVATION_QUANTITY)))
    assert maximum.reserved_quantity == pytest.approx(float(MAX_RESERVATION_QUANTITY))
    consumed = MaterialReservationConsumeIn(quantity=str(MAX_RESERVATION_QUANTITY))
    assert consumed.quantity == pytest.approx(float(MAX_RESERVATION_QUANTITY))


def test_invalid_reservation_create_quantity_has_no_write_side_effects(
    client,
    auth_headers,
):
    before = _write_counts()

    response = client.post(
        "/api/inventory/reservations",
        headers=auth_headers,
        json=_reservation_payload("10000000000"),
    )

    assert response.status_code == 422, response.text
    assert _write_counts() == before


def test_invalid_reservation_consume_quantity_has_no_write_side_effects(
    client,
    auth_headers,
):
    before = _write_counts()

    response = client.post(
        "/api/inventory/reservations/1/consume",
        headers=auth_headers,
        json={"quantity": "Infinity"},
    )

    assert response.status_code == 422, response.text
    assert _write_counts() == before


def test_invalid_reservation_quantity_preserves_authentication_precedence(client):
    before = _write_counts()

    response = client.post(
        "/api/inventory/reservations",
        json=_reservation_payload("10000000000"),
    )

    assert response.status_code == 401, response.text
    assert _write_counts() == before
