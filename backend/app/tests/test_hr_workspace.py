from datetime import datetime, timezone


def test_hr_workspace_is_additive_and_factory_scoped(client, auth_headers):
    position = client.post(
        "/api/hr/positions",
        headers=auth_headers,
        json={
            "name": "Safety Test Operator",
            "required_skills": ["machine safety"],
            "approved_count": 3,
            "salary_min": 100,
            "salary_max": 200,
        },
    )
    assert position.status_code == 201, position.text
    position_id = position.json()["id"]

    employee = client.post(
        "/api/employees",
        headers=auth_headers,
        json={
            "employee_no": "991001",
            "full_name": "HR Workspace Test",
            "position": "Operator",
            "hr_position_id": position_id,
            "hr_profile_json": {
                "nationality": "Uzbekistan",
                "employment_type": "full_time",
                "scheduled_daily_hours": 8,
            },
        },
    )
    assert employee.status_code == 201, employee.text
    assert employee.json()["hr_profile_json"]["nationality"] == "Uzbekistan"

    staffing = client.get("/api/hr/positions", headers=auth_headers)
    assert staffing.status_code == 200
    row = next(item for item in staffing.json() if item["id"] == position_id)
    assert row["approved_count"] == 3
    assert row["occupied_count"] == 1
    assert row["vacant_count"] == 2

    dashboard = client.get("/api/hr/dashboard", headers=auth_headers)
    assert dashboard.status_code == 200
    assert dashboard.json()["headcount"] >= 1


def test_hr_calendar_recruitment_and_settings(client, auth_headers):
    candidate = client.post(
        "/api/hr/recruitment",
        headers=auth_headers,
        json={
            "full_name": "Karimov Aziz Bekzodovich",
            "last_name": "Karimov",
            "first_name": "Aziz",
            "middle_name": "Bekzodovich",
            "pinfl": "30101999012345",
            "passport_number": "AA1234567",
            "phone": "+998901234567",
            "country": "Uzbekistan",
            "region": "Tashkent",
            "stage": "screening",
        },
    )
    assert candidate.status_code == 201, candidate.text
    candidates = client.get("/api/hr/recruitment", headers=auth_headers)
    assert candidates.status_code == 200, candidates.text
    saved_candidate = next(row for row in candidates.json() if row["id"] == candidate.json()["id"])
    assert saved_candidate["pinfl"] == "30101999012345"
    assert saved_candidate["passport_number"] == "AA1234567"
    assert saved_candidate["first_name"] == "Aziz"

    event = client.post(
        "/api/hr/calendar",
        headers=auth_headers,
        json={
            "event_type": "training",
            "title": "Safety training",
            "starts_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    assert event.status_code == 201, event.text

    saved = client.put(
        "/api/hr/settings",
        headers=auth_headers,
        json={
            "company_name": "Milana Premium",
            "default_workday_hours": 8,
            "default_monthly_hours": 176,
            "probation_days": 90,
            "contract_warning_days": 30,
            "weekend_days": [6, 7],
        },
    )
    assert saved.status_code == 200, saved.text
    loaded = client.get("/api/hr/settings", headers=auth_headers)
    assert loaded.status_code == 200
    assert loaded.json()["default_monthly_hours"] == 176
