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
