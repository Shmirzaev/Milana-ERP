"""Department draft operations; explicit submission/approval owns publication."""
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.libs.dto.planning.price_calculation_request_input import PriceCalculationCreateIn
from app.libs.dto.planning.price_calculation_request_update import PriceCalculationAccessoriesIn, PriceCalculationCuttingIn, PriceCalculationFinanceIn, PriceCalculationPurchasingIn
from app.libs.enums.planning import PriceContributionTeam, PriceRequestQueue
from app.libs.enums.catalog import CatalogScope
from app.models import price_calculation_service as pricing
from app.models.audit_service import log_action
from app.models.planning import variant_pricing_service as workflow
from app.models.planning.price_workflow_calculation import amount, number
from app.schemas import User
from app.schemas.planning.price_calculation_persistence import apply_finance_contribution, apply_workflow_fields


def load_price_request(db, request_id):
    request = db.query(workflow.PriceCalculationRequest).options(*pricing.price_request_load_options()).filter_by(id=request_id).first()
    if request is None:
        raise HTTPException(404, "Price calculation request not found")
    return request


def list_price_requests(db, current, limit, before_id, queue=PriceRequestQueue.ALL, team=None, q="", catalog_scope=CatalogScope.STANDARD):
    return workflow.list_requests(db, current, limit, before_id, queue, team, q, catalog_scope)


def create_price_request(db: Session, payload: PriceCalculationCreateIn, current: User):
    return workflow.create_request(db, payload, current)


def update_cutting_details(db: Session, request_id: int, payload: PriceCalculationCuttingIn, current: User):
    if not pricing.is_cutting_pricing_user(current):
        raise HTTPException(403, "Cutting price calculation access required")
    request = workflow.locked_request(db, request_id, current, payload.expected_revision)
    workflow.require_editable(request)
    # Exact passport identity is authoritative. The old manual fallback remains
    # for requests that genuinely have no passport, never for a mismatched row.
    kroy = payload.kroy_no.casefold()
    passport = workflow.passport_query(db, request.model_id, request.model.code, current).filter(
        func.lower(workflow.CuttingPassport.passport_no) == kroy).order_by(workflow.CuttingPassport.id.desc()).first()
    if passport is None and db.query(workflow.CuttingPassport.id).filter(func.lower(workflow.CuttingPassport.passport_no) == kroy).first():
        raise HTTPException(409, "Select a passport for this exact variant and factory")
    if passport:
        workflow.snapshot_passport(db, request, passport)
    else:
        apply_workflow_fields(db, request, cutting_passport_id=None,
            **payload.model_dump(exclude={"expected_revision"}))
        width, length, gsm = map(amount, (request.fabric_width_m, request.lay_length_m, request.gramage))
        count = request.size_count
        quantity = width * length * gsm / count if all(value is not None and value > 0 for value in (width, length, gsm)) and count else None
        binding = amount(request.binding_kg_per_piece) or Decimal(0)
        rows = [{"key": "manual", "name": "Fabric", "unit": "kg", "consumption": number(quantity, "0.000001"), "rate": request.fabric_price and float(request.fabric_price)}]
        if binding > 0:
            rows.append({"key": "manual:binding", "name": "Binding", "unit": "kg", "consumption": number(binding, "0.000001"), "rate": request.fabric_price and float(request.fabric_price)})
        corrected = {"correction_team": None, "correction_reason": None} if request.correction_team == PriceContributionTeam.CUTTING and rows != request.materials_json else {}
        apply_workflow_fields(db, request, **corrected, materials_json=rows, passport_snapshot_json={"has_print": False, "manual": True},
            purchasing_submitted_at=None, accessories_submitted_at=None, workflow_state="collecting")
    workflow.finish_draft(db, request)
    log_action(db, current, "save_cutting_price_draft", "PriceCalculationRequest", request.id, new_value={"kroy_no": payload.kroy_no})
    db.commit()
    return workflow.serialize(request, current)


def update_finance_details(db: Session, request_id: int, payload: PriceCalculationFinanceIn, current: User):
    if not pricing.is_finance_pricing_user(current):
        raise HTTPException(403, "Finance access required")
    request = workflow.locked_request(db, request_id, current, payload.expected_revision)
    workflow.require_editable(request)
    changes = payload.model_dump(exclude_unset=True, exclude={"expected_revision", "cost_price_uzs"})
    apply_finance_contribution(db, request, changes, updated_by_id=current.id)
    workflow.finish_draft(db, request)
    log_action(db, current, "save_finance_price_draft", "PriceCalculationRequest", request.id, new_value=changes)
    db.commit()
    return workflow.serialize(request, current)


def update_purchasing_details(db: Session, request_id: int, payload: PriceCalculationPurchasingIn, current: User):
    if not pricing.is_price_purchaser(current):
        raise HTTPException(403, "Purchasing price calculation access required")
    request = workflow.locked_request(db, request_id, current, payload.expected_revision)
    workflow.require_editable(request, PriceContributionTeam.PURCHASING)
    values = payload.model_dump(exclude_unset=True, exclude={"expected_revision", "materials"})
    rates = {row.key: row.rate for row in payload.materials} if payload.materials is not None else None
    rows = request.materials_json or []
    if rates is not None:
        keys = {row["key"] for row in rows}
        if len(rates) != len(payload.materials) or set(rates) != keys:
            raise HTTPException(409, "Fabric rows changed; refresh and price every material")
        rows = [{**row, "rate": rates[row["key"]]} for row in rows]
    elif "fabric_price" in payload.model_fields_set:
        # The operator supplies one rate for all passport fabric/binding rows.
        # Keep each recorded consumption and the existing costing formula.
        rows = [{**row, "rate": payload.fabric_price} for row in rows]
    apply_workflow_fields(db, request, **values, materials_json=rows, purchasing_updated_by_id=current.id,
        revision=request.revision + 1)
    log_action(db, current, "save_purchasing_price_draft", "PriceCalculationRequest", request.id,
        new_value={**values, "materials": rows})
    db.commit()
    return workflow.serialize(request, current)


def update_accessories(db: Session, request_id: int, payload: PriceCalculationAccessoriesIn, current: User):
    if not pricing.is_accessory_pricing_user(current):
        raise HTTPException(403, "Accessory team access required")
    request = workflow.locked_request(db, request_id, current, payload.expected_revision)
    workflow.require_editable(request, PriceContributionTeam.ACCESSORIES)
    rows = [{"name": row.name, "price": row.price} for row in payload.accessories if row.name or row.price is not None]
    reason = payload.no_accessories_reason.strip() if payload.no_accessories_reason else None
    if reason and (len(reason) < 3 or rows):
        raise HTTPException(422, "No-accessories reason requires an empty accessory list")
    apply_workflow_fields(db, request, accessories_json=rows, no_accessories_reason=reason,
        accessories_updated_by_id=current.id, revision=request.revision + 1)
    log_action(db, current, "save_accessory_price_draft", "PriceCalculationRequest", request.id,
        new_value={"accessories": rows, "no_accessories_reason": reason})
    db.commit()
    return workflow.serialize(request, current)
