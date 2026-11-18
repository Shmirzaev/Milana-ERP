"""Query growth and persisted behavior for accessory save and approval.

These tests use the disposable PostgreSQL fixture so row-lock semantics are real.
"""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import event

from app.libs.dto.inventory.eco_accessory_input import EcoAccessoryDecisionIn, EcoAccessoryPlanIn
from app.libs.enums.eco_accessories import EcoAccessoryStatus
from app.models.inventory import eco_accessory_service as service
from app.schemas import BrandedPlanningOrder, Department, Item, Model, ProductionOrder, WorkOrder
from app.schemas.inventory.eco_inventory import EcoMaterialBatch
from app.schemas.inventory.eco_accessory import EcoAccessoryAllocation, EcoAccessoryPlan, EcoAccessoryRequirement
from app.schemas.inventory import eco_accessory_persistence as writes
from app.models.factory_scope_service import bind_session_factory
from app.tests.test_eco_inventory_postgres import actor, accessory_case, pg_case as pg_case


def _count_reads(db, operation):
    """Capture every SELECT, including persistence and output reads."""
    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        sql = " ".join(statement.lower().split())
        if sql.startswith("select "):
            statements.append(sql)

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", capture)
    try:
        result = operation()
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    return result, statements


def _case(sessions, user_id, size):
    item_id, _, (order_id,) = accessory_case(sessions, user_id, orders=1)
    with sessions() as db:
        user = actor(db, user_id, "ECO")
        items = [db.get(Item, item_id)]
        for index in range(1, size):
            item = Item(sku=f"PG-GROW-{index}", name="Accessory", category="accessory", unit="pcs", is_active=True)
            db.add(item)
            db.flush()
            db.add(EcoMaterialBatch(item_id=item.id, kind="accessory", batch_no=f"PG-GROW-{index}",
                unit="pcs", quantity=10, reserved_quantity=0, created_by=user_id))
            items.append(item)
        db.commit()
        ids = [item.id for item in items]
        payload = [{"item_id": value, "quantity": "2"} for value in ids]
        draft = service.save_plan(db, user, order_id, EcoAccessoryPlanIn(revision=0, lines=payload))
        return order_id, ids, payload, draft.revision


def _growth_case(sessions, user_id, size):
    with sessions() as db:
        user = actor(db, user_id, "ECO")
        # Factory scope recognizes ECO, so all growth cases share one department.
        department = db.query(Department).filter_by(code="ECO").first() or Department(code="ECO", name="Growth test")
        model = Model(code=f"GROW-MODEL-{size}", name="Growth model")
        bso = BrandedPlanningOrder(order_no=f"GROW-BSO-{size}", ordered_for_type="eco_cotton", ordered_for_name="ECO")
        db.add_all([department, model, bso]); db.flush()
        order = ProductionOrder(production_no=f"GROW-PO-{size}", production_type="branded_stock",
            planning_order_id=bso.id, model_id=model.id, planned_quantity=10, status="cutting")
        db.add(order); db.flush()
        db.add(WorkOrder(production_order_id=order.id, department_id=department.id, operation="sewing",
            planned_input_qty=10, planned_output_qty=10))
        ids = []
        for index in range(size):
            item = Item(sku=f"GROW-{size}-{index}", name="Accessory", category="accessory", unit="pcs", is_active=True)
            db.add(item); db.flush()
            db.add(EcoMaterialBatch(item_id=item.id, kind="accessory", batch_no=f"GROW-{size}-{index}",
                unit="pcs", quantity=10, reserved_quantity=0, created_by=user_id))
            ids.append(item.id)
        db.commit()
        order_id = order.id
        lines = [{"item_id": item_id, "quantity": "2"} for item_id in ids]
        draft = service.save_plan(db, user, order_id, EcoAccessoryPlanIn(revision=0, lines=lines))
        return order_id, ids, lines, draft.revision


def test_save_and_approve_whole_operation_select_growth(pg_case):
    sessions, (user_id, _) = pg_case
    counts = []
    captured = []
    for size in (1, 10, 50):
        order_id, ids, lines, revision = _growth_case(sessions, user_id, size)
        with sessions() as db:
            user = actor(db, user_id, "ECO")
            saved, save_sql = _count_reads(db, lambda: service.save_plan(db, user, order_id,
                EcoAccessoryPlanIn(revision=revision, lines=lines, notes="revised")))
            assert saved.revision == revision + 1 and saved.notes == "revised"
            assert [line.item_id for line in saved.lines] == ids
            assert all(line.quantity == Decimal("2") and line.unit == "pcs" for line in saved.lines)
            pending = service.submit_plan(db, user, order_id, EcoAccessoryDecisionIn(revision=saved.revision))
        with sessions() as db:
            user = actor(db, user_id, "ECO")
            approved, approve_sql = _count_reads(db, lambda: service.approve_plan(db, user, order_id,
                EcoAccessoryDecisionIn(revision=pending.revision)))
            assert approved.status == EcoAccessoryStatus.APPROVED
            assert approved.revision == pending.revision + 1
            assert [line.item_id for line in approved.lines] == ids
            assert all(sum(a.quantity for a in line.allocations) == Decimal("2") for line in approved.lines)
        with sessions() as db:
            batches = db.query(EcoMaterialBatch).filter(EcoMaterialBatch.item_id.in_(ids)).all()
            assert len(batches) == size and all(batch.reserved_quantity == Decimal("2") for batch in batches)
        counts.append((len(save_sql), len(approve_sql)))
        captured.append((save_sql, approve_sql))
    assert counts[1:] == [counts[0], counts[0]], f"SELECT counts {counts}; SQL: {captured}"


def test_save_refuses_reduction_below_issued_and_approval_shortage_rolls_back(pg_case):
    sessions, (user_id, _) = pg_case
    order_id, ids, lines, revision = _case(sessions, user_id, 2)
    with sessions() as db:
        user = actor(db, user_id, "ECO")
        pending = service.submit_plan(db, user, order_id, EcoAccessoryDecisionIn(revision=revision))
        approved = service.approve_plan(db, user, order_id, EcoAccessoryDecisionIn(revision=pending.revision))
        from app.libs.dto.inventory.eco_accessory_input import EcoAccessoryIssueIn
        issued = service.issue_plan(db, user, order_id, EcoAccessoryIssueIn(revision=approved.revision,
            lines=[{"allocation_id": approved.lines[0].allocations[0].id, "quantity": "1"}]), "growth-issue")
        draft = service.reopen_plan(db, user, order_id, EcoAccessoryDecisionIn(revision=issued.revision))
        with pytest.raises(HTTPException, match="issueExceeded"):
            service.save_plan(db, user, order_id, EcoAccessoryPlanIn(revision=draft.revision,
                lines=[{"item_id": ids[1], "quantity": "2"}]))
        db.rollback()
        plan = db.query(EcoAccessoryPlan).filter_by(production_order_id=order_id).one()
        assert plan.revision == draft.revision and plan.status == EcoAccessoryStatus.DRAFT
        assert db.query(EcoAccessoryAllocation).one().issued_quantity == Decimal("1")
        # The first requirement is satisfiable, while the second is not.
        pending = service.submit_plan(db, user, order_id, EcoAccessoryDecisionIn(revision=draft.revision))
        batch = db.query(EcoMaterialBatch).filter_by(item_id=ids[1]).one()
        batch.quantity = 0
        db.commit()
        with pytest.raises(HTTPException, match="shortage"):
            service.approve_plan(db, user, order_id, EcoAccessoryDecisionIn(revision=pending.revision))
        db.rollback()
        assert db.query(EcoAccessoryPlan).filter_by(production_order_id=order_id).one().status == EcoAccessoryStatus.PENDING
        assert all(batch.reserved_quantity == 0 for batch in db.query(EcoMaterialBatch).all())
        assert db.query(EcoAccessoryAllocation).one().issued_quantity == Decimal("1")


def test_reapproval_increments_existing_allocation(pg_case):
    sessions, (user_id, _) = pg_case
    order_id, _, _, revision = _case(sessions, user_id, 1)
    from app.libs.dto.inventory.eco_accessory_input import EcoAccessoryIssueIn
    with sessions() as db:
        user = actor(db, user_id, "ECO")
        pending = service.submit_plan(db, user, order_id, EcoAccessoryDecisionIn(revision=revision))
        approved = service.approve_plan(db, user, order_id, EcoAccessoryDecisionIn(revision=pending.revision))
        allocation_id = approved.lines[0].allocations[0].id
        issued = service.issue_plan(db, user, order_id, EcoAccessoryIssueIn(revision=approved.revision,
            lines=[{"allocation_id": allocation_id, "quantity": "1"}]), "increment-issue")
        draft = service.reopen_plan(db, user, order_id, EcoAccessoryDecisionIn(revision=issued.revision))
        pending = service.submit_plan(db, user, order_id, EcoAccessoryDecisionIn(revision=draft.revision))
        result = service.approve_plan(db, user, order_id, EcoAccessoryDecisionIn(revision=pending.revision))
        allocation = result.lines[0].allocations[0]
        assert (allocation.id, allocation.quantity, allocation.issued_quantity) == (allocation_id, Decimal("2"), Decimal("1"))
        assert db.query(EcoAccessoryAllocation).count() == 1


def test_allocation_batch_handles_repeated_unflushed_key_and_dto_refuses_duplicates(pg_case):
    sessions, (user_id, _) = pg_case
    order_id, ids, _, _ = _case(sessions, user_id, 1)
    with pytest.raises(ValidationError):
        EcoAccessoryPlanIn(revision=1, lines=[{"item_id": ids[0], "quantity": 1}, {"item_id": ids[0], "quantity": 1}])
    with sessions() as db:
        plan = db.query(EcoAccessoryPlan).filter_by(production_order_id=order_id).one()
        req = db.query(EcoAccessoryRequirement).filter_by(plan_id=plan.id).one()
        batch = db.query(EcoMaterialBatch).filter_by(item_id=ids[0]).one()
        writes.allocate_many(db, [(req.id, batch.id, Decimal("1")), (req.id, batch.id, Decimal("2"))])
        db.flush()
        allocation = db.query(EcoAccessoryAllocation).one()
        assert allocation.quantity == Decimal("3") and allocation.issued_quantity == 0
        db.rollback()


def test_same_plan_competing_approvals_and_factory_refusal(pg_case):
    sessions, (user_id, _) = pg_case
    order_id, _, _, revision = _case(sessions, user_id, 1)
    with sessions() as db:
        user = actor(db, user_id, "ECO")
        pending = service.submit_plan(db, user, order_id, EcoAccessoryDecisionIn(revision=revision))
        bind_session_factory(user, "MIL")
        with pytest.raises(HTTPException) as denied:
            service.approve_plan(db, user, order_id, EcoAccessoryDecisionIn(revision=pending.revision))
        assert denied.value.status_code == 403
        db.rollback()
        assert db.query(EcoAccessoryAllocation).count() == 0
        assert db.query(EcoMaterialBatch).one().reserved_quantity == 0
    barrier = Barrier(2)
    def approve(_):
        with sessions() as db:
            user = actor(db, user_id, "ECO")
            barrier.wait(timeout=10)
            try:
                return service.approve_plan(db, user, order_id, EcoAccessoryDecisionIn(revision=pending.revision)).revision
            except HTTPException as error:
                db.rollback()
                assert error.status_code == 409
                return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(approve, range(2)))
    assert sorted(result for result in results if result is not None) == [pending.revision + 1]
    with sessions() as db:
        assert db.query(EcoAccessoryAllocation).count() == 1
        assert db.query(EcoMaterialBatch).one().reserved_quantity == Decimal("2")
        plan = db.query(EcoAccessoryPlan).filter_by(production_order_id=order_id).one()
        assert plan.status == EcoAccessoryStatus.APPROVED and plan.revision == pending.revision + 1
