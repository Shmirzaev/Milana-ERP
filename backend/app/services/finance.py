"""Finance/reporting service."""
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    SalesOrder, SalesOrderItem, ProductionOrder, FinishedGoodsStock,
    WasteRecord, WasteSale, Invoice, Payment, ModelBOM, StockBatch,
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
    val = db.query(func.coalesce(func.sum(WasteSale.total_amount), 0)).scalar()
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
    for po in pos:
        bom = db.query(ModelBOM).filter(ModelBOM.model_id == po.model_id).all()
        for b in bom:
            avg = db.query(StockBatch).filter(StockBatch.item_id == b.item_id).order_by(StockBatch.id.desc()).first()
            unit_cost = float(avg.cost_per_unit) if avg else 0.0
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
