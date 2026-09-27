import pytest

from app.db.session import SessionLocal
from app.models import AuditLog, SystemSetting


def _seed_preferences(value: dict) -> None:
    with SessionLocal() as db:
        row = db.query(SystemSetting).filter_by(key="preferences").one_or_none()
        if row:
            row.value_json = value
        else:
            db.add(SystemSetting(key="preferences", value_json=value))
        db.commit()


def _state() -> tuple[dict | None, int]:
    with SessionLocal() as db:
        row = db.query(SystemSetting).filter_by(key="preferences").one_or_none()
        return (row.value_json if row else None, db.query(AuditLog).count())


@pytest.mark.parametrize("language", ["en", "ru", "uz"])
def test_preferences_accept_every_established_language(client, auth_headers, language):
    response = client.patch(
        "/api/settings/preferences",
        headers=auth_headers,
        json={"default_language": language},
    )

    assert response.status_code == 200, response.text
    assert response.json()["default_language"] == language
    assert _state()[0]["default_language"] == language


def test_preferences_patch_keeps_omitted_language_compatibility(client, auth_headers):
    _seed_preferences({
        "default_language": "ru",
        "timezone": "UTC",
        "model_types": ["Dress"],
        "require_material_reservation_before_cutting": False,
    })

    response = client.patch(
        "/api/settings/preferences",
        headers=auth_headers,
        json={"timezone": "Asia/Tashkent"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["default_language"] == "ru"
    assert response.json()["timezone"] == "Asia/Tashkent"


def test_invalid_language_does_not_write_settings_or_audit(client, auth_headers):
    _seed_preferences({
        "default_language": "uz",
        "timezone": "Asia/Tashkent",
        "model_types": ["Dress"],
        "require_material_reservation_before_cutting": True,
    })
    before = _state()

    response = client.patch(
        "/api/settings/preferences",
        headers=auth_headers,
        json={"default_language": "klingon"},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid default_language"}
    assert _state() == before


def test_authentication_precedes_language_validation(client):
    response = client.patch(
        "/api/settings/preferences",
        json={"default_language": "klingon"},
    )

    assert response.status_code == 401


def test_permission_denial_precedes_language_validation(client):
    login = client.post(
        "/api/auth/token",
        data={"username": "hr@example.com", "password": "demo12345"},
    )
    assert login.status_code == 200, login.text

    response = client.patch(
        "/api/settings/preferences",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        json={"default_language": "klingon"},
    )

    assert response.status_code == 403


def test_missing_section_and_unknown_field_precede_language_validation(client, auth_headers):
    missing = client.patch(
        "/api/settings/missing",
        headers=auth_headers,
        json={"default_language": "klingon"},
    )
    unknown = client.patch(
        "/api/settings/preferences",
        headers=auth_headers,
        json={"default_language": "klingon", "unexpected": True},
    )

    assert missing.status_code == 404
    assert missing.json() == {"detail": "Settings section not found"}
    assert unknown.status_code == 422
    assert unknown.json()["detail"][0]["loc"] == ["body", "unexpected"]
