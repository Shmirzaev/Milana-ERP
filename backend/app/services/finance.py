"""Finance/reporting service."""
from datetime import datetime
from decimal import Decimal
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.dt import as_utc
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
    total = sum(
        (Decimal(str(r.available_qty or 0)) * Decimal(str(r.cost_per_piece or 0)) for r in rows),
        Decimal("0"),
    )
    return float(total)


def order_profit(db: Session, sales_order_id: int) -> dict:
    so = db.get(SalesOrder, sales_order_id)
    if not so:
        return {}
    # Keep intermediate money arithmetic exact; the public response remains
    # JSON-compatible floats for the existing finance clients.
    revenue = sum(
        (Decimal(str(i.quantity or 0)) * Decimal(str(i.unit_price or 0))
         for i in so.items),
        Decimal("0"),
    )
    # cost = sum over production orders linked to SO: estimated material cost via BOM
    cost = Decimal("0")
    pos = db.query(ProductionOrder).filter(ProductionOrder.sales_order_id == sales_order_id).all()
    if pos:
        model_ids = {p.model_id for p in pos}
        bom_rows = db.query(ModelBOM).filter(ModelBOM.model_id.in_(model_ids)).all()
        boms_by_model: dict[int, list[ModelBOM]] = {}
        for row in bom_rows:
            boms_by_model.setdefault(row.model_id, []).append(row)

        item_ids = {row.item_id for row in bom_rows}
        latest_cost_by_item: dict[int, Decimal] = {}
        if item_ids:
            latest_rows = (
                db.query(StockBatch)
                .filter(StockBatch.item_id.in_(item_ids))
                .order_by(StockBatch.item_id.asc(), StockBatch.id.desc())
                .all()
            )
            for r in latest_rows:
                if r.item_id not in latest_cost_by_item:
                    latest_cost_by_item[r.item_id] = Decimal(str(r.cost_per_unit or 0))

        for po in pos:
            for b in boms_by_model.get(po.model_id, []):
                unit_cost = latest_cost_by_item.get(b.item_id, Decimal("0"))
                cost += (
                    Decimal(str(b.quantity_per_piece or 0))
                    * Decimal(str(po.planned_quantity or 0))
                    * unit_cost
                    * (Decimal("1") + Decimal(str(b.waste_percent or 0)) / Decimal("100"))
                )
    waste = Decimal(str(db.query(func.coalesce(func.sum(WasteRecord.estimated_value), 0)).filter(
        WasteRecord.production_order_id.in_([p.id for p in pos]) if pos else False
    ).scalar() or 0))
    return {
        "sales_order_id": sales_order_id,
        "order_no": so.order_no,
        "revenue": float(revenue),
        "material_cost": float(cost),
        "waste_cost": float(waste),
        "gross_profit": float(revenue - cost - waste),
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
    safe_limit = max(1, min(int(limit or 50), 500))
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
    from_dt, to_dt = as_utc(from_dt), as_utc(to_dt)
    timestamp = func.coalesce(Invoice.issued_at, Invoice.created_at)
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        period = func.to_char(timestamp, "YYYY-MM")
    else:
        period = func.strftime("%Y-%m", timestamp)
    qry = db.query(period.label("period"), func.coalesce(func.sum(Invoice.amount), 0).label("amount"))
    if from_dt:
        qry = qry.filter(timestamp >= from_dt)
    if to_dt:
        qry = qry.filter(timestamp <= to_dt)
    rows = qry.filter(timestamp.isnot(None)).group_by(period).order_by(period).all()
    return [{"period": key, "amount": round(float(amount or 0), 2)} for key, amount in rows if key]


def cost_breakdown(db: Session) -> dict:
    """Estimate COGS split into fabric, accessories, and labor components."""
    pos = db.query(ProductionOrder).all()
    model_ids = {int(po.model_id) for po in pos if po.model_id}
    bom_rows = db.query(ModelBOM).filter(ModelBOM.model_id.in_(model_ids)).all() if model_ids else []

    item_ids = {int(row.item_id) for row in bom_rows if row.item_id}
    item_rows = db.query(Item).filter(Item.id.in_(item_ids)).all() if item_ids else []
    item_map = {int(item.id): item for item in item_rows}

    latest_cost_by_item: dict[int, Decimal] = {}
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
                latest_cost_by_item[item_id] = Decimal(str(row.cost_per_unit or 0))

    boms_by_model: dict[int, list[ModelBOM]] = {}
    for row in bom_rows:
        boms_by_model.setdefault(int(row.model_id), []).append(row)

    fabric_cost = Decimal("0")
    accessories_cost = Decimal("0")
    for po in pos:
        for bom in boms_by_model.get(int(po.model_id), []):
            # Unlinked BOM rows describe manual/material notes and have no
            # inventory cost to include in the item-based COGS estimate.
            if bom.item_id is None:
                continue
            item_id = int(bom.item_id)
            item = item_map.get(item_id)
            category = str(item.category if item else "").lower()
            fallback_cost = Decimal(str(item.default_cost or 0)) if item else Decimal("0")
            unit_cost = latest_cost_by_item.get(item_id, fallback_cost)
            row_cost = (
                Decimal(str(bom.quantity_per_piece or 0))
                * Decimal(str(po.planned_quantity or 0))
                * unit_cost
                * (Decimal("1") + Decimal(str(bom.waste_percent or 0)) / Decimal("100"))
            )
            if category in ("accessory", "packaging"):
                accessories_cost += row_cost
            else:
                fabric_cost += row_cost

    labor_cost = float(db.query(func.coalesce(func.sum(SalesOrder.planning_estimated_labor_cost), 0)).scalar() or 0)
    labor_cost_decimal = Decimal(str(labor_cost))
    total_cogs = fabric_cost + accessories_cost + labor_cost_decimal
    return {
        "fabric_cost": round(float(fabric_cost), 2),
        "labor_cost": round(float(labor_cost_decimal), 2),
        "accessories_cost": round(float(accessories_cost), 2),
        "total_cogs": round(float(total_cogs), 2),
    }
