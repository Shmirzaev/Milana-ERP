"""SAL-UPDATE characterization only; frozen 8a application is unmodified."""
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError

from app.core.security import create_access_token
from app.core.signing import verify_path
from app.db.session import SessionLocal
from app.libs.dto.sales.sales_order_update import SalesOrderUpdate
from app.libs.enums.sales import SalesOrderStatus
from app.models.sales import orders_service as sales
from app.schemas import (
    AuditLog, Customer, FinishedGoodsStock, IdempotencyRecord, Model, Notification,
    SalesOrder, SalesOrderItem, StockReservation, User,
)
from app.tests.test_customer_invoice_creation_race import receipt_race_sessions as receipt_race_sessions


def seed(sessions, *, status="reserved", permission="sales.orders"):
    with sessions() as db:
        actor = User(name="Synthetic edit reviewer", email=f"{uuid4().hex}@example.invalid",
                     password_hash="unused", extra_permissions=[permission])
        customer = Customer(name="Original edit customer")
        model = Model(code=f"EDIT-{uuid4().hex}", name="Edit study model")
        db.add_all([actor, customer, model]); db.flush()
        order = SalesOrder(order_no=f"EDIT-{uuid4().hex}", customer_id=customer.id,
                           status=status, order_type="branded_stock_sale", total_amount=Decimal("40.00"),
                           deadline=datetime(2026, 11, 1, tzinfo=timezone.utc),
                           printing_instructions="old instructions", notes="old notes",
                           printing_attachments=[{"file_url": "/storage/sales-order-files/old.png", "file_name": "old.png", "content_type": "image/png"}])
        db.add(order); db.flush()
        line = SalesOrderItem(sales_order_id=order.id, model_id=model.id, color="white", size="M",
                              quantity=4, unit_price=10, source_type="from_stock", printing_required=False)
        stock = FinishedGoodsStock(model_id=model.id, color="white", size="M", quantity=10,
                                   available_qty=6, reserved_qty=4, sold_qty=0, status="available")
        db.add_all([line, stock]); db.flush()
        reservation = StockReservation(sales_order_id=order.id, finished_goods_stock_id=stock.id,
                                        quantity=4, reserved_by=actor.id)
        db.add(reservation); db.commit()
        return order.id, actor.id, customer.id, line.id, stock.id, reservation.id


def assert_physical_unchanged(db, ids):
    oid, _uid, _cid, line_id, stock_id, reservation_id = ids
    line, stock, reservation = db.get(SalesOrderItem, line_id), db.get(FinishedGoodsStock, stock_id), db.get(StockReservation, reservation_id)
    assert (line.quantity, line.unit_price, line.source_type) == (4, Decimal("10.00"), "from_stock")
    assert (stock.quantity, stock.available_qty, stock.reserved_qty, stock.sold_qty) == (10, 6, 4, 0)
    assert reservation.quantity == 4
    assert db.get(SalesOrder, oid).total_amount == Decimal("40.00")


def test_patch_preserves_omitted_fields_and_signed_attachment_storage(client, auth_headers):
    from urllib.parse import urlsplit, parse_qs
    ids = seed(SessionLocal)
    response = client.patch(f"/api/sales-orders/{ids[0]}", headers=auth_headers, json={
        "notes": "changed", "printing_attachments": [{"file_url": "/storage/sales-order-files/new.png?exp=1&sig=expired", "file_name": "new.png", "content_type": "image/png"}],
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert "items" not in body and body["notes"] == "changed"
    assert body["customer"] == {"id": ids[2], "name": "Original edit customer"}
    assert body["printing_instructions"] == "old instructions" and body["deadline"]
    url = urlsplit(body["printing_attachments"][0]["file_url"]); query = parse_qs(url.query)
    assert verify_path(url.path, query["exp"][0], query["sig"][0])
    with SessionLocal() as db:
        stored = db.get(SalesOrder, ids[0]).printing_attachments[0]
        assert stored["file_url"] == "/storage/sales-order-files/new.png"
        assert_physical_unchanged(db, ids)


def test_explicit_null_clears_header_and_normalizes_attachments_to_empty(client, auth_headers):
    ids = seed(SessionLocal)
    response = client.patch(f"/api/sales-orders/{ids[0]}", headers=auth_headers,
                            json={"customer_id": None, "deadline": None, "printing_instructions": None,
                                  "printing_attachments": None, "notes": None})
    assert response.status_code == 200, response.text
    body = response.json()
    assert all(body[key] is None for key in ["customer_id", "customer", "customer_name", "deadline", "printing_instructions", "notes"])
    assert body["printing_attachments"] == []
    with SessionLocal() as db:
        assert db.get(SalesOrder, ids[0]).printing_attachments == []
        assert_physical_unchanged(db, ids)


@pytest.mark.parametrize("payload", [{}, {"items": [], "total_amount": 0, "order_type": "client_order"}])
def test_empty_or_unsupported_patch_audits_each_retry_without_repricing_or_idempotency(client, auth_headers, payload):
    ids = seed(SessionLocal)
    with SessionLocal() as db:
        notification_count = db.query(Notification).count()
        retry_count = db.query(IdempotencyRecord).count()
    headers = {**auth_headers, "Idempotency-Key": "same-edit-key"}
    for _ in range(2):
        response = client.patch(f"/api/sales-orders/{ids[0]}", headers=headers, json=payload)
        assert response.status_code == 200, response.text
        assert response.json()["order_type"] == "branded_stock_sale"
        assert "items" not in response.json()
    with SessionLocal() as db:
        rows = db.query(AuditLog).filter_by(entity_type="SalesOrder", entity_id=ids[0], action="update").all()
        assert len(rows) == 2
        assert all(row.old_value_json is None and row.new_value_json is None for row in rows)
        assert db.query(Notification).count() == notification_count
        assert db.query(IdempotencyRecord).count() == retry_count
        assert_physical_unchanged(db, ids)


@pytest.mark.parametrize("status", ["closed", "ready_to_ship", "printing", "pending_sales_approval"])
def test_unchanged_extended_status_is_allowed_and_internal_result_is_dict(client, auth_headers, status):
    ids = seed(SessionLocal, status=status)
    with SessionLocal() as db:
        result = sales.update_sales_order(ids[0], SalesOrderUpdate(status=status, notes="edited"), db, db.get(User, ids[1]))
        assert isinstance(result, dict) and result["status"] is SalesOrderStatus(status)
    response = client.patch(f"/api/sales-orders/{ids[0]}", headers=auth_headers, json={"status": status})
    assert response.status_code == 200 and response.json()["status"] == status


@pytest.mark.parametrize("permission,expected", [("sales.orders", 200), ("sales.customers", 403)])
def test_actual_patch_permission_dependency(client, permission, expected):
    ids = seed(SessionLocal, permission=permission)
    headers = {"Authorization": f"Bearer {create_access_token(ids[1])}"}
    response = client.patch(f"/api/sales-orders/{ids[0]}", headers=headers, json={"notes": "permitted edit"})
    assert response.status_code == expected, response.text
    with SessionLocal() as db:
        assert db.get(SalesOrder, ids[0]).notes == ("permitted edit" if expected == 200 else "old notes")
        assert db.query(AuditLog).filter_by(entity_type="SalesOrder", entity_id=ids[0], action="update").count() == (1 if expected == 200 else 0)


def test_missing_order_is_404_and_unauthenticated_is_401(client, auth_headers):
    assert client.patch("/api/sales-orders/999999999", headers=auth_headers, json={"notes": "x"}).status_code == 404
    client.cookies.clear()
    assert client.patch("/api/sales-orders/999999999", json={"notes": "x"}).status_code == 401


def test_pg_stale_unchanged_status_cannot_rewind_concurrent_workflow(receipt_race_sessions):
    sessions = receipt_race_sessions
    ids = seed(sessions)
    with sessions() as stale:
        retained = stale.get(SalesOrder, ids[0])
        assert retained.status == "reserved"
        actor = stale.get(User, ids[1])
        with sessions() as other:
            row = other.get(SalesOrder, ids[0]); row.status = "shipped"; row.printing_instructions = "workflow note"
            other.commit()
        statements = []
        def capture(_conn, _cursor, statement, _params, _context, _many): statements.append(statement.lower())
        event.listen(stale.bind, "before_cursor_execute", capture)
        try:
            result = sales.update_sales_order(ids[0], SalesOrderUpdate(status="reserved", notes="late header"), stale, actor)
        finally:
            event.remove(stale.bind, "before_cursor_execute", capture)
        assert result["status"] is SalesOrderStatus.SHIPPED
        assert result["printing_instructions"] == "workflow note"
        writes = [s for s in statements if s.startswith("update sales_orders")]
        assert len(writes) == 1 and "status=" not in writes[0].replace(" ", "")
        assert not any("for update" in s or "for no key update" in s for s in statements)
    with sessions() as db:
        assert db.get(SalesOrder, ids[0]).status == "shipped"
        assert_physical_unchanged(db, ids)


@pytest.mark.parametrize("phase", ["audit_enqueue", "audit_finalized"])
def test_pg_edit_and_audit_rollback_together_then_retry(receipt_race_sessions, monkeypatch, phase):
    sessions = receipt_race_sessions; ids = seed(sessions)
    real_log = sales.log_action; observed = []
    def fail_log(db, *args, **kwargs):
        real_log(db, *args, **kwargs)
        assert db.get(SalesOrder, ids[0]).notes == "must roll back"
        if phase == "audit_enqueue":
            observed.append(True); raise RuntimeError("injected edit failure")
        def after_finalizer(session):
            audit = session.query(AuditLog).filter_by(entity_type="SalesOrder", entity_id=ids[0], action="update").one()
            assert audit.entry_hash
            observed.append(True); raise RuntimeError("injected edit failure")
        event.listen(db, "before_commit", after_finalizer)
    monkeypatch.setattr(sales, "log_action", fail_log)
    with sessions() as db:
        with pytest.raises(RuntimeError, match="injected edit failure"):
            sales.update_sales_order(ids[0], SalesOrderUpdate(notes="must roll back"), db, db.get(User, ids[1]))
        db.rollback()
    assert observed
    monkeypatch.undo()
    with sessions() as db:
        assert db.get(SalesOrder, ids[0]).notes == "old notes"
        assert db.query(AuditLog).filter_by(entity_type="SalesOrder", entity_id=ids[0], action="update").count() == 0
        result = sales.update_sales_order(ids[0], SalesOrderUpdate(notes="retry saved"), db, db.get(User, ids[1]))
        assert result["notes"] == "retry saved"
        assert db.query(AuditLog).filter_by(entity_type="SalesOrder", entity_id=ids[0], action="update").count() == 1
        assert_physical_unchanged(db, ids)


def test_pg_unknown_customer_fails_fk_atomically_without_custom_service_refusal(receipt_race_sessions):
    sessions = receipt_race_sessions; ids = seed(sessions)
    with sessions() as db:
        with pytest.raises(IntegrityError) as error:
            sales.update_sales_order(ids[0], SalesOrderUpdate(customer_id=2_000_000_000, notes="not saved"), db, db.get(User, ids[1]))
        assert error.value.orig.pgcode == "23503"
        db.rollback()
    with sessions() as db:
        order = db.get(SalesOrder, ids[0])
        assert order.customer_id == ids[2] and order.notes == "old notes"
        assert db.query(AuditLog).filter_by(entity_type="SalesOrder", entity_id=ids[0], action="update").count() == 0
        assert_physical_unchanged(db, ids)
