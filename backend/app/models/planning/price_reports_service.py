"""Finance price register and complete, consistently filtered Excel export."""
from io import BytesIO

from fastapi import HTTPException
from openpyxl import Workbook
from sqlalchemy import and_, exists, or_, select

from app.libs.enums.catalog import CatalogScope
from app.libs.enums.planning import PriceReportFilter, PriceWorkflowState
from app.models import price_calculation_service as pricing
from app.models.factory_scope_service import CUTTING_DEPARTMENTS, selected_factory_code
from app.models.planning import variant_pricing_service as workflow
from app.models.planning import variant_pricing_policy as policy
from app.schemas import CuttingPassport, Department, Model, ProductionOrder, WorkOrder
from app.schemas.planning.price_calculation import PriceCalculationRequest


def require_finance(current):
    if not pricing.is_finance_pricing_user(current):
        raise HTTPException(403, "Finance access required")


def _query(db, current, status, q, catalog_scope):
    require_finance(current)
    workflow.require_catalog(current, catalog_scope)
    factory = selected_factory_code(current)
    cutting = CUTTING_DEPARTMENTS.get(factory)
    scoped_work = exists(select(WorkOrder.id).join(Department).where(
        WorkOrder.production_order_id == ProductionOrder.id, WorkOrder.operation == "cutting", Department.code == cutting)).correlate(ProductionOrder)
    passport = exists(select(CuttingPassport.id).outerjoin(ProductionOrder, ProductionOrder.id == CuttingPassport.production_order_id).where(
        or_(and_(ProductionOrder.model_id == Model.id, scoped_work),
            and_(CuttingPassport.production_order_id.is_(None), CuttingPassport.model_code == Model.code, factory == "MIL")))).correlate(Model)
    request = exists(select(PriceCalculationRequest.id).where(PriceCalculationRequest.model_id == Model.id, workflow.request_scope(current))).correlate(Model)
    priced = Model.selling_price > 0
    query = db.query(Model).options(*pricing.model_asset_load_options()).filter(Model.catalog_scope == catalog_scope,
        or_(priced, passport, request))
    if q.strip():
        term = f"%{q.strip()}%"
        matching_kroy = exists(select(PriceCalculationRequest.id).where(PriceCalculationRequest.model_id == Model.id,
            workflow.request_scope(current), PriceCalculationRequest.kroy_no.ilike(term))).correlate(Model)
        query = query.filter(or_(Model.code.ilike(term), Model.name.ilike(term), matching_kroy))
    if status == PriceReportFilter.PENDING:
        query = query.filter(policy.predicate())
    elif status == PriceReportFilter.PRICED:
        query = query.filter(priced)
    elif status == PriceReportFilter.APPROVAL:
        query = query.filter(policy.predicate(), exists(select(PriceCalculationRequest.id).where(
            PriceCalculationRequest.model_id == Model.id, workflow.request_scope(current),
            PriceCalculationRequest.active_model_id.is_not(None),
            PriceCalculationRequest.workflow_state == PriceWorkflowState.AWAITING_FINANCE)))
    return query


def list_prices(db, current, status=PriceReportFilter.ALL, q="", catalog_scope=CatalogScope.STANDARD, before_id=None, limit=50):
    query = _query(db, current, status, q, catalog_scope)
    if before_id is not None:
        query = query.filter(Model.id < before_id)
    models = query.order_by(Model.id.desc()).limit(limit).all()
    ids = [model.id for model in models]
    requests = db.query(PriceCalculationRequest).options(*pricing.price_request_load_options()).filter(
        PriceCalculationRequest.model_id.in_(ids), workflow.request_scope(current)).order_by(PriceCalculationRequest.id.desc()).all() if ids else []
    latest = {}
    for request in requests:
        if request.model_id not in latest or request.active_model_id:
            latest[request.model_id] = request
    owners = dict(db.query(PriceCalculationRequest.active_model_id, PriceCalculationRequest.factory_code).filter(
        PriceCalculationRequest.active_model_id.in_(ids)).all()) if ids else {}
    result = []
    for model in models:
        model_no, variant_no = pricing._model_parts(model)
        request = latest.get(model.id)
        result.append({"model_id": model.id, "model_no": model_no, "variant_no": variant_no,
            "model_name": model.name, "catalog_scope": model.catalog_scope,
            "selling_price": float(model.selling_price) if model.selling_price is not None else None,
            "currency": model.selling_price_currency, "source": model.selling_price_source,
            "price_updated_at": model.selling_price_updated_at,
            "pending_factory": owners.get(model.id), "request": workflow.serialize(request, current) if request else None})
    return result


def history(db, current, model_id):
    require_finance(current)
    model = db.get(Model, model_id)
    if model is None:
        raise HTTPException(404, "Model not found")
    workflow.require_catalog(current, model.catalog_scope)
    return [workflow.serialize(request, current) for request in db.query(PriceCalculationRequest).options(
        *pricing.price_request_load_options()).filter(PriceCalculationRequest.model_id == model_id,
        workflow.request_scope(current)).order_by(PriceCalculationRequest.id.desc()).all()]


def export_prices(db, current, status=PriceReportFilter.ALL, q="", catalog_scope=CatalogScope.STANDARD):
    require_finance(current)
    workflow.require_catalog(current, catalog_scope)
    workbook = Workbook(write_only=True)
    prices = workbook.create_sheet("Variant Prices")
    costs = workbook.create_sheet("Cost Breakdown")
    audit = workbook.create_sheet("Approval History")
    prices.append(["Model", "Variant", "Name", "Catalogue", "Selling price", "Currency", "Source", "Updated", "Pricing state", "Factory", "Kroy"])
    costs.append(["Model", "Variant", "Request", "State", "Component", "Unit", "Consumption per piece", "Rate USD", "Cost USD"])
    audit.append(["Model", "Variant", "Request", "State", "Cost USD", "Selling USD", "Approved by", "Approved at", "Correction", "Kroy"])
    def safe(value):
        # Keep text as text even when opened by spreadsheet applications.
        return "'" + value if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")) else value
    cursor = None
    while True:
        rows = list_prices(db, current, status, q, catalog_scope, cursor, 200)
        if not rows:
            break
        for row in rows:
            request = row["request"] or {}
            prices.append([safe(row["model_no"]), safe(row["variant_no"]), safe(row["model_name"]), row["catalog_scope"], row["selling_price"], row["currency"], row["source"],
                row["price_updated_at"].isoformat() if row["price_updated_at"] else None, request.get("workflow_state"), row["pending_factory"], safe(request.get("kroy_no"))])
        model_ids = [row["model_id"] for row in rows]
        requests = db.query(PriceCalculationRequest).options(*pricing.price_request_load_options()).filter(
            PriceCalculationRequest.model_id.in_(model_ids), workflow.request_scope(current)).order_by(PriceCalculationRequest.id.desc()).all()
        for request in requests:
            data = request.approval_snapshot_json or workflow.serialize(request, current)
            model_no, variant_no = pricing._model_parts(request.model)
            model_no, variant_no = data.get("model_no", model_no), data.get("variant_no", variant_no)
            prefix = [safe(model_no), safe(variant_no), request.id, request.workflow_state]
            for material in data.get("materials", []):
                costs.append([*prefix, safe(material["name"]), material["unit"], material.get("consumption"), material.get("rate"), material.get("cost")])
            for label, value in (("Sewing", data.get("sewing_cost")), ("Printing", data.get("printing_cost")), ("Packaging", data.get("packaging_cost"))):
                costs.append([*prefix, label, "piece", 1, value, value])
            for accessory in data.get("accessories", []):
                costs.append([*prefix, safe(accessory.get("name")), "piece", 1, accessory.get("price"), accessory.get("price")])
            audit.append([*prefix, data.get("cost_price"), data.get("selling_price"), safe(request.approved_by.name) if request.approved_by else None,
                request.approved_at.isoformat() if request.approved_at else None, safe(request.correction_reason), safe(request.kroy_no)])
        cursor = rows[-1]["model_id"]
    for sheet in workbook:
        sheet.freeze_panes = "A2"
        for column in "ABCDEFGHIJK":
            sheet.column_dimensions[column].width = 22
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()
