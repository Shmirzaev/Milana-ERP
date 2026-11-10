"""Read-only costing projection shared by queues, approval and reports."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext

from app.libs.enums.planning import PriceCalculationStatus, PriceWorkflowState


def amount(value):
    try:
        result = Decimal(str(value)) if value is not None else None
        return result if result is not None and result.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def number(value, precision="0.0001"):
    with localcontext() as context:
        context.prec = 80
        return float(value.quantize(Decimal(precision), rounding=ROUND_HALF_UP)) if value is not None else None


def has_price(model):
    price = amount(model.selling_price)
    return price is not None and price > 0


def cutting_ready(request):
    rows = request.materials_json or []
    return bool(rows) and all(amount(row.get("consumption")) is not None and amount(row.get("consumption")) >= 0 for row in rows)


def purchasing_ready(request):
    rows = request.materials_json or []
    sewing = amount(request.sewing_cost)
    printing = amount(request.printing_cost)
    required = bool((request.passport_snapshot_json or {}).get("has_print"))
    return bool(rows) and all(amount(row.get("rate")) is not None and amount(row.get("rate")) >= 0 for row in rows) and sewing is not None and sewing >= 0 and (not required or printing is not None and printing >= 0)


def accessories_ready(request):
    rows = request.accessories_json or []
    if request.no_accessories_reason:
        return not rows and len(request.no_accessories_reason.strip()) >= 3
    return bool(rows) and all(str(row.get("name") or "").strip() and amount(row.get("price")) is not None and amount(row.get("price")) >= 0 for row in rows)


def ready_for_finance(request):
    return bool(not request.correction_team and request.purchasing_submitted_at and request.accessories_submitted_at and cutting_ready(request) and purchasing_ready(request) and accessories_ready(request))


def projection(request):
    materials = []
    for row in request.materials_json or []:
        quantity, rate = amount(row.get("consumption")), amount(row.get("rate"))
        materials.append({**row, "cost": number(quantity * rate) if quantity is not None and rate is not None else None})
    ready = ready_for_finance(request)
    cost = None
    if ready:
        cost = sum((amount(row["consumption"]) * amount(row["rate"]) for row in materials), Decimal(0))
        cost += amount(request.sewing_cost) + Decimal("0.1")
        cost += sum((amount(row.get("price")) for row in request.accessories_json or []), Decimal(0))
        cost += amount(request.printing_cost) or Decimal(0)
    selling, exchange = amount(request.selling_price), amount(request.exchange_rate)
    issues = []
    if not cutting_ready(request):
        issues.append("passport_consumption")
    if not purchasing_ready(request):
        issues.append("purchasing_costs")
    if not accessories_ready(request):
        issues.append("accessory_costs")
    submitted_purchase = bool(request.purchasing_submitted_at)
    submitted_accessory = bool(request.accessories_submitted_at)
    return {
        "workflow_state": request.workflow_state,
        "factory_code": request.factory_code,
        "catalog_scope": request.model.catalog_scope,
        "revision": request.revision,
        "materials": materials,
        "purchasing_submitted_at": request.purchasing_submitted_at,
        "accessories_submitted_at": request.accessories_submitted_at,
        "no_accessories_reason": request.no_accessories_reason,
        "printing_required": bool((request.passport_snapshot_json or {}).get("has_print")),
        "printing_cost": number(amount(request.printing_cost)),
        "correction_team": request.correction_team,
        "correction_reason": request.correction_reason,
        "approved_at": request.approved_at,
        "approved_by_id": request.approved_by_id,
        "approved_by_name": request.approved_by.name if request.approved_by else None,
        "calculation_issues": issues,
        "cutting_status": PriceCalculationStatus.COMPLETE if cutting_ready(request) else PriceCalculationStatus.IN_PROGRESS,
        "purchasing_status": PriceCalculationStatus.COMPLETE if submitted_purchase else PriceCalculationStatus.IN_PROGRESS if any(row.get("rate") is not None for row in materials) or request.sewing_cost is not None else PriceCalculationStatus.NEW,
        "accessories_status": PriceCalculationStatus.COMPLETE if submitted_accessory else PriceCalculationStatus.IN_PROGRESS if request.accessories_json or request.no_accessories_reason else PriceCalculationStatus.NEW,
        "overall_status": PriceCalculationStatus.COMPLETE if request.workflow_state == PriceWorkflowState.APPROVED else PriceCalculationStatus.IN_PROGRESS,
        "cost_price": number(cost),
        "cost_price_uzs": number(cost * exchange, "0.01") if cost is not None and exchange is not None and exchange > 0 else None,
        "consumption_cost": number(sum((amount(row["consumption"]) * amount(row["rate"]) for row in materials), Decimal(0))) if ready else None,
        "binding_price": None,
        "fabric_consumption": materials[0]["consumption"] if materials else None,
        "difference": number(selling - cost) if selling is not None and cost is not None else None,
        "margin_percentage": number((selling - cost) / selling * 100, "0.01") if selling is not None and selling > 0 and cost is not None else None,
    }
