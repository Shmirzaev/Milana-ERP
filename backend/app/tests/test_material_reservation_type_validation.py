from app.schemas.inventory import MaterialReservationIn
from app.tests.conftest import TestSessionLocal


def _write_state():
    from app.models import AuditLog, IdempotencyRecord, MaterialReservation, StockMovement

    with TestSessionLocal() as db:
        return (
            db.query(MaterialReservation).count(),
            db.query(StockMovement).count(),
            db.query(AuditLog).count(),
            db.query(IdempotencyRecord).count(),
        )


def test_reservation_type_schema_keeps_codes_default_and_blank_alias(client):
    base_payload = {
        "production_order_id": 1,
        "item_id": 1,
        "reserved_quantity": 1,
        "unit": "kg",
    }
    assert MaterialReservationIn.model_validate(base_payload).reservation_type == "material"
    for code in ("material", "accessory", "packaging"):
        assert MaterialReservationIn.model_validate(
            {**base_payload, "reservation_type": code},
        ).reservation_type == code
    assert MaterialReservationIn.model_validate(
        {**base_payload, "reservation_type": " accessory "},
    ).reservation_type == "accessory"
    assert MaterialReservationIn.model_validate(
        {**base_payload, "reservation_type": " "},
    ).reservation_type == ""

    openapi = client.get("/openapi.json")
    assert openapi.status_code == 200, openapi.text
    schema = openapi.json()["components"]["schemas"]["MaterialReservationIn"]["properties"]["reservation_type"]
    assert set(schema["enum"]) == {"material", "accessory", "packaging", ""}
    assert schema["default"] == "material"
    assert "category-derived" in schema["description"]


def test_invalid_reservation_type_rejects_without_writes_and_auth_precedes(client, auth_headers):
    payload = {
        "production_order_id": 999999,
        "item_id": 999999,
        "reserved_quantity": 1,
        "unit": "kg",
        "reservation_type": "finished_goods",
    }
    before = _write_state()

    invalid = client.post("/api/inventory/reservations", headers=auth_headers, json=payload)
    assert invalid.status_code == 422, invalid.text
    assert _write_state() == before

    unauthenticated = client.post("/api/inventory/reservations", json=payload)
    assert unauthenticated.status_code == 401, unauthenticated.text
    assert _write_state() == before
