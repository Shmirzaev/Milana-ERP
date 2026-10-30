"""Approved PostgreSQL coverage for the full Inventory accessory issue operation."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from threading import Barrier, Event
from time import monotonic, sleep
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import event, text
from sqlalchemy.orm import Session, object_session

from app.api.routes.inventory import router
from app.core.deps import get_current_user, get_db
from app.libs.dto.inventory.accessory_issue_input import AccessoryIssueIn, AccessoryIssueLineIn
from app.libs.enums.inventory import StockMovementType
from app.models import audit_service
from app.models.inventory import stock_service
from app.models.inventory_service import ACCESSORY_SEWING_BLOCK_REASON, sync_sewing_accessory_block
from app.schemas import (
    AuditLog,
    CuttingRecord,
    IdempotencyRecord,
    Item,
    ManualAccessoryIssue,
    ModelBOM,
    Notification,
    ProductionOrder,
    StockBatch,
    StockMovement,
    User,
    Warehouse,
    WorkOrder,
)
from app.schemas.inventory import accessory_issue_persistence, stock_movement_persistence
from app.tests.test_customer_create_postgres import chain, customer_pg_sessions  # noqa: F401
from app.tests.test_sewing_output_postgres import sewing_case  # noqa: F401


def _client_for(sessions, actor_id: int | None) -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api")

    def isolated_db():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = isolated_db
    if actor_id is not None:
        def current_user():
            with sessions() as db:
                user = db.get(User, actor_id)
                if user is not None:
                    db.expunge(user)
                return user

        app.dependency_overrides[get_current_user] = current_user
    return TestClient(app, raise_server_exceptions=False)


def _seed_accessory(
    sessions,
    sewing_case: dict,
    *,
    quantities: tuple[float, ...] = (6.0,),
    required_quantity: float = 4.0,
    include_cutting_output: bool = True,
    initialize_gate: bool = True,
) -> dict:
    marker = uuid4().hex[:12]
    with sessions.begin() as db:
        order = db.get(ProductionOrder, sewing_case["order_id"])
        warehouse = Warehouse(name=f"Issue QA {marker}", type="accessory_storage")
        item = Item(
            sku=f"ISSUE-{marker}", name=f"Issue QA {marker}", category="accessory",
            unit="pcs", default_cost=Decimal("0.25"), reorder_level=0,
            track_batch=True, is_active=True,
        )
        db.add_all([warehouse, item])
        db.flush()
        batches = []
        for index, quantity in enumerate(quantities):
            batch = StockBatch(
                item_id=item.id, batch_no=f"ISSUE-{marker}-{index}",
                quantity=quantity, unit="pcs", cost_per_unit=Decimal("0.25"),
                warehouse_id=warehouse.id, qc_status="passed",
                received_date=datetime(2024, 1, 1 + index, tzinfo=timezone.utc),
            )
            db.add(batch)
            batches.append(batch)
        db.add(ModelBOM(
            model_id=order.model_id, item_id=item.id,
            quantity_per_piece=Decimal(str(required_quantity / order.planned_quantity)),
            unit="pcs", waste_percent=0,
        ))
        if include_cutting_output:
            db.add(CuttingRecord(
                work_order_id=sewing_case["cutting_id"],
                cut_pieces=50, report_piece_count=50, passed_pieces=50,
            ))
        db.flush()
        if include_cutting_output and initialize_gate:
            sync_sewing_accessory_block(db, int(order.id))
        return {
            "order_id": int(order.id),
            "item_id": int(item.id),
            "sku": item.sku,
            "actor_id": int(sewing_case["actor_id"]),
            "sewing_id": int(sewing_case["sewing_id"]),
            "batch_ids": tuple(int(batch.id) for batch in batches),
            "warehouse_id": int(warehouse.id),
            "initial_quantities": quantities,
        }


def _payload(case: dict, lines: list[dict], notes: str | None = None) -> AccessoryIssueIn:
    return AccessoryIssueIn(
        production_order_id=case["order_id"],
        lines=[AccessoryIssueLineIn(**line) for line in lines],
        notes=notes,
    )


def test_pg_route_stock_issue_persists_fifo_gate_and_audit_same_session(
    customer_pg_sessions, sewing_case, monkeypatch,
):
    sessions = customer_pg_sessions
    case = _seed_accessory(sessions, sewing_case, quantities=(3, 3), required_quantity=4)
    actor_id = case["actor_id"]
    writer_sessions = []
    audit_sessions = []
    commits = []
    add_manual = accessory_issue_persistence.add_manual_accessory_issue
    add_movement = stock_movement_persistence.record_stock_consumption
    log = stock_service.log_action

    def observe_manual(db, **values):
        writer_sessions.append(db)
        return add_manual(db, **values)

    def observe_movement(db, **values):
        writer_sessions.append(db)
        result = add_movement(db, **values)
        assert object_session(result) is db
        return result

    def observe_audit(db, *args, **kwargs):
        audit_sessions.append(db)
        assert writer_sessions and all(session is db for session in writer_sessions)
        return log(db, *args, **kwargs)

    def count_commit(session):
        if writer_sessions and session is writer_sessions[0]:
            commits.append(session)

    monkeypatch.setattr(accessory_issue_persistence, "add_manual_accessory_issue", observe_manual)
    monkeypatch.setattr(stock_movement_persistence, "record_stock_consumption", observe_movement)
    monkeypatch.setattr(stock_service, "log_action", observe_audit)
    event.listen(Session, "after_commit", count_commit)
    try:
        with _client_for(sessions, actor_id) as client:
            response = client.post(
                "/api/inventory/accessory-issues",
                json={"production_order_id": case["order_id"], "lines": [
                    {"item_id": case["item_id"], "quantity": 4, "unit": "pcs"},
                ]},
            )
    finally:
        event.remove(Session, "after_commit", count_commit)

    assert response.status_code == 201, response.text
    result = response.json()
    assert result["production_order_id"] == case["order_id"]
    assert result["issued"] == [{
        "item_id": case["item_id"], "item_sku": case["sku"],
        "item_name": f"Issue QA {case['sku'].split('-')[-1]}",
        "item_image_url": None, "quantity": 4.0, "unit": "pcs",
    }]
    assert len(writer_sessions) == 2 and writer_sessions[0] is writer_sessions[1]
    assert audit_sessions == [writer_sessions[0]]
    assert commits == [writer_sessions[0]]
    with sessions() as db:
        rows = [db.get(StockBatch, batch_id) for batch_id in case["batch_ids"]]
        assert [float(row.quantity) for row in rows] == [0.0, 2.0]
        movements = db.query(StockMovement).filter(
            StockMovement.reference_type == "ProductionOrder",
            StockMovement.reference_id == case["order_id"],
            StockMovement.item_id == case["item_id"],
            StockMovement.movement_type == StockMovementType.CONSUME.value,
        ).order_by(StockMovement.id).all()
        assert [(row.batch_id, float(row.quantity), row.unit, row.created_by) for row in movements] == [
            (case["batch_ids"][0], 3.0, "pcs", actor_id),
            (case["batch_ids"][1], 1.0, "pcs", actor_id),
        ]
        sewing = db.get(WorkOrder, case["sewing_id"])
        assert sewing.is_blocked is False and sewing.block_reason is None
        plan = stock_service.accessory_issue_plan(db, case["order_id"])
        assert plan["is_complete"] is True
        assert plan["summary"]["remaining_quantity"] == 0
        audit = db.query(AuditLog).filter_by(
            action="issue_accessories", entity_type="ProductionOrder",
            entity_id=case["order_id"], user_id=actor_id,
        ).one()
        assert audit.old_value_json is None
        assert audit.new_value_json["issued"][0]["quantity"] == 4.0
        assert audit.new_value_json["notes"] is None
        assert db.query(ManualAccessoryIssue).filter_by(production_order_id=case["order_id"]).count() == 0
        assert db.query(Notification).filter_by(user_id=actor_id).count() == 0
        assert db.query(IdempotencyRecord).filter(IdempotencyRecord.key.like("accessory-issue-%")).count() == 0
    chain(sessions)


def test_pg_route_manual_issue_records_without_stock_or_movement(customer_pg_sessions, sewing_case):
    sessions = customer_pg_sessions
    case = _seed_accessory(sessions, sewing_case, quantities=(7,), include_cutting_output=False)
    batch_columns = tuple(StockBatch.__table__.columns)
    with sessions() as db:
        before_batches = [
            tuple(getattr(db.get(StockBatch, batch_id), column.name) for column in batch_columns)
            for batch_id in case["batch_ids"]
        ]
    with _client_for(sessions, case["actor_id"]) as client:
        response = client.post(
            "/api/inventory/accessory-issues",
            json={"production_order_id": case["order_id"], "lines": [{
                "item_id": case["item_id"], "quantity": 1, "unit": "pcs", "manual": True,
            }]},
        )
    assert response.status_code == 201, response.text
    assert response.json()["issued"][0]["item_id"] == case["item_id"]
    with sessions() as db:
        rows = db.query(ManualAccessoryIssue).filter_by(
            production_order_id=case["order_id"], created_by=case["actor_id"],
        ).all()
        assert len(rows) == 1
        linked = rows[0]
        assert linked.item_id == case["item_id"]
        assert (linked.item_sku, linked.item_name, float(linked.quantity), linked.unit) == (
            case["sku"], f"Issue QA {case['sku'].split('-')[-1]}", 1.0, "pcs",
        )
        after_batches = [
            tuple(getattr(db.get(StockBatch, batch_id), column.name) for column in batch_columns)
            for batch_id in case["batch_ids"]
        ]
        assert after_batches == before_batches
        assert db.query(StockMovement).filter_by(
            reference_type="ProductionOrder", reference_id=case["order_id"],
        ).count() == 0
        assert db.query(StockMovement).filter_by(item_id=case["item_id"]).count() == 0
        assert db.query(AuditLog).filter_by(
            action="issue_accessories", entity_type="ProductionOrder",
            entity_id=case["order_id"], user_id=case["actor_id"],
        ).count() == 1

    # An unlinked manual line is accepted even when the catalog item has no stock row.
    with sessions.begin() as db:
        for batch_id in case["batch_ids"]:
            db.delete(db.get(StockBatch, batch_id))
    with _client_for(sessions, case["actor_id"]) as client:
        response = client.post(
            "/api/inventory/accessory-issues",
            json={"production_order_id": case["order_id"], "lines": [{
                "item_id": 0, "item_sku": "OPS-CABLE", "item_name": "Operator cable",
                "quantity": 2.5, "unit": "pcs", "manual": True,
            }]},
        )
    assert response.status_code == 201, response.text
    assert response.json()["issued"][0]["item_id"] == 0
    with sessions() as db:
        rows = db.query(ManualAccessoryIssue).filter_by(
            production_order_id=case["order_id"], created_by=case["actor_id"],
        ).all()
        assert len(rows) == 2
        unlinked = next(row for row in rows if row.item_id is None)
        assert (unlinked.item_sku, unlinked.item_name, float(unlinked.quantity), unlinked.unit) == (
            "OPS-CABLE", "Operator cable", 2.5, "pcs",
        )
        assert db.query(StockBatch).filter_by(item_id=case["item_id"]).count() == 0
        assert db.query(StockMovement).filter_by(item_id=case["item_id"]).count() == 0
        assert db.query(AuditLog).filter_by(
            action="issue_accessories", entity_type="ProductionOrder",
            entity_id=case["order_id"], user_id=case["actor_id"],
        ).count() == 2
    chain(sessions)


@pytest.mark.parametrize("permissions", [["inventory.view"], ["*", "inventory.materials_only"]])
def test_pg_route_permission_denials_leave_business_and_audit_rows_unchanged(
    customer_pg_sessions, sewing_case, permissions,
):
    sessions = customer_pg_sessions
    case = _seed_accessory(sessions, sewing_case, quantities=(6,), required_quantity=4)
    with sessions.begin() as db:
        user = db.get(User, case["actor_id"])
        user.extra_permissions = permissions
    with sessions() as db:
        before = (
            float(db.get(StockBatch, case["batch_ids"][0]).quantity),
            db.query(StockMovement).filter_by(item_id=case["item_id"]).count(),
            db.query(ManualAccessoryIssue).filter_by(production_order_id=case["order_id"]).count(),
            db.query(AuditLog).filter_by(entity_type="ProductionOrder", entity_id=case["order_id"]).count(),
        )
    with _client_for(sessions, case["actor_id"]) as client:
        response = client.post(
            "/api/inventory/accessory-issues",
            json={"production_order_id": case["order_id"], "lines": [{
                "item_id": case["item_id"], "quantity": 1, "unit": "pcs",
            }]},
        )
    assert response.status_code == 403, response.text
    with sessions() as db:
        after = (
            float(db.get(StockBatch, case["batch_ids"][0]).quantity),
            db.query(StockMovement).filter_by(item_id=case["item_id"]).count(),
            db.query(ManualAccessoryIssue).filter_by(production_order_id=case["order_id"]).count(),
            db.query(AuditLog).filter_by(entity_type="ProductionOrder", entity_id=case["order_id"]).count(),
        )
    assert after == before


def test_pg_repeated_manual_issue_posts_keep_existing_no_idempotency_behavior(
    customer_pg_sessions, sewing_case,
):
    sessions = customer_pg_sessions
    case = _seed_accessory(sessions, sewing_case, quantities=(), include_cutting_output=False)
    request = {"production_order_id": case["order_id"], "lines": [{
        "item_id": 0, "item_sku": "REPEAT-CABLE", "item_name": "Repeat cable",
        "quantity": 1, "unit": "pcs", "manual": True,
    }]}
    with _client_for(sessions, case["actor_id"]) as client:
        first = client.post("/api/inventory/accessory-issues", json=request)
        second = client.post("/api/inventory/accessory-issues", json=request)
    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()
    with sessions() as db:
        rows = db.query(ManualAccessoryIssue).filter_by(
            production_order_id=case["order_id"], item_sku="REPEAT-CABLE",
        ).order_by(ManualAccessoryIssue.id).all()
        assert len(rows) == 2 and rows[0].id != rows[1].id
        assert db.query(StockMovement).filter_by(
            reference_type="ProductionOrder", reference_id=case["order_id"],
        ).count() == 0
        assert db.query(AuditLog).filter_by(
            action="issue_accessories", entity_type="ProductionOrder",
            entity_id=case["order_id"], user_id=case["actor_id"],
        ).count() == 2
        assert db.query(IdempotencyRecord).filter(
            IdempotencyRecord.key.like("accessory-issue-%"),
        ).count() == 0
    chain(sessions)


def test_pg_duplicate_stock_lines_keep_current_preloop_bom_limit_check(
    customer_pg_sessions, sewing_case,
):
    sessions = customer_pg_sessions
    case = _seed_accessory(sessions, sewing_case, quantities=(8,), required_quantity=4)
    with _client_for(sessions, case["actor_id"]) as client:
        response = client.post(
            "/api/inventory/accessory-issues",
            json={"production_order_id": case["order_id"], "lines": [
                {"item_id": case["item_id"], "quantity": 3, "unit": "pcs"},
                {"item_id": case["item_id"], "quantity": 3, "unit": "pcs"},
            ]},
        )
    assert response.status_code == 201, response.text
    assert [line["quantity"] for line in response.json()["issued"]] == [3.0, 3.0]
    with sessions() as db:
        batch = db.get(StockBatch, case["batch_ids"][0])
        assert float(batch.quantity) == 2.0
        movements = db.query(StockMovement).filter_by(
            item_id=case["item_id"], batch_id=batch.id,
            reference_type="ProductionOrder", reference_id=case["order_id"],
            movement_type=StockMovementType.CONSUME.value,
        ).all()
        assert len(movements) == 2 and sum(float(row.quantity) for row in movements) == 6.0
        plan = stock_service.accessory_issue_plan(db, case["order_id"])
        assert plan["rows"][0]["issued_quantity"] == 6.0
        assert plan["rows"][0]["remaining_quantity"] == 0
    chain(sessions)


@pytest.mark.parametrize("failure", ["wrong_unit", "over_remaining", "insufficient", "manual_name"])
def test_pg_route_refusals_leave_issue_rows_stock_gate_and_audit_unchanged(
    customer_pg_sessions, sewing_case, failure,
):
    sessions = customer_pg_sessions
    case = _seed_accessory(sessions, sewing_case, quantities=(2,), required_quantity=4)
    if failure == "manual_name":
        lines = [{"item_id": 0, "quantity": 1, "manual": True}]
        expected_status = 400
        expected_detail = "Manual accessory name is required"
    elif failure == "wrong_unit":
        lines = [{"item_id": case["item_id"], "quantity": 1, "unit": "roll"}]
        expected_status = 409
        expected_detail = "Accessory issue unit must match the item unit"
    elif failure == "over_remaining":
        lines = [{"item_id": case["item_id"], "quantity": 5, "unit": "pcs"}]
        expected_status = 409
        expected_detail = f"Issue quantity for {case['sku']} exceeds remaining accessory requirement"
    else:
        lines = [{"item_id": case["item_id"], "quantity": 3, "unit": "pcs"}]
        expected_status = 409
        expected_detail = f"Insufficient available stock for {case['sku']}: available 2, requested 3"
    with sessions() as db:
        before_batches = [(row.id, float(row.quantity)) for row in db.query(StockBatch).filter_by(item_id=case["item_id"]).order_by(StockBatch.id)]
        before_movements = db.query(StockMovement).filter_by(item_id=case["item_id"]).count()
        before_manual = db.query(ManualAccessoryIssue).filter_by(production_order_id=case["order_id"]).count()
        before_audit = db.query(AuditLog).filter_by(entity_type="ProductionOrder", entity_id=case["order_id"]).count()
        before_gate = db.get(WorkOrder, case["sewing_id"]).is_blocked
    with _client_for(sessions, case["actor_id"]) as client:
        response = client.post(
            "/api/inventory/accessory-issues",
            json={"production_order_id": case["order_id"], "lines": lines},
        )
    assert response.status_code == expected_status, response.text
    assert response.json()["detail"] == expected_detail
    with sessions() as db:
        assert [(row.id, float(row.quantity)) for row in db.query(StockBatch).filter_by(item_id=case["item_id"]).order_by(StockBatch.id)] == before_batches
        assert db.query(StockMovement).filter_by(item_id=case["item_id"]).count() == before_movements
        assert db.query(ManualAccessoryIssue).filter_by(production_order_id=case["order_id"]).count() == before_manual
        assert db.query(AuditLog).filter_by(entity_type="ProductionOrder", entity_id=case["order_id"]).count() == before_audit
        assert db.get(WorkOrder, case["sewing_id"]).is_blocked is before_gate


@pytest.mark.parametrize("failure_point", ["after_audit_flush", "audit_finalize", "before_commit"])
def test_pg_issue_failure_rolls_back_and_retries_on_same_session(
    customer_pg_sessions, sewing_case, monkeypatch, failure_point,
):
    sessions = customer_pg_sessions
    case = _seed_accessory(
        sessions, sewing_case, quantities=(12,), required_quantity=10, initialize_gate=False,
    )
    payload = _payload(case, [
        {"item_id": case["item_id"], "quantity": 3, "unit": "pcs"},
        {"item_id": 0, "item_sku": "MANUAL-1", "item_name": "Manual issue", "quantity": 1, "unit": "pcs", "manual": True},
    ])
    attempted_sessions = []
    writer_sessions = []
    original_log = stock_service.log_action
    original_hash = audit_service._audit_entry_hash
    original_manual = accessory_issue_persistence.add_manual_accessory_issue
    original_movement = stock_movement_persistence.record_stock_consumption
    failing_session = None
    injected = False
    listener_installed = False

    def observe_manual(db, **values):
        writer_sessions.append(db)
        return original_manual(db, **values)

    def observe_movement(db, **values):
        writer_sessions.append(db)
        return original_movement(db, **values)

    def observed_log(db, *args, **kwargs):
        nonlocal injected
        attempted_sessions.append(db)
        result = original_log(db, *args, **kwargs)
        if failure_point == "after_audit_flush" and not injected:
            injected = True
            raise RuntimeError("injected issue failure after audit enqueue flush")
        return result

    def fail_hash(*args, **kwargs):
        raise RuntimeError("injected issue audit finalization failure")

    def fail_before_commit(session):
        if session is failing_session:
            raise RuntimeError("injected issue before-commit failure")

    with sessions() as db:
        failing_session = db
        actor = db.get(User, case["actor_id"])
        monkeypatch.setattr(stock_service, "log_action", observed_log)
        monkeypatch.setattr(accessory_issue_persistence, "add_manual_accessory_issue", observe_manual)
        monkeypatch.setattr(stock_movement_persistence, "record_stock_consumption", observe_movement)
        if failure_point == "audit_finalize":
            monkeypatch.setattr(audit_service, "_audit_entry_hash", fail_hash)
        elif failure_point == "before_commit":
            event.listen(Session, "before_commit", fail_before_commit)
            listener_installed = True
        try:
            with pytest.raises(RuntimeError, match="injected issue"):
                stock_service.issue_accessories(db, payload, actor)
            assert db.is_active
            assert attempted_sessions == [db]
            db.rollback()
            if failure_point == "before_commit":
                event.remove(Session, "before_commit", fail_before_commit)
                listener_installed = False
            if failure_point == "audit_finalize":
                monkeypatch.setattr(audit_service, "_audit_entry_hash", original_hash)

            with sessions() as fresh:
                assert [float(row.quantity) for row in fresh.query(StockBatch).filter_by(item_id=case["item_id"]).order_by(StockBatch.id)] == [12.0]
                assert fresh.query(StockMovement).filter_by(item_id=case["item_id"]).count() == 0
                assert fresh.query(ManualAccessoryIssue).filter_by(production_order_id=case["order_id"]).count() == 0
                assert fresh.query(AuditLog).filter_by(action="issue_accessories", entity_id=case["order_id"]).count() == 0
                assert fresh.get(WorkOrder, case["sewing_id"]).is_blocked is False

            actor = db.get(User, case["actor_id"])
            retried = stock_service.issue_accessories(db, payload, actor)
            assert retried.production_order_id == case["order_id"]
            assert len(retried.issued) == 2
            assert attempted_sessions == [db, db]
            assert writer_sessions and all(session is db for session in writer_sessions)
        finally:
            if listener_installed:
                event.remove(Session, "before_commit", fail_before_commit)
            if failure_point == "audit_finalize":
                monkeypatch.setattr(audit_service, "_audit_entry_hash", original_hash)

    with sessions() as db:
        assert float(db.query(StockBatch).filter_by(id=case["batch_ids"][0]).one().quantity) == 9.0
        assert db.query(StockMovement).filter_by(item_id=case["item_id"]).count() == 1
        assert db.query(ManualAccessoryIssue).filter_by(production_order_id=case["order_id"]).count() == 1
        assert db.query(AuditLog).filter_by(
            action="issue_accessories", entity_type="ProductionOrder",
            entity_id=case["order_id"], user_id=case["actor_id"],
        ).count() == 1
        sewing = db.get(WorkOrder, case["sewing_id"])
        assert sewing.is_blocked is True
        assert sewing.block_reason == ACCESSORY_SEWING_BLOCK_REASON
    chain(sessions)


def _blocking_chain_to_holder(
    pid: int,
    holder_pid: int,
    graph: dict[int, tuple[str | None, tuple[int, ...]]],
    visited: frozenset[int] = frozenset(),
) -> list[int] | None:
    if pid == holder_pid:
        return [holder_pid]
    if pid in visited:
        return None
    sample = graph.get(pid)
    if sample is None or sample[0] != "Lock":
        return None
    for blocker in sample[1]:
        chain_to_holder = _blocking_chain_to_holder(
            blocker, holder_pid, graph, visited | {pid},
        )
        if chain_to_holder is not None:
            return [pid, *chain_to_holder]
    return None


def test_pg_issue_batch_lock_prevents_physical_oversell_with_observed_blocker(
    customer_pg_sessions, sewing_case, monkeypatch, record_property,
):
    sessions = customer_pg_sessions
    case = _seed_accessory(sessions, sewing_case, quantities=(4,), required_quantity=10)
    workers_ready = Event()
    ready_at: list[float] = []

    def record_rendezvous():
        if not workers_ready.is_set():
            ready_at.append(monotonic())
            workers_ready.set()

    barrier = Barrier(2, action=record_rendezvous)
    worker_pids: dict[int, int] = {}
    holder = sessions()
    holder_pid = int(holder.execute(text("SELECT pg_backend_pid()")).scalar_one())
    holder.execute(text("SELECT id FROM stock_batches WHERE id = :id FOR UPDATE"), {"id": case["batch_ids"][0]}).one()
    original_available = stock_service.available_stock_for_item

    def barrier_after_available(db, item_id):
        available = original_available(db, item_id)
        if int(item_id) == case["item_id"]:
            barrier.wait(timeout=8)
        return available

    monkeypatch.setattr(stock_service, "available_stock_for_item", barrier_after_available)

    def worker(index: int):
        with sessions() as db:
            actor = db.get(User, case["actor_id"])
            worker_pids[index] = int(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
            try:
                result = stock_service.issue_accessories(
                    db,
                    _payload(case, [{"item_id": case["item_id"], "quantity": 3, "unit": "pcs"}]),
                    actor,
                )
                return ("ok", result.production_order_id)
            except HTTPException as error:
                db.rollback()
                return ("http", error.status_code)

    executor = ThreadPoolExecutor(max_workers=2)
    futures = [executor.submit(worker, index) for index in range(2)]
    saw_waits = False
    rendezvous_ok = False
    holder_relation_lock = False
    last_graph: dict[int, tuple[str | None, tuple[int, ...]]] = {}
    observed_chains: dict[int, list[int]] = {}
    try:
        rendezvous_ok = workers_ready.wait(timeout=8)
        deadline = ready_at[0] + 5 if rendezvous_ok else monotonic()
        while monotonic() < deadline:
            if len(worker_pids) == 2:
                with sessions() as observer:
                    waits = observer.execute(text(
                        "SELECT pid, wait_event_type, pg_blocking_pids(pid) "
                        "FROM pg_stat_activity "
                        "WHERE datname = current_database() AND state = 'active'"
                    )).all()
                    holder_relation_lock = bool(observer.execute(text(
                        "SELECT EXISTS (SELECT 1 FROM pg_locks "
                        "WHERE pid = :holder AND relation = 'stock_batches'::regclass "
                        "AND mode = 'RowShareLock' AND granted)"
                    ), {"holder": holder_pid}).scalar_one())
                last_graph = {
                    int(pid): (wait_type, tuple(int(value) for value in blockers))
                    for pid, wait_type, blockers in waits
                }
                observed_chains = {}
                for pid in worker_pids.values():
                    lock_chain = _blocking_chain_to_holder(pid, holder_pid, last_graph)
                    if lock_chain is not None:
                        observed_chains[pid] = lock_chain
                if (holder_relation_lock
                        and len(set(worker_pids.values())) == 2
                        and holder_pid not in worker_pids.values()
                        and set(observed_chains) == set(worker_pids.values())):
                    saw_waits = True
                    break
            sleep(0.02)
    finally:
        try:
            holder.rollback()
        finally:
            holder.close()
            try:
                outcomes = [future.result(timeout=30) for future in futures]
            finally:
                executor.shutdown(wait=True, cancel_futures=False)

    record_property("accessory_issue_batch_lock_witness", {
        "holder_pid": holder_pid,
        "holder_locked_batch_id": case["batch_ids"][0],
        "holder_stock_batches_row_share_lock_observed": holder_relation_lock,
        "worker_pids": sorted(worker_pids.values()),
        "workers_reached_availability_barrier": rendezvous_ok,
        "both_workers_observed_blocked_by_holder": saw_waits,
        "worker_to_exact_holder_chains": observed_chains,
        "last_wait_graph": {
            pid: {"wait_event_type": value[0], "blockers": list(value[1])}
            for pid, value in last_graph.items()
        },
        "outcomes": outcomes,
        "rendezvous_timeout_seconds": 8,
        "observer_window_after_rendezvous_seconds": 5,
    })
    assert rendezvous_ok, f"workers did not reach the availability barrier: {worker_pids}"
    assert saw_waits, (
        f"both worker lock chains must reach exact batch holder {holder_pid}; "
        f"workers={worker_pids}, graph={last_graph}, chains={observed_chains}, "
        f"holder_relation_lock={holder_relation_lock}"
    )
    assert sorted(outcome[0] for outcome in outcomes) == ["http", "ok"]
    assert next(outcome[1] for outcome in outcomes if outcome[0] == "http") == 409
    with sessions() as db:
        batch = db.get(StockBatch, case["batch_ids"][0])
        assert float(batch.quantity) == 1.0
        movements = db.query(StockMovement).filter_by(
            item_id=case["item_id"], batch_id=batch.id,
            reference_type="ProductionOrder", reference_id=case["order_id"],
            movement_type=StockMovementType.CONSUME.value,
        ).all()
        assert len(movements) == 1 and float(movements[0].quantity) == 3.0
        assert db.query(AuditLog).filter_by(
            action="issue_accessories", entity_type="ProductionOrder",
            entity_id=case["order_id"],
        ).count() == 1
    chain(sessions)
