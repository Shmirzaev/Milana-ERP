"""Writes only. Services retain policy, locks and the outer transaction."""
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy.orm import Session
from app.libs.enums.eco_accessories import EcoAccessoryStatus
from app.schemas.inventory.eco_accessory import EcoAccessoryPlan, EcoAccessoryRequirement, EcoAccessoryAllocation


def create_plan(db: Session, *, order, actor_id: int) -> EcoAccessoryPlan:
    plan = EcoAccessoryPlan(production_order_id=order.id, model_id=order.model_id,
        planning_order_id=order.planning_order_id, planned_quantity=order.planned_quantity,
        status=EcoAccessoryStatus.DRAFT.value, revision=1, notes="", created_by=actor_id)
    db.add(plan)
    db.flush()
    return plan


def replace_requirements(db: Session, *, plan: EcoAccessoryPlan, order, notes: str, lines: list[tuple[int, Decimal, str]]) -> None:
    db.query(EcoAccessoryRequirement).filter_by(plan_id=plan.id).delete(synchronize_session=False)
    for item_id, quantity, unit in lines:
        db.add(EcoAccessoryRequirement(plan_id=plan.id, item_id=item_id, quantity=quantity, unit=unit))
    plan.model_id = order.model_id
    plan.planning_order_id = order.planning_order_id
    plan.planned_quantity = order.planned_quantity
    plan.notes = notes
    plan.revision += 1
    db.flush()


def set_status(db: Session, plan: EcoAccessoryPlan, status: EcoAccessoryStatus, *, actor_id: int | None = None, notes: str = "") -> None:
    plan.status = status.value
    plan.revision += 1
    plan.approval_notes = notes
    if status == EcoAccessoryStatus.APPROVED:
        plan.approved_by = actor_id
        plan.approved_at = datetime.now(timezone.utc)
    elif status != EcoAccessoryStatus.ISSUED:
        plan.approved_by = None
        plan.approved_at = None
    db.flush()


def allocate(db: Session, requirement_id: int, batch_id: int, quantity: Decimal) -> None:
    db.add(EcoAccessoryAllocation(requirement_id=requirement_id, batch_id=batch_id, quantity=quantity, issued_quantity=0))


def issue_allocation(db: Session, allocation: EcoAccessoryAllocation, quantity: Decimal) -> None:
    allocation.issued_quantity += quantity
    db.flush()


def advance_revision(db: Session, plan: EcoAccessoryPlan) -> None:
    plan.revision += 1
    db.flush()


def delete_allocations(db: Session, requirement_ids: list[int]) -> None:
    db.query(EcoAccessoryAllocation).filter(EcoAccessoryAllocation.requirement_id.in_(requirement_ids)).delete(synchronize_session=False)
