"""Full-app SQLite checks for reservation raw-type compatibility."""
import hashlib
import json
from uuid import uuid4

import pytest

from app.tests.test_material_reservations import (
    _create_accessory_item, _create_branded_po, _fabric_item, _receive_batch, _warehouse,
)
from app.tests.test_sewing_workspace_permissions import _create_user_headers

URL = "/api/inventory/reservations"


def _fixture(client, headers, category):
    order = _create_branded_po(client, headers, qty=10)
    item = _fabric_item(client, headers) if category == "material" else _create_accessory_item(client, headers)
    warehouse = _warehouse(client, headers, "fabric_storage" if category == "material" else "accessory_storage")
    batch = _receive_batch(client, headers, item_id=item["id"], warehouse_id=warehouse["id"], quantity=10, unit=item["unit"])
    return {
        "production_order_id": order["id"], "item_id": item["id"], "stock_batch_id": batch["id"],
        "warehouse_id": warehouse["id"], "reserved_quantity": 2, "unit": item["unit"],
    }


def _legacy_payload(payload):
    return {"production_order_id": payload["production_order_id"], "item_id": payload["item_id"],
            "stock_batch_id": payload["stock_batch_id"], "warehouse_id": payload["warehouse_id"],
            "reserved_quantity": float(payload["reserved_quantity"]), "unit": payload["unit"],
            "reservation_type": payload["reservation_type"], "notes": None}


def _hash(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


@pytest.mark.parametrize("category,raw,expected", [
    ("material", " material ", "material"), ("accessory", " accessory ", "accessory"),
    ("material", "", "material"), ("accessory", "", "accessory"),
])
def test_raw_type_success_and_historical_replay(client, auth_headers, category, raw, expected):
    from app.db.session import SessionLocal
    from app.libs.dto.inventory.material_reservation_output import MaterialReservationOut
    from app.schemas import AuditLog, IdempotencyRecord, MaterialReservation

    payload = {**_fixture(client, auth_headers, category), "reservation_type": raw}
    key = "compat-" + uuid4().hex
    headers = {**auth_headers, "Idempotency-Key": key}
    who = client.get("/api/auth/me", headers=auth_headers)
    assert who.status_code == 200, who.text
    created = client.post(URL, headers=headers, json=payload)
    assert created.status_code == 201, created.text
    result = created.json()
    assert result["reservation_type"] == expected
    with SessionLocal() as db:
        row = db.get(MaterialReservation, result["id"])
        assert row is not None and row.reservation_type == expected
        saved = db.query(IdempotencyRecord).filter_by(key=key).one()
        assert saved.request_hash == _hash(_legacy_payload(payload))
        assert saved.user_id == who.json()["id"] and saved.status_code == 201
        assert MaterialReservationOut.model_validate(saved.response_json).model_dump(mode="json") == result
        before = (db.query(MaterialReservation).count(), db.query(AuditLog).count(), db.query(IdempotencyRecord).count())
    replay = client.post(URL, headers=headers, json=payload)
    assert replay.status_code == 201 and replay.json() == result
    conflict = client.post(URL, headers=headers, json={**payload, "reservation_type": raw + " "})
    assert conflict.status_code == 409
    with SessionLocal() as db:
        assert before == (db.query(MaterialReservation).count(), db.query(AuditLog).count(), db.query(IdempotencyRecord).count())


@pytest.mark.parametrize("raw", ["unknown", "   ", "MATERIAL"])
def test_invalid_type_persists_exact_failure_audit_only(client, auth_headers, raw):
    from app.db.session import SessionLocal
    from app.schemas import AuditLog, IdempotencyRecord, MaterialReservation

    payload = {**_fixture(client, auth_headers, "accessory"), "reservation_type": raw}
    key = "compat-invalid-" + uuid4().hex
    who = client.get("/api/auth/me", headers=auth_headers).json()["id"]
    with SessionLocal() as db:
        before = (db.query(MaterialReservation).count(), db.query(IdempotencyRecord).count())
        last_audit = db.query(AuditLog.id).order_by(AuditLog.id.desc()).first()
        last_audit_id = last_audit[0] if last_audit else 0
    response = client.post(URL, headers={**auth_headers, "Idempotency-Key": key}, json=payload)
    assert response.status_code == 400 and response.json()["detail"] == "Invalid reservation_type"
    with SessionLocal() as db:
        assert before == (db.query(MaterialReservation).count(), db.query(IdempotencyRecord).count())
        assert db.query(IdempotencyRecord).filter_by(key=key).count() == 0
        events = db.query(AuditLog).filter(AuditLog.id > last_audit_id).all()
        assert len(events) == 1
        event = events[0]
        assert (event.action, event.entity_type, event.entity_id, event.user_id, event.old_value_json) == (
            "failed_create_material_reservation", "MaterialReservation", None, who, None)
        assert event.new_value_json == {"payload": _legacy_payload(payload), "detail": "Invalid reservation_type"}


def test_auth_permission_null_and_item_precedence(client, auth_headers):
    from app.db.session import SessionLocal
    from app.schemas import AuditLog, MaterialReservation

    payload = {**_fixture(client, auth_headers, "accessory"), "reservation_type": "unknown"}
    sewing = _create_user_headers(client, auth_headers, role="Sewing", department="SEW")
    with SessionLocal() as db:
        before = (db.query(MaterialReservation).count(), db.query(AuditLog).filter_by(action="failed_create_material_reservation").count())
    assert client.post(URL, json=payload).status_code == 401
    assert client.post(URL, headers=sewing, json=payload).status_code == 403
    assert client.post(URL, headers=auth_headers, json={**payload, "reservation_type": None}).status_code == 422
    missing_order = client.post(URL, headers=auth_headers, json={**payload, "production_order_id": 999999999})
    assert missing_order.status_code == 404
    with SessionLocal() as db:
        assert before == (db.query(MaterialReservation).count(), db.query(AuditLog).filter_by(action="failed_create_material_reservation").count())
