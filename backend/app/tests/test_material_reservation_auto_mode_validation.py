from app.schemas.inventory import MaterialReservationAutoIn
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


def test_auto_reservation_mode_schema_documents_supported_commands(client):
    base_payload = {"production_order_id": 1}
    assert MaterialReservationAutoIn.model_validate(base_payload).mode == "full_remaining"
    for mode in ("shortage_only", "full_remaining"):
        assert MaterialReservationAutoIn.model_validate(
            {**base_payload, "mode": mode},
        ).mode == mode

    openapi = client.get("/openapi.json")
    assert openapi.status_code == 200, openapi.text
    schema = openapi.json()["components"]["schemas"]["MaterialReservationAutoIn"]["properties"]["mode"]
    assert set(schema["enum"]) == {"shortage_only", "full_remaining"}
    assert schema["default"] == "full_remaining"


def test_invalid_auto_reservation_mode_rejects_without_writes_and_auth_precedes(
    client, auth_headers,
):
    payload = {
        "production_order_id": 2_147_483_647,
        "mode": "over_reserve",
        "reserve_accessories": False,
        "reserve_materials": True,
        "reserve_packaging": False,
    }
    before = _write_state()

    invalid = client.post("/api/inventory/reservations/auto", headers=auth_headers, json=payload)
    assert invalid.status_code == 422, invalid.text
    assert _write_state() == before

    unauthenticated = client.post("/api/inventory/reservations/auto", json=payload)
    assert unauthenticated.status_code == 401, unauthenticated.text
    assert _write_state() == before


def test_valid_auto_reservation_mode_keeps_missing_order_precedence(client, auth_headers):
    before = _write_state()
    response = client.post(
        "/api/inventory/reservations/auto",
        headers=auth_headers,
        json={
            "production_order_id": 2_147_483_647,
            "mode": "shortage_only",
            "reserve_accessories": False,
            "reserve_materials": True,
            "reserve_packaging": False,
        },
    )
    assert response.status_code == 404, response.text
    assert _write_state() == before
