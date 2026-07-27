"""Finance/reporting service."""
from datetime import datetime
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    SalesOrder, ProductionOrder, FinishedGoodsStock,
    WasteRecord, Invoice, Payment, ModelBOM, StockBatch, Customer, Item,
)


def revenue_total(db: Session) -> float:
    val = db.query(func.coalesce(func.sum(Invoice.amount), 0)).scalar()
    return float(val or 0)


def payments_total(db: Session) -> float:
    val = db.query(func.coalesce(func.sum(Payment.amount), 0)).scalar()
    return float(val or 0)


def waste_cost(db: Session) -> float:
    val = db.query(func.coalesce(func.sum(WasteRecord.estimated_value), 0)) \
        .filter(WasteRecord.sellable.is_(False)).scalar()
    return float(val or 0)


def waste_income(db: Session) -> float:
    val = db.query(func.coalesce(func.sum(WasteRecord.estimated_value), 0)) \
        .filter(WasteRecord.sellable.is_(True)).scalar()
    return float(val or 0)


def branded_stock_value(db: Session) -> float:
    rows = db.query(FinishedGoodsStock).filter(
        FinishedGoodsStock.brand_id.isnot(None),
        FinishedGoodsStock.status == "available",
    ).all()
    return float(sum(float(r.available_qty) * float(r.cost_per_piece) for r in rows))


def order_profit(db: Session, sales_order_id: int) -> dict:
    so = db.get(SalesOrder, sales_order_id)
    if not so:
        return {}
    revenue = sum(float(i.quantity) * float(i.unit_price) for i in so.items)
    # cost = sum over production orders linked to SO: estimated material cost via BOM
    cost = 0.0
    pos = db.query(ProductionOrder).filter(ProductionOrder.sales_order_id == sales_order_id).all()
    if pos:
        model_ids = {p.model_id for p in pos}
        bom_rows = db.query(ModelBOM).filter(ModelBOM.model_id.in_(model_ids)).all()
        boms_by_model: dict[int, list[ModelBOM]] = {}
        for row in bom_rows:
            boms_by_model.setdefault(row.model_id, []).append(row)

        item_ids = {row.item_id for row in bom_rows}
        latest_cost_by_item: dict[int, float] = {}
        if item_ids:
            latest_rows = (
                db.query(StockBatch)
                .filter(StockBatch.item_id.in_(item_ids))
                .order_by(StockBatch.item_id.asc(), StockBatch.id.desc())
                .all()
            )
            for r in latest_rows:
                if r.item_id not in latest_cost_by_item:
                    latest_cost_by_item[r.item_id] = float(r.cost_per_unit or 0)

        for po in pos:
            for b in boms_by_model.get(po.model_id, []):
                unit_cost = latest_cost_by_item.get(b.item_id, 0.0)
                cost += float(b.quantity_per_piece) * po.planned_quantity * unit_cost * (1.0 + float(b.waste_percent) / 100.0)
    waste = float(db.query(func.coalesce(func.sum(WasteRecord.estimated_value), 0)).filter(
        WasteRecord.production_order_id.in_([p.id for p in pos]) if pos else False
    ).scalar() or 0)
    return {
        "sales_order_id": sales_order_id,
        "order_no": so.order_no,
        "revenue": revenue,
        "material_cost": cost,
        "waste_cost": waste,
        "gross_profit": revenue - cost - waste,
    }


def dashboard_summary(db: Session) -> dict:
    return {
        "revenue_total": revenue_total(db),
        "payments_received": payments_total(db),
        "branded_stock_value": branded_stock_value(db),
        "waste_cost": waste_cost(db),
        "waste_income": waste_income(db),
    }


def list_recent_invoices(db: Session, limit: int = 50) -> list[dict]:
    """Return recent invoices with sales-order and customer labels for finance UI."""
    safe_limit = max(1, min(int(limit or 50), 200))
    rows = (
        db.query(Invoice, SalesOrder, Customer)
        .join(SalesOrder, SalesOrder.id == Invoice.sales_order_id)
        .outerjoin(Customer, Customer.id == SalesOrder.customer_id)
        .order_by(Invoice.id.desc())
        .limit(safe_limit)
        .all()
    )
    out: list[dict] = []
    for invoice, so, customer in rows:
        dt = invoice.issued_at or invoice.created_at
        out.append(
            {
                "id": int(invoice.id),
                "invoice_no": invoice.invoice_no,
                "sales_order_id": int(so.id),
                "order_no": so.order_no,
                "customer": customer.name if customer else None,
                "amount": float(invoice.amount or 0),
                "status": invoice.status,
                "date": dt.isoformat() if dt else None,
            }
        )
    return out


def revenue_by_period(db: Session, *, from_dt: datetime | None = None, to_dt: datetime | None = None) -> list[dict]:
    """Aggregate invoice revenue by month for charting."""
    invoices = db.query(Invoice).order_by(Invoice.id.asc()).all()
    buckets: dict[str, float] = {}
    for invoice in invoices:
        dt = invoice.issued_at or invoice.created_at
        if not dt:
            continue
        if from_dt and dt < from_dt:
            continue
        if to_dt and dt > to_dt:
            continue
        key = dt.strftime("%Y-%m")
        buckets[key] = buckets.get(key, 0.0) + float(invoice.amount or 0)
    return [{"period": k, "amount": round(v, 2)} for k, v in sorted(buckets.items(), key=lambda x: x[0])]


def cost_breakdown(db: Session) -> dict:
    """Estimate COGS split into fabric, accessories, and labor components."""
    pos = db.query(ProductionOrder).all()
    model_ids = {int(po.model_id) for po in pos if po.model_id}
    bom_rows = db.query(ModelBOM).filter(ModelBOM.model_id.in_(model_ids)).all() if model_ids else []

    item_ids = {int(row.item_id) for row in bom_rows if row.item_id}
    item_rows = db.query(Item).filter(Item.id.in_(item_ids)).all() if item_ids else []
    item_map = {int(item.id): item for item in item_rows}

    latest_cost_by_item: dict[int, float] = {}
    if item_ids:
        latest_rows = (
            db.query(StockBatch)
            .filter(StockBatch.item_id.in_(item_ids))
            .order_by(StockBatch.item_id.asc(), StockBatch.id.desc())
            .all()
        )
        for row in latest_rows:
            item_id = int(row.item_id)
            if item_id not in latest_cost_by_item:
                latest_cost_by_item[item_id] = float(row.cost_per_unit or 0)

    boms_by_model: dict[int, list[ModelBOM]] = {}
    for row in bom_rows:
        boms_by_model.setdefault(int(row.model_id), []).append(row)

    fabric_cost = 0.0
    accessories_cost = 0.0
    for po in pos:
        for bom in boms_by_model.get(int(po.model_id), []):
            item_id = int(bom.item_id)
            item = item_map.get(item_id)
            category = str(item.category if item else "").lower()
            fallback_cost = float(item.default_cost or 0) if item else 0.0
            unit_cost = latest_cost_by_item.get(item_id, fallback_cost)
            row_cost = (
                float(bom.quantity_per_piece or 0)
                * float(po.planned_quantity or 0)
                * unit_cost
                * (1.0 + float(bom.waste_percent or 0) / 100.0)
            )
            if category in ("accessory", "packaging"):
                accessories_cost += row_cost
            else:
                fabric_cost += row_cost

    labor_cost = float(db.query(func.coalesce(func.sum(SalesOrder.planning_estimated_labor_cost), 0)).scalar() or 0)
    total_cogs = fabric_cost + accessories_cost + labor_cost
    return {
        "fabric_cost": round(fabric_cost, 2),
        "labor_cost": round(labor_cost, 2),
        "accessories_cost": round(accessories_cost, 2),
        "total_cogs": round(total_cogs, 2),
    }
