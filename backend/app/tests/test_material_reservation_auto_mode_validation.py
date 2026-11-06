from app.libs.dto.inventory.material_reservation_input import MaterialReservationAutoIn
from app.tests.conftest import TestSessionLocal
from app.libs.enums.inventory import MaterialReservationAutoMode


def _write_state():
    from app.schemas import AuditLog, IdempotencyRecord, MaterialReservation, StockMovement

    with TestSessionLocal() as db:
        return (
            db.query(MaterialReservation).count(),
            db.query(StockMovement).count(),
            db.query(AuditLog).count(),
            db.query(IdempotencyRecord).count(),
        )


def test_auto_reservation_mode_schema_documents_supported_commands(client):
    base_payload = {"production_order_id": 1}
    assert MaterialReservationAutoIn.model_validate(base_payload).mode is MaterialReservationAutoMode.FULL_REMAINING
    for mode in ("shortage_only", "full_remaining"):
        assert MaterialReservationAutoIn.model_validate(
            {**base_payload, "mode": mode},
        ).mode is MaterialReservationAutoMode(mode)

    openapi = client.get("/openapi.json")
    assert openapi.status_code == 200, openapi.text
    schema = openapi.json()["components"]["schemas"]["MaterialReservationAutoIn"]["properties"]["mode"]
    assert schema["$ref"] == "#/components/schemas/MaterialReservationAutoMode"
    enum_schema = openapi.json()["components"]["schemas"]["MaterialReservationAutoMode"]
    assert set(enum_schema["enum"]) == {"shortage_only", "full_remaining"}
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


def test_auto_mode_serializes_to_existing_json_values():
    for mode in ("shortage_only", "full_remaining"):
        payload = MaterialReservationAutoIn(production_order_id=1, mode=mode)
        assert payload.model_dump(mode="json")["mode"] == mode


def test_auto_service_passes_strings_to_shared_service_and_audit(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock
    from app.models.inventory import reservations_service as service

    shared = Mock(return_value={"reservations": [], "plan": {}})
    audit = Mock()
    monkeypatch.setattr(service, "auto_reserve_materials_for_production_order", shared)
    monkeypatch.setattr(service, "log_action", audit)
    monkeypatch.setattr(service.inventory_access, "materials_only", lambda current: False)
    db = Mock()
    for mode in ("shortage_only", "full_remaining"):
        payload = MaterialReservationAutoIn(
            production_order_id=42, mode=mode,
            reserve_accessories=False, reserve_packaging=False,
        )
        service.auto_create_material_reservations(db, payload, SimpleNamespace(id=7))
        assert type(shared.call_args.kwargs["mode"]) is str
        assert shared.call_args.kwargs["mode"] == mode
        assert audit.call_args.kwargs["new_value"]["mode"] == mode
        assert type(audit.call_args.kwargs["new_value"]["mode"]) is str
    assert db.commit.call_count == 2
