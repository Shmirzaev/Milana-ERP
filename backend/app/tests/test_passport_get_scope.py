"""Passport detail reads must respect the selected cutting factory."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes import cutting_passports
from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.models import AuditLog, CuttingPassport, Department, ProductionOrder, User, WorkOrder


def _actor(factory="MIL", permissions=("cutting.records",)):
    with SessionLocal() as db:
        user = User(name="Passport scope reader", email=f"passport-reader-{uuid4().hex}@example.invalid",
                    password_hash="unused-by-synthetic-token-test", factory_code=factory,
                    extra_permissions=list(permissions), is_active=True)
        db.add(user)
        db.commit()
        return user.id


def _headers(user_id, factory):
    return {"Authorization": f"Bearer {create_access_token(user_id, {'factory_code': factory})}"}


def _passport(factory="MIL", *, linked=True):
    suffix = uuid4().hex[:8]
    with SessionLocal() as db:
        references = []
        order = None
        if linked:
            code = {"MIL": "CUT", "ECO": "ECT"}[factory]
            department = db.query(Department).filter_by(code=code).first()
            if department is None:
                department = Department(name=f"Passport scope {factory}", code=code)
                db.add(department)
                db.flush()
            order = ProductionOrder(production_no=f"PO-PASSPORT-{suffix}", production_type="branded_stock",
                                    model_id=1, planned_quantity=20)
            db.add(order)
            db.flush()
            work_order = WorkOrder(production_order_id=order.id, department_id=department.id,
                                   operation="cutting", status="in_progress", planned_input_qty=20,
                                   planned_output_qty=20)
            db.add(work_order)
            db.flush()
            references.extend([(ProductionOrder, order.id), (WorkOrder, work_order.id)])
        passport = CuttingPassport(
            passport_no=f"SCOPE-{suffix}", date=datetime(2026, 9, 18, tzinfo=timezone.utc),
            production_order_id=order.id if order else None, operator_name_manual="Synthetic cutting operator",
            notes=f"{factory} private cutting notes", fabric_type="Synthetic cotton", size_range="44-48",
            layer_weight_kg=2, total_layers=5, pieces=20, planned_kg=16,
            beka_per_piece_kg=0.1, scrap_kg=1,
        )
        db.add(passport)
        db.commit()
        return [(CuttingPassport, passport.id), *references]


def _snapshot(references):
    with SessionLocal() as db:
        result = {}
        for model, row_id in references:
            row = db.get(model, row_id)
            result[model.__tablename__] = {column.name: getattr(row, column.name) for column in model.__table__.columns}
        result["audit_count"] = db.query(AuditLog).count()
        return result


@pytest.mark.parametrize(("selected", "target"), [("MIL", "ECO"), ("ECO", "MIL"), ("BST", "MIL"), ("BST", "ECO")])
@pytest.mark.parametrize("permissions", [("cutting.records",), ("*", "admin.super")])
def test_passport_get_rejects_other_factory_before_serialization_or_writes(
    client, monkeypatch, selected, target, permissions
):
    actor = _actor(selected, permissions)
    references = _passport(target)
    before = _snapshot(references)
    serialized, writes = [], []
    original = cutting_passports._serialize

    def track_serialization(passport, *args, **kwargs):
        serialized.append(passport.id)
        return original(passport, *args, **kwargs)

    def capture_write(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().split(None, 1)[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            writes.append(statement)

    monkeypatch.setattr(cutting_passports, "_serialize", track_serialization)
    with SessionLocal() as db:
        engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", capture_write)
    try:
        path = f"/api/cutting-passports/{references[0][1]}"
        response = client.get(path, headers=_headers(actor, selected))
        existing_guard = client.delete(path, headers=_headers(actor, selected))
    finally:
        event.remove(engine, "before_cursor_execute", capture_write)

    assert (response.status_code, response.json().get("notes")) == (403, None)
    assert existing_guard.status_code == 403
    assert response.json() == existing_guard.json()
    assert serialized == [], "Wrong-factory passports must not reach the response serializer"
    assert writes == []
    assert _snapshot(references) == before


@pytest.mark.parametrize("factory", ["MIL", "ECO"])
@pytest.mark.parametrize("permissions", [(), ("cutting.records",), ("*", "admin.super")])
def test_passport_get_preserves_authorized_payload_and_read_only_behavior(client, factory, permissions):
    actor = _actor(factory, permissions)
    references = _passport(factory)
    before = _snapshot(references)

    response = client.get(f"/api/cutting-passports/{references[0][1]}", headers=_headers(actor, factory))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == references[0][1]
    assert body["passport_no"] == before["cutting_passports"]["passport_no"]
    assert body["production_order_id"] == references[1][1]
    assert body["production_order_no"] == body["order_no"] == before["production_orders"]["production_no"]
    assert body["notes"] == f"{factory} private cutting notes"
    assert body["operator_name"] == "Synthetic cutting operator"
    assert body["fabric_type"] == "Synthetic cotton"
    assert body["materials"] == []
    assert body["pieces"] == 20 and body["pieces_per_layer"] == 4
    assert body["size_count"] == 3 and body["actual_kg"] == 13
    assert body["total_beka_kg"] == 2 and body["gross_kg_per_piece"] == 0.8
    assert _snapshot(references) == before


def test_passport_get_requires_selecting_the_granted_secondary_factory(client):
    actor = _actor(permissions=("cutting.records", "factory:ECO:cutting.records"))
    eco_id = _passport("ECO")[0][1]
    milana_id = _passport("MIL")[0][1]

    assert client.get(f"/api/cutting-passports/{eco_id}", headers=_headers(actor, "MIL")).status_code == 403
    assert client.get(f"/api/cutting-passports/{eco_id}", headers=_headers(actor, "ECO")).status_code == 200
    assert client.get(f"/api/cutting-passports/{milana_id}", headers=_headers(actor, "ECO")).status_code == 403


@pytest.mark.parametrize("factory", ["MIL", "ECO", "BST"])
def test_passport_get_missing_id_keeps_404_and_requires_authentication(client, factory):
    path = "/api/cutting-passports/2000000000"
    assert client.get(path).status_code == 401
    response = client.get(path, headers=_headers(_actor(factory), factory))
    assert response.status_code == 404
    assert response.json() == {"detail": "Cutting passport not found"}


def test_passport_get_rejects_ungranted_factory_even_for_missing_id(client):
    actor = _actor("MIL")
    for passport_id in (_passport("ECO")[0][1], 2_000_000_000):
        response = client.get(f"/api/cutting-passports/{passport_id}", headers=_headers(actor, "ECO"))
        assert response.status_code == 403
        assert response.json() == {"detail": "This account is not assigned to the selected factory"}


@pytest.mark.parametrize(("broken_link", "status", "detail"), [
    ("order", 404, "Production order not found"),
    ("cutting", 400, "The order has no cutting work order"),
])
def test_passport_get_with_unresolvable_factory_fails_like_delete(client, broken_link, status, detail):
    actor = _actor()
    references = _passport()
    with SessionLocal() as db:
        if broken_link == "order":
            db.get(CuttingPassport, references[0][1]).production_order_id = 2_000_000_000
        else:
            db.get(WorkOrder, references[2][1]).operation = "sewing"
        db.commit()
    before = _snapshot(references)
    path = f"/api/cutting-passports/{references[0][1]}"

    response = client.get(path, headers=_headers(actor, "MIL"))

    assert response.status_code == status
    assert response.json() == {"detail": detail}
    assert client.delete(path, headers=_headers(actor, "MIL")).json() == response.json()
    assert _snapshot(references) == before


def test_passport_get_keeps_existing_unlinked_manual_passport_behavior(client):
    actor = _actor()
    references = _passport(linked=False)
    response = client.get(f"/api/cutting-passports/{references[0][1]}", headers=_headers(actor, "MIL"))
    assert response.status_code == 200
    assert response.json()["production_order_id"] is None
    assert response.json()["notes"] == "MIL private cutting notes"
