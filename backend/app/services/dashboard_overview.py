"""Read-only management aggregates; production demand is independent of sales."""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func

from app.models import CuttingRecord, PackagingRecord, PrintingRecord, ProductionOrder, SewingRecord

ACTIVE_STATUSES = ("new", "planning", "waiting_material", "cutting", "printing", "sewing", "packaging", "storage_transfer")
STAGES = (
    ("cutting", CuttingRecord, CuttingRecord.passed_pieces),
    ("printing", PrintingRecord, PrintingRecord.passed_qty),
    ("sewing", SewingRecord, SewingRecord.passed_qty),
    ("packaging", PackagingRecord, PackagingRecord.packed_qty),
)


def overview(db, start: date, end: date):
    tz = ZoneInfo("Asia/Tashkent")
    lower = datetime.combine(start, time.min, tzinfo=tz).astimezone(timezone.utc)
    upper = datetime.combine(end + timedelta(days=1), time.min, tzinfo=tz).astimezone(timezone.utc)
    points = {(start + timedelta(days=i)).isoformat(): {key: 0 for key, _, _ in STAGES}
              for i in range((end - start).days + 1)}
    totals = {}
    for key, model, quantity in STAGES:
        # Group on the business day in SQL, not the server's UTC calendar date.
        day = (func.date(func.timezone("Asia/Tashkent", model.created_at))
               if db.bind.dialect.name == "postgresql"
               else func.date(model.created_at, "+5 hours"))
        query = db.query(day, func.coalesce(func.sum(quantity), 0)).filter(
            model.created_at >= lower, model.created_at < upper,
        )
        if key == "cutting":
            query = query.filter(CuttingRecord.approval_status == "approved")
        totals[key] = 0
        for stamp, value in query.group_by(day).all():
            value = int(value or 0)
            points[str(stamp)][key] = value
            totals[key] += value

    active = db.query(ProductionOrder).filter(ProductionOrder.status.in_(ACTIVE_STATUSES))
    statuses = dict(db.query(ProductionOrder.status, func.count(ProductionOrder.id)).filter(
        ProductionOrder.status.in_(ACTIVE_STATUSES),
    ).group_by(ProductionOrder.status).all())
    late = active.filter(ProductionOrder.deadline < datetime.now(timezone.utc)).count()
    planned = active.with_entities(func.coalesce(func.sum(ProductionOrder.planned_quantity), 0)).scalar()
    # Scalar selection avoids loading materials/batches for every dashboard row.
    orders = active.with_entities(
        ProductionOrder.id, ProductionOrder.production_no, ProductionOrder.production_type, ProductionOrder.source_type,
        ProductionOrder.status, ProductionOrder.planned_quantity, ProductionOrder.deadline,
    ).order_by(ProductionOrder.deadline.asc().nullslast(), ProductionOrder.id.desc()).limit(100).all()
    return {
        "start": start.isoformat(), "end": end.isoformat(), "timezone": "Asia/Tashkent",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "active_orders": sum(statuses.values()), "late_orders": late,
        "planned_quantity": int(planned or 0), "by_status": statuses,
        "totals": totals, "daily": [{"date": day, **values} for day, values in points.items()],
        "orders": [{"id": row.id, "order_no": row.production_no, "type": row.production_type, "source_type": row.source_type,
                    "status": row.status, "qty": row.planned_quantity,
                    "deadline": row.deadline.isoformat() if row.deadline else None} for row in orders],
        "orders_limit": 100,
    }
