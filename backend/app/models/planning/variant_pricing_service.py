"""Variant costing lifecycle. Never mutates orders, stock or manufacturing stages."""
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from copy import copy

from fastapi import HTTPException
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session, lazyload

from app.core.deps import user_permissions
from app.libs.enums.catalog import CatalogScope
from app.libs.enums.planning import PriceContributionTeam, PriceRequestQueue, PriceWorkflowState, PriceMaterialUnit
from app.libs.types.planning import PriceMaterialSnapshot
from app.models import price_calculation_service as pricing
from app.models.audit_service import log_action
from app.models.factory_scope_service import available_factory_codes, selected_factory_code
from app.models.passport_sizes_service import passport_order_sizes, size_count_from_range
from app.models.planning.price_workflow_calculation import amount, has_price, number, ready_for_finance, purchasing_ready, accessories_ready
from app.models.user_access_service import permission_denied
from app.schemas import CuttingPassport, Model, ProductionOrder, User, WorkOrder, Department
from app.schemas.core_persistence import add_notification_row
from app.schemas.catalog.model_price_persistence import apply_request_selling_price
from app.schemas.planning.price_calculation import PriceCalculationRequest
from app.schemas.planning.price_calculation_persistence import apply_workflow_fields, insert_workflow_request


APPROVE_PERMISSION = "price_calculation.approve"


def can_approve(user):
    granted = user_permissions(user)
    return pricing.is_finance_pricing_user(user) and not permission_denied(user, APPROVE_PERMISSION) and bool({"*", APPROVE_PERMISSION}.intersection(granted))


def require_catalog(user, scope):
    if scope == CatalogScope.USLUGA and (selected_factory_code(user) != "ECO" or not {"*", "usluga.view", "usluga.manage"}.intersection(user_permissions(user))):
        raise HTTPException(403, "Usluga pricing requires Eco Cotton and Usluga access")


def request_scope(user):
    factory = selected_factory_code(user)
    return or_(PriceCalculationRequest.factory_code == factory,
               and_(PriceCalculationRequest.factory_code.is_(None), factory == "MIL"))


def require_request_scope(user, request):
    require_catalog(user, request.model.catalog_scope)
    if (request.factory_code or "MIL") != selected_factory_code(user):
        raise HTTPException(403, "Price request belongs to another factory")


def model_lock(db, model_id):
    model = db.query(Model).options(lazyload("*")).filter(Model.id == model_id).with_for_update(of=Model).populate_existing().one_or_none()
    if model is None:
        raise HTTPException(404, "Model not found")
    return model


def locked_request(db, request_id, user, expected_revision=None):
    model_id = db.query(PriceCalculationRequest.model_id).filter_by(id=request_id).scalar()
    if model_id is None:
        raise HTTPException(404, "Price calculation request not found")
    model_lock(db, model_id)
    request = db.query(PriceCalculationRequest).options(*pricing.price_request_load_options()).filter_by(id=request_id).with_for_update(of=PriceCalculationRequest).populate_existing().one()
    require_request_scope(user, request)
    if expected_revision is not None and request.revision != expected_revision:
        raise HTTPException(409, "Pricing changed; refresh before saving or confirming")
    return request


def require_editable(request, team=None):
    if request.workflow_state in {PriceWorkflowState.LEGACY, PriceWorkflowState.APPROVED, PriceWorkflowState.CANCELLED}:
        raise HTTPException(409, "Historical pricing is read-only; open a new pricing request")
    if team == PriceContributionTeam.PURCHASING and request.purchasing_submitted_at:
        raise HTTPException(409, "Submitted Purchasing costs require Finance to return them for correction")
    if team == PriceContributionTeam.ACCESSORIES and request.accessories_submitted_at:
        raise HTTPException(409, "Submitted Accessories costs require Finance to return them for correction")


def passport_query(db, model_id, model_code, current):
    from app.models.factory_scope_service import CUTTING_DEPARTMENTS
    factory = selected_factory_code(current)
    work = db.query(WorkOrder.id).join(Department, Department.id == WorkOrder.department_id).filter(
        WorkOrder.production_order_id == ProductionOrder.id, WorkOrder.operation == "cutting",
        Department.code == CUTTING_DEPARTMENTS.get(factory)).correlate(ProductionOrder).exists()
    return db.query(CuttingPassport).outerjoin(ProductionOrder, ProductionOrder.id == CuttingPassport.production_order_id).filter(
        or_(and_(ProductionOrder.model_id == model_id, work),
            and_(CuttingPassport.production_order_id.is_(None), CuttingPassport.model_code == model_code, factory == "MIL")))


def baseline(model, reason=None):
    return {"price": str(model.selling_price) if model.selling_price is not None else None,
            "currency": model.selling_price_currency, "source": model.selling_price_source,
            "request_id": model.selling_price_request_id,
            "updated_at": model.selling_price_updated_at.isoformat() if model.selling_price_updated_at else None,
            "reason": reason}


def serialize(request, user):
    result = pricing.serialize_price_request(request)
    if request.workflow_state == PriceWorkflowState.APPROVED and request.approval_snapshot_json:
        snapshot = request.approval_snapshot_json
        for field in ("model_no", "variant_no", "model_name", "model_sizes", "date", "materials", "cost_price",
            "cost_price_uzs", "profit_percentage", "exchange_rate", "sewing_cost", "printing_cost", "accessories",
            "printing_required", "fabric_consumption", "consumption_cost", "binding_price", "difference", "margin_percentage", "packaging_cost"):
            if field in snapshot:
                result[field] = snapshot[field]
    result["can_approve"] = can_approve(user)
    return result


def _notify(db, request, teams):
    checks = {PriceContributionTeam.PURCHASING: (pricing.is_price_purchaser, "/purchasing/price-calculation"),
              PriceContributionTeam.ACCESSORIES: (pricing.is_accessory_pricing_user, "/inventory/accessory-pricing"),
              PriceContributionTeam.CUTTING: (pricing.is_cutting_pricing_user, "/cutting/price-calculation")}
    for user in db.query(User).filter(User.is_active.is_(True)).all():
        if request.factory_code not in available_factory_codes(user):
            continue
        scoped_user = copy(user)
        scoped_user.session_factory_code = request.factory_code
        if "*" in user_permissions(scoped_user):
            continue
        if request.model.catalog_scope == CatalogScope.USLUGA and not {"usluga.view", "usluga.manage"}.intersection(user_permissions(scoped_user)):
            continue
        if teams == "finance":
            if pricing.is_finance_pricing_user(scoped_user):
                add_notification_row(db, user_id=user.id, title="Price ready for Finance approval",
                    message=f"Model {request.model.code}: both costing teams have submitted.", link="/finance/price-calculation")
            continue
        for team in teams:
            check, link = checks[team]
            if check(scoped_user):
                add_notification_row(db, user_id=user.id, title="Variant price information required",
                    message=f"Model {request.model.code}: {request.correction_reason or 'enter and submit costs'}.", link=link)


def _create_or_reuse(db, model, current, reason=None):
    active = db.query(PriceCalculationRequest).options(*pricing.price_request_load_options()).filter_by(active_model_id=model.id).one_or_none()
    if active:
        if active.factory_code != selected_factory_code(current):
            return active, False
        saved = dict(active.price_baseline_json or {})
        if has_price(model) and baseline(model, saved.get("reason")) != saved:
            apply_workflow_fields(db, active, workflow_state=PriceWorkflowState.CANCELLED.value,
                active_model_id=None, correction_reason="Existing variant price was changed outside this request", revision=active.revision + 1)
            log_action(db, current, "cancel_stale_price_request", "PriceCalculationRequest", active.id,
                       new_value={"model_id": model.id, "existing_price_preserved": True})
        else:
            return active, False
    if has_price(model) and not reason:
        return None, False
    request = insert_workflow_request(db, model_id=model.id, created_by_id=current.id,
        factory_code=selected_factory_code(current), baseline=baseline(model, reason))
    log_action(db, current, "create", "PriceCalculationRequest", request.id,
        new_value={"model_id": model.id, "reprice_reason": reason})
    _notify(db, request, [PriceContributionTeam.PURCHASING, PriceContributionTeam.ACCESSORIES])
    return request, True


def create_request(db, payload, current):
    if not pricing.is_sales_pricing_user(current):
        raise HTTPException(403, "Sales access required")
    model = model_lock(db, payload.model_id)
    require_catalog(current, model.catalog_scope)
    # Preserve the manually requested target-margin validation. Automatic
    # passport requests do not depend on this optional PLM setting.
    details = model.details_json if isinstance(model.details_json, dict) else {}
    costing = details.get("costing") if isinstance(details.get("costing"), dict) else {}
    margin = pricing._decimal(costing.get("target_margin_pct"))
    if margin is not None and (not margin.is_finite() or abs(margin) > Decimal("999999.99") or margin != margin.quantize(Decimal("0.01"))):
        raise HTTPException(422, "Model target margin exceeds supported price calculation precision")
    request, created = _create_or_reuse(db, model, current, payload.reprice_reason)
    if request is None:
        raise HTTPException(409, "Variant already has a price; an explicit repricing reason is required")
    require_request_scope(current, request)
    if created:
        apply_workflow_fields(db, request, profit_percentage=margin)
        passport = passport_query(db, model.id, model.code, current).order_by(CuttingPassport.date.desc(), CuttingPassport.id.desc()).first()
        if passport:
            snapshot_passport(db, request, passport)
    db.commit()
    return serialize(request, current)


def _material_rows(passport) -> list[PriceMaterialSnapshot]:
    source = passport.materials or [{field: getattr(passport, field, None) for field in (
        "fabric_type", "size_range", "meter_mode", "fabric_width_m", "lay_length_m", "gramage",
        "beka_per_piece_kg", "other_beka_per_piece_kg", "ribana_per_piece_kg", "pieces", "total_layers")}]
    result: list[PriceMaterialSnapshot] = []
    order_sizes = passport_order_sizes(passport)
    for index, row in enumerate(source):
        key = str(row.get("stock_batch_id") or f"passport-{index}")
        count = size_count_from_range(row.get("size_range") or passport.size_range, order_sizes)
        length = amount(row.get("lay_length_m"))
        width, gsm = amount(row.get("fabric_width_m")), amount(row.get("gramage"))
        unit = PriceMaterialUnit.METRE if row.get("meter_mode") else PriceMaterialUnit.KG
        consumption = None
        if count > 0 and length is not None and length > 0:
            if unit == "m":
                consumption = length / count
            elif width is not None and width > 0 and gsm is not None and gsm > 0:
                consumption = width * length * gsm / count
        result.append({"key": key, "name": str(row.get("fabric_type") or passport.fabric_type or f"Fabric {index + 1}"),
                       "unit": unit, "consumption": number(consumption, "0.000001"), "rate": None})
        # Binding and ribana remain separate priced material lines. Do not
        # silently price a distinct fabric using the main fabric's rate.
        for field, name in (("beka_per_piece_kg", "Binding"), ("other_beka_per_piece_kg", "Other binding"), ("ribana_per_piece_kg", "Ribana")):
            quantity = amount(row.get(field))
            if quantity is not None and quantity > 0:
                result.append({"key": f"{key}:{field}", "name": name, "unit": unit,
                               "consumption": number(quantity, "0.000001"), "rate": None})
    return result


def passport_evidence(passport):
    rows = _material_rows(passport)
    # Rates are intentionally outside evidence: operators own those drafts.
    has_print = bool(passport.has_print or any(item.printing_required for item in passport.production_order.items)) if passport.production_order else bool(passport.has_print)
    data = {"passport_id": passport.id, "kroy_no": passport.passport_no,
            "production_order_id": passport.production_order_id, "model_code": passport.model_code,
            "has_print": has_print, "materials": rows}
    data["fingerprint"] = hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
    return data


def snapshot_passport(db, request, passport):
    evidence = passport_evidence(passport)
    if (request.passport_snapshot_json or {}).get("fingerprint") == evidence["fingerprint"]:
        return False
    old_rates = {row["key"]: row.get("rate") for row in request.materials_json or []}
    rows = [{**row, "rate": old_rates.get(row["key"])} for row in evidence["materials"]]
    correction = {"correction_team": None, "correction_reason": None} if request.correction_team == PriceContributionTeam.CUTTING else {}
    apply_workflow_fields(db, request, **correction, cutting_passport_id=passport.id, kroy_no=passport.passport_no,
        passport_snapshot_json=evidence, materials_json=rows, fabric_width_m=passport.fabric_width_m,
        lay_length_m=passport.lay_length_m, gramage=passport.gramage,
        size_count=size_count_from_range(passport.size_range, passport_order_sizes(passport)) or None,
        binding_kg_per_piece=(amount(passport.beka_per_piece_kg) or Decimal(0)) + (amount(passport.other_beka_per_piece_kg) or Decimal(0)),
        purchasing_submitted_at=None, accessories_submitted_at=None,
        workflow_state=PriceWorkflowState.COLLECTING.value, revision=request.revision + 1)
    return True


def sync_passport_pricing(db: Session, passport: CuttingPassport, current: User):
    """Participant of passport save: no commit, stock write, stage gate or cost validation."""
    # Scalar FK edits do not invalidate an already eager-loaded relationship.
    # Resolve the saved identity, never its old Session relationship cache.
    db.flush()
    db.expire(passport, ["production_order"])
    model_id = db.query(ProductionOrder.model_id).filter_by(id=passport.production_order_id).scalar() if passport.production_order_id else None
    if model_id is None and passport.model_code:
        model_id = db.query(Model.id).filter(Model.code == passport.model_code).scalar()
    references = db.query(PriceCalculationRequest.id, PriceCalculationRequest.model_id).filter_by(cutting_passport_id=passport.id).all()
    for locked_model_id in sorted({row.model_id for row in references} | ({model_id} if model_id is not None else set())):
        model_lock(db, locked_model_id)
    for request_id, old_model_id in references:
        request = db.get(PriceCalculationRequest, request_id)
        if old_model_id == model_id and (request.factory_code or "MIL") == selected_factory_code(current):
            continue
        if request.workflow_state in {PriceWorkflowState.LEGACY, PriceWorkflowState.APPROVED, PriceWorkflowState.CANCELLED}:
            apply_workflow_fields(db, request, cutting_passport_id=None)
        else:
            apply_workflow_fields(db, request, cutting_passport_id=None, active_model_id=None,
                workflow_state=PriceWorkflowState.CANCELLED.value, correction_reason="Cutting passport moved to another variant or factory", revision=request.revision + 1)
        log_action(db, current, "detach_moved_price_passport", "PriceCalculationRequest", request.id,
                   new_value={"passport_id": passport.id, "old_model_id": old_model_id, "new_model_id": model_id})
    if model_id is None:
        return
    model = model_lock(db, model_id)
    if model.catalog_scope == CatalogScope.USLUGA and (selected_factory_code(current) != "ECO" or not {"*", "usluga.view", "usluga.manage"}.intersection(user_permissions(current))):
        return
    request, created = _create_or_reuse(db, model, current)
    if request is None:
        return
    if request.factory_code != selected_factory_code(current):
        return
    # Later passports reuse the request; only the selected source may invalidate it.
    if request.cutting_passport_id in (None, passport.id):
        changed = snapshot_passport(db, request, passport)
        if changed and not created:
            log_action(db, current, "refresh_passport_evidence", "PriceCalculationRequest", request.id,
                       new_value={"passport_id": passport.id, "revision": request.revision})


def unlink_passport_pricing(db, passport, current):
    """Deleting an unused passport cancels/rebinds its open pricing task only."""
    ids = db.query(PriceCalculationRequest.id, PriceCalculationRequest.model_id).filter_by(cutting_passport_id=passport.id).all()
    for request_id, model_id in sorted(ids, key=lambda row: row.model_id):
        model = model_lock(db, model_id)
        request = db.get(PriceCalculationRequest, request_id)
        if request.workflow_state in {PriceWorkflowState.APPROVED, PriceWorkflowState.LEGACY, PriceWorkflowState.CANCELLED}:
            snapshot = request.approval_snapshot_json or json.loads(json.dumps(pricing.serialize_price_request(request), default=str))
            apply_workflow_fields(db, request, cutting_passport_id=None,
                passport_snapshot_json=request.passport_snapshot_json or passport_evidence(passport),
                approval_snapshot_json=snapshot)
            log_action(db, current, "detach_historical_price_passport", "PriceCalculationRequest", request.id,
                new_value={"passport_id": passport.id, "history_preserved": True})
            continue
        replacement = passport_query(db, model.id, model.code, current).filter(CuttingPassport.id != passport.id).order_by(CuttingPassport.id).first()
        if replacement:
            snapshot_passport(db, request, replacement)
        else:
            apply_workflow_fields(db, request, cutting_passport_id=None, active_model_id=None,
                workflow_state=PriceWorkflowState.CANCELLED.value, revision=request.revision + 1)
        if request.cutting_passport_id == passport.id:
            apply_workflow_fields(db, request, cutting_passport_id=None)
        log_action(db, current, "remove_passport_price_source", "PriceCalculationRequest", request.id,
            new_value={"passport_id": passport.id, "replacement_id": replacement.id if replacement else None})


def finish_draft(db, request):
    apply_workflow_fields(db, request, revision=request.revision + 1)


def submit_contribution(db, request_id, team: PriceContributionTeam, payload, current):
    if team == PriceContributionTeam.CUTTING:
        raise HTTPException(422, "Only Purchasing and Accessories submit cost contributions")
    check = pricing.is_price_purchaser if team == PriceContributionTeam.PURCHASING else pricing.is_accessory_pricing_user
    if not check(current):
        raise HTTPException(403, "Pricing team access required")
    request = locked_request(db, request_id, current, payload.expected_revision)
    require_editable(request, team)
    ready = purchasing_ready(request) if team == PriceContributionTeam.PURCHASING else accessories_ready(request)
    if not ready:
        raise HTTPException(409, "Complete all costs or give an explicit no-accessories reason before submitting")
    field = "purchasing_submitted_at" if team == PriceContributionTeam.PURCHASING else "accessories_submitted_at"
    before = request.workflow_state
    changes = {field: datetime.now(timezone.utc), "revision": request.revision + 1}
    if request.correction_team == team:
        changes.update(correction_team=None, correction_reason=None)
    apply_workflow_fields(db, request, **changes)
    if ready_for_finance(request):
        apply_workflow_fields(db, request, workflow_state=PriceWorkflowState.AWAITING_FINANCE.value)
        if before != PriceWorkflowState.AWAITING_FINANCE:
            _notify(db, request, "finance")
    log_action(db, current, "submit_price_costs", "PriceCalculationRequest", request.id, new_value={"team": team.value, "revision": request.revision})
    db.commit()
    return serialize(request, current)


def approve(db, request_id, payload, current):
    if not can_approve(current):
        raise HTTPException(403, "Price confirmation permission required")
    request = locked_request(db, request_id, current, payload.expected_revision)
    require_editable(request)
    if request.workflow_state != PriceWorkflowState.AWAITING_FINANCE or not ready_for_finance(request):
        raise HTTPException(409, "Both teams and passport evidence must be complete before confirmation")
    if request.cutting_passport:
        # populate_existing refreshes a passport held in this Session's identity map.
        db.refresh(request.cutting_passport)
        evidence = passport_evidence(request.cutting_passport)
        if evidence["fingerprint"] != (request.passport_snapshot_json or {}).get("fingerprint"):
            raise HTTPException(409, "Cutting passport changed; refresh costing before approval")
    saved = dict(request.price_baseline_json or {})
    actual = baseline(request.model, saved.get("reason"))
    if actual != saved:
        raise HTTPException(409, "Variant price changed while this request was pending; existing price was preserved")
    now = datetime.now(timezone.utc)
    apply_workflow_fields(db, request, selling_price=payload.selling_price)
    snapshot = serialize(request, current)
    snapshot = json.loads(json.dumps(snapshot, default=lambda value: value.isoformat() if isinstance(value, datetime) else str(value)))
    apply_workflow_fields(db, request, workflow_state=PriceWorkflowState.APPROVED.value,
        approved_at=now, approved_by_id=current.id, approval_snapshot_json=snapshot,
        active_model_id=None, revision=request.revision + 1)
    apply_request_selling_price(db, request.model, price=Decimal(str(payload.selling_price)), request_id=request.id, updated_at=now)
    log_action(db, current, "approve_variant_price", "PriceCalculationRequest", request.id,
        new_value={"model_id": request.model_id, "selling_price": payload.selling_price, "currency": "USD", "revision": request.revision})
    db.commit()
    return serialize(request, current)


def return_for_correction(db, request_id, payload, current):
    if not can_approve(current):
        raise HTTPException(403, "Price confirmation permission required")
    request = locked_request(db, request_id, current, payload.expected_revision)
    require_editable(request)
    reason = payload.reason.strip()
    if len(reason) < 3:
        raise HTTPException(422, "A correction reason is required")
    changes = {"correction_team": payload.team.value, "correction_reason": reason,
               "workflow_state": PriceWorkflowState.COLLECTING.value, "revision": request.revision + 1}
    if payload.team in {PriceContributionTeam.PURCHASING, PriceContributionTeam.CUTTING}:
        changes["purchasing_submitted_at"] = None
    if payload.team == PriceContributionTeam.ACCESSORIES:
        changes["accessories_submitted_at"] = None
    apply_workflow_fields(db, request, **changes)
    _notify(db, request, [payload.team])
    log_action(db, current, "return_price_costs", "PriceCalculationRequest", request.id,
               new_value={"team": payload.team.value, "reason": reason})
    db.commit()
    return serialize(request, current)


def cancel_request(db, request_id, payload, current):
    if not can_approve(current):
        raise HTTPException(403, "Price confirmation permission required")
    request = locked_request(db, request_id, current, payload.expected_revision)
    require_editable(request)
    if len(payload.reason.strip()) < 3:
        raise HTTPException(422, "A cancellation reason is required")
    apply_workflow_fields(db, request, active_model_id=None, workflow_state=PriceWorkflowState.CANCELLED.value,
        correction_reason=payload.reason.strip(), revision=request.revision + 1)
    log_action(db, current, "cancel_price_request", "PriceCalculationRequest", request.id, new_value={"reason": payload.reason.strip()})
    db.commit()
    return serialize(request, current)


def request_reprice(db, model_id, payload, current):
    if not can_approve(current):
        raise HTTPException(403, "Price confirmation permission required")
    model = model_lock(db, model_id)
    require_catalog(current, model.catalog_scope)
    reason = payload.reason.strip()
    if len(reason) < 3:
        raise HTTPException(422, "A repricing reason is required")
    request, created = _create_or_reuse(db, model, current, reason)
    require_request_scope(current, request)
    if created:
        passport = passport_query(db, model.id, model.code, current).order_by(CuttingPassport.id.desc()).first()
        if passport:
            snapshot_passport(db, request, passport)
    db.commit()
    return serialize(request, current)


def list_requests(db, current, limit, before_id, queue=PriceRequestQueue.ALL, team=None, q="", catalog_scope=CatalogScope.STANDARD):
    if not pricing.can_view_price_requests(current):
        raise HTTPException(403, "Price calculation access required")
    require_catalog(current, catalog_scope)
    query = db.query(PriceCalculationRequest).join(Model, Model.id == PriceCalculationRequest.model_id).options(*pricing.price_request_load_options()).filter(request_scope(current), Model.catalog_scope == catalog_scope)
    if q.strip():
        term = f"%{q.strip()}%"
        query = query.filter(or_(Model.code.ilike(term), Model.name.ilike(term), PriceCalculationRequest.kroy_no.ilike(term)))
    if queue == PriceRequestQueue.PENDING:
        query = query.filter(PriceCalculationRequest.active_model_id.is_not(None))
        if team == PriceContributionTeam.PURCHASING:
            query = query.filter(PriceCalculationRequest.purchasing_submitted_at.is_(None))
        elif team == PriceContributionTeam.ACCESSORIES:
            query = query.filter(PriceCalculationRequest.accessories_submitted_at.is_(None))
    elif queue == PriceRequestQueue.COMPLETED:
        if team == PriceContributionTeam.PURCHASING:
            query = query.filter(PriceCalculationRequest.purchasing_submitted_at.is_not(None))
        elif team == PriceContributionTeam.ACCESSORIES:
            query = query.filter(PriceCalculationRequest.accessories_submitted_at.is_not(None))
        else:
            query = query.filter(PriceCalculationRequest.workflow_state == PriceWorkflowState.APPROVED)
    elif queue == PriceRequestQueue.APPROVAL:
        query = query.filter(PriceCalculationRequest.workflow_state == PriceWorkflowState.AWAITING_FINANCE)
    if before_id is not None:
        query = query.filter(PriceCalculationRequest.id < before_id)
    return [serialize(request, current) for request in query.order_by(PriceCalculationRequest.id.desc()).limit(limit).all()]
