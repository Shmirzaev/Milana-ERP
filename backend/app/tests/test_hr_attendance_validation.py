from datetime import datetime, timezone

import pytest
from sqlalchemy import event

from app.api.routes import hr_workspace
from app.db.session import SessionLocal
from app.models import AttendanceDevice, AttendanceEvent, Employee, SystemSetting
from app.services.attendance_reports import TASHKENT
from app.tests.conftest import test_engine


def _as_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _create_employee(employee_no: str, profile) -> int:
    with SessionLocal.begin() as db:
        employee = Employee(
            factory_code="MIL",
            employee_no=employee_no,
            full_name=f"Attendance employee {employee_no}",
            status="active",
            hr_profile_json=profile,
        )
        db.add(employee)
        db.flush()
        return employee.id


def _create_events(employee_no: str, *occurred_at: datetime) -> None:
    with SessionLocal.begin() as db:
        device = AttendanceDevice(
            factory_code="MIL",
            device_key=f"hr-day-boundary-{employee_no}",
            name="HR day boundary",
            vendor="Synthetic",
            read_only=True,
        )
        db.add(device)
        db.flush()
        for index, timestamp in enumerate(occurred_at):
            db.add(AttendanceEvent(
                factory_code="MIL",
                device_id=device.id,
                event_uid=f"hr-day-{employee_no}-{index}",
                external_person_id=employee_no,
                occurred_at=timestamp,
                received_at=timestamp,
                direction="unknown",
            ))


def _set_hr_settings(value) -> None:
    with SessionLocal.begin() as db:
        row = db.query(SystemSetting).filter(SystemSetting.key == "hr.settings.mil").first()
        if row is None:
            row = SystemSetting(key="hr.settings.mil", value_json=value)
            db.add(row)
        else:
            row.value_json = value


def test_hr_attendance_uses_tashkent_day_boundaries(client, auth_headers):
    _create_employee("810001", {})
    _create_events(
        "810001",
        datetime(2026, 8, 16, 19, 30, tzinfo=timezone.utc),
        datetime(2026, 8, 17, 18, 30, tzinfo=timezone.utc),
        datetime(2026, 8, 17, 19, 30, tzinfo=timezone.utc),
    )

    response = client.get(
        "/api/hr/attendance?day=2026-08-17&search=810001",
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    row = next(item for item in response.json()["rows"] if item["employee_no"] == "810001")
    assert _as_utc(row["arrival_at"]) == datetime(
        2026, 8, 16, 19, 30, tzinfo=timezone.utc,
    )
    assert _as_utc(row["departure_at"]) == datetime(
        2026, 8, 17, 18, 30, tzinfo=timezone.utc,
    )
    assert row["worked_minutes"] == 1380


def test_hr_attendance_omitted_day_uses_tashkent_today(client, auth_headers, monkeypatch):
    fixed_utc = datetime(2026, 8, 16, 20, 30, tzinfo=timezone.utc)

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_utc.astimezone(tz) if tz else fixed_utc.replace(tzinfo=None)

    monkeypatch.setattr(hr_workspace, "datetime", FrozenDatetime)

    response = client.get("/api/hr/attendance", headers=auth_headers)

    assert response.status_code == 200, response.text
    assert response.json()["day"] == fixed_utc.astimezone(TASHKENT).date().isoformat()


def test_hr_attendance_uses_one_factory_setting_and_safe_employee_overrides(client, auth_headers):
    _set_hr_settings({"default_workday_hours": 7.5})
    expected_minutes = {
        "810010": 450,
        "810011": 390,
        "810012": 450,
        "810013": 450,
        "810014": 450,
    }
    _create_employee("810010", {})
    _create_employee("810011", {"scheduled_daily_hours": "6.5"})
    _create_employee("810012", {"scheduled_daily_hours": "not-a-number"})
    _create_employee("810013", "legacy-non-object-profile")
    _create_employee("810014", {"scheduled_daily_hours": 10**500})
    statements = []

    def capture(_conn, _cursor, statement, _params, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(test_engine, "before_cursor_execute", capture)
    try:
        response = client.get(
            "/api/hr/attendance?day=2026-08-17&search=8100",
            headers=auth_headers,
        )
    finally:
        event.remove(test_engine, "before_cursor_execute", capture)

    assert response.status_code == 200, response.text
    rows = {row["employee_no"]: row for row in response.json()["rows"]}
    assert {number: rows[number]["scheduled_minutes"] for number in expected_minutes} == expected_minutes
    settings_reads = [statement for statement in statements if "FROM system_settings" in statement]
    assert len(settings_reads) == 1


@pytest.mark.parametrize(
    "field",
    ["default_workday_hours", "default_monthly_hours"],
)
def test_hr_settings_reject_nonfinite_raw_json_with_422(client, auth_headers, field):
    response = client.put(
        "/api/hr/settings",
        headers={**auth_headers, "Content-Type": "application/json"},
        content=f'{{"{field}":Infinity}}',
    )

    assert response.status_code == 422, response.text


@pytest.mark.parametrize(
    "legacy_value",
    [
        "not-an-object",
        {"default_workday_hours": "broken"},
        {"default_workday_hours": float("inf")},
    ],
)
def test_hr_settings_legacy_invalid_values_return_safe_defaults(client, auth_headers, legacy_value):
    _set_hr_settings(legacy_value)

    response = client.get("/api/hr/settings", headers=auth_headers)

    assert response.status_code == 200, response.text
    assert response.json()["default_workday_hours"] == 8
