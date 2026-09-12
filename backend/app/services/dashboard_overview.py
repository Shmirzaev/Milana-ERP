"""Read-only management aggregates; production demand is independent of sales."""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import and_, case, func

from app.models import CuttingRecord, Department, PackagingRecord, PrintingRecord, ProductionOrder, SewingRecord, WorkOrder
from app.services.factory_scope import DEPARTMENT_FACTORIES, FACTORY_CODES, FACTORY_LABELS
from app.services.payroll_factory_scope import production_order_factory_condition
from app.models.sewing_daily_report import SewingDailyReport
from app.models import SewingFlow

ACTIVE_STATUSES = ("new", "planning", "waiting_material", "cutting", "printing", "sewing", "packaging", "storage_transfer")
STAGES = (
    ("cutting", CuttingRecord, CuttingRecord.passed_pieces),
    ("printing", PrintingRecord, PrintingRecord.passed_qty),
    ("sewing", SewingRecord, SewingRecord.passed_qty),
    ("packaging", PackagingRecord, PackagingRecord.packed_qty),
)


def overview(db, start: date, end: date, factory: str = "ALL"):
    if factory not in ("ALL", *FACTORY_CODES):
        raise ValueError("Unknown dashboard factory")
    tz = ZoneInfo("Asia/Tashkent")
    lower = datetime.combine(start, time.min, tzinfo=tz).astimezone(timezone.utc)
    upper = datetime.combine(end + timedelta(days=1), time.min, tzinfo=tz).astimezone(timezone.utc)
    scopes = ("ALL", *FACTORY_CODES, "UNASSIGNED")
    points_by_factory = {
        code: {(start + timedelta(days=i)).isoformat(): {key: 0 for key, _, _ in STAGES}
               for i in range((end - start).days + 1)} for code in scopes
    }
    totals_by_factory = {code: {key: 0 for key, _, _ in STAGES} for code in scopes}
    report_days = {day: {code: 0 for code in FACTORY_CODES} for day in points_by_factory["ALL"]}
    report_totals = {code: 0 for code in FACTORY_CODES}
    # This reporting ledger does not update stage completion. Keep it separate
    # and group by the report's business date, including backdated entries.
    report_query = db.query(
        SewingDailyReport.report_date, SewingFlow.factory_code,
        func.coalesce(func.sum(SewingDailyReport.sewn_qty), 0),
    ).join(SewingFlow, SewingFlow.id == SewingDailyReport.sewing_flow_id).filter(
        SewingDailyReport.report_date >= start, SewingDailyReport.report_date <= end,
        SewingFlow.factory_code.in_(FACTORY_CODES),
    )
    if factory != "ALL":
        report_query = report_query.filter(SewingFlow.factory_code == factory)
    for day, code, quantity in report_query.group_by(SewingDailyReport.report_date, SewingFlow.factory_code).all():
        report_days[str(day)][code] += int(quantity)
        report_totals[code] += int(quantity)
    # Output belongs to the department doing the work, not every factory an
    # order's bundles pass through. Outer joins preserve unattributed records.
    output_factory = case(DEPARTMENT_FACTORIES, value=func.upper(func.trim(Department.code)), else_="UNASSIGNED")
    for key, model, quantity in STAGES:
        # Group on the business day in SQL, not the server's UTC calendar date.
        day = (func.date(func.timezone("Asia/Tashkent", model.created_at))
               if db.bind.dialect.name == "postgresql"
               else func.date(model.created_at, "+5 hours"))
        query = db.query(day, output_factory, func.coalesce(func.sum(quantity), 0)).select_from(model).outerjoin(
            WorkOrder, WorkOrder.id == model.work_order_id,
        ).outerjoin(Department, Department.id == WorkOrder.department_id).filter(
            model.created_at >= lower, model.created_at < upper,
        )
        if key == "cutting":
            query = query.filter(CuttingRecord.approval_status == "approved")
        for stamp, code, value in query.group_by(day, output_factory).all():
            value = int(value or 0)
            for scope in ("ALL", code):
                points_by_factory[scope][str(stamp)][key] += value
                totals_by_factory[scope][key] += value

    active = db.query(ProductionOrder).filter(ProductionOrder.status.in_(ACTIVE_STATUSES))
    routing = {code: production_order_factory_condition(code) for code in FACTORY_CODES}
    aggregates = {}
    now = datetime.now(timezone.utc)
    for code in ("ALL", *FACTORY_CODES):
        query = active if code == "ALL" else active.filter(routing[code])
        rows = query.with_entities(
            ProductionOrder.status, func.count(ProductionOrder.id),
            func.coalesce(func.sum(ProductionOrder.planned_quantity), 0),
            func.sum(case((ProductionOrder.deadline < now, 1), else_=0)),
        ).group_by(ProductionOrder.status).all()
        aggregates[code] = {
            "active_orders": sum(row[1] for row in rows),
            "planned_quantity": sum(int(row[2]) for row in rows),
            "late_orders": sum(int(row[3]) for row in rows),
            "by_status": {row[0]: row[1] for row in rows},
        }
    unassigned = active.filter(and_(*(~condition for condition in routing.values()))).count()
    if factory != "ALL":
        active = active.filter(routing[factory])
    # Scalar selection avoids loading materials/batches for every dashboard row.
    orders = active.with_entities(
        ProductionOrder.id, ProductionOrder.production_no, ProductionOrder.production_type, ProductionOrder.source_type,
        ProductionOrder.status, ProductionOrder.planned_quantity, ProductionOrder.deadline,
        *(condition.label(f"factory_{code}") for code, condition in routing.items()),
    ).order_by(ProductionOrder.deadline.asc().nullslast(), ProductionOrder.id.desc()).limit(100).all()
    return {
        "start": start.isoformat(), "end": end.isoformat(), "timezone": "Asia/Tashkent",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "factory": factory, **aggregates[factory],
        "sewing_reports": {
            "totals": report_totals,
            "daily": [{"date": day, "values": values} for day, values in report_days.items()],
        },
        "factories": [{"code": code, "name": FACTORY_LABELS[code], **aggregates[code],
                       "totals": totals_by_factory[code]} for code in FACTORY_CODES],
        "unassigned_orders": unassigned,
        "unassigned_output": totals_by_factory["UNASSIGNED"],
        "totals": totals_by_factory[factory],
        "daily": [{"date": day, **values} for day, values in points_by_factory[factory].items()],
        "orders": [{"id": row.id, "order_no": row.production_no, "type": row.production_type, "source_type": row.source_type,
                    "status": row.status, "qty": row.planned_quantity,
                    "factories": [code for code in FACTORY_CODES if getattr(row, f"factory_{code}")],
                    "deadline": row.deadline.isoformat() if row.deadline else None} for row in orders],
        "orders_limit": 100,
    }
