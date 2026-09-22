"""Partial settings updates preserve omitted fields and reject malformed input."""

import asyncio
import os
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Event
from time import monotonic, sleep
from types import SimpleNamespace
from uuid import uuid4

import pytest
from anyio import CancelScope
from PIL import Image
from fastapi import HTTPException, UploadFile
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.api.routes import settings as settings_routes
from app.db.base import Base
from app.models import AuditLog, SystemSetting, User
from app.tests.conftest import TestSessionLocal


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
    _seed(section, settings_routes._SCHEMAS[section]().model_dump())
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


def test_audit_failure_rolls_back_patch(client, auth_headers, monkeypatch):
    _seed("financial", {"default_currency": "UZS", "fiscal_year_start_month": 4})
    before = _state()
    original = settings_routes.log_action

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("Synthetic settings audit failure")

    monkeypatch.setattr(settings_routes, "log_action", fail)
    with pytest.raises(RuntimeError, match="Synthetic settings audit failure"):
        client.patch("/api/settings/financial", headers=auth_headers, json={"fiscal_year_start_month": 6})
    assert _state() == before


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


def test_logo_transaction_failure_removes_new_files_and_preserves_existing_logo(tmp_path, monkeypatch):
    previous_url = "/storage/model-files/existing-company-logo.webp"
    _seed("company_info", {
        "name": "Synthetic",
        "address": "Keep address",
        "phone": "123",
        "email": None,
        "logo_url": previous_url,
    })
    previous_file = tmp_path / "existing-company-logo.webp"
    previous_file.write_bytes(b"keep the configured logo")
    unrelated = tmp_path / "unrelated.webp"
    unrelated.write_bytes(b"keep unrelated content")
    monkeypatch.setattr(settings_routes.app_settings, "MODEL_FILES_DIR", str(tmp_path))

    data = BytesIO()
    Image.new("RGB", (12, 12), "white").save(data, format="PNG")
    upload = UploadFile(file=BytesIO(data.getvalue()), filename="replacement.png")
    before_state = _state()
    try:
        with TestSessionLocal() as db:
            current = db.query(User).filter(User.email == "admin@example.com").one()

            def fail_commit():
                raise RuntimeError("Synthetic logo commit failure")

            monkeypatch.setattr(db, "commit", fail_commit)
            with pytest.raises(RuntimeError, match="Synthetic logo commit failure"):
                asyncio.run(settings_routes.upload_company_logo(db, file=upload, current=current))
    finally:
        asyncio.run(upload.close())

    assert _state() == before_state
    assert previous_file.read_bytes() == b"keep the configured logo"
    assert unrelated.read_bytes() == b"keep unrelated content"
    assert list(tmp_path.glob("company_logo_*.webp")) == []
    assert list((tmp_path / "_thumbs").glob("*")) == []


def test_logo_cancellation_shields_new_file_cleanup(tmp_path, monkeypatch):
    previous_url = "/storage/model-files/existing-company-logo.webp"
    _seed("company_info", {
        "name": "Synthetic",
        "address": None,
        "phone": None,
        "email": None,
        "logo_url": previous_url,
    })
    previous_file = tmp_path / "existing-company-logo.webp"
    previous_file.write_bytes(b"keep the configured logo")
    monkeypatch.setattr(settings_routes.app_settings, "MODEL_FILES_DIR", str(tmp_path))

    data = BytesIO()
    Image.new("RGB", (12, 12), "white").save(data, format="PNG")
    upload = UploadFile(file=BytesIO(data.getvalue()), filename="cancelled.png")
    before_state = _state()

    async def run():
        with TestSessionLocal() as db:
            current = db.query(User).filter(User.email == "admin@example.com").one()
            with CancelScope() as scope:
                def cancel_after_file_write(_db, _section):
                    scope.cancel()
                    raise asyncio.CancelledError

                monkeypatch.setattr(settings_routes, "_setting_for_update", cancel_after_file_write)
                with pytest.raises(asyncio.CancelledError):
                    await settings_routes.upload_company_logo(db, file=upload, current=current)
                assert scope.cancel_called

    try:
        asyncio.run(run())
    finally:
        asyncio.run(upload.close())

    assert _state() == before_state
    assert previous_file.read_bytes() == b"keep the configured logo"
    assert list(tmp_path.glob("company_logo_*.webp")) == []
    assert list((tmp_path / "_thumbs").glob("*")) == []


@pytest.fixture(scope="module")
def settings_postgres():
    raw = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw:
        pytest.skip("Requires disposable PostgreSQL settings concurrency coverage")
    url = make_url(raw)
    if url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"} or url.query:
        pytest.fail("Settings tests require loopback PostgreSQL without connection overrides")
    schema = f"settings_patch_{uuid4().hex}"
    engine = create_engine(url, pool_size=4, max_overflow=0, isolation_level="READ COMMITTED",
                           connect_args={"options": f"-csearch_path={schema} -clock_timeout=15000 -cstatement_timeout=20000"})
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        tables = {SystemSetting.__table__, User.__table__, AuditLog.__table__}
        pending = list(tables)
        while pending:
            for fk in pending.pop().foreign_keys:
                if fk.column.table not in tables:
                    tables.add(fk.column.table)
                    pending.append(fk.column.table)
        Base.metadata.create_all(engine, tables=list(tables))
        yield engine
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()


@pytest.mark.parametrize("case", ["existing", "first_create", "rollback", "logo"])
def test_postgres_partial_updates_merge_after_waiting(settings_postgres, monkeypatch, case):
    engine = settings_postgres
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    section = "company_info" if case == "logo" else "financial"
    with sessions() as db:
        db.query(SystemSetting).filter_by(key=section).delete()
        if case != "first_create":
            db.add(SystemSetting(key=section, value_json=settings_routes._SCHEMAS[section]().model_dump()))
        user = User(name="Synthetic settings admin", email=f"settings-{uuid4().hex}@example.com", password_hash="unused")
        db.add(user)
        db.commit()
        uid = user.id
    if case == "logo":
        from app.services import image_storage

        async def fake_store(*args, **kwargs):
            return SimpleNamespace(file_url="/synthetic-upload.webp")

        monkeypatch.setattr(image_storage, "store_uploaded_image", fake_store)
    held, release = Event(), Event()
    ready = Queue()
    original_audit = settings_routes.log_action

    def hold_first_audit(db, *args, **kwargs):
        original_audit(db, *args, **kwargs)
        if db.info.get("settings_worker") == "first":
            held.set()
            assert release.wait(12), "First settings patch was not released"
            if case == "rollback":
                raise HTTPException(503, "Synthetic settings rollback")

    monkeypatch.setattr(settings_routes, "log_action", hold_first_audit)

    def worker(name):
        with sessions() as db:
            db.info["settings_worker"] = name
            actor = db.get(User, uid)
            if name == "second":
                # Existing identity-map state must be refreshed after the lock.
                cached = db.query(SystemSetting).filter_by(key=section).first()
                ready.put(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
            try:
                if case == "logo" and name == "second":
                    return 201, asyncio.run(settings_routes.upload_company_logo(db, file=None, current=actor))
                payload = ({"address": "Changed address"} if case == "logo" else
                           {"fiscal_year_start_month": 4} if name == "first" else {"default_currency": "UZS"})
                result = settings_routes.save_settings_section(section, payload, db, current=actor)
                if name == "second" and cached is not None:
                    assert cached.value_json == result
                return 200, result
            except HTTPException as exc:
                db.rollback()
                return exc.status_code, exc.detail

    with ThreadPoolExecutor(max_workers=2) as workers:
        first = workers.submit(worker, "first")
        second = None
        try:
            assert held.wait(10), "First settings patch did not reach its audit"
            second = workers.submit(worker, "second")
            pid = ready.get(timeout=10)
            with engine.connect() as observer:
                deadline = monotonic() + 10
                while monotonic() < deadline:
                    if observer.execute(text("SELECT pg_blocking_pids(:pid)"), {"pid": pid}).scalar_one():
                        break
                    sleep(0.02)
                else:
                    pytest.fail("Second settings write did not wait on the section lock")
        finally:
            release.set()
        assert first.result(timeout=10)[0] == (503 if case == "rollback" else 200)
        assert second is not None and second.result(timeout=10)[0] == (201 if case == "logo" else 200)
    with sessions() as db:
        rows = db.query(SystemSetting).filter_by(key=section).all()
        assert len(rows) == 1
        if case == "logo":
            assert rows[0].value_json["address"] == "Changed address"
            assert rows[0].value_json["logo_url"] == "/synthetic-upload.webp"
        else:
            assert rows[0].value_json == {"default_currency": "UZS", "fiscal_year_start_month": 1 if case == "rollback" else 4}
        assert db.query(AuditLog).filter_by(user_id=uid).count() == (1 if case == "rollback" else 2)
