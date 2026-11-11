"""Explicit, atomic retirement of requests outside the owner's active scope."""
from fastapi import HTTPException
from sqlalchemy.orm import lazyload

from app.libs.dto.planning.price_workflow_input import PriceRetirementTarget
from app.libs.enums.planning import PriceWorkflowState
from app.models.factory_scope_service import user_is_super_admin
from app.models.planning import variant_pricing_policy as policy, variant_pricing_service as workflow
from app.schemas import Model, PriceCalculationRequest


def _excluded(db):
    return db.query(PriceCalculationRequest).join(Model, Model.id == PriceCalculationRequest.model_id).options(
        lazyload("*")).filter(PriceCalculationRequest.active_model_id.is_not(None),
            PriceCalculationRequest.workflow_state.in_([PriceWorkflowState.COLLECTING, PriceWorkflowState.AWAITING_FINANCE]),
            ~policy.predicate())


def reconcile(db, current, targets: list[PriceRetirementTarget] | None = None, *, apply=False):
    if not current.is_active or not user_is_super_admin(current) or not workflow.can_approve(current):
        raise HTTPException(403, "An active global Finance approver is required")
    if apply:
        if targets is None or len({item.request_id for item in targets}) != len(targets):
            raise HTTPException(409, "A reviewed unique request list is required")
        model_ids = sorted({item.model_id for item in targets})
        db.query(Model).options(lazyload("*")).filter(Model.id.in_(model_ids)).order_by(Model.id).with_for_update(of=Model).populate_existing().all()
        db.query(PriceCalculationRequest).options(lazyload("*")).filter(
            PriceCalculationRequest.id.in_([item.request_id for item in targets])).order_by(
            PriceCalculationRequest.id).with_for_update(of=PriceCalculationRequest).populate_existing().all()
    requests = _excluded(db).order_by(PriceCalculationRequest.id).all()
    actual = [PriceRetirementTarget(request_id=row.id, model_id=row.model_id, expected_revision=row.revision) for row in requests]
    if apply and actual != sorted(targets, key=lambda item: item.request_id):
        raise HTTPException(409, "Excluded pricing requests changed since preview; review again")
    report = {"applied": False, "targets": [item.model_dump() for item in actual]}
    if not apply:
        db.rollback()
        return report
    for request in requests:
        workflow.retire_request(db, request, current, policy.POLICY_REASON)
    db.commit()
    db.expire_all()
    for item in actual:
        saved = db.query(PriceCalculationRequest).options(lazyload("*")).filter_by(id=item.request_id).one()
        if saved.active_model_id is not None or saved.workflow_state != PriceWorkflowState.CANCELLED or saved.revision != item.expected_revision + 1:
            raise RuntimeError("Committed retirement readback failed; inspect audit before any retry")
    return {**report, "applied": True, "readback_verified": True}
