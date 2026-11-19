"""Customer DELETE on the approved, identity-pinned disposable PostgreSQL target."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.core.security import create_access_token
from app.models import audit_service
from app.models.catalog import partners_service
from app.schemas import AuditLog, Customer, SalesOrder, Shipment
from app.tests.test_customer_create_postgres import chain, customer_pg_sessions  # noqa: F401
from app.tests.test_supplier_update_postgres import real_auth_client, role_actor


def create_customer(sessions):
    name = "Delete PG " + uuid4().hex
    with sessions.begin() as db:
        row = Customer(name=name, phone="saved", notes="preserve on failure")
        db.add(row)
        db.flush()
        return row.id, name


def headers(actor_id):
    return {"Authorization": f"Bearer {create_access_token(actor_id)}"}


def state(sessions, cid):
    with sessions() as db:
        row = db.get(Customer, cid)
        fields = None if row is None else (row.name, row.phone, row.notes)
        logs = db.query(AuditLog).filter_by(entity_type="Customer", entity_id=cid, action="delete").order_by(AuditLog.id).all()
        return fields, [(log.user_id, log.old_value_json, log.new_value_json) for log in logs]


def test_pg_delete_route_success_repeat_and_missing(customer_pg_sessions):
    sessions = customer_pg_sessions
    actor_id = role_actor(sessions, ["sales.customers"])
    cid, name = create_customer(sessions)
    with real_auth_client(sessions) as client:
        response = client.delete(f"/customers/{cid}", headers=headers(actor_id))
        assert response.status_code == 204, response.text
        assert response.content == b""
        repeat = client.delete(f"/customers/{cid}", headers=headers(actor_id))
        assert repeat.status_code == 404 and repeat.json()["detail"] == "Customer not found"
        missing = client.delete("/customers/2147483647", headers=headers(actor_id))
        assert missing.status_code == 404 and missing.json()["detail"] == "Customer not found"
    assert state(sessions, cid) == (None, [(actor_id, None, {"name": name})])
    chain(sessions)


def test_pg_delete_route_auth_denials_preserve_customer(customer_pg_sessions):
    sessions = customer_pg_sessions
    actor_id = role_actor(sessions, ["sales.view"])
    cid, name = create_customer(sessions)
    with real_auth_client(sessions) as client:
        assert client.delete(f"/customers/{cid}").status_code == 401
        assert client.delete(f"/customers/{cid}", headers=headers(actor_id)).status_code == 403
    assert state(sessions, cid) == ((name, "saved", "preserve on failure"), [])


@pytest.mark.parametrize("references", ["sales", "shipment", "both"])
def test_pg_delete_reference_refusal_preserves_customer(customer_pg_sessions, references):
    sessions = customer_pg_sessions
    actor_id = role_actor(sessions, ["sales.customers"])
    cid, name = create_customer(sessions)
    marker = uuid4().hex
    with sessions.begin() as db:
        if references in ("sales", "both"):
            db.add(SalesOrder(order_no="SO-" + marker, customer_id=cid))
        if references in ("shipment", "both"):
            db.add(Shipment(shipment_no="SH-" + marker, customer_id=cid))
    with real_auth_client(sessions) as client:
        response = client.delete(f"/customers/{cid}", headers=headers(actor_id))
    assert response.status_code == 409
    expected = "Customer is linked to sales orders" if references in ("sales", "both") else "Customer is linked to shipments"
    assert response.json()["detail"] == expected
    assert state(sessions, cid) == ((name, "saved", "preserve on failure"), [])
    with sessions() as db:
        assert db.query(SalesOrder).filter_by(customer_id=cid).count() == (1 if references in ("sales", "both") else 0)
        assert db.query(Shipment).filter_by(customer_id=cid).count() == (1 if references in ("shipment", "both") else 0)


@pytest.mark.parametrize("point", ["audit_enqueue", "audit_finalize", "before_commit"])
def test_pg_delete_precommit_failure_rolls_back_then_retry(customer_pg_sessions, monkeypatch, point):
    sessions = customer_pg_sessions
    actor_id = role_actor(sessions, ["sales.customers"])
    cid, name = create_customer(sessions)
    original = partners_service.log_action
    observed = []
    def fail(*args, **kwargs):
        raise RuntimeError("injected delete precommit failure")
    def wrapped(db, user, action, entity_type, entity_id, **kwargs):
        entry = original(db, user, action, entity_type, entity_id, **kwargs)
        observed.append(entity_id)
        if point == "audit_enqueue":
            fail()
        if point == "before_commit":
            event.listen(db, "before_commit", fail)
        return entry
    with monkeypatch.context() as patch:
        patch.setattr(partners_service, "log_action", wrapped)
        if point == "audit_finalize":
            patch.setattr(audit_service, "add_audit_log_rows", fail)
        with real_auth_client(sessions) as client:
            response = client.delete(f"/customers/{cid}", headers=headers(actor_id))
            assert response.status_code == 500
    assert observed == [cid]
    assert state(sessions, cid) == ((name, "saved", "preserve on failure"), [])
    with real_auth_client(sessions) as client:
        response = client.delete(f"/customers/{cid}", headers=headers(actor_id))
        assert response.status_code == 204, response.text
    assert state(sessions, cid) == (None, [(actor_id, None, {"name": name})])
    chain(sessions)


def test_pg_delete_distinct_rows_concurrently_preserves_audit_chain(customer_pg_sessions):
    sessions = customer_pg_sessions
    actor_id = role_actor(sessions, ["sales.customers"])
    pairs = [create_customer(sessions) for _ in range(4)]
    barrier = Barrier(4)
    def worker(cid):
        with sessions() as db:
            from app.schemas import User
            actor = db.get(User, actor_id)
            barrier.wait(timeout=10)
            partners_service.delete_customer(actor, db, cid)
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(worker, cid) for cid, _ in pairs]
        for future in futures:
            future.result(timeout=30)
    for cid, name in pairs:
        assert state(sessions, cid) == (None, [(actor_id, None, {"name": name})])
    chain(sessions)
