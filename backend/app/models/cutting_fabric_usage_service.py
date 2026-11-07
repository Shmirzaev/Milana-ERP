"""Read-only fabric consumption backed by the cutting stock-movement ledger.

One row is one cutting record/material/batch/unit. Reservation consumption and
direct consumption can split that evidence into several movements; summing the
ledger once avoids joining/fanning out over reservations, BOM lines or bundles.
Cutting passport plans and customer-owned Usluga fabric are not stock usage.
"""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func, literal, or_, select, union_all
from sqlalchemy.orm import Session

from app.core.dt import as_utc
from app.core.order_reference import order_reference_contains
from app.core.pagination import clamp_pagination
from app.schemas import CuttingRecord, Department, Item, Model, ProductionOrder, SalesOrder, StockBatch, StockMovement, User, WorkOrder
from app.models.factory_scope_service import cutting_department_scope
from app.models.inventory_access_service import MATERIAL_CATEGORIES
from app.schemas.inventory.eco_inventory import EcoMaterialBatch, EcoMaterialMovement
from app.models.production.ect_passport_fabric_service import REVERSAL_REFERENCE


def _cutting_movement_source(department):
    if department != "ECT":
        return StockMovement, StockMovement
    reversal = EcoMaterialMovement.__table__.alias("eco_cutting_reversal")
    central = select(StockMovement.id, StockMovement.item_id, StockMovement.batch_id,
        StockMovement.unit, StockMovement.quantity, StockMovement.reference_id,
        StockMovement.movement_type, StockMovement.reference_type).where(
        StockMovement.movement_type == "consume", StockMovement.reference_type == "CuttingRecord")
    eco = select(EcoMaterialMovement.id, EcoMaterialBatch.item_id,
        EcoMaterialBatch.source_stock_batch_id.label("batch_id"), EcoMaterialBatch.unit,
        EcoMaterialMovement.quantity, EcoMaterialMovement.reference_id,
        literal("consume").label("movement_type"), literal("CuttingRecord").label("reference_type")).join(
        EcoMaterialBatch, EcoMaterialBatch.id == EcoMaterialMovement.batch_id,
    ).where(EcoMaterialMovement.kind == "consume", EcoMaterialMovement.reference_type == "CuttingRecord",
        EcoMaterialBatch.kind == "fabric", EcoMaterialBatch.source_stock_batch_id.isnot(None),
        ~select(reversal.c.id).where(reversal.c.reference_type == REVERSAL_REFERENCE,
            reversal.c.reference_id == EcoMaterialMovement.id).exists())
    ledger = union_all(central, eco).subquery("cutting_fabric_movements")
    return ledger, ledger.c


def cutting_fabric_usage(
    db: Session,
    user: User,
    *,
    q: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    item_id: int | None = None,
    batch_id: int | None = None,
    unit: str | None = None,
    cutting_department: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict:
    department = cutting_department_scope(user, cutting_department)
    if date_from and date_to and date_from > date_to:
        raise HTTPException(400, "Start date must not be after end date")
    page, page_size, offset = clamp_pagination(page, page_size, max_page_size=200)
    movement_source, movement = _cutting_movement_source(department)
    columns = [
        CuttingRecord.id.label("cutting_record_id"),
        CuttingRecord.cutting_batch_no,
        CuttingRecord.created_at.label("cutting_date"),
        ProductionOrder.id.label("production_order_id"),
        ProductionOrder.production_no,
        func.coalesce(SalesOrder.order_no, ProductionOrder.production_no).label("order_no"),
        Model.id.label("model_id"), Model.code.label("model_code"), Model.name.label("model_name"),
        Item.id.label("item_id"), Item.sku.label("item_sku"), Item.name.label("item_name"),
        movement.batch_id, StockBatch.batch_no, StockBatch.internal_batch_no, StockBatch.color,
        movement.unit,
    ]
    query = (
        select(*columns, func.sum(movement.quantity).label("quantity"), func.count(movement.id).label("movement_count"))
        .select_from(movement_source)
        .join(CuttingRecord, CuttingRecord.id == movement.reference_id)
        .join(WorkOrder, WorkOrder.id == CuttingRecord.work_order_id)
        .join(Department, Department.id == WorkOrder.department_id)
        .join(ProductionOrder, ProductionOrder.id == WorkOrder.production_order_id)
        .join(Model, Model.id == ProductionOrder.model_id)
        .join(Item, Item.id == movement.item_id)
        .outerjoin(StockBatch, StockBatch.id == movement.batch_id)
        .outerjoin(SalesOrder, SalesOrder.id == ProductionOrder.sales_order_id)
        .where(
            movement.movement_type == "consume",
            movement.reference_type == "CuttingRecord",
            movement.quantity > 0,
            CuttingRecord.approval_status == "approved",
            WorkOrder.operation == "cutting",
            Department.code == department,
            Item.category.in_(MATERIAL_CATEGORIES),
        )
    )
    # Calendar filters match the factory's displayed Tashkent date, including
    # records just before midnight UTC. Boundaries are half-open UTC instants.
    zone = ZoneInfo("Asia/Tashkent")
    if date_from:
        start = datetime.combine(date_from, time.min, tzinfo=zone).astimezone(timezone.utc)
        query = query.where(CuttingRecord.created_at >= start)
    if date_to:
        end = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=zone).astimezone(timezone.utc)
        query = query.where(CuttingRecord.created_at < end)
    if item_id is not None:
        query = query.where(movement.item_id == item_id)
    if batch_id is not None:
        query = query.where(movement.batch_id == batch_id)
    if unit is not None and unit.strip():
        query = query.where(movement.unit == unit.strip())
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        query = query.where(or_(
            order_reference_contains(ProductionOrder.production_no, pattern),
            order_reference_contains(SalesOrder.order_no, pattern),
            Model.code.ilike(pattern), Model.name.ilike(pattern),
            Item.sku.ilike(pattern), Item.name.ilike(pattern),
            StockBatch.batch_no.ilike(pattern), StockBatch.internal_batch_no.ilike(pattern),
            StockBatch.color.ilike(pattern), CuttingRecord.cutting_batch_no.ilike(pattern),
        ))
    query = query.group_by(*columns)
    grouped = query.subquery()
    total = db.scalar(select(func.count()).select_from(grouped)) or 0
    totals = db.execute(
        select(grouped.c.unit, func.sum(grouped.c.quantity).label("quantity"))
        .group_by(grouped.c.unit).order_by(grouped.c.unit)
    ).mappings().all()
    rows = db.execute(
        select(grouped).order_by(
            grouped.c.cutting_date.desc(), grouped.c.cutting_record_id.desc(),
            grouped.c.item_id, grouped.c.batch_id, grouped.c.unit,
        ).offset(offset).limit(page_size)
    ).mappings().all()
    payload = []
    for row in rows:
        value = dict(row)
        value.update(
            id=f"{row['cutting_record_id']}:{row['item_id']}:{row['batch_id'] or 0}:{row['unit']}",
            cutting_date=as_utc(row["cutting_date"]),
            quantity=float(row["quantity"]),
            evidence="stock_consumption",
        )
        payload.append(value)
    return {
        "rows": payload, "total": int(total), "page": page, "page_size": page_size,
        "totals": [{"unit": row["unit"], "quantity": float(row["quantity"])} for row in totals],
        "cutting_department": department,
    }
