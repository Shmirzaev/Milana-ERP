import pytest

from app.models import AuditLog, SystemSetting
from app.tests.conftest import TestSessionLocal


@pytest.mark.parametrize("weekend_days", [[0], [8], [6, 6], [True], ["6"]])
def test_hr_settings_reject_invalid_weekday_json_without_writes(
    client,
    auth_headers,
    weekend_days,
):
    with TestSessionLocal() as db:
        before_audits = db.query(AuditLog).filter(
            AuditLog.entity_type == "HrSettings",
        ).count()

    response = client.put(
        "/api/hr/settings",
        headers=auth_headers,
        json={"weekend_days": weekend_days},
    )

    assert response.status_code == 422, response.text
    with TestSessionLocal() as db:
        assert db.query(SystemSetting).filter(
            SystemSetting.key == "hr.settings.mil",
        ).one_or_none() is None
        assert db.query(AuditLog).filter(
            AuditLog.entity_type == "HrSettings",
        ).count() == before_audits


def test_hr_settings_store_valid_iso_weekday_json(client, auth_headers):
    response = client.put(
        "/api/hr/settings",
        headers=auth_headers,
        json={"weekend_days": [5, 6, 7]},
    )

    assert response.status_code == 200, response.text
    assert response.json()["weekend_days"] == [5, 6, 7]

    with TestSessionLocal() as db:
        row = db.query(SystemSetting).filter(
            SystemSetting.key == "hr.settings.mil",
        ).one()
        assert row.value_json["weekend_days"] == [5, 6, 7]


def test_hr_settings_keep_legacy_weekday_json_readable(client, auth_headers):
    with TestSessionLocal() as db:
        row = SystemSetting(key="hr.settings.mil", value_json={"weekend_days": [0, 8, 8]})
        db.add(row)
        db.commit()

    response = client.get("/api/hr/settings", headers=auth_headers)

    assert response.status_code == 200, response.text
    assert response.json()["weekend_days"] == [0, 8, 8]


def test_hr_settings_allow_unrelated_edit_with_unchanged_legacy_days(client, auth_headers):
    with TestSessionLocal() as db:
        db.add(SystemSetting(key="hr.settings.mil", value_json={"weekend_days": [0, 8, 8]}))
        db.commit()

    loaded = client.get("/api/hr/settings", headers=auth_headers)
    assert loaded.status_code == 200, loaded.text
    payload = loaded.json()
    payload["company_name"] = "Updated HR Company"

    updated = client.put("/api/hr/settings", headers=auth_headers, json=payload)

    assert updated.status_code == 200, updated.text
    assert updated.json()["company_name"] == "Updated HR Company"
    assert updated.json()["weekend_days"] == [0, 8, 8]


def test_hr_settings_reject_changed_legacy_days_without_writes(client, auth_headers):
    with TestSessionLocal() as db:
        row = SystemSetting(key="hr.settings.mil", value_json={"weekend_days": [0, 8, 8]})
        db.add(row)
        db.commit()
        before_audits = db.query(AuditLog).filter(
            AuditLog.entity_type == "HrSettings",
        ).count()
        before_value = row.value_json

    response = client.put(
        "/api/hr/settings",
        headers=auth_headers,
        json={"company_name": "Must Not Save", "weekend_days": [0, 8, 7]},
    )

    assert response.status_code == 422, response.text
    with TestSessionLocal() as db:
        row = db.query(SystemSetting).filter(
            SystemSetting.key == "hr.settings.mil",
        ).one()
        assert row.value_json == before_value
        assert db.query(AuditLog).filter(
            AuditLog.entity_type == "HrSettings",
        ).count() == before_audits


def test_hr_settings_reject_oversized_new_company_name_without_writes(client, auth_headers):
    with TestSessionLocal() as db:
        before_audits = db.query(AuditLog).filter(AuditLog.entity_type == "HrSettings").count()

    response = client.put(
        "/api/hr/settings",
        headers=auth_headers,
        json={"company_name": "Ж" * (8 * 1024 + 1)},
    )

    assert response.status_code == 422, response.text
    assert "UTF-8 bytes" in response.text
    with TestSessionLocal() as db:
        assert db.query(SystemSetting).filter_by(key="hr.settings.mil").one_or_none() is None
        assert db.query(AuditLog).filter(AuditLog.entity_type == "HrSettings").count() == before_audits


def test_hr_settings_allow_unchanged_oversized_legacy_but_reject_changed_document(client, auth_headers):
    legacy = {
        "company_name": "Ж" * (8 * 1024 + 1),
        "default_workday_hours": 8.0,
        "default_monthly_hours": 176.0,
        "probation_days": 90,
        "contract_warning_days": 30,
        "weekend_days": [6, 7],
    }
    with TestSessionLocal() as db:
        db.add(SystemSetting(key="hr.settings.mil", value_json=legacy))
        db.commit()

    loaded = client.get("/api/hr/settings", headers=auth_headers)
    assert loaded.status_code == 200, loaded.text
    unchanged = client.put("/api/hr/settings", headers=auth_headers, json=loaded.json())
    assert unchanged.status_code == 200, unchanged.text
    assert unchanged.json()["company_name"] == legacy["company_name"]
    with TestSessionLocal() as db:
        row = db.query(SystemSetting).filter_by(key="hr.settings.mil").one()
        assert row.value_json["company_name"] == legacy["company_name"]
        before_audits = db.query(AuditLog).filter(AuditLog.entity_type == "HrSettings").count()
        before_value = row.value_json

    changed = client.put(
        "/api/hr/settings",
        headers=auth_headers,
        json={**loaded.json(), "probation_days": 91},
    )

    assert changed.status_code == 422, changed.text
    assert "UTF-8 bytes" in changed.text
    with TestSessionLocal() as db:
        row = db.query(SystemSetting).filter_by(key="hr.settings.mil").one()
        assert row.value_json == before_value
        assert db.query(AuditLog).filter(AuditLog.entity_type == "HrSettings").count() == before_audits


def test_hr_settings_reject_changed_document_with_deep_unchanged_legacy_weekend_value(client, auth_headers):
    legacy_weekend_days: list = [6]
    for _ in range(17):
        legacy_weekend_days = [legacy_weekend_days]
    legacy = {
        "company_name": "Legacy HR",
        "default_workday_hours": 8.0,
        "default_monthly_hours": 176.0,
        "probation_days": 90,
        "contract_warning_days": 30,
        "weekend_days": legacy_weekend_days,
    }
    with TestSessionLocal() as db:
        db.add(SystemSetting(key="hr.settings.mil", value_json=legacy))
        db.commit()
        before_audits = db.query(AuditLog).filter(AuditLog.entity_type == "HrSettings").count()

    changed = client.put(
        "/api/hr/settings",
        headers=auth_headers,
        json={**legacy, "company_name": "Must not save"},
    )

    assert changed.status_code == 422, changed.text
    assert "nested container levels" in changed.text
    with TestSessionLocal() as db:
        row = db.query(SystemSetting).filter_by(key="hr.settings.mil").one()
        assert row.value_json == legacy
        assert db.query(AuditLog).filter(AuditLog.entity_type == "HrSettings").count() == before_audits
