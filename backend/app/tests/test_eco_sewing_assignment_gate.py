"""Persisted line/batch scope controls ECO approval on shared sewing work."""
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.api.routes.production import post_sewing
from app.libs.dto.inventory.eco_accessory_input import EcoAccessoryDecisionIn, EcoAccessoryIssueIn, EcoAccessoryPlanIn
from app.libs.dto.production.production import SewingRecordIn
from app.models.factory_scope_service import bind_session_factory
from app.models.idempotency_service import bind_idempotency_identity
from app.models.inventory import eco_accessory_service as service
from app.models.inventory_service import sync_sewing_accessory_block
from app.schemas import BrandedPlanningOrder, Bundle, CuttingRecord, Department, Item, Model, ProductionBatch, ProductionOrder, SewingAssignment, SewingFlow, SewingRecord, User, WorkOrder
from app.schemas.inventory.eco_accessory import EcoAccessoryPlan
from app.schemas.inventory.eco_inventory import EcoMaterialBatch, EcoMaterialMovement
from app.tests.conftest import TestSessionLocal


@pytest.fixture
def shared_order():
    with TestSessionLocal() as db:
        user = db.query(User).filter_by(email="admin@example.com").one()
        model = Model(code="ECO-ASSIGNMENT-GATE", name="Shared assignment model")
        bso = BrandedPlanningOrder(order_no="BSO-ASSIGNMENT-GATE", ordered_for_type="eco_cotton", ordered_for_name="ECO", status="open")
        db.add_all([model, bso]); db.flush()
        order = ProductionOrder(production_no="PO-ASSIGNMENT-GATE", production_type="branded_stock", model_id=model.id,
            planning_order_id=bso.id, planned_quantity=10)
        db.add(order); db.flush()
        work = WorkOrder(production_order_id=order.id, department_id=db.query(Department).filter_by(code="SEW").one().id,
            operation="sewing", status="in_progress", planned_input_qty=10, planned_output_qty=10)
        cutting = WorkOrder(production_order_id=order.id, department_id=db.query(Department).filter_by(code="CUT").one().id,
            operation="cutting", status="in_progress", planned_output_qty=10, actual_output_qty=10, passed_qty=10)
        flow = SewingFlow(factory_code="ECO", code="ECO-GATE-LINE", name="ECO gate line")
        db.add_all([work, cutting, flow]); db.flush()
        assignment = SewingAssignment(work_order_id=work.id, sewing_flow_id=flow.id, quantity=10)
        record = CuttingRecord(work_order_id=cutting.id, input_quantity=1, input_unit="kg", cut_pieces=10, passed_pieces=10)
        db.add_all([assignment, record]); db.commit()
        yield db, user, order, work, assignment, record


def output(work, assignment, *, by_name=False, batch_id=None):
    return SewingRecordIn(work_order_id=work.id, input_qty=1, sewn_qty=1, passed_qty=1,
        production_batch_id=batch_id, sewing_assignment_id=None if by_name else assignment.id,
        line_name="ECO-GATE-LINE" if by_name else None)


@pytest.mark.parametrize("by_name,with_mil_bundle", [(False, False), (True, False), (False, True)])
def test_positive_eco_assignment_output_requires_approval_before_any_write(shared_order, by_name, with_mil_bundle):
    db, user, order, work, assignment, _ = shared_order
    if with_mil_bundle:
        db.add(Bundle(bundle_no="MIL-GATE-BUNDLE", barcode="MIL-GATE-BUNDLE", production_order_id=order.id,
            model_id=order.model_id, color="black", size="M", quantity=10, sewing_factory_code="MIL", status="created"))
        db.commit()
    with pytest.raises(HTTPException, match="approvalRequired"):
        post_sewing(output(work, assignment, by_name=by_name), db, user)
    db.rollback()
    assert db.query(SewingRecord).count() == 0 and assignment.completed_qty == 0
    assert db.query(EcoAccessoryPlan).count() == 0
    assert service.is_eco_bso_order(db, order.id)


def test_inferred_gate_includes_active_eco_assignment_despite_mil_bundle(shared_order):
    db, _, order, work, _, _ = shared_order
    db.add(Bundle(bundle_no="MIL-INFER-BUNDLE", barcode="MIL-INFER-BUNDLE", production_order_id=order.id,
        model_id=order.model_id, color="black", size="M", quantity=10, sewing_factory_code="MIL", status="created"))
    db.commit()
    assert service.accessory_gate_factories(db, order.id) == {"MIL", "ECO"}
    assert not sync_sewing_accessory_block(db, order.id)["is_complete"]
    assert work.is_blocked and work.block_reason == "ecoAccessories.approvalRequired"


def test_assignment_batch_is_resolved_before_approval_scope(shared_order):
    db, user, order, work, assignment, record = shared_order
    eco = ProductionBatch(production_order_id=order.id, batch_no="ECO", planned_quantity=10)
    mil = ProductionBatch(production_order_id=order.id, batch_no="MIL", planned_quantity=10)
    db.add_all([eco, mil]); db.flush()
    assignment.production_batch_id = eco.id
    record.production_batch_id = eco.id
    db.add(Bundle(bundle_no="MIL-OTHER-BATCH", barcode="MIL-OTHER-BATCH", production_order_id=order.id,
        production_batch_id=mil.id, model_id=order.model_id, color="black", size="M", quantity=10, sewing_factory_code="MIL", status="created"))
    db.commit()
    assert service.accessory_gate_factories(db, order.id, eco.id) == {"ECO"}
    assert service.accessory_gate_factories(db, order.id, mil.id) == {"MIL"}
    with pytest.raises(HTTPException, match="approvalRequired"):
        post_sewing(output(work, assignment), db, user)  # batch deliberately omitted; assignment owns ECO batch
    db.rollback()
    assert db.query(SewingRecord).count() == 0
    with pytest.raises(HTTPException, match="different production batch"):
        post_sewing(output(work, assignment, batch_id=mil.id), db, user)
    db.rollback()
    assert db.query(SewingRecord).count() == 0


def test_foreign_assignment_is_refused_before_factory_gate(shared_order):
    db, user, order, work, assignment, _ = shared_order
    other = WorkOrder(production_order_id=order.id, department_id=work.department_id, operation="sewing")
    db.add(other); db.commit()
    with pytest.raises(HTTPException, match="does not belong") as failure:
        post_sewing(output(other, assignment), db, user)
    assert failure.value.status_code == 400
    db.rollback()
    assert db.query(SewingRecord).count() == 0


@pytest.mark.parametrize("status", ["cancelled", "transferred"])
def test_inactive_assignment_is_not_new_eco_ownership(shared_order, status):
    db, user, order, work, assignment, _ = shared_order
    assignment.status = status; db.commit()
    assert not service.is_eco_bso_order(db, order.id)
    assert service.accessory_gate_factories(db, order.id) == {"MIL"}
    with pytest.raises(HTTPException, match="returned or cancelled"):
        post_sewing(output(work, assignment), db, user)
    db.rollback()
    assert db.query(SewingRecord).count() == 0


@pytest.mark.parametrize("factory", ["MIL", "BST"])
def test_other_factory_assignment_keeps_its_own_gate_on_shared_work(shared_order, factory):
    db, user, order, work, _, _ = shared_order
    flow = SewingFlow(factory_code=factory, code="LEGACY-GATE-LINE", name="Other gate line")
    db.add(flow); db.flush()
    assignment = SewingAssignment(work_order_id=work.id, sewing_flow_id=flow.id, quantity=10)
    db.add(assignment); db.commit()
    # Simulate the ECO plan's own pending block on the shared work order.
    work.is_blocked = True; work.block_reason = "ecoAccessories.approvalRequired"; db.commit()
    result = post_sewing(output(work, assignment), db, user)
    assert db.get(SewingRecord, result["id"]).passed_qty == 1
    assert not work.is_blocked


def test_assigned_eco_bso_can_approve_then_record_and_issue_exactly_once(shared_order):
    db, user, order, work, assignment, _ = shared_order
    bind_session_factory(user, "ECO"); bind_idempotency_identity(db, user)
    item = Item(sku="ASSIGNMENT-BUTTON", name="Gate buttons", category="accessory", unit="pcs")
    db.add(item); db.flush()
    stock = EcoMaterialBatch(item_id=item.id, kind="accessory", batch_no="GATE-STOCK", unit="pcs", quantity=10,
        reserved_quantity=0, created_by=user.id)
    db.add(stock); db.commit()
    assert any(row.production_order_id == order.id for row in service.list_orders(db, user)["items"])
    draft = service.save_plan(db, user, order.id, EcoAccessoryPlanIn(revision=0, lines=[{"item_id": item.id, "quantity": 5}]))
    pending = service.submit_plan(db, user, order.id, EcoAccessoryDecisionIn(revision=draft.revision))
    plan = service.approve_plan(db, user, order.id, EcoAccessoryDecisionIn(revision=pending.revision))
    assert stock.quantity == 10 and stock.reserved_quantity == 5
    # Preserve existing authorization for this historical SEW work order. The
    # allocation approves handoff; physical issue is a distinct stock operation.
    bind_session_factory(user, "MIL")
    result = post_sewing(output(work, assignment), db, user)
    assert db.get(SewingRecord, result["id"]).passed_qty == 1 and stock.quantity == 10
    bind_session_factory(user, "ECO"); bind_idempotency_identity(db, user)
    payload = EcoAccessoryIssueIn(revision=plan.revision, lines=[{"allocation_id": plan.lines[0].allocations[0].id, "quantity": 5}])
    issued = service.issue_plan(db, user, order.id, payload, "assignment-gate-issue")
    assert service.issue_plan(db, user, order.id, payload, "assignment-gate-issue") == issued
    assert stock.quantity == Decimal("5") and stock.reserved_quantity == 0
    assert db.query(EcoMaterialMovement).count() == 1
