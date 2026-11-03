"""Stock-backed approval, sewing refusal, retries and isolated ECO balances."""
from decimal import Decimal
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from app.schemas import BrandedPlanningOrder, Bundle, Department, Item, Model, ProductionOrder, Role, User, WorkOrder
from app.schemas.inventory.eco_inventory import EcoMaterialBatch, EcoMaterialMovement
from app.schemas.inventory.eco_accessory import EcoAccessoryPlan, EcoAccessoryAllocation
from app.libs.dto.inventory.eco_accessory_input import EcoAccessoryPlanIn, EcoAccessoryDecisionIn, EcoAccessoryIssueIn
from app.libs.enums.eco_accessories import EcoAccessoryStatus as Status
from app.models.inventory import eco_accessory_service as service
from app.models.inventory_service import ensure_accessories_issued_for_sewing
from app.models.factory_scope_service import bind_session_factory
from app.models.idempotency_service import bind_idempotency_identity
from app.tests.conftest import TestSessionLocal


@pytest.fixture
def scenario():
    db = TestSessionLocal()
    user = db.query(User).filter_by(email="admin@example.com").one()
    bind_session_factory(user, "ECO")
    bind_idempotency_identity(db, user)
    dept = db.query(Department).filter_by(code="ECO").one()
    model = db.query(Model).first()
    item = Item(sku="APP-BUTTON", name="Buttons", category="accessory", unit="pcs", is_active=True)
    bso = BrandedPlanningOrder(order_no="BSO-APP-TEST", ordered_for_type="eco_cotton", ordered_for_name="ECO", status="open")
    db.add_all([item, bso]); db.flush()
    order = ProductionOrder(production_no="PO-APP-TEST", production_type="branded_stock", planning_order_id=bso.id,
        model_id=model.id, planned_quantity=10, status="cutting")
    db.add(order); db.flush()
    db.add(WorkOrder(production_order_id=order.id, department_id=dept.id, operation="sewing", planned_input_qty=10, planned_output_qty=10))
    batch = EcoMaterialBatch(item_id=item.id, kind="accessory", batch_no="ECO-APP-01", unit="pcs", quantity=20,
        reserved_quantity=0, created_by=user.id)
    db.add(batch); db.commit()
    yield db, user, order, item, batch
    db.close()


def pending(s, quantity="12"):
    db, user, order, item, _ = s
    draft = service.save_plan(db, user, order.id, EcoAccessoryPlanIn(revision=0, lines=[{"item_id": item.id, "quantity": quantity}]))
    return service.submit_plan(db, user, order.id, EcoAccessoryDecisionIn(revision=draft.revision))


def approved(s):
    db, user, order, _, _ = s
    plan = pending(s)
    return service.approve_plan(db, user, order.id, EcoAccessoryDecisionIn(revision=plan.revision))


def test_approval_reserves_issue_deducts_and_retry_is_exactly_once(scenario):
    db, user, order, _, batch = scenario
    with pytest.raises(HTTPException, match="approvalRequired"):
        ensure_accessories_issued_for_sewing(db, order.id)
    db.rollback()
    plan = approved(scenario)
    assert batch.quantity == Decimal("20") and batch.reserved_quantity == Decimal("12")
    assert ensure_accessories_issued_for_sewing(db, order.id)["is_complete"]
    approved_by, approved_at = plan.approved_by, plan.approved_at
    allocation = plan.lines[0].allocations[0]
    partial = EcoAccessoryIssueIn(revision=plan.revision, lines=[{"allocation_id": allocation.id, "quantity": "5"}])
    result = service.issue_plan(db, user, order.id, partial, "issue-one")
    assert result.status == Status.APPROVED
    assert batch.quantity == 15 and batch.reserved_quantity == 7
    assert service.issue_plan(db, user, order.id, partial, "issue-one") == result
    assert db.query(EcoMaterialMovement).count() == 1
    final = service.issue_plan(db, user, order.id, EcoAccessoryIssueIn(revision=result.revision,
        lines=[{"allocation_id": allocation.id, "quantity": "7"}]), "issue-two")
    assert final.status == Status.ISSUED and batch.quantity == 8 and batch.reserved_quantity == 0
    assert final.approved_by == approved_by and final.approved_at == approved_at


def test_shortage_and_repeat_approval_do_not_reserve_twice(scenario):
    db, user, order, _, batch = scenario
    plan = pending(scenario, "21")
    with pytest.raises(HTTPException, match="shortage"):
        service.approve_plan(db, user, order.id, EcoAccessoryDecisionIn(revision=plan.revision))
    db.rollback()
    assert batch.reserved_quantity == 0 and db.query(EcoAccessoryAllocation).count() == 0
    assert db.query(EcoAccessoryPlan).one().status == Status.PENDING


def test_approval_revision_and_reopen_release_reservation(scenario):
    db, user, order, _, batch = scenario
    plan = approved(scenario)
    with pytest.raises(HTTPException, match="stale"):
        service.approve_plan(db, user, order.id, EcoAccessoryDecisionIn(revision=plan.revision - 1))
    db.rollback()
    assert batch.reserved_quantity == 12
    draft = service.reopen_plan(db, user, order.id, EcoAccessoryDecisionIn(revision=plan.revision, notes="Revise quantity"))
    assert draft.status == Status.DRAFT and batch.quantity == 20 and batch.reserved_quantity == 0
    assert db.query(EcoAccessoryAllocation).count() == 0
    with pytest.raises(HTTPException, match="approvalRequired"):
        ensure_accessories_issued_for_sewing(db, order.id)


def test_changed_production_plan_requires_new_approval(scenario):
    db, _, order, _, _ = scenario
    approved(scenario)
    order.planned_quantity = 15; db.commit()
    with pytest.raises(HTTPException, match="approvalRequired"):
        ensure_accessories_issued_for_sewing(db, order.id)


def test_bso_and_factory_scope_are_required(scenario):
    db, user, order, _, _ = scenario
    bind_session_factory(user, "MIL")
    with pytest.raises(HTTPException) as err:
        service.get_plan(db, user, order.id)
    assert err.value.status_code == 403
    bind_session_factory(user, "ECO")
    order.planning_order_id = None; db.commit()
    with pytest.raises(HTTPException) as err:
        service.save_plan(db, user, order.id, EcoAccessoryPlanIn(revision=0, lines=[]))
    assert err.value.status_code == 404


def test_distinct_approval_permission_at_service_boundary(scenario):
    db, _, order, _, _ = scenario
    plan = pending(scenario)
    role = Role(name="ECO requester test", permissions=["eco_accessories.manage"])
    db.add(role); db.flush()
    user = User(email="eco-requester-test@example.com", name="Requester", password_hash="unused", role_id=role.id, factory_code="ECO")
    db.add(user); db.commit()
    with pytest.raises(HTTPException) as err:
        service.approve_plan(db, user, order.id, EcoAccessoryDecisionIn(revision=plan.revision))
    assert err.value.status_code == 403


def test_empty_requirement_requires_explicit_approval(scenario):
    db, user, order, _, _ = scenario
    draft = service.save_plan(db, user, order.id, EcoAccessoryPlanIn(revision=0, lines=[]))
    pending_plan = service.submit_plan(db, user, order.id, EcoAccessoryDecisionIn(revision=draft.revision))
    with pytest.raises(HTTPException, match="approvalRequired"):
        ensure_accessories_issued_for_sewing(db, order.id)
    db.rollback()
    service.approve_plan(db, user, order.id, EcoAccessoryDecisionIn(revision=pending_plan.revision))
    assert ensure_accessories_issued_for_sewing(db, order.id)["is_complete"]


def test_foreign_allocation_and_overissue_never_deduct_stock(scenario):
    db, user, order, _, batch = scenario
    plan = approved(scenario)
    for allocation_id, qty in [(999999, "1"), (plan.lines[0].allocations[0].id, "13")]:
        with pytest.raises(HTTPException, match="issueExceeded"):
            service.issue_plan(db, user, order.id, EcoAccessoryIssueIn(revision=plan.revision,
                lines=[{"allocation_id": allocation_id, "quantity": qty}]), f"bad-{allocation_id}")
        db.rollback()
    assert batch.quantity == 20 and batch.reserved_quantity == 12
    assert db.query(EcoMaterialMovement).count() == 0


def test_sent_bundle_freezes_edit_and_historical_missing_plan_is_preserved(scenario):
    db, user, order, _, _ = scenario
    bundle = Bundle(bundle_no="ECO-APP-B", barcode="ECO-APP-B", production_order_id=order.id,
        model_id=order.model_id, color="black", size="M", quantity=10, sewing_factory_code="ECO", status="sent_to_sewing")
    db.add(bundle); db.commit()
    assert service.ensure_eco_accessory_approval(db, order.id) is None
    with pytest.raises(HTTPException, match="sewingStarted"):
        service.save_plan(db, user, order.id, EcoAccessoryPlanIn(revision=0, lines=[]))


def test_issued_allocation_cannot_be_reopened(scenario):
    db, user, order, _, batch = scenario
    plan = approved(scenario)
    result = service.issue_plan(db, user, order.id, EcoAccessoryIssueIn(revision=plan.revision,
        lines=[{"allocation_id": plan.lines[0].allocations[0].id, "quantity": "1"}]), "partial")
    with pytest.raises(HTTPException, match="alreadyIssued"):
        service.reopen_plan(db, user, order.id, EcoAccessoryDecisionIn(revision=result.revision))
    db.rollback()
    assert batch.quantity == 19 and batch.reserved_quantity == 11


@pytest.mark.parametrize("quantity", ["0", "-1", "NaN", "1.00001", "10000000000"])
def test_requirement_precision_and_bounds(quantity):
    with pytest.raises(ValidationError):
        EcoAccessoryPlanIn(revision=0, lines=[{"item_id": 1, "quantity": quantity}])


def test_public_http_guards_and_order_list(scenario, client):
    from app.core.security import create_access_token
    db, user, order, item, _ = scenario
    headers = {"Authorization": f"Bearer {create_access_token(user.id, {'factory_code': 'ECO'})}"}
    result = client.get("/api/eco-accessories", headers=headers)
    assert result.status_code == 200, result.text
    assert any(row["production_order_id"] == order.id for row in result.json()["items"])
    result = client.get("/api/eco-accessories/items/options", headers=headers)
    assert result.status_code == 200 and any(row["id"] == item.id for row in result.json())
    assert client.get("/api/eco-accessories").status_code == 401
    headers = {"Authorization": f"Bearer {create_access_token(user.id, {'factory_code': 'MIL'})}"}
    assert client.get("/api/eco-accessories", headers=headers).status_code == 403
