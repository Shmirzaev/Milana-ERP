from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.db.session import SessionLocal
from app.models import AttendanceDevice, AttendanceEvent, Employee
from app.tests.conftest import test_engine


@pytest.mark.parametrize("scan_count", [1, 50, 401])
def test_hr_attendance_aggregates_scans_in_sql(client, auth_headers, scan_count):
    marker = uuid4().hex[:10]
    employee_no = f"PERF35-{marker}"
    first_scan = datetime(2026, 8, 17, 4, tzinfo=timezone.utc)
    with SessionLocal.begin() as db:
        db.add(Employee(
            factory_code="MIL",
            employee_no=employee_no,
            full_name=f"Attendance {marker}",
            status="active",
            hr_profile_json={},
        ))
        device = AttendanceDevice(
            factory_code="MIL",
            device_key=f"perf35-hr-{marker}",
            name="PERF35 query growth fixture",
            vendor="Synthetic",
            read_only=True,
        )
        db.add(device)
        db.flush()
        db.add_all([
            AttendanceEvent(
                factory_code="MIL",
                device_id=device.id,
                event_uid=f"perf35-hr-{marker}-{index:04d}",
                external_person_id=employee_no,
                occurred_at=first_scan + timedelta(minutes=index),
                received_at=first_scan + timedelta(minutes=index),
                direction="unknown",
                result="success",
            )
            for index in range(scan_count)
        ])

    statements: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(" ".join(statement.lower().split()))

    event.listen(test_engine, "before_cursor_execute", capture)
    try:
        response = client.get("/api/hr/attendance?day=2026-08-17", headers=auth_headers)
    finally:
        event.remove(test_engine, "before_cursor_execute", capture)

    assert response.status_code == 200, response.text
    row = next(item for item in response.json()["rows"] if item["employee_no"] == employee_no)
    assert row["arrival_at"] == first_scan.replace(tzinfo=None).isoformat()
    expected_departure = first_scan + timedelta(minutes=scan_count - 1) if scan_count > 1 else None
    assert row["departure_at"] == (
        expected_departure.replace(tzinfo=None).isoformat() if expected_departure else None
    )
    assert row["worked_minutes"] == max(0, scan_count - 1)
    event_reads = [statement for statement in statements if " from attendance_events " in statement]
    print(f"HR attendance {scan_count} scans: {len(event_reads)} event SELECT")
    assert len(event_reads) == 1
    assert "group by attendance_events.external_person_id" in event_reads[0]
    employee_reads = [statement for statement in statements if " from employees " in statement]
    assert len(employee_reads) == 1, statements
    selected_columns = employee_reads[0].split(" from employees", 1)[0]
    for needed in (
        "employees.id",
        "employees.employee_no",
        "employees.full_name",
        "employees.hr_profile_json",
    ):
        assert needed in selected_columns
    for unrelated in (
        "employees.salary",
        "employees.phone",
        "employees.user_id",
        "employees.position",
    ):
        assert unrelated not in selected_columns
