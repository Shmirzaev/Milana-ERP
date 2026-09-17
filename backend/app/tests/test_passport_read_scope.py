"""Passport IDs must not bypass the factory selected at sign-in."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.models import Department, ProductionOrder, User, WorkOrder
from app.models.cutting_passport import CuttingPassport


def _actor(factory, permissions):
    with SessionLocal() as db:
        user = User(
            name="Passport scope test", email=f"passport-{uuid4().hex}@example.invalid",
            password_hash="unused", is_active=True, factory_code=factory,
            extra_permissions=list(permissions),
        )
        db.add(user)
        db.commit()
        return user.id


def _headers(user_id, factory):
    return {"Authorization": f"Bearer {create_access_token(user_id, {'factory_code': factory})}"}


def _passport(factory=None, *, with_work_order=True):
    with SessionLocal() as db:
        order_id = None
        if factory:
            order = ProductionOrder(
                production_no=f"PO-PASSPORT-{uuid4().hex[:8]}",
                production_type="branded_stock", model_id=1, planned_quantity=10,
            )
            db.add(order)
            db.flush()
            order_id = order.id
            if with_work_order:
                code = {"MIL": "CUT", "ECO": "ECT"}[factory]
                department = db.query(Department).filter_by(code=code).first()
                if department is None:
                    department = Department(name=f"Passport {code}", code=code)
                    db.add(department)
                    db.flush()
                db.add(WorkOrder(
                    production_order_id=order_id, department_id=department.id,
                    operation="cutting", status="in_progress",
                    planned_input_qty=10, planned_output_qty=10,
                ))
        passport = CuttingPassport(
            passport_no=f"TEST-{uuid4().hex[:8]}", date=datetime.now(timezone.utc),
            production_order_id=order_id, notes="Factory-private passport details", pieces=10,
        )
        db.add(passport)
        db.commit()
        return passport.id


@pytest.mark.parametrize("session_factory,target_factory", [("MIL", "ECO"), ("ECO", "MIL"), ("BST", "MIL"), ("BST", "ECO")])
@pytest.mark.parametrize("permissions", [("cutting.records",), ("*", "admin.super")])
def test_passport_detail_rejects_other_factory(client, session_factory, target_factory, permissions):
    actor = _actor(session_factory, permissions)
    passport_id = _passport(target_factory)
    headers = _headers(actor, session_factory)

    listing = client.get("/api/cutting-passports", headers=headers)
    if session_factory == "BST":
        assert listing.status_code == 403
    else:
        assert listing.status_code == 200, listing.text
        assert passport_id not in {row["id"] for row in listing.json()}
    response = client.get(f"/api/cutting-passports/{passport_id}", headers=headers)

    assert response.status_code == 403, response.text
    assert "Factory-private passport details" not in response.text


@pytest.mark.parametrize("factory", ["MIL", "ECO"])
@pytest.mark.parametrize("permissions", [("cutting.records",), ("cutting.bundles",), ("planning.production",), ("*", "admin.super")])
def test_passport_detail_keeps_authorized_read_roles(client, factory, permissions):
    actor = _actor(factory, permissions)
    passport_id = _passport(factory)
    headers = _headers(actor, factory)

    listing = client.get("/api/cutting-passports", headers=headers)
    response = client.get(f"/api/cutting-passports/{passport_id}", headers=headers)

    assert listing.status_code == 200, listing.text
    assert response.status_code == 200, response.text
    assert response.json() == next(row for row in listing.json() if row["id"] == passport_id)


def test_secondary_factory_passport_requires_selected_session(client):
    actor = _actor("MIL", ("cutting.records", "factory:ECO:cutting.records"))
    passport_id = _passport("ECO")

    denied = client.get(f"/api/cutting-passports/{passport_id}", headers=_headers(actor, "MIL"))
    allowed = client.get(f"/api/cutting-passports/{passport_id}", headers=_headers(actor, "ECO"))

    assert denied.status_code == 403
    assert allowed.status_code == 200, allowed.text


@pytest.mark.parametrize("factory,expected", [("MIL", 200), ("ECO", 403), ("BST", 403)])
def test_unlinked_legacy_passport_keeps_milana_scope(client, factory, expected):
    actor = _actor(factory, ("cutting.records",))
    passport_id = _passport()

    response = client.get(f"/api/cutting-passports/{passport_id}", headers=_headers(actor, factory))

    assert response.status_code == expected, response.text


def test_passport_with_missing_cutting_work_order_fails_closed(client):
    actor = _actor("MIL", ("cutting.records",))
    passport_id = _passport("MIL", with_work_order=False)

    response = client.get(f"/api/cutting-passports/{passport_id}", headers=_headers(actor, "MIL"))

    assert response.status_code == 400
    assert "Factory-private passport details" not in response.text


def test_missing_passport_still_returns_404(client):
    actor = _actor("MIL", ("cutting.records",))
    response = client.get("/api/cutting-passports/2000000000", headers=_headers(actor, "MIL"))
    assert response.status_code == 404


def test_passport_read_requires_authentication(client):
    passport_id = _passport("MIL")
    response = client.get(f"/api/cutting-passports/{passport_id}")
    assert response.status_code == 401
