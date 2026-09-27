from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.db.session import SessionLocal
from app.models import AttendanceDevice, AttendanceEvent, Employee


DAY = "2026-08-17"
PAGE_SIZE = 50


@pytest.mark.parametrize("employee_count", [1, 50, 401])
def test_hr_attendance_returns_searchable_bounded_pages_and_exact_global_metrics(
    client,
    auth_headers,
    employee_count,
):
    marker = f"PAGE{uuid4().hex[:10]}"
    search = f"{marker}%"
    before = client.get(
        "/api/hr/attendance",
        params={"day": DAY},
        headers=auth_headers,
    )
    assert before.status_code == 200, before.text
    before_summary = before.json()["summary"]

    with SessionLocal.begin() as db:
        device = AttendanceDevice(
            factory_code="MIL",
            device_key=f"hr-page-{marker.lower()}",
            name="HR attendance page fixture",
            vendor="Synthetic",
            read_only=True,
        )
        db.add(device)
        db.flush()
        employees = [
            Employee(
                factory_code="MIL",
                employee_no=f"{marker}-{index:04d}",
                full_name=f"HR attendance {marker}% {index:04d}",
                status="active",
                hr_profile_json={},
            )
            for index in range(employee_count)
        ]
        db.add_all(employees)
        employee_no = employees[0].employee_no
        first = datetime(2026, 8, 17, 3, tzinfo=timezone.utc)
        last = datetime(2026, 8, 17, 13, tzinfo=timezone.utc)
        db.add_all([
            AttendanceEvent(
                factory_code="MIL",
                device_id=device.id,
                event_uid=f"hr-page-{marker}-first",
                external_person_id=employee_no,
                occurred_at=first,
                received_at=first,
                direction="unknown",
                result="success",
            ),
            AttendanceEvent(
                factory_code="MIL",
                device_id=device.id,
                event_uid=f"hr-page-{marker}-last",
                external_person_id=employee_no,
                occurred_at=last,
                received_at=last,
                direction="unknown",
                result="success",
            ),
        ])

    def get_page(page: int):
        return client.get(
            "/api/hr/attendance",
            params={"day": DAY, "search": search, "page": page, "page_size": PAGE_SIZE},
            headers=auth_headers,
        )

    response = get_page(1)
    assert response.status_code == 200, response.text
    first_page = response.json()
    assert first_page["search"] == search
    assert first_page["total"] == employee_count
    assert first_page["page"] == 1
    assert first_page["page_size"] == PAGE_SIZE
    assert len(first_page["rows"]) == min(PAGE_SIZE, employee_count)
    assert first_page["has_more"] is (employee_count > PAGE_SIZE)
    assert all(search in row["full_name"] for row in first_page["rows"])

    summary = first_page["summary"]
    assert summary["employees"] == before_summary["employees"] + employee_count
    assert summary["present"] == before_summary["present"] + 1
    assert summary["absent"] == before_summary["absent"] + employee_count - 1
    assert summary["overtime_minutes"] == before_summary["overtime_minutes"] + 120

    rows = list(first_page["rows"])
    page = 2
    while first_page["has_more"] and page <= (employee_count + PAGE_SIZE - 1) // PAGE_SIZE:
        response = get_page(page)
        assert response.status_code == 200, response.text
        current = response.json()
        assert current["total"] == employee_count
        assert current["summary"] == summary
        assert current["page"] == page
        assert len(current["rows"]) <= PAGE_SIZE
        rows.extend(current["rows"])
        first_page = current
        page += 1

    assert len(rows) == employee_count
    assert len({row["employee_id"] for row in rows}) == employee_count
    marked = next(row for row in rows if row["employee_no"] == f"{marker}-0000")
    assert marked["worked_minutes"] == 600
    assert marked["scheduled_minutes"] == 480
    assert marked["variance_minutes"] == 120
    assert marked["status"] == "present"


def test_hr_attendance_pagination_still_requires_hr_authorization(client):
    response = client.get("/api/hr/attendance?page=1&page_size=50")

    assert response.status_code == 401
