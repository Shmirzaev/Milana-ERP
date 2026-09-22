from datetime import datetime, timedelta, timezone


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

    limited = client.get("/api/hr/recruitment?limit=1", headers=auth_headers)
    assert limited.status_code == 200, limited.text
    assert len(limited.json()) == 1
    assert client.get("/api/hr/recruitment?limit=501", headers=auth_headers).status_code == 422

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


def test_hr_documents_pagination_preserves_legacy_rows_and_metrics(client, auth_headers, tmp_path, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "HR_DOCUMENTS_DIR", str(tmp_path))
    employee_ids = []
    for index in range(3):
        response = client.post(
            "/api/employees",
            headers=auth_headers,
            json={"employee_no": f"990000{index}", "full_name": f"Document Employee {index}"},
        )
        assert response.status_code == 201, response.text
        employee_ids.append(response.json()["id"])
        uploaded = client.post(
            "/api/hr/documents",
            headers=auth_headers,
            data={"employee_id": employee_ids[-1], "category": "other", "title": f"Doc {index}"},
            files={"file": (f"doc-{index}.txt", b"abc", "text/plain")},
        )
        assert uploaded.status_code == 201, uploaded.text

    legacy = client.get("/api/hr/documents", headers=auth_headers)
    assert legacy.status_code == 200 and isinstance(legacy.json(), list)
    page = client.get("/api/hr/documents?page=1&page_size=2", headers=auth_headers)
    assert page.status_code == 200, page.text
    body = page.json()
    assert [row["title"] for row in body["rows"]] == ["Doc 2", "Doc 1"]
    assert body["total"] == 3 and body["has_more"] is True
    assert body["metrics"]["employee_folders"] == 3
    assert body["metrics"]["archive_size_bytes"] == 9
    assert body["metrics"]["expiring_in_30_days"] == 0
    empty = client.get("/api/hr/documents?page=3&page_size=2", headers=auth_headers)
    assert empty.status_code == 200 and empty.json()["rows"] == []
    assert empty.json()["total"] == 3 and empty.json()["has_more"] is False


def test_hr_calendar_pagination_preserves_legacy_rows_and_global_metrics(client, auth_headers):
    now = datetime.now(timezone.utc)
    events = [
        ("Past probation", "probation_end", now - timedelta(days=2), "scheduled"),
        ("Future training", "training", now + timedelta(days=1), "scheduled"),
        ("Future contract", "contract_expiry", now + timedelta(days=2), "scheduled"),
        ("Completed training", "training", now + timedelta(days=3), "completed"),
    ]
    for title, event_type, starts_at, status in events:
        response = client.post(
            "/api/hr/calendar",
            headers=auth_headers,
            json={
                "title": title,
                "event_type": event_type,
                "starts_at": starts_at.isoformat(),
                "status": status,
            },
        )
        assert response.status_code == 201, response.text

    legacy = client.get("/api/hr/calendar", headers=auth_headers)
    assert legacy.status_code == 200 and isinstance(legacy.json(), list)
    assert [row["title"] for row in legacy.json()] == [title for title, *_rest in events]

    first = client.get("/api/hr/calendar?page=1&page_size=2", headers=auth_headers)
    assert first.status_code == 200, first.text
    body = first.json()
    assert [row["title"] for row in body["rows"]] == ["Past probation", "Future training"]
    assert body["total"] == 4 and body["has_more"] is True
    assert body["metrics"] == {
        "upcoming": 2,
        "contracts_expiring": 1,
        "probation_ending": 0,
        "training": 1,
    }

    empty = client.get("/api/hr/calendar?page=3&page_size=2", headers=auth_headers)
    assert empty.status_code == 200 and empty.json()["rows"] == []
    assert empty.json()["total"] == 4 and empty.json()["has_more"] is False
