from datetime import datetime, timezone, timedelta, time
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends
from sqlalchemy import func

from app.core.deps import DbSession, CurrentUser
from app.models import (
    SalesOrder, ProductionOrder, WorkOrder, Bundle, Package, WasteRecord, FinishedGoodsStock,
    Item, StockBatch, CuttingRecord, SewingRecord, PrintingRecord, PackagingRecord,
)
from app.services.finance import dashboard_summary, branded_stock_value
from app.services.inventory import stock_summary

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/management")
def management(db: DbSession, _: CurrentUser, tz: str | None = None):
    now = datetime.now(timezone.utc)
    try:
        client_tz = ZoneInfo(tz) if tz else timezone.utc
    except Exception:
        client_tz = timezone.utc
    today_local = now.astimezone(client_tz).date()
    start_local = datetime.combine(today_local, time.min, tzinfo=client_tz)
    end_local = start_local + timedelta(days=1)
    start_utc = start_local.astimezone(timezone.utc)
    end_utc = end_local.astimezone(timezone.utc)

    active_orders = db.query(func.count(SalesOrder.id)).filter(
        SalesOrder.status.in_(["confirmed", "pending_sales_approval", "planning_approved", "planning", "production", "ready"])
    ).scalar() or 0
    late_orders = db.query(func.count(SalesOrder.id)).filter(SalesOrder.deadline < now, SalesOrder.status.not_in(["delivered", "closed", "cancelled"])).scalar() or 0
    todays_defects = (
        db.query(func.coalesce(func.sum(SewingRecord.failed_qty + SewingRecord.rejected_qty), 0))
        .filter(SewingRecord.created_at >= start_utc, SewingRecord.created_at < end_utc)
        .scalar()
        or 0
    )
    todays_waste = (
        db.query(func.coalesce(func.sum(WasteRecord.quantity), 0))
        .filter(WasteRecord.created_at >= start_utc, WasteRecord.created_at < end_utc)
        .scalar()
        or 0
    )
    return {
        "active_orders": int(active_orders),
        "late_orders": int(late_orders),
        "todays_defects": float(todays_defects),
        "todays_waste": float(todays_waste),
        "branded_stock_value": branded_stock_value(db),
    }


@router.get("/planning")
def planning(db: DbSession, _: CurrentUser):
    return {
        "orders_waiting_planning": db.query(func.count(SalesOrder.id)).filter(
            SalesOrder.status.in_(["confirmed", "planning_approved"])
        ).scalar() or 0,
        "active_production_orders": db.query(func.count(ProductionOrder.id)).filter(ProductionOrder.status.in_(["new", "planning", "waiting_material", "cutting", "printing", "sewing", "packaging"])).scalar() or 0,
        "branded_plans": db.query(func.count(ProductionOrder.id)).filter(ProductionOrder.production_type == "branded_stock").scalar() or 0,
    }


@router.get("/production")
def production(db: DbSession, _: CurrentUser):
    return {
        "cutting_output": int(db.query(func.coalesce(func.sum(CuttingRecord.passed_pieces), 0)).scalar() or 0),
        "printing_output": int(db.query(func.coalesce(func.sum(PrintingRecord.passed_qty), 0)).scalar() or 0),
        "sewing_output": int(db.query(func.coalesce(func.sum(SewingRecord.passed_qty), 0)).scalar() or 0),
        "packaging_output": int(db.query(func.coalesce(func.sum(PackagingRecord.packed_qty), 0)).scalar() or 0),
        "rework_qty": int(db.query(func.coalesce(func.sum(SewingRecord.rework_qty), 0)).scalar() or 0),
        "active_work_orders": db.query(func.count(WorkOrder.id)).filter(WorkOrder.status == "in_progress").scalar() or 0,
    }


@router.get("/finance")
def finance(db: DbSession, _: CurrentUser):
    return dashboard_summary(db)


@router.get("/waste")
def waste(db: DbSession, _: CurrentUser):
    rows = db.query(WasteRecord.status, func.coalesce(func.sum(WasteRecord.quantity), 0)).group_by(WasteRecord.status).all()
    by_status = {s: float(q or 0) for s, q in rows}
    return {
        "by_status": by_status,
        "sellable_count": db.query(func.count(WasteRecord.id)).filter(WasteRecord.sellable.is_(True)).scalar() or 0,
        "non_sellable_count": db.query(func.count(WasteRecord.id)).filter(WasteRecord.sellable.is_(False)).scalar() or 0,
    }


@router.get("/inventory")
def inventory(db: DbSession, _: CurrentUser):
    summary = stock_summary(db)
    fg_total = int(db.query(func.coalesce(func.sum(FinishedGoodsStock.available_qty), 0)).scalar() or 0)
    return {
        "items": summary[:50],
        "finished_goods_total": fg_total,
        "branded_stock_value": branded_stock_value(db),
    }
