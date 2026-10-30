"""Partial settings updates preserve omitted fields and reject malformed input."""

from io import BytesIO

import pytest
from PIL import Image

from app.api.routes import settings as settings_routes
from app.libs.dto.support.company_info_input import CompanyInfoUpdate
from app.libs.dto.support.financial_settings_input import FinancialSettingsUpdate
from app.libs.dto.support.system_preferences_input import SystemPreferencesUpdate
from app.libs.dto.support.company_info_output import CompanyInfoOut
from app.libs.dto.support.financial_settings_output import FinancialSettingsOut
from app.libs.dto.support.system_preferences_output import SystemPreferencesOut
from app.models.support import settings_service
from app.schemas import AuditLog, SystemSetting
from app.tests.conftest import TestSessionLocal


_SECTION_MODELS = {
    "company_info": (CompanyInfoUpdate, CompanyInfoOut),
    "financial": (FinancialSettingsUpdate, FinancialSettingsOut),
    "preferences": (SystemPreferencesUpdate, SystemPreferencesOut),
}


def _default_json(section):
    return _SECTION_MODELS[section][1]().model_dump(mode="json")


def _patch_model(section, payload):
    return _SECTION_MODELS[section][0](**payload)


def _seed(section, value):
    with TestSessionLocal() as db:
        row = db.query(SystemSetting).filter_by(key=section).first()
        if row:
            row.value_json = value
        else:
            db.add(SystemSetting(key=section, value_json=value))
        db.commit()


def _state():
    with TestSessionLocal() as db:
        return ({row.key: row.value_json for row in db.query(SystemSetting)}, db.query(AuditLog).count())


@pytest.mark.parametrize(("section", "original", "patch"), [
    ("company_info", {"name": "Synthetic company", "address": "Warehouse A", "phone": "123",
                      "email": "office@example.com", "logo_url": "/synthetic-logo.webp"}, {"phone": "456"}),
    ("financial", {"default_currency": "UZS", "fiscal_year_start_month": 4}, {"fiscal_year_start_month": 6}),
    ("preferences", {"default_language": "uz", "timezone": "Asia/Tashkent", "model_types": ["Synthetic"],
                     "require_material_reservation_before_cutting": True}, {"default_language": "ru"}),
])
def test_patch_preserves_omitted_fields_and_other_sections(client, auth_headers, section, original, patch):
    _seed(section, original)
    _seed("unrelated_synthetic_setting", {"keep": True})
    response = client.patch(f"/api/settings/{section}", headers=auth_headers, json=patch)
    assert response.status_code == 200, response.text
    expected = {**original, **patch}
    assert response.json() == expected
    state, _ = _state()
    assert state[section] == expected and state["unrelated_synthetic_setting"] == {"keep": True}
    assert client.get("/api/settings", headers=auth_headers).json()[section] == expected


def test_explicit_null_clears_optional_value_but_empty_patch_preserves_all(client, auth_headers):
    _seed("company_info", {"name": "Synthetic", "address": "Keep", "phone": "123", "email": None, "logo_url": None})
    cleared = client.patch("/api/settings/company_info", headers=auth_headers, json={"phone": None})
    assert cleared.status_code == 200 and cleared.json()["phone"] is None
    assert cleared.json()["name"] == "Synthetic" and cleared.json()["address"] == "Keep"
    empty = client.patch("/api/settings/company_info", headers=auth_headers, json={})
    assert empty.status_code == 200 and empty.json() == cleared.json()


@pytest.mark.parametrize(("section", "payload", "field"), [
    ("financial", {"fiscal_year_start_month": 0}, "fiscal_year_start_month"),
    ("financial", {"fiscal_year_start_month": 13}, "fiscal_year_start_month"),
    ("financial", {"fiscal_year_start_month": "invalid"}, "fiscal_year_start_month"),
    ("financial", {"default_currency": None}, "default_currency"),
    ("company_info", {"email": "not-an-email"}, "email"),
    ("company_info", {"name": None}, "name"),
    ("preferences", {"model_types": "Dress"}, "model_types"),
    ("preferences", {"require_material_reservation_before_cutting": "sometimes"}, "require_material_reservation_before_cutting"),
    ("preferences", {"unknown_setting": "typo"}, "unknown_setting"),
])
def test_invalid_patch_returns_422_and_changes_nothing(client, auth_headers, section, payload, field):
    _seed(section, _default_json(section))
    before = _state()
    response = client.patch(f"/api/settings/{section}", headers=auth_headers, json=payload)
    assert response.status_code == 422, response.text
    assert any(error["loc"][:2] == ["body", field] for error in response.json()["detail"])
    assert _state() == before


def test_missing_section_row_uses_defaults_for_omitted_fields(client, auth_headers):
    with TestSessionLocal() as db:
        db.query(SystemSetting).filter_by(key="financial").delete()
        db.commit()
    response = client.patch("/api/settings/financial", headers=auth_headers, json={"default_currency": "UZS"})
    assert response.status_code == 200 and response.json() == {"default_currency": "UZS", "fiscal_year_start_month": 1}
    with TestSessionLocal() as db:
        assert db.query(SystemSetting).filter_by(key="financial").count() == 1


def test_invalid_patch_never_creates_missing_row(client, auth_headers):
    with TestSessionLocal() as db:
        db.query(SystemSetting).filter_by(key="financial").delete()
        db.commit()
    before = _state()
    response = client.patch("/api/settings/financial", headers=auth_headers, json={"fiscal_year_start_month": 25})
    assert response.status_code == 422, response.text
    assert _state() == before


def test_permissions_and_missing_section_unchanged(client, auth_headers):
    before = _state()
    assert client.patch("/api/settings/financial", json={}).status_code == 401
    login = client.post("/api/auth/token", data={"username": "hr@example.com", "password": "demo12345"})
    assert login.status_code == 200
    hr = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert client.patch("/api/settings/financial", json={}, headers=hr).status_code == 403
    assert client.patch("/api/settings/missing", json={}, headers=auth_headers).status_code == 404
    assert _state() == before


@pytest.mark.parametrize("body", [None, [], "not-an-object"])
def test_settings_section_route_body_shape_preserved(client, auth_headers, body):
    response = client.patch("/api/settings/unknown", headers=auth_headers, json=body)
    assert response.status_code == 422, response.text

    for section in ("company_info", "financial", "preferences"):
        known = client.patch(f"/api/settings/{section}", headers=auth_headers, json=body)
        assert known.status_code == 422, known.text


def test_unknown_settings_section_still_returns_404_for_object_body(client, auth_headers):
    response = client.patch("/api/settings/unknown", headers=auth_headers, json={})
    assert response.status_code == 404


def test_preference_language_contract_and_legacy_unknown_stored_value(client, auth_headers):
    defaults = client.get("/api/settings", headers=auth_headers)
    assert defaults.status_code == 200
    assert defaults.json()["preferences"]["default_language"] == "en"

    _seed("preferences", {**_default_json("preferences"), "default_language": "xx"})
    before = _state()
    rejected = client.patch("/api/settings/preferences", headers=auth_headers, json={})
    assert rejected.status_code == 422
    assert _state() == before
    unsupported = client.patch(
        "/api/settings/preferences", headers=auth_headers, json={"default_language": "xx"}
    )
    assert unsupported.status_code == 422
    assert _state() == before
    # The read contract fails closed instead of silently rewriting unknown
    # historical values; the stored row remains available for the value audit.
    assert client.get("/api/settings", headers=auth_headers).status_code == 500
    assert _state() == before


def test_audit_failure_rolls_back_patch(client, auth_headers, monkeypatch):
    _seed("financial", {"default_currency": "UZS", "fiscal_year_start_month": 4})
    before = _state()
    original = settings_service.log_action

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("Synthetic settings audit failure")

    monkeypatch.setattr(settings_service, "log_action", fail)
    with pytest.raises(RuntimeError, match="Synthetic settings audit failure"):
        client.patch("/api/settings/financial", headers=auth_headers, json={"fiscal_year_start_month": 6})
    assert _state() == before
    monkeypatch.setattr(settings_service, "log_action", original)
    retried = client.patch("/api/settings/financial", headers=auth_headers, json={"fiscal_year_start_month": 6})
    assert retried.status_code == 200
    assert _state()[0]["financial"]["fiscal_year_start_month"] == 6


def test_service_uses_one_session_and_one_outer_commit(client, auth_headers, monkeypatch):
    original_writer = settings_service.write_settings_section
    captured = []

    def capture_writer(db, **kwargs):
        captured.append(db)
        return original_writer(db, **kwargs)

    monkeypatch.setattr(settings_service, "write_settings_section", capture_writer)
    from sqlalchemy.orm import Session

    original_commit = Session.commit
    commits = []

    def count_commit(db):
        if any(db is seen for seen in captured):
            commits.append(db)
        return original_commit(db)

    monkeypatch.setattr(Session, "commit", count_commit)
    response = client.patch("/api/settings/financial", headers=auth_headers, json={"default_currency": "UZS"})
    assert response.status_code == 200, response.text
    assert len(captured) == 1 and len(commits) == 1
    assert commits[0] is captured[0]


def test_cutting_reservation_preference_remains_visible_to_existing_reader(client, auth_headers):
    response = client.patch(
        "/api/settings/preferences",
        headers=auth_headers,
        json={"require_material_reservation_before_cutting": True},
    )
    assert response.status_code == 200, response.text
    assert response.json()["require_material_reservation_before_cutting"] is True
    from app.models.inventory_service import require_material_reservation_before_cutting

    with TestSessionLocal() as db:
        assert require_material_reservation_before_cutting(db) is True


def test_real_logo_upload_and_partial_patch_preserve_company_fields(client, auth_headers):
    _seed("company_info", {"name": "Synthetic", "address": "Keep address", "phone": "123", "email": None, "logo_url": None})
    data = BytesIO()
    Image.new("RGB", (12, 12), "white").save(data, format="PNG")
    uploaded = client.post("/api/settings/company-logo/upload", headers=auth_headers,
                           files={"file": ("synthetic-logo.png", data.getvalue(), "image/png")})
    assert uploaded.status_code == 201, uploaded.text
    logo = uploaded.json()["logo_url"]
    assert logo.endswith(".webp")
    patched = client.patch("/api/settings/company_info", headers=auth_headers, json={"phone": "456"})
    assert patched.status_code == 200
    assert patched.json() == {"name": "Synthetic", "address": "Keep address", "phone": "456", "email": None, "logo_url": logo}


@pytest.mark.parametrize("fail_commit", [False, True])
def test_logo_replacement_preserves_old_file_until_commit(client, auth_headers, tmp_path, monkeypatch, fail_commit):
    monkeypatch.setattr(settings_routes.app_settings, "MODEL_FILES_DIR", str(tmp_path))
    def upload(color):
        image = BytesIO()
        Image.new("RGB", (12, 12), color).save(image, format="PNG")
        return client.post("/api/settings/company-logo/upload", headers=auth_headers,
            files={"file": ("review-logo.png", image.getvalue(), "image/png")})
    first = upload("blue")
    assert first.status_code == 201, first.text
    old_url = first.json()["logo_url"]
    old_name = old_url.rsplit("/", 1)[1]
    assert (tmp_path / old_name).is_file()
    old_thumbnails = list((tmp_path / "_thumbs").glob(f"*{old_name}.webp"))
    assert old_thumbnails
    if fail_commit:
        def failed_commit(_db):
            raise RuntimeError("synthetic logo commit failure")
        monkeypatch.setattr(TestSessionLocal.class_, "commit", failed_commit)
        with pytest.raises(RuntimeError, match="synthetic logo commit failure"):
            upload("green")
        assert (tmp_path / old_name).is_file()
        assert all(path.is_file() for path in old_thumbnails)
        with TestSessionLocal() as db:
            assert db.query(SystemSetting).filter_by(key="company_info").one().value_json["logo_url"] == old_url
    else:
        second = upload("green")
        assert second.status_code == 201, second.text
        new_url = second.json()["logo_url"]
        assert new_url != old_url
        assert not (tmp_path / old_name).exists()
        assert all(not path.exists() for path in old_thumbnails)
        assert (tmp_path / new_url.rsplit("/", 1)[1]).is_file()
        with TestSessionLocal() as db:
            assert db.query(SystemSetting).filter_by(key="company_info").one().value_json["logo_url"] == new_url
