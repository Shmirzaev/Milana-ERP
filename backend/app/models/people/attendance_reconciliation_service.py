"""HR attendance reconciliation; this read operation never commits."""

from collections.abc import Callable
from datetime import date, datetime

from sqlalchemy.orm import Session

from app.models.attendance_event_policy_service import accepted_attendance_result
from app.models.attendance_reports_service import TASHKENT
from app.models.factory_scope_service import selected_factory_code
from app.schemas import AttendanceEvent, Employee, User


def hr_attendance(
    db: Session, current: User, day: date | None = None, *,
    load_hr_settings: Callable, scheduled_minutes: Callable,
    day_bounds: Callable, clock: type[datetime],
):
    factory = selected_factory_code(current); selected = day or clock.now(TASHKENT).date()
    start, end = day_bounds(selected)
    default_hours = load_hr_settings(db, factory).default_workday_hours
    employees = db.query(Employee).filter(Employee.factory_code == factory, Employee.status == "active").all()
    events = db.query(AttendanceEvent).filter(
        AttendanceEvent.factory_code == factory,
        AttendanceEvent.occurred_at >= start,
        AttendanceEvent.occurred_at < end,
        accepted_attendance_result(AttendanceEvent.result),
    ).order_by(AttendanceEvent.occurred_at).all()
    grouped: dict[str, list[AttendanceEvent]] = {}
    for event in events:
        if event.external_person_id: grouped.setdefault(event.external_person_id, []).append(event)
    rows = []
    for employee in employees:
        scans = grouped.get(str(employee.employee_no or ""), [])
        first = scans[0].occurred_at if scans else None; last = scans[-1].occurred_at if len(scans) > 1 else None
        worked = max(0, int((last - first).total_seconds() // 60)) if first and last else 0
        scheduled = scheduled_minutes(employee.hr_profile_json, default_hours)
        rows.append({"employee_id": employee.id, "employee_no": employee.employee_no, "full_name": employee.full_name, "arrival_at": first, "departure_at": last, "worked_minutes": worked, "scheduled_minutes": scheduled, "variance_minutes": worked - scheduled, "status": "present" if scans else "absent"})
    return {"day": selected, "summary": {"employees": len(rows), "present": sum(1 for row in rows if row["status"] == "present"), "absent": sum(1 for row in rows if row["status"] == "absent"), "overtime_minutes": sum(max(0, row["variance_minutes"]) for row in rows)}, "rows": rows}
