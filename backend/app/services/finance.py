"""Finance/reporting service."""
from datetime import datetime
from decimal import Decimal
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, load_only, noload, selectinload

from app.core.dt import as_utc
from app.models import (
    SalesOrder, SalesOrderItem, ProductionOrder, FinishedGoodsStock,
    WasteRecord, WasteSale, Invoice, Payment, ModelBOM, StockBatch, Customer, Item,
    StockMovement, CuttingRecord, PackagingRecord, WorkOrder, MaterialReservation,
)


def _single_currency_total(db: Session, model, *, predicate=None) -> tuple[float | None, str | None]:
    query = db.query(
        func.count(model.id), func.count(model.currency),
        func.min(model.currency), func.max(model.currency),
        func.coalesce(func.sum(model.amount), 0),
    )
    if predicate is not None:
        query = query.filter(predicate)
    count, known_count, lowest, highest, amount = query.one()
    if not count:
        return 0.0, None
    if known_count != count or lowest != highest:
        return None, None
    return float(amount), str(lowest)


def revenue_summary(db: Session) -> tuple[float | None, str | None]:
    return _single_currency_total(db, Invoice, predicate=Invoice.status.notin_(("void", "cancelled")))


def revenue_total(db: Session) -> float | None:
    return revenue_summary(db)[0]


def payments_summary(db: Session) -> tuple[float | None, str | None]:
    return _single_currency_total(db, Payment)


def payments_total(db: Session) -> float | None:
    return payments_summary(db)[0]


def waste_cost(db: Session) -> float:
    val = db.query(func.coalesce(func.sum(WasteRecord.estimated_value), 0)) \
        .filter(WasteRecord.sellable.is_(False)).scalar()
    return float(val or 0)


def waste_income(db: Session) -> float:
    val = db.query(func.coalesce(func.sum(WasteSale.total_amount), 0)).scalar()
    return float(val or 0)


def branded_stock_value(db: Session) -> float:
    total = db.query(
        func.coalesce(
            func.sum(FinishedGoodsStock.available_qty * FinishedGoodsStock.cost_per_piece),
            0,
        )
    ).filter(
        FinishedGoodsStock.brand_id.isnot(None),
        FinishedGoodsStock.status == "available",
    ).scalar()
    return float(total)


def _latest_stock_batch_costs(db: Session, item_ids: set[int]) -> dict[int, Decimal]:
    if not item_ids:
        return {}
    latest_ids = (
        db.query(StockBatch.item_id, func.max(StockBatch.id).label("latest_id"))
        .filter(StockBatch.item_id.in_(item_ids))
        .group_by(StockBatch.item_id)
        .subquery()
    )
    rows = (
        db.query(StockBatch.item_id, StockBatch.cost_per_unit)
        .join(latest_ids, StockBatch.id == latest_ids.c.latest_id)
        .all()
    )
    return {int(item_id): Decimal(str(cost or 0)) for item_id, cost in rows}


def _recorded_material_cost_details(db: Session, production_order_ids: set[int]) -> tuple[Decimal | None, str | None]:
    if not production_order_ids:
        return None, None
    cutting_ids = (
        select(CuttingRecord.id)
        .join(WorkOrder, CuttingRecord.work_order_id == WorkOrder.id)
        .where(WorkOrder.production_order_id.in_(production_order_ids))
    )
    packaging_ids = (
        select(PackagingRecord.id)
        .join(WorkOrder, PackagingRecord.work_order_id == WorkOrder.id)
        .where(WorkOrder.production_order_id.in_(production_order_ids))
    )
    reservation_ids = select(MaterialReservation.id).where(
        MaterialReservation.production_order_id.in_(production_order_ids)
    )
    linked_reference = or_(
        and_(StockMovement.reference_type == "ProductionOrder",
             StockMovement.reference_id.in_(production_order_ids)),
        and_(StockMovement.reference_type == "CuttingRecord",
             StockMovement.reference_id.in_(cutting_ids)),
        and_(StockMovement.reference_type == "PackagingRecord",
             StockMovement.reference_id.in_(packaging_ids)),
        and_(StockMovement.reference_type == "MaterialReservation",
             StockMovement.reference_id.in_(reservation_ids)),
    )
    rows = (
        db.query(StockMovement.quantity, StockMovement.unit_cost_at_movement,
                 StockMovement.cost_currency_at_movement)
        .filter(StockMovement.movement_type == "consume", linked_reference)
        .all()
    )
    # Older and batchless movements have no cost snapshot. Never price them
    # from a mutable batch or today's BOM and call the result historical profit.
    if not rows or any(cost is None or Decimal(str(cost)) < 0 for _, cost, _ in rows):
        return None, None
    currencies = {currency for _, _, currency in rows}
    cost_currency = next(iter(currencies)) if len(currencies) == 1 and None not in currencies else None
    return (sum(
        (Decimal(str(quantity)) * Decimal(str(cost)) for quantity, cost, _ in rows),
        Decimal("0"),
    ), cost_currency)


def _recorded_material_cost(db: Session, production_order_ids: set[int]) -> Decimal | None:
    return _recorded_material_cost_details(db, production_order_ids)[0]


def order_profit(db: Session, sales_order_id: int) -> dict:
    so = (
        db.query(SalesOrder)
        .options(
            load_only(SalesOrder.id, SalesOrder.order_no, SalesOrder.currency),
            selectinload(SalesOrder.items).load_only(
                SalesOrderItem.id,
                SalesOrderItem.sales_order_id,
                SalesOrderItem.quantity,
                SalesOrderItem.unit_price,
            ),
        )
        .filter(SalesOrder.id == sales_order_id)
        .first()
    )
    if not so:
        return {}
    # Keep intermediate money arithmetic exact; the public response remains
    # JSON-compatible floats for the existing finance clients.
    revenue = sum(
        (Decimal(str(i.quantity or 0)) * Decimal(str(i.unit_price or 0))
         for i in so.items),
        Decimal("0"),
    )
    pos = (
        db.query(ProductionOrder)
        .options(load_only(
            ProductionOrder.id,
            ProductionOrder.sales_order_id,
        ))
        .filter(ProductionOrder.sales_order_id == sales_order_id)
        .all()
    )
    cost, cost_currency = _recorded_material_cost_details(db, {int(po.id) for po in pos})
    waste = Decimal(str(db.query(func.coalesce(func.sum(WasteRecord.estimated_value), 0)).filter(
        WasteRecord.production_order_id.in_([p.id for p in pos]) if pos else False
    ).scalar() or 0))
    money_available = (
        so.currency is not None and cost_currency == so.currency and cost is not None and waste == 0
    )
    return {
        "sales_order_id": sales_order_id,
        "order_no": so.order_no,
        "currency": so.currency,
        "revenue": float(revenue) if so.currency else None,
        "material_cost": float(cost) if cost is not None and cost_currency == so.currency else None,
        "waste_cost": float(waste) if waste == 0 and so.currency else None,
        "gross_profit": float(revenue - cost) if money_available else None,
        "material_cost_basis": "transaction_snapshot" if cost is not None and cost_currency == so.currency else "unavailable",
    }


def dashboard_summary(db: Session) -> dict:
    revenue_amount, revenue_currency = revenue_summary(db)
    payment_amount, payment_currency = payments_summary(db)
    return {
        "revenue_total": revenue_amount,
        "revenue_currency": revenue_currency,
        "payments_received": payment_amount,
        "payments_currency": payment_currency,
        "branded_stock_value": None,
        "waste_cost": None,
        "waste_income": None,
    }


def count_invoices(db: Session) -> int:
    return int(db.query(func.count(Invoice.id)).scalar() or 0)


def list_recent_invoices(db: Session, limit: int = 50, offset: int = 0) -> list[dict]:
    """Return recent invoices with sales-order and customer labels for finance UI."""
    safe_limit = max(1, min(int(limit or 50), 500))
    safe_offset = max(0, int(offset or 0))
    rows = (
        db.query(Invoice, SalesOrder, Customer)
        .options(
            load_only(
                Invoice.id,
                Invoice.invoice_no,
                Invoice.sales_order_id,
                Invoice.amount,
                Invoice.currency,
                Invoice.status,
                Invoice.issued_at,
                Invoice.created_at,
            ),
            load_only(SalesOrder.id, SalesOrder.order_no),
            load_only(Customer.id, Customer.name),
        )
        .join(SalesOrder, SalesOrder.id == Invoice.sales_order_id)
        .outerjoin(Customer, Customer.id == SalesOrder.customer_id)
        .order_by(Invoice.id.desc())
        .offset(safe_offset)
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
                "currency": invoice.currency,
                "status": invoice.status,
                "date": dt.isoformat() if dt else None,
            }
        )
    return out


def _revenue_period_query(db: Session, *, from_dt: datetime | None = None, to_dt: datetime | None = None):
    from_dt, to_dt = as_utc(from_dt), as_utc(to_dt)
    timestamp = func.coalesce(Invoice.issued_at, Invoice.created_at)
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        period = func.to_char(timestamp, "YYYY-MM")
    else:
        period = func.strftime("%Y-%m", timestamp)
    qry = db.query(
        period.label("period"), func.count(Invoice.id), func.count(Invoice.currency),
        func.min(Invoice.currency), func.max(Invoice.currency),
        func.coalesce(func.sum(Invoice.amount), 0).label("amount"),
    )
    if from_dt:
        qry = qry.filter(timestamp >= from_dt)
    if to_dt:
        qry = qry.filter(timestamp <= to_dt)
    return (
        qry.filter(
            timestamp.isnot(None),
            Invoice.status.notin_(("void", "cancelled")),
        )
        .group_by(period)
        .order_by(period)
    )


def count_revenue_periods(db: Session, *, from_dt: datetime | None = None, to_dt: datetime | None = None) -> int:
    return int(_revenue_period_query(db, from_dt=from_dt, to_dt=to_dt).order_by(None).count())


def revenue_by_period(
    db: Session,
    *,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> list[dict]:
    """Aggregate invoice revenue by month for charting."""
    qry = _revenue_period_query(db, from_dt=from_dt, to_dt=to_dt)
    if limit is not None:
        qry = qry.offset(max(0, int(offset or 0))).limit(max(1, int(limit)))
    rows = qry.all()
    return [
        {
            "period": key,
            "amount": round(float(amount), 2) if count == known_count and lowest == highest else None,
            "currency": str(lowest) if count == known_count and lowest == highest else None,
        }
        for key, count, known_count, lowest, highest, amount in rows if key
    ]


def cost_breakdown(db: Session) -> dict:
    """Estimate COGS split into fabric, accessories, and labor components."""
    pos = db.query(ProductionOrder).options(
        load_only(ProductionOrder.id, ProductionOrder.model_id, ProductionOrder.planned_quantity),
    ).all()
    model_ids = {int(po.model_id) for po in pos if po.model_id}
    bom_rows = (
        db.query(ModelBOM)
        .options(
            load_only(
                ModelBOM.id,
                ModelBOM.model_id,
                ModelBOM.item_id,
                ModelBOM.quantity_per_piece,
                ModelBOM.waste_percent,
            ),
            noload(ModelBOM.item),
            noload(ModelBOM.stock_batch),
        )
        .filter(ModelBOM.model_id.in_(model_ids))
        .all()
        if model_ids
        else []
    )

    item_ids = {int(row.item_id) for row in bom_rows if row.item_id}
    item_rows = (
        db.query(Item)
        .options(load_only(Item.id, Item.category, Item.default_cost))
        .filter(Item.id.in_(item_ids))
        .all()
        if item_ids
        else []
    )
    item_map = {int(item.id): item for item in item_rows}

    latest_cost_by_item = _latest_stock_batch_costs(db, item_ids)

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

    labor_cost_decimal = Decimal(str(
        db.query(func.coalesce(func.sum(SalesOrder.planning_estimated_labor_cost), 0)).scalar() or 0
    ))
    total_cogs = fabric_cost + accessories_cost + labor_cost_decimal
    return {
        "fabric_cost": round(float(fabric_cost), 2),
        "labor_cost": round(float(labor_cost_decimal), 2),
        "accessories_cost": round(float(accessories_cost), 2),
        "total_cogs": round(float(total_cogs), 2),
    }
