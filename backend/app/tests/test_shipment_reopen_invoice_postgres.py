"""Shipment-reopen Finance participant checks on the approved disposable PG target."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
from queue import Queue
from threading import Barrier
from time import monotonic, sleep
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.routes.shipments import router as shipments_router
from app.core.deps import get_current_user, get_db
from app.libs.dto.fulfillment.shipment_review import ShipmentReopen
from app.libs.dto.sales.payment_input import PaymentIn
from app.libs.enums.finance import InvoiceStatus
from app.libs.enums.fulfillment import FinishedGoodsStatus
from app.models.finance.invoices_service import void_invoices_for_shipment_reopen
from app.models.finance.payments_service import record_invoice_payment
from app.models import shipment_reopen_service
from app.schemas import (
    AuditLog,
    Department,
    FinishedGoodsStock,
    IdempotencyRecord,
    Invoice,
    LegacyStockReceipt,
    Model,
    Package,
    PackageItem,
    Payment,
    Role,
    SalesOrder,
    Shipment,
    ShipmentPackage,
    User,
)
from app.tests.test_customer_create_postgres import chain, customer_pg_sessions  # noqa: F401


@pytest.fixture(scope="module")
def shipment_actors(customer_pg_sessions):
    marker = uuid4().hex
    with customer_pg_sessions.begin() as db:
        storage_role = Role(
            name="Storage",
            permissions=[
                "sales.customers", "storage.receive", "storage.transfer", "storage.items",
                "storage.suppliers", "storage.packages", "storage.shipment",
                "inventory.reservations.view", "inventory.reservations.create",
                "inventory.reservations.release", "inventory.reservations.consume",
                "purchasing.view", "purchasing.receive", "traceability.view", "traceability.export",
            ],
        )
        finance_role = Role(
            name="Finance",
            permissions=[
                "finance.view", "finance.invoice", "finance.payment",
                "inventory.reservations.view", "purchasing.view", "forecasting.view",
            ],
        )
        storage_department = Department(name="Fabric & Accessories Storage", code="STR")
        finance_department = Department(name="Finance", code="FIN")
        db.add_all([storage_role, finance_role, storage_department, finance_department])
        db.flush()
        storage_user = User(
            name="PG shipment storage actor",
            email=f"shipment-storage-{marker}@example.invalid",
            password_hash="unused",
            role_id=storage_role.id,
            department_id=storage_department.id,
            factory_code="MIL",
            extra_permissions=[],
            is_active=True,
        )
        finance_user = User(
            name="PG invoice finance actor",
            email=f"shipment-finance-{marker}@example.invalid",
            password_hash="unused",
            role_id=finance_role.id,
            department_id=finance_department.id,
            factory_code="MIL",
            extra_permissions=[],
            is_active=True,
        )
        db.add_all([storage_user, finance_user])
        db.flush()
        return {"storage": storage_user.id, "finance": finance_user.id}


def _shipment_case(sessions, actor_id, *, later_invoice_status: InvoiceStatus | None = None):
    marker = uuid4().hex
    now = datetime.now(timezone.utc)
    with sessions.begin() as db:
        order = SalesOrder(
            order_no=f"PG-REOPEN-{marker[:16]}",
            status="ready_to_ship",
            total_amount=Decimal("2.00"),
            created_by=actor_id,
        )
        model = Model(code=f"PG-{marker[:20]}", name=f"PG reopen model {marker[:8]}", status="approved")
        receipt = LegacyStockReceipt(
            source_system="PG-REOPEN-QA",
            source_warehouse_id="PG-QA",
            source_record_id=marker,
            source_checksum=sha256(marker.encode()).hexdigest(),
            source_payload={"quantity": 2, "fixture": "shipment-reopen-invoice"},
            imported_by=actor_id,
        )
        db.add_all([order, model, receipt])
        db.flush()
        package = Package(
            package_no=f"PG-REOPEN-{marker[:16]}",
            barcode=f"PG-REOPEN-{marker[:16]}",
            legacy_receipt_id=receipt.id,
            model_id=model.id,
            color="Navy",
            total_quantity=2,
            dispatched_quantities={"1": 2},
            dispatched_quantity=2,
            status="shipped",
            shipped_at=now,
        )
        db.add(package)
        db.flush()
        item = PackageItem(package_id=package.id, model_id=model.id, color="Navy", size="M", quantity=2)
        db.add(item)
        db.flush()
        package.dispatched_quantities = {str(item.id): 2}
        shipment = Shipment(
            sales_order_id=order.id,
            shipment_no=f"PG-REOPEN-{marker[:16]}",
            status="shipped",
            shipped_at=now,
            dispatch_snapshot={"package_quantities": {str(package.id): {str(item.id): 2}}},
        )
        stock = FinishedGoodsStock(
            sales_order_id=order.id,
            package_id=package.id,
            model_id=model.id,
            color="Navy",
            size="M",
            quantity=2,
            available_qty=0,
            reserved_qty=0,
            sold_qty=2,
            status=FinishedGoodsStatus.SOLD.value,
        )
        invoice = Invoice(
            sales_order_id=order.id,
            invoice_no=f"PG-INV-{marker[:16]}",
            amount=Decimal("2.00"),
            status=InvoiceStatus.UNPAID,
            issued_at=now,
        )
        db.add_all([shipment, stock, invoice])
        db.flush()
        link = ShipmentPackage(shipment_id=shipment.id, package_id=package.id, quantity=2)
        db.add(link)
        if later_invoice_status is not None:
            later = Invoice(
                sales_order_id=order.id,
                invoice_no=f"PG-INV-BLOCK-{marker[:12]}",
                amount=Decimal("1.00"),
                status=later_invoice_status,
                issued_at=now,
            )
            db.add(later)
            db.flush()
            later_invoice_id = later.id
        else:
            later_invoice_id = None
        scan_record = IdempotencyRecord(
            scope="shipments.scan-package",
            key=f"pg-reopen-{marker}",
            request_hash="a" * 64,
            response_json={"shipment_id": shipment.id, "package_id": package.id},
            status_code=200,
            user_id=actor_id,
        )
        ship_record = IdempotencyRecord(
            scope="shipments.ship",
            key=f"pg-reopen-{marker}",
            request_hash="b" * 64,
            response_json={"id": shipment.id},
            status_code=200,
            user_id=actor_id,
        )
        db.add_all([scan_record, ship_record])
        db.flush()
        return {
            "shipment_id": shipment.id,
            "order_id": order.id,
            "package_id": package.id,
            "stock_id": stock.id,
            "invoice_id": invoice.id,
            "later_invoice_id": later_invoice_id,
            "actor_id": actor_id,
            "shipped_at": now,
            "idempotency_ids": [scan_record.id, ship_record.id],
        }


def _payload(case):
    return ShipmentReopen(
        reason="QA verified return to preparation",
        expected_shipped_at=case["shipped_at"],
        packages_returned=True,
    )


def _client_for(sessions, actor_id):
    app = FastAPI()
    app.include_router(shipments_router)

    def isolated_db():
        with sessions() as db:
            yield db

    def current_user():
        with sessions() as db:
            user = db.get(User, actor_id)
            assert user is not None
            db.expunge(user)
            return user

    app.dependency_overrides[get_db] = isolated_db
    app.dependency_overrides[get_current_user] = current_user
    return TestClient(app, raise_server_exceptions=False)


def _wait_until_both_invoice_workers_are_blocked(sessions, worker_pids, holder_pid):
    """Observe actual PG row-lock waits and blocking chains, bounded below lock_timeout."""
    pid_a, pid_b = worker_pids
    deadline = monotonic() + 8
    activity_sql = text(
        """
        SELECT pid, wait_event_type, query
        FROM pg_stat_activity
        WHERE pid IN (:pid_a, :pid_b)
        """
    )
    blockers_sql = text(
        """
        WITH RECURSIVE blocker_chain(root_pid, blocked_pid, depth, path) AS (
            SELECT candidate.pid, candidate.pid, 0, ARRAY[candidate.pid]::int[]
            FROM unnest(ARRAY[CAST(:pid_a AS int), CAST(:pid_b AS int)]) AS candidate(pid)
            UNION ALL
            SELECT chain.root_pid, blocker.pid, chain.depth + 1, chain.path || blocker.pid
            FROM blocker_chain AS chain
            CROSS JOIN LATERAL unnest(pg_blocking_pids(chain.blocked_pid)) AS blocker(pid)
            WHERE chain.depth < 8 AND NOT blocker.pid = ANY(chain.path)
        )
        SELECT root_pid
        FROM blocker_chain
        WHERE blocked_pid = :holder_pid
        """
    )
    with sessions() as observer:
        while monotonic() < deadline:
            observer.execute(text("SELECT pg_stat_clear_snapshot()"))
            activities = {
                int(row.pid): row
                for row in observer.execute(activity_sql, {"pid_a": pid_a, "pid_b": pid_b})
            }
            if set(activities) == {pid_a, pid_b}:
                workers_waiting_on_invoice = all(
                    row.wait_event_type == "Lock"
                    and "INVOICES" in str(row.query).upper()
                    and "FOR UPDATE" in str(row.query).upper()
                    for row in activities.values()
                )
                roots_blocked_by_holder = {
                    int(root_pid)
                    for root_pid in observer.execute(
                        blockers_sql,
                        {"pid_a": pid_a, "pid_b": pid_b, "holder_pid": holder_pid},
                    ).scalars()
                }
                if workers_waiting_on_invoice and roots_blocked_by_holder == {pid_a, pid_b}:
                    return
            sleep(0.02)
    raise AssertionError(
        "both invoice workers did not show bounded PostgreSQL FOR UPDATE waits blocked by the holder"
    )


def test_pg_shipment_reopen_finance_participant_same_session_and_no_early_commit(
    customer_pg_sessions, shipment_actors, monkeypatch,
):
    sessions = customer_pg_sessions
    case = _shipment_case(sessions, shipment_actors["storage"])
    called = []
    original = void_invoices_for_shipment_reopen

    with sessions() as db:
        actor = db.get(User, case["actor_id"])
        invoice = db.query(Invoice).filter_by(id=case["invoice_id"]).one()

        def participant(session, invoices):
            assert session is db
            assert invoices == [invoice]
            assert all(invoice in session for invoice in invoices)
            called.append(session)
            return original(session, invoices)

        monkeypatch.setattr(shipment_reopen_service, "void_invoices_for_shipment_reopen", participant)
        result = shipment_reopen_service.reopen_shipment(db, case["shipment_id"], _payload(case), actor)

        assert result.id == case["shipment_id"]
        assert called == [db]
        assert invoice.status is InvoiceStatus.VOID
        assert invoice.amount == Decimal("0.00")
        assert db.in_transaction()
        db.rollback()

    with sessions() as db:
        invoice = db.get(Invoice, case["invoice_id"])
        assert invoice.status is InvoiceStatus.UNPAID
        assert invoice.amount == Decimal("2.00")
        assert db.get(Shipment, case["shipment_id"]).status == "shipped"
        assert db.get(FinishedGoodsStock, case["stock_id"]).sold_qty == 2


def test_pg_shipment_reopen_preflights_every_invoice_before_any_finance_write(
    customer_pg_sessions, shipment_actors,
):
    sessions = customer_pg_sessions
    case = _shipment_case(sessions, shipment_actors["storage"], later_invoice_status=InvoiceStatus.PAID)
    assert case["later_invoice_id"] is not None
    with sessions() as db:
        invoice_before = [
            (row.id, row.status, row.amount)
            for row in db.query(Invoice).filter_by(sales_order_id=case["order_id"]).order_by(Invoice.id)
        ]
        stock_before = db.get(FinishedGoodsStock, case["stock_id"])
        stock_before = (stock_before.quantity, stock_before.available_qty, stock_before.reserved_qty,
                        stock_before.sold_qty, stock_before.status)
        package_before = db.get(Package, case["package_id"])
        package_before = (package_before.status, package_before.shipped_at,
                          package_before.dispatched_quantity, package_before.dispatched_quantities)
        hashes_before = {
            row.id: row.request_hash
            for row in db.query(IdempotencyRecord).filter(IdempotencyRecord.id.in_(case["idempotency_ids"]))
        }
        audit_count = db.query(AuditLog).filter_by(
            entity_type="Shipment", entity_id=case["shipment_id"], action="reopen_shipment",
        ).count()
        with pytest.raises(HTTPException) as refused:
            shipment_reopen_service.reopen_shipment(
                db,
                case["shipment_id"],
                _payload(case),
                db.get(User, case["actor_id"]),
            )
        assert refused.value.status_code == 409
        assert refused.value.detail == "shipment_reopen_finance"
        direct_invoice_after = [
            (row.id, row.status, row.amount)
            for row in db.query(Invoice).filter_by(sales_order_id=case["order_id"]).order_by(Invoice.id)
        ]
        assert direct_invoice_after == invoice_before
        assert db.get(Shipment, case["shipment_id"]).status == "shipped"
        direct_stock = db.get(FinishedGoodsStock, case["stock_id"])
        assert (direct_stock.quantity, direct_stock.available_qty, direct_stock.reserved_qty,
                direct_stock.sold_qty, direct_stock.status) == stock_before
        direct_package = db.get(Package, case["package_id"])
        assert (direct_package.status, direct_package.shipped_at, direct_package.dispatched_quantity,
                direct_package.dispatched_quantities) == package_before
        assert not db.new and not db.dirty and not db.deleted
        assert db.query(AuditLog).filter_by(
            entity_type="Shipment", entity_id=case["shipment_id"], action="reopen_shipment",
        ).count() == audit_count
        assert {
            row.id: row.request_hash
            for row in db.query(IdempotencyRecord).filter(IdempotencyRecord.id.in_(case["idempotency_ids"]))
        } == hashes_before
        db.rollback()

    with _client_for(sessions, shipment_actors["storage"]) as client:
        response = client.post(f"/shipments/{case['shipment_id']}/reopen", json=_payload(case).model_dump(mode="json"))
    assert response.status_code == 409, response.text
    assert response.json() == {"detail": "shipment_reopen_finance"}
    with sessions() as db:
        invoice_after = [
            (row.id, row.status, row.amount)
            for row in db.query(Invoice).filter_by(sales_order_id=case["order_id"]).order_by(Invoice.id)
        ]
        assert invoice_after == invoice_before
        assert invoice_after[0][1] is InvoiceStatus.UNPAID
        assert invoice_after[1][1] is InvoiceStatus.PAID
        assert db.query(Payment).filter(Payment.invoice_id.in_([row[0] for row in invoice_before])).count() == 0
        assert db.get(Shipment, case["shipment_id"]).status == "shipped"
        stock = db.get(FinishedGoodsStock, case["stock_id"])
        assert (stock.quantity, stock.available_qty, stock.reserved_qty, stock.sold_qty, stock.status) == stock_before
        package = db.get(Package, case["package_id"])
        assert (package.status, package.shipped_at, package.dispatched_quantity,
                package.dispatched_quantities) == package_before
        assert {
            row.id: row.request_hash
            for row in db.query(IdempotencyRecord).filter(IdempotencyRecord.id.in_(case["idempotency_ids"]))
        } == hashes_before
        assert db.query(AuditLog).filter_by(
            entity_type="Shipment", entity_id=case["shipment_id"], action="reopen_shipment",
        ).count() == audit_count


def test_pg_shipment_reopen_audit_failure_rolls_back_and_retry_commits_all(
    customer_pg_sessions, shipment_actors, monkeypatch,
):
    sessions = customer_pg_sessions
    case = _shipment_case(sessions, shipment_actors["storage"])
    with sessions() as db:
        hashes_before = {
            row.id: row.request_hash
            for row in db.query(IdempotencyRecord).filter(IdempotencyRecord.id.in_(case["idempotency_ids"]))
        }
        audit_count = db.query(AuditLog).filter_by(
            entity_type="Shipment", entity_id=case["shipment_id"], action="reopen_shipment",
        ).count()

    def fail_audit(*args, **kwargs):
        raise RuntimeError("injected PG shipment reopen audit failure")

    with monkeypatch.context() as scoped:
        scoped.setattr(shipment_reopen_service, "log_action", fail_audit)
        with _client_for(sessions, shipment_actors["storage"]) as client:
            response = client.post(
                f"/shipments/{case['shipment_id']}/reopen",
                json=_payload(case).model_dump(mode="json"),
            )
        assert response.status_code == 500

    with sessions() as db:
        invoice = db.get(Invoice, case["invoice_id"])
        assert invoice.status is InvoiceStatus.UNPAID
        assert invoice.amount == Decimal("2.00")
        assert db.get(Shipment, case["shipment_id"]).status == "shipped"
        package = db.get(Package, case["package_id"])
        assert package.status == "shipped" and package.dispatched_quantity == 2
        stock = db.get(FinishedGoodsStock, case["stock_id"])
        assert (stock.quantity, stock.available_qty, stock.reserved_qty, stock.sold_qty, stock.status) == (
            2, 0, 0, 2, FinishedGoodsStatus.SOLD.value,
        )
        assert {
            row.id: row.request_hash
            for row in db.query(IdempotencyRecord).filter(IdempotencyRecord.id.in_(case["idempotency_ids"]))
        } == hashes_before
        assert db.query(AuditLog).filter_by(
            entity_type="Shipment", entity_id=case["shipment_id"], action="reopen_shipment",
        ).count() == audit_count

    with _client_for(sessions, shipment_actors["storage"]) as client:
        retried = client.post(
            f"/shipments/{case['shipment_id']}/reopen",
            json=_payload(case).model_dump(mode="json"),
        )
    assert retried.status_code == 200, retried.text
    with sessions() as db:
        invoice = db.get(Invoice, case["invoice_id"])
        assert invoice.status is InvoiceStatus.VOID
        assert invoice.amount == Decimal("0.00")
        assert db.get(Shipment, case["shipment_id"]).status == "created"
        assert db.query(AuditLog).filter_by(
            entity_type="Shipment", entity_id=case["shipment_id"], action="reopen_shipment",
        ).count() == audit_count + 1
        assert all(
            db.get(IdempotencyRecord, row_id).request_hash != old_hash
            for row_id, old_hash in hashes_before.items()
        )
    chain(sessions)


def test_pg_invoice_payment_and_shipment_reopen_serialize_on_invoice_row(
    customer_pg_sessions, shipment_actors,
):
    sessions = customer_pg_sessions
    case = _shipment_case(sessions, shipment_actors["storage"])
    barrier = Barrier(3)
    pids = Queue()
    holder = sessions()
    holder.query(Invoice).filter_by(id=case["invoice_id"]).with_for_update().one()
    holder_pid = int(holder.execute(text("SELECT pg_backend_pid()")).scalar_one())

    def reopen_worker():
        with sessions() as db:
            actor = db.get(User, shipment_actors["storage"])
            pids.put(int(db.execute(text("SELECT pg_backend_pid()")).scalar_one()))
            barrier.wait(timeout=10)
            try:
                shipment_reopen_service.reopen_shipment(db, case["shipment_id"], _payload(case), actor)
                db.commit()
                return "reopened"
            except HTTPException as error:
                db.rollback()
                return f"reopen-refused:{error.detail}"

    def payment_worker():
        with sessions() as db:
            actor = db.get(User, shipment_actors["finance"])
            pids.put(int(db.execute(text("SELECT pg_backend_pid()")).scalar_one()))
            barrier.wait(timeout=10)
            try:
                record_invoice_payment(
                    db,
                    PaymentIn(invoice_id=case["invoice_id"], amount=Decimal("0.50"), payment_method="cash"),
                    actor,
                    f"pg-reopen-race-{uuid4().hex}",
                )
                return "paid"
            except HTTPException as error:
                db.rollback()
                return f"payment-refused:{error.detail}"

    executor = ThreadPoolExecutor(max_workers=2)
    futures = []
    try:
        futures = [executor.submit(reopen_worker), executor.submit(payment_worker)]
        worker_pids = [pids.get(timeout=5), pids.get(timeout=5)]
        barrier.wait(timeout=5)
        _wait_until_both_invoice_workers_are_blocked(sessions, worker_pids, holder_pid)
    finally:
        if holder.in_transaction():
            holder.rollback()
        holder.close()
        executor.shutdown(wait=True)
    outcomes = [future.result(timeout=45) for future in futures]

    assert set(outcomes) in (
        {"reopened", "payment-refused:Cannot pay a reversed or cancelled invoice"},
        {"reopen-refused:shipment_reopen_finance", "paid"},
    )
    with sessions() as db:
        invoice = db.get(Invoice, case["invoice_id"])
        payment_count = db.query(Payment).filter_by(invoice_id=case["invoice_id"]).count()
        shipment = db.get(Shipment, case["shipment_id"])
        stock = db.get(FinishedGoodsStock, case["stock_id"])
        if "reopened" in outcomes:
            assert invoice.status is InvoiceStatus.VOID
            assert invoice.amount == Decimal("0.00")
            assert payment_count == 0
            assert shipment.status == "created"
            assert (stock.available_qty, stock.reserved_qty, stock.sold_qty, stock.status) == (
                2, 0, 0, FinishedGoodsStatus.AVAILABLE.value,
            )
        else:
            assert invoice.status is InvoiceStatus.PARTIALLY_PAID
            assert invoice.amount == Decimal("2.00")
            assert payment_count == 1
            payment = db.query(Payment).filter_by(invoice_id=case["invoice_id"]).one()
            assert payment.amount == Decimal("0.50")
            assert shipment.status == "shipped"
            assert (stock.available_qty, stock.reserved_qty, stock.sold_qty, stock.status) == (
                0, 0, 2, FinishedGoodsStatus.SOLD.value,
            )
    chain(sessions)
