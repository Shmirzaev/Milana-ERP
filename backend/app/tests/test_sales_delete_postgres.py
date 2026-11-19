"""Sales DELETE cases for the identity-pinned, migrated disposable PG target.

This test source does not authorize execution. The coordinator must provide the
existing approved-instance contract; no preserved QA or production DB is used.
"""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import object_session

from app.api.routes.sales import router
from app.core.deps import get_db
from app.core.security import create_access_token
from app.models import audit_service
from app.models.sales import orders_service
from app.schemas import (
    AuditLog, FinishedGoodsStock, Invoice, Model, ProductionOrder, PurchaseRequest,
    SalesOrder, SalesOrderItem, Shipment, StockReservation, User,
)
from app.tests.test_customer_create_postgres import chain, customer_pg_sessions  # noqa: F401
from app.tests.test_supplier_update_postgres import role_actor


def sales_client(sessions):
    app = FastAPI()
    app.include_router(router)

    def isolated_db():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = isolated_db
    return TestClient(app, raise_server_exceptions=False)


def headers(actor_id):
    return {"Authorization": f"Bearer {create_access_token(actor_id)}"}


def create_order(sessions, status="draft"):
    marker = uuid4().hex
    with sessions.begin() as db:
        model = Model(code="DELETE-M-" + marker, name="Sales delete fixture")
        db.add(model)
        db.flush()
        order = SalesOrder(order_no="DELETE-SO-" + marker, status=status, total_amount=3, notes="preserve on failure")
        db.add(order)
        db.flush()
        line = SalesOrderItem(
            sales_order_id=order.id, model_id=model.id, color="fixture", size="M",
            quantity=2, unit_price=1.5, source_type="produce_new", notes="fixture line",
        )
        db.add(line)
        db.flush()
        return order.id, order.order_no, line.id, model.id


def state(sessions, sid):
    with sessions() as db:
        row = db.get(SalesOrder, sid)
        fields = None if row is None else (row.order_no, row.status, row.total_amount, row.notes)
        lines = db.query(SalesOrderItem).filter_by(sales_order_id=sid).order_by(SalesOrderItem.id).all()
        line_fields = [(x.id, x.model_id, x.color, x.size, x.quantity, x.unit_price, x.source_type, x.notes) for x in lines]
        logs = db.query(AuditLog).filter_by(entity_type="SalesOrder", entity_id=sid, action="delete").order_by(AuditLog.id).all()
        return fields, line_fields, [(x.user_id, x.old_value_json, x.new_value_json) for x in logs]


@pytest.mark.parametrize("status", ["draft", "cancelled"])
def test_pg_sales_delete_route_success_cascades_lines_repeat_and_missing(customer_pg_sessions, monkeypatch, status):
    sessions = customer_pg_sessions
    actor_id = role_actor(sessions, ["sales.orders"])
    sid, order_no, line_id, model_id = create_order(sessions, status)
    original_writer = orders_service.delete_sales_order_row
    original_audit = orders_service.log_action
    seen = []

    def writer(db, row):
        assert object_session(row) is db and row.id == sid
        seen.append((db, row))
        return original_writer(db, row)

    def audit(db, actor, *args, **kwargs):
        assert len(seen) == 1 and seen[0][0] is db
        assert seen[0][1] in db.deleted and actor.id == actor_id
        return original_audit(db, actor, *args, **kwargs)

    monkeypatch.setattr(orders_service, "delete_sales_order_row", writer)
    monkeypatch.setattr(orders_service, "log_action", audit)
    with sales_client(sessions) as client:
        response = client.delete(f"/sales-orders/{sid}", headers=headers(actor_id))
        assert response.status_code == 204, response.text
        assert response.content == b""
        repeat = client.delete(f"/sales-orders/{sid}", headers=headers(actor_id))
        assert repeat.status_code == 404 and repeat.json()["detail"] == "Sales order not found"
        missing = client.delete("/sales-orders/2147483647", headers=headers(actor_id))
        assert missing.status_code == 404 and missing.json()["detail"] == "Sales order not found"
    assert len(seen) == 1
    assert state(sessions, sid) == (None, [], [(actor_id, None, {"order_no": order_no})])
    with sessions() as db:
        assert db.get(SalesOrderItem, line_id) is None
        assert db.get(Model, model_id) is not None
    chain(sessions)


def test_pg_sales_delete_real_auth_denials_preserve_order_and_lines(customer_pg_sessions):
    sessions = customer_pg_sessions
    actor_id = role_actor(sessions, ["sales.view"])
    sid, _, _, _ = create_order(sessions)
    before = state(sessions, sid)
    with sales_client(sessions) as client:
        assert client.delete(f"/sales-orders/{sid}").status_code == 401
        denied = client.delete(f"/sales-orders/{sid}", headers=headers(actor_id))
        assert denied.status_code == 403, denied.text
    assert state(sessions, sid) == before


@pytest.mark.parametrize("status", ["confirmed", "planning", "closed"])
def test_pg_sales_delete_status_refusal_precedes_references(customer_pg_sessions, status):
    sessions = customer_pg_sessions
    actor_id = role_actor(sessions, ["sales.orders"])
    sid, _, _, _ = create_order(sessions, status)
    with sessions.begin() as db:
        shipment = Shipment(shipment_no="DELETE-SH-" + uuid4().hex, sales_order_id=sid)
        db.add(shipment)
        db.flush()
        shipment_id = shipment.id
    before = state(sessions, sid)
    with sales_client(sessions) as client:
        response = client.delete(f"/sales-orders/{sid}", headers=headers(actor_id))
    assert response.status_code == 409
    assert response.json()["detail"] == "Only draft or cancelled sales orders can be deleted"
    assert state(sessions, sid) == before
    with sessions() as db:
        assert db.get(Shipment, shipment_id).sales_order_id == sid


@pytest.mark.parametrize("references", [
    "production", "shipment", "stock", "production+shipment",
    "production+stock", "shipment+stock", "production+shipment+stock",
])
def test_pg_sales_delete_reference_guard_precedence_preserves_rows(customer_pg_sessions, references):
    sessions = customer_pg_sessions
    actor_id = role_actor(sessions, ["sales.orders"])
    sid, _, _, model_id = create_order(sessions)
    kinds = references.split("+")
    saved = []
    with sessions.begin() as db:
        if "production" in kinds:
            row = ProductionOrder(
                production_no="DELETE-PROD-" + uuid4().hex,
                production_type="client_order", sales_order_id=sid, model_id=model_id, planned_quantity=1,
            )
            db.add(row)
            db.flush()
            saved.append((ProductionOrder, row.id))
        if "shipment" in kinds:
            row = Shipment(shipment_no="DELETE-SH-" + uuid4().hex, sales_order_id=sid)
            db.add(row)
            db.flush()
            saved.append((Shipment, row.id))
        if "stock" in kinds:
            stock = FinishedGoodsStock(
                model_id=model_id, color="fixture", size="M", quantity=1, available_qty=0, reserved_qty=1,
            )
            db.add(stock)
            db.flush()
            reservation = StockReservation(sales_order_id=sid, finished_goods_stock_id=stock.id, quantity=1)
            db.add(reservation)
            db.flush()
            saved.append((StockReservation, reservation.id))
            stock_id = stock.id
    before = state(sessions, sid)
    with sales_client(sessions) as client:
        response = client.delete(f"/sales-orders/{sid}", headers=headers(actor_id))
    assert response.status_code == 409
    first = next(kind for kind in ("production", "shipment", "stock") if kind in kinds)
    expected = {
        "production": "Sales order already has linked production orders",
        "shipment": "Sales order already has linked shipments",
        "stock": "Sales order already has stock reservations",
    }[first]
    assert response.json()["detail"] == expected
    assert state(sessions, sid) == before
    with sessions() as db:
        assert all(db.get(cls, identifier).sales_order_id == sid for cls, identifier in saved)
        if "stock" in kinds:
            stock = db.get(FinishedGoodsStock, stock_id)
            assert (stock.quantity, stock.available_qty, stock.reserved_qty, stock.sold_qty) == (1, 0, 1, 0)


@pytest.mark.parametrize("point", ["audit_enqueue", "audit_finalize", "before_commit"])
def test_pg_sales_delete_precommit_failure_restores_order_lines_then_retry(customer_pg_sessions, monkeypatch, point):
    sessions = customer_pg_sessions
    actor_id = role_actor(sessions, ["sales.orders"])
    sid, order_no, _, _ = create_order(sessions)
    before = state(sessions, sid)
    original = orders_service.log_action
    attempted = []

    def fail(*args, **kwargs):
        raise RuntimeError("injected Sales deletion precommit failure")

    def audit(db, actor, *args, **kwargs):
        entry = original(db, actor, *args, **kwargs)
        attempted.append(args[2])
        if point == "audit_enqueue":
            fail()
        if point == "before_commit":
            event.listen(db, "before_commit", fail)
        return entry

    with monkeypatch.context() as patch:
        patch.setattr(orders_service, "log_action", audit)
        if point == "audit_finalize":
            patch.setattr(audit_service, "add_audit_log_rows", fail)
        with sales_client(sessions) as client:
            response = client.delete(f"/sales-orders/{sid}", headers=headers(actor_id))
        assert response.status_code == 500
    assert attempted == [sid]
    assert state(sessions, sid) == before
    with sales_client(sessions) as client:
        response = client.delete(f"/sales-orders/{sid}", headers=headers(actor_id))
    assert response.status_code == 204, response.text
    assert state(sessions, sid) == (None, [], [(actor_id, None, {"order_no": order_no})])
    chain(sessions)


@pytest.mark.parametrize("kind", ["invoice", "purchase_request"])
def test_pg_sales_delete_unguarded_fk_blocks_atomically_then_retry(customer_pg_sessions, monkeypatch, kind):
    sessions = customer_pg_sessions
    sid, order_no, _, _ = create_order(sessions)
    cls, table = {"invoice": (Invoice, "invoices"), "purchase_request": (PurchaseRequest, "purchase_requests")}[kind]
    with sessions.begin() as db:
        if kind == "invoice":
            blocker = Invoice(invoice_no="DELETE-INV-" + uuid4().hex, sales_order_id=sid, amount=3)
        else:
            blocker = PurchaseRequest(request_no="DELETE-PR-" + uuid4().hex, sales_order_id=sid)
        db.add(blocker)
        db.flush()
        blocker_id = blocker.id
    with sessions() as db:
        constraints = db.execute(text("""
            SELECT c.conname, c.confdeltype, c.condeferrable, c.condeferred
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(c.conkey)
            WHERE n.nspname = current_schema() AND t.relname = :table
              AND c.contype = 'f' AND a.attname = 'sales_order_id'
              AND c.confrelid = 'sales_orders'::regclass
        """), {"table": table}).all()
        assert len(constraints) == 1
        constraint, action, deferrable, deferred = constraints[0]
        assert action == "a" and not deferrable and not deferred
    before = state(sessions, sid)
    called, returned = [], []
    original = orders_service.log_action

    def audit(db, *args, **kwargs):
        called.append(True)
        entry = original(db, *args, **kwargs)
        returned.append(True)
        return entry

    with monkeypatch.context() as patch:
        patch.setattr(orders_service, "log_action", audit)
        with sessions() as db:
            with pytest.raises(IntegrityError) as failure:
                orders_service.delete_sales_order(sid, db, None)
            assert failure.value.orig.pgcode == "23503"
            assert failure.value.orig.diag.constraint_name == constraint
            db.rollback()
    assert called == [True] and returned == []
    assert state(sessions, sid) == before
    with sessions.begin() as db:
        blocker = db.get(cls, blocker_id)
        assert blocker is not None and blocker.sales_order_id == sid
        db.delete(blocker)  # only this test's isolated blocking reference
    with sessions() as db:
        orders_service.delete_sales_order(sid, db, None)
    assert state(sessions, sid) == (None, [], [(None, None, {"order_no": order_no})])
    chain(sessions)


def test_pg_sales_delete_distinct_orders_concurrent_audit_chain(customer_pg_sessions):
    sessions = customer_pg_sessions
    actor_id = role_actor(sessions, ["sales.orders"])
    orders = [create_order(sessions) for _ in range(4)]
    barrier = Barrier(4)

    def delete(sid):
        with sessions() as db:
            actor = db.get(User, actor_id)
            try:
                barrier.wait(timeout=10)
                orders_service.delete_sales_order(sid, db, actor)
            except Exception:
                barrier.abort()
                raise

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(delete, sid) for sid, _, _, _ in orders]
        for future in futures:
            future.result(timeout=30)
    for sid, order_no, line_id, model_id in orders:
        assert state(sessions, sid) == (None, [], [(actor_id, None, {"order_no": order_no})])
        with sessions() as db:
            assert db.get(SalesOrderItem, line_id) is None
            assert db.get(Model, model_id) is not None
    chain(sessions)
