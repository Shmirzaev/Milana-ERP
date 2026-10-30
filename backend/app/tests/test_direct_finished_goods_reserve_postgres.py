"""Approved PostgreSQL parity and race checks for direct stock reservation."""

from concurrent.futures import ThreadPoolExecutor
import json
from queue import Queue
from threading import Barrier
from time import monotonic, sleep
from uuid import uuid4

from fastapi import HTTPException
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import event, text

from app.api.routes.finished_goods import router as finished_goods_router
from app.core.deps import get_current_user, get_db
from app.libs.types.stock_reservation import ManualPackageReservationResult
from app.models import audit_service
from app.models.fulfillment import stock_service
from app.models.fulfillment.stock_service import reserve_direct_stock
from app.schemas import (
    AuditLog, FinishedGoodsStock, LegacyStockReceipt, ManualPackageReceipt,
    Model, Package, PackageItem, SalesOrder, StockReservation, User,
)
from app.tests.test_customer_create_postgres import chain, customer_pg_sessions  # noqa: F401


def _client(sessions, actor_id):
    app = FastAPI()
    app.include_router(finished_goods_router, prefix="/api")

    def isolated_db():
        with sessions() as db:
            yield db

    def current_user():
        with sessions() as db:
            actor = db.get(User, actor_id)
            db.expunge(actor)
            return actor

    app.dependency_overrides[get_db] = isolated_db
    app.dependency_overrides[get_current_user] = current_user
    return TestClient(app)


def _stock_fixture(sessions, *, manual: bool):
    marker = uuid4().hex
    with sessions.begin() as db:
        user = User(
            name="Direct reserve PG actor", email=f"direct-reserve-{marker}@example.invalid",
            password_hash="unused", factory_code="MIL", extra_permissions=["sales.orders"],
            is_active=True,
        )
        model = Model(code=f"DR-{marker}", name="Direct reserve PG", status="approved")
        orders = [
            SalesOrder(order_no=f"DR-{marker}-{index}", order_type="branded_stock_sale", status="draft")
            for index in range(2)
        ]
        db.add_all([user, model, *orders])
        db.flush()
        package_fields = {}
        if manual:
            receipt = ManualPackageReceipt(
                receipt_no=f"DR-{marker}", created_by=user.id,
                evidence={"quantities": [10]}, evidence_hash="a" * 64,
            )
            db.add(receipt)
            db.flush()
            package_fields["manual_receipt_id"] = receipt.id
        else:
            receipt = LegacyStockReceipt(
                source_system="TEST", source_warehouse_id="direct-reserve",
                source_record_id=marker, source_checksum="b" * 64,
                source_payload={"quantity": 10}, imported_by=user.id,
            )
            db.add(receipt)
            db.flush()
            package_fields["legacy_receipt_id"] = receipt.id
        package = Package(
            package_no=f"DR-{marker}", barcode=f"DR-{marker}", model_id=model.id,
            color="blue", total_quantity=10, capacity=10,
            status="received_in_storage", **package_fields,
        )
        db.add(package)
        db.flush()
        db.add_all([
            PackageItem(package_id=package.id, model_id=model.id, color="blue", size="M", quantity=10),
            FinishedGoodsStock(
                package_id=package.id, model_id=model.id, color="blue", size="M",
                quantity=10, available_qty=10, reserved_qty=0, sold_qty=0, status="available",
            ),
        ])
        db.flush()
        stock = db.query(FinishedGoodsStock).filter_by(package_id=package.id).one()
        return {
            "user_id": user.id, "model_id": model.id, "package_id": package.id,
            "stock_id": stock.id, "order_ids": [order.id for order in orders],
            "manual": manual,
        }


def test_pg_direct_reserve_manual_package_persists_rows_and_audit(customer_pg_sessions):
    sessions = customer_pg_sessions
    fixture = _stock_fixture(sessions, manual=True)
    with sessions() as db:
        actor = db.get(User, fixture["user_id"])
        result = reserve_direct_stock(
            db, actor=actor, stock_id=fixture["stock_id"], quantity=10,
            sales_order_id=fixture["order_ids"][0],
        )
        assert type(result) is ManualPackageReservationResult
        assert (result.stock_id, result.package_id, result.quantity) == (
            fixture["stock_id"], fixture["package_id"], 10,
        )
    with sessions() as db:
        stock = db.get(FinishedGoodsStock, fixture["stock_id"])
        package = db.get(Package, fixture["package_id"])
        reservations = db.query(StockReservation).filter_by(package_id=fixture["package_id"]).all()
        audit = db.query(AuditLog).filter_by(
            action="reserve", entity_type="Package", entity_id=fixture["package_id"],
        ).all()
        assert (stock.quantity, stock.available_qty, stock.reserved_qty, stock.sold_qty, stock.status) == (
            10, 0, 10, 0, "reserved",
        )
        assert package.status == "received_in_storage"
        assert [(row.sales_order_id, row.finished_goods_stock_id, row.package_id,
                 row.quantity, row.reserved_by) for row in reservations] == [
            (fixture["order_ids"][0], fixture["stock_id"], fixture["package_id"], 10, fixture["user_id"]),
        ]
        assert len(audit) == 1 and audit[0].user_id == fixture["user_id"]
        assert audit[0].new_value_json == {
            "qty": 10, "sales_order_id": fixture["order_ids"][0],
            "stock_ids": [fixture["stock_id"]],
        }
    chain(sessions)


def test_pg_direct_reserve_denied_actor_makes_no_business_writes(customer_pg_sessions):
    sessions = customer_pg_sessions
    fixture = _stock_fixture(sessions, manual=False)
    with sessions.begin() as db:
        denied = User(
            name="Direct reserve denied actor", email=f"direct-denied-{uuid4().hex}@example.invalid",
            password_hash="unused", factory_code="MIL", extra_permissions=["sales.view"],
            is_active=True,
        )
        db.add(denied)
        db.flush()
        denied_id = denied.id

    with _client(sessions, denied_id) as client:
        response = client.post("/api/finished-goods/reserve", params={
            "stock_id": fixture["stock_id"], "quantity": 2,
            "sales_order_id": fixture["order_ids"][0],
        })
    assert response.status_code == 403, response.text
    with sessions() as db:
        stock = db.get(FinishedGoodsStock, fixture["stock_id"])
        assert (stock.available_qty, stock.reserved_qty) == (10, 0)
        assert db.query(StockReservation).filter_by(finished_goods_stock_id=fixture["stock_id"]).count() == 0
        assert db.query(AuditLog).filter_by(entity_type="FinishedGoodsStock", entity_id=fixture["stock_id"]).count() == 0


def test_pg_direct_reserve_competing_piece_requests_do_not_oversell(
    customer_pg_sessions, record_property,
):
    sessions = customer_pg_sessions
    fixture = _stock_fixture(sessions, manual=False)
    holder = sessions()
    holder_pid = holder.execute(text("SELECT pg_backend_pid()")).scalar_one()
    holder.query(Package).filter(Package.id == fixture["package_id"]).with_for_update().one()
    worker_pids = Queue()
    start = Barrier(3)

    def reserve(order_id):
        with sessions() as db:
            actor = db.get(User, fixture["user_id"])
            worker_pids.put(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
            start.wait(timeout=8)
            try:
                result = reserve_direct_stock(
                    db, actor=actor, stock_id=fixture["stock_id"], quantity=6,
                    sales_order_id=order_id,
                )
                return ("reserved", result.quantity)
            except HTTPException as error:
                db.rollback()
                return ("refused", error.status_code, error.detail)

    pool = ThreadPoolExecutor(max_workers=2)
    workers = [pool.submit(reserve, order_id) for order_id in fixture["order_ids"]]
    observer = sessions()
    blocked_pids = set()
    witnesses = {}
    latest = {}
    refreshes = 0
    try:
        blocked_pids = {worker_pids.get(timeout=5), worker_pids.get(timeout=5)}
        start.wait(timeout=8)
        deadline = monotonic() + 8
        while monotonic() < deadline:
            observer.execute(text("SELECT pg_stat_clear_snapshot()"))
            refreshes += 1
            for pid in blocked_pids:
                state = observer.execute(text("""
                    SELECT wait_event_type, wait_event, query, length(query) AS query_length,
                           current_setting('track_activity_query_size') AS query_size_limit,
                           pg_blocking_pids(pid) AS blocking_pids
                      FROM pg_stat_activity WHERE pid = :pid
                """), {"pid": pid}).one_or_none()
                locks = observer.execute(text("""
                    SELECT l.locktype, l.mode, l.granted, l.page, l.tuple,
                           l.transactionid, n.nspname, c.relname
                      FROM pg_locks AS l
                      LEFT JOIN pg_class AS c ON c.oid = l.relation
                      LEFT JOIN pg_namespace AS n ON n.oid = c.relnamespace
                     WHERE l.pid = :pid
                """), {"pid": pid}).mappings().all()
                if not state:
                    continue
                package_row_share = any(
                    lock["granted"] and lock["locktype"] == "relation"
                    and lock["nspname"] == "public" and lock["relname"] == "packages"
                    and lock["mode"] == "RowShareLock"
                    for lock in locks
                )
                waiting_on_row = any(
                    not lock["granted"] and lock["locktype"] in {"transactionid", "tuple"}
                    for lock in locks
                )
                blocker_chain = set(state.blocking_pids or ())
                frontier = list(blocker_chain)
                while frontier:
                    blocker = frontier.pop()
                    for parent in observer.execute(
                        text("SELECT pg_blocking_pids(:pid)"), {"pid": blocker},
                    ).scalar_one():
                        if parent not in blocker_chain:
                            blocker_chain.add(parent)
                            frontier.append(parent)
                latest[pid] = {
                    "wait_event_type": state.wait_event_type,
                    "wait_event": state.wait_event,
                    "query_length": state.query_length,
                    "query_size_limit": state.query_size_limit,
                    "query_prefix": (state.query or "")[:100],
                    "query_has_for_update": "for update" in (state.query or "").lower(),
                    "package_row_share": package_row_share,
                    "waiting_on_row": waiting_on_row,
                    "refreshes": refreshes,
                    "blocking_chain": sorted(blocker_chain),
                }
                if (state.wait_event_type == "Lock" and package_row_share
                        and waiting_on_row and holder_pid in blocker_chain):
                    witnesses[pid] = latest[pid]
            if set(witnesses) == blocked_pids or all(worker.done() for worker in workers):
                break
            sleep(0.02)
    finally:
        try:
            holder.rollback()
        finally:
            try:
                holder.close()
            finally:
                try:
                    observer.close()
                finally:
                    pool.shutdown(wait=True, cancel_futures=True)

    outcomes = [worker.result(timeout=15) for worker in workers]
    record_property(
        "direct_reserve_postgres_package_lock_witnesses",
        json.dumps({"holder_pid": holder_pid, "worker_pids": sorted(blocked_pids),
                    "refreshes": refreshes, "witnesses": witnesses}, sort_keys=True),
    )
    assert len(blocked_pids) == 2 and set(witnesses) == blocked_pids, (
        f"both workers must wait on the locked package row with blocker chain to holder; "
        f"holder={holder_pid}, workers={sorted(blocked_pids)}, "
        f"witnesses={witnesses}, refreshes={refreshes}, latest={latest}"
    )
    assert sorted(outcome[0] for outcome in outcomes) == ["refused", "reserved"]
    refused = next(outcome for outcome in outcomes if outcome[0] == "refused")
    assert refused[1:] == (400, "Not enough available")

    with sessions() as db:
        stock = db.get(FinishedGoodsStock, fixture["stock_id"])
        rows = db.query(StockReservation).filter_by(finished_goods_stock_id=fixture["stock_id"]).all()
        audits = db.query(AuditLog).filter_by(
            action="reserve", entity_type="FinishedGoodsStock", entity_id=fixture["stock_id"],
        ).all()
        assert (stock.quantity, stock.available_qty, stock.reserved_qty, stock.sold_qty, stock.status) == (
            10, 4, 6, 0, "available",
        )
        assert len(rows) == 1 and rows[0].quantity == 6
        assert rows[0].sales_order_id in fixture["order_ids"]
        assert rows[0].reserved_by == fixture["user_id"]
        assert len(audits) == 1 and audits[0].user_id == fixture["user_id"]
        assert audits[0].new_value_json == {"qty": 6}
    chain(sessions)


@pytest.mark.parametrize("failure_point", ["audit_enqueue", "audit_finalize", "before_commit"])
def test_pg_direct_reserve_failure_rolls_back_then_retry(customer_pg_sessions, monkeypatch, failure_point):
    sessions = customer_pg_sessions
    fixture = _stock_fixture(sessions, manual=False)
    original_log = stock_service.log_action

    def injected_failure(*args, **kwargs):
        raise RuntimeError("injected direct reserve failure")

    def observed_log(db, *args, **kwargs):
        result = original_log(db, *args, **kwargs)
        if failure_point == "audit_enqueue":
            injected_failure()
        if failure_point == "before_commit":
            event.listen(db, "before_commit", injected_failure)
        return result

    with monkeypatch.context() as patch:
        patch.setattr(stock_service, "log_action", observed_log)
        if failure_point == "audit_finalize":
            patch.setattr(audit_service, "_audit_entry_hash", injected_failure)
        with sessions() as db:
            actor = db.get(User, fixture["user_id"])
            try:
                with pytest.raises(RuntimeError, match="injected direct reserve failure"):
                    reserve_direct_stock(
                        db, actor=actor, stock_id=fixture["stock_id"], quantity=2,
                        sales_order_id=fixture["order_ids"][0],
                    )
            finally:
                if failure_point == "before_commit":
                    event.remove(db, "before_commit", injected_failure)
                db.rollback()

    with sessions() as db:
        stock = db.get(FinishedGoodsStock, fixture["stock_id"])
        assert (stock.available_qty, stock.reserved_qty, stock.status) == (10, 0, "available")
        assert db.query(StockReservation).filter_by(finished_goods_stock_id=fixture["stock_id"]).count() == 0
        assert db.query(AuditLog).filter_by(
            action="reserve", entity_type="FinishedGoodsStock", entity_id=fixture["stock_id"],
        ).count() == 0

    with sessions() as db:
        actor = db.get(User, fixture["user_id"])
        result = reserve_direct_stock(
            db, actor=actor, stock_id=fixture["stock_id"], quantity=2,
            sales_order_id=fixture["order_ids"][0],
        )
        assert result.quantity == 2
    with sessions() as db:
        stock = db.get(FinishedGoodsStock, fixture["stock_id"])
        reservations = db.query(StockReservation).filter_by(finished_goods_stock_id=fixture["stock_id"]).all()
        audit = db.query(AuditLog).filter_by(
            action="reserve", entity_type="FinishedGoodsStock", entity_id=fixture["stock_id"],
        ).all()
        assert (stock.available_qty, stock.reserved_qty, stock.status) == (8, 2, "available")
        assert len(reservations) == 1 and reservations[0].quantity == 2
        assert len(audit) == 1 and audit[0].new_value_json == {"qty": 2}
    chain(sessions)
