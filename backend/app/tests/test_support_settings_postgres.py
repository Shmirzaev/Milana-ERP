"""Approved-fixture PostgreSQL contract tests for Support settings sections."""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic, sleep
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session, object_session

from app.api.routes import settings as settings_routes
from app.core.deps import get_current_user, get_db
from app.libs.dto.support.company_info_input import CompanyInfoUpdate
from app.libs.dto.support.financial_settings_input import FinancialSettingsUpdate
from app.libs.dto.support.system_preferences_input import SystemPreferencesUpdate
from app.libs.dto.support.company_info_output import CompanyInfoOut
from app.libs.dto.support.financial_settings_output import FinancialSettingsOut
from app.libs.dto.support.system_preferences_output import SystemPreferencesOut
from app.libs.enums.settings import SettingsSection
from app.models.support import settings_service
from app.schemas import AuditLog, SystemSetting, User
from app.tests.test_customer_create_postgres import actor as create_actor
from app.tests.test_customer_create_postgres import chain, customer_pg_sessions  # noqa: F401


_INPUTS = {
    "company_info": CompanyInfoUpdate,
    "financial": FinancialSettingsUpdate,
    "preferences": SystemPreferencesUpdate,
}
_OUTPUTS = {
    "company_info": CompanyInfoOut,
    "financial": FinancialSettingsOut,
    "preferences": SystemPreferencesOut,
}
_LOCK_IDS = {"company_info": 1, "financial": 2, "preferences": 3}


def _defaults(section):
    return _OUTPUTS[section]().model_dump(mode="json")


def _update(db, actor, section, values):
    return settings_service.update_settings_section(
        db,
        actor=actor,
        section=SettingsSection(section),
        patch=_INPUTS[section](**values),
    )


def _backend_pid(db):
    return int(db.execute(text("SELECT pg_backend_pid()")).scalar_one())


def _client(sessions, user_id):
    app = FastAPI()
    app.include_router(settings_routes.router, prefix="/api")

    def isolated_db():
        with sessions() as db:
            yield db

    def current_user():
        with sessions() as db:
            user = db.get(User, user_id)
            db.expunge(user)
            return user

    app.dependency_overrides[get_db] = isolated_db
    app.dependency_overrides[get_current_user] = current_user
    return TestClient(app, raise_server_exceptions=False)


def _lock_rows(db, pid):
    return db.execute(text("""
        SELECT classid::bigint, objid::bigint, objsubid, mode, granted
        FROM pg_locks
        WHERE pid = :pid AND locktype = 'advisory'
        ORDER BY granted DESC, mode
    """), {"pid": pid}).mappings().all()


@pytest.mark.parametrize(
    ("section", "existing"),
    [
        ("company_info", False),
        ("company_info", True),
        ("financial", False),
        ("financial", True),
        ("preferences", False),
        ("preferences", True),
    ],
    ids=[
        "company_info_missing", "company_info_existing",
        "financial_missing", "financial_existing",
        "preferences_missing", "preferences_existing",
    ],
)
def test_pg_section_merge_waits_on_exact_missing_or_existing_lock(
    customer_pg_sessions, monkeypatch, record_property, section, existing,
):
    sessions = customer_pg_sessions
    user_id = create_actor(sessions, ["*"])
    with sessions.begin() as db:
        db.query(SystemSetting).filter_by(key=section).delete(synchronize_session=False)
        if existing:
            db.add(SystemSetting(key=section, value_json=_defaults(section)))

    first_values, second_values, expected = {
        "company_info": (
            {"phone": "first"}, {"address": "second"},
            {**_defaults(section), "phone": "first", "address": "second"},
        ),
        "financial": (
            {"fiscal_year_start_month": 4}, {"default_currency": "UZS"},
            {**_defaults(section), "fiscal_year_start_month": 4, "default_currency": "UZS"},
        ),
        "preferences": (
            {"timezone": "Asia/Tashkent"}, {"model_types": ["Synthetic"]},
            {**_defaults(section), "timezone": "Asia/Tashkent", "model_types": ["Synthetic"]},
        ),
    }[section]
    holder_at_audit, release_holder, waiter_started = Event(), Event(), Event()
    pids = {}
    original_audit = settings_service.log_action

    def hold_first_audit(db, *args, **kwargs):
        result = original_audit(db, *args, **kwargs)
        if db.info.get("settings_worker") == "holder":
            pids["holder"] = _backend_pid(db)
            holder_at_audit.set()
            assert release_holder.wait(20), "Timed out waiting to release the held settings transaction"
        return result

    monkeypatch.setattr(settings_service, "log_action", hold_first_audit)

    def write(role, values):
        with sessions() as db:
            db.info["settings_worker"] = role
            actor = db.get(User, user_id)
            if role == "waiter":
                cached = db.query(SystemSetting).filter_by(key=section).first()
                pids["waiter"] = _backend_pid(db)
                waiter_started.set()
            else:
                cached = None
            try:
                result = _update(db, actor, section, values)
                return result.model_dump(mode="json"), cached
            except HTTPException:
                db.rollback()
                raise

    with ThreadPoolExecutor(max_workers=2) as workers:
        holder = workers.submit(write, "holder", first_values)
        waiter = None
        observed = None
        try:
            assert holder_at_audit.wait(15), "Holder did not reach its post-audit transaction gate"
            waiter = workers.submit(write, "waiter", second_values)
            assert waiter_started.wait(10), "Waiter backend did not start"
            deadline = monotonic() + 8
            while monotonic() < deadline:
                with sessions() as observer:
                    state = observer.execute(text("""
                        SELECT a.wait_event_type, a.wait_event, pg_blocking_pids(a.pid) AS blockers,
                               EXISTS (
                                   SELECT 1 FROM pg_locks l
                                   WHERE l.pid = a.pid AND l.locktype = 'advisory'
                                     AND l.classid::bigint = :namespace
                                     AND l.objid::bigint = :section AND l.objsubid = 2
                                     AND NOT l.granted
                               ) AS waiting_for_section_lock
                        FROM pg_stat_activity a WHERE a.pid = :waiter
                    """), {
                        "waiter": pids["waiter"],
                        "namespace": 1_297_047_635,
                        "section": _LOCK_IDS[section],
                    }).mappings().one_or_none()
                    holder_locks = _lock_rows(observer, pids["holder"])
                    if (
                        state
                        and state["wait_event_type"] == "Lock"
                        and state["waiting_for_section_lock"]
                        and pids["holder"] in state["blockers"]
                        and any(
                            int(lock["classid"]) == 1_297_047_635
                            and int(lock["objid"]) == _LOCK_IDS[section]
                            and int(lock["objsubid"]) == 2
                            and lock["granted"]
                            for lock in holder_locks
                        )
                    ):
                        observed = {
                            "wait_event_type": state["wait_event_type"],
                            "wait_event": state["wait_event"],
                            "blockers": list(state["blockers"]),
                            "holder_locks": [dict(row) for row in holder_locks],
                        }
                        break
                if holder.done() or (waiter is not None and waiter.done()):
                    break
                sleep(0.025)
            assert observed is not None, "No actual section advisory-lock blocker was observed"
            record_property("support_settings_pg_lock_witness", json.dumps({
                "section": section,
                "existing_row": existing,
                "holder_pid": pids["holder"],
                "waiter_pid": pids["waiter"],
                **observed,
            }, sort_keys=True))
        finally:
            release_holder.set()
        assert holder.result(timeout=25)[0] == {
            **_defaults(section),
            **first_values,
        }
        assert waiter is not None and waiter.result(timeout=25)[0] == expected

    with sessions() as db:
        row = db.query(SystemSetting).filter_by(key=section).one()
        assert row.value_json == expected
        assert db.query(AuditLog).filter_by(user_id=user_id, entity_type="SystemSetting", action="update").count() == 2
    chain(sessions)


def test_pg_logo_update_waits_on_shared_company_info_lock(customer_pg_sessions, monkeypatch, record_property):
    sessions = customer_pg_sessions
    user_id = create_actor(sessions, ["*"])
    with sessions.begin() as db:
        db.query(SystemSetting).filter_by(key="company_info").delete(synchronize_session=False)
        db.add(SystemSetting(key="company_info", value_json=_defaults("company_info")))

    from app.models import image_storage_service

    async def store(*args, **kwargs):
        return SimpleNamespace(file_url="/synthetic-upload.webp")

    monkeypatch.setattr(image_storage_service, "store_uploaded_image", store)
    holder_at_audit, release_holder, waiter_started = Event(), Event(), Event()
    pids = {}
    original_audit = settings_service.log_action
    original_route_audit = settings_routes.log_action

    def hold_first_audit(db, *args, **kwargs):
        result = original_audit(db, *args, **kwargs)
        if db.info.get("settings_worker") == "holder":
            pids["holder"] = _backend_pid(db)
            holder_at_audit.set()
            assert release_holder.wait(20), "Timed out waiting to release the held settings transaction"
        return result

    monkeypatch.setattr(settings_service, "log_action", hold_first_audit)
    monkeypatch.setattr(settings_routes, "log_action", hold_first_audit)

    def patch_company():
        with sessions() as db:
            db.info["settings_worker"] = "holder"
            actor = db.get(User, user_id)
            return _update(db, actor, "company_info", {"address": "changed"}).model_dump(mode="json")

    def upload_logo():
        assert holder_at_audit.wait(10)
        with sessions() as db:
            db.info["settings_worker"] = "waiter"
            actor = db.get(__import__("app.schemas", fromlist=["User"]).User, user_id)
            pids["waiter"] = _backend_pid(db)
            waiter_started.set()
            return asyncio.run(settings_routes.upload_company_logo(db, file=None, current=actor))

    with ThreadPoolExecutor(max_workers=2) as workers:
        holder = workers.submit(patch_company)
        waiter = workers.submit(upload_logo)
        observed = None
        try:
            assert waiter_started.wait(12)
            deadline = monotonic() + 8
            while monotonic() < deadline:
                with sessions() as observer:
                    state = observer.execute(text("""
                        SELECT a.wait_event_type, pg_blocking_pids(a.pid) AS blockers,
                               EXISTS (
                                   SELECT 1 FROM pg_locks l WHERE l.pid = a.pid
                                     AND l.locktype = 'advisory' AND l.classid::bigint = :namespace
                                     AND l.objid::bigint = 1 AND l.objsubid = 2 AND NOT l.granted
                               ) AS waiting_for_company_lock
                        FROM pg_stat_activity a WHERE a.pid = :waiter
                    """), {"waiter": pids["waiter"], "namespace": 1_297_047_635}).mappings().one_or_none()
                    if (
                        state
                        and state["wait_event_type"] == "Lock"
                        and state["waiting_for_company_lock"]
                        and pids["holder"] in state["blockers"]
                    ):
                        observed = dict(state)
                        break
                if holder.done() or waiter.done():
                    break
                sleep(0.025)
            assert observed is not None, "Logo upload did not wait on the shared company_info advisory lock"
            record_property("support_settings_logo_lock_witness", json.dumps({
                "holder_pid": pids["holder"], "waiter_pid": pids["waiter"],
                "wait_event_type": observed["wait_event_type"],
                "blockers": list(observed["blockers"]),
            }, sort_keys=True))
        finally:
            release_holder.set()
        assert holder.result(timeout=25)["address"] == "changed"
        assert waiter.result(timeout=25) == {"logo_url": "/synthetic-upload.webp"}

    with sessions() as db:
        row = db.query(SystemSetting).filter_by(key="company_info").one()
        assert row.value_json["address"] == "changed"
        assert row.value_json["logo_url"] == "/synthetic-upload.webp"
        assert db.query(AuditLog).filter_by(user_id=user_id, entity_type="SystemSetting").count() == 2
    chain(sessions)


def test_pg_existing_row_wait_refreshes_after_preexisting_row_lock(
    customer_pg_sessions, record_property,
):
    sessions = customer_pg_sessions
    section = "company_info"
    user_id = create_actor(sessions, ["*"])
    with sessions.begin() as db:
        db.query(SystemSetting).filter_by(key=section).delete(synchronize_session=False)
        db.add(SystemSetting(key=section, value_json=_defaults(section)))
    row_locked, release_row, waiter_started = Event(), Event(), Event()
    pids = {}

    def hold_row_lock():
        with sessions() as db:
            row = db.query(SystemSetting).filter_by(key=section).with_for_update().one()
            row.value_json = {**row.value_json, "address": "committed by row-lock holder"}
            db.flush()
            pids["row_holder"] = _backend_pid(db)
            row_locked.set()
            assert release_row.wait(20), "Timed out waiting to release the settings row lock"
            db.commit()

    def update_section():
        assert row_locked.wait(10)
        with sessions() as db:
            actor = db.get(User, user_id)
            pids["waiter"] = _backend_pid(db)
            waiter_started.set()
            return _update(db, actor, section, {"phone": "updated after row wait"}).model_dump(mode="json")

    with ThreadPoolExecutor(max_workers=2) as workers:
        holder = workers.submit(hold_row_lock)
        waiter = workers.submit(update_section)
        observed = None
        try:
            assert waiter_started.wait(12)
            deadline = monotonic() + 8
            while monotonic() < deadline:
                with sessions() as observer:
                    state = observer.execute(text("""
                        SELECT a.wait_event_type, a.wait_event, pg_blocking_pids(a.pid) AS blockers,
                               EXISTS (
                                   SELECT 1 FROM pg_locks l WHERE l.pid = a.pid
                                     AND l.locktype = 'advisory' AND l.classid::bigint = :namespace
                                     AND l.objid::bigint = 1 AND l.objsubid = 2 AND l.granted
                               ) AS passed_section_advisory_lock
                        FROM pg_stat_activity a WHERE a.pid = :waiter
                    """), {"waiter": pids["waiter"], "namespace": 1_297_047_635}).mappings().one_or_none()
                    if (
                        state
                        and state["wait_event_type"] == "Lock"
                        and state["wait_event"] == "transactionid"
                        and state["passed_section_advisory_lock"]
                        and pids["row_holder"] in state["blockers"]
                    ):
                        observed = dict(state)
                        break
                if waiter.done() or holder.done():
                    break
                sleep(0.025)
            assert observed is not None, "Waiter did not block on the preexisting settings row lock"
            record_property("support_settings_pg_row_lock_witness", json.dumps({
                "section": section,
                "row_holder_pid": pids["row_holder"],
                "waiter_pid": pids["waiter"],
                "wait_event_type": observed["wait_event_type"],
                "wait_event": observed["wait_event"],
                "blockers": list(observed["blockers"]),
                "passed_section_advisory_lock": observed["passed_section_advisory_lock"],
            }, sort_keys=True))
        finally:
            release_row.set()
        holder.result(timeout=25)
        result = waiter.result(timeout=25)
    assert result["address"] == "committed by row-lock holder"
    assert result["phone"] == "updated after row wait"
    with sessions() as db:
        assert db.query(SystemSetting).filter_by(key=section).one().value_json == result
        assert db.query(AuditLog).filter_by(user_id=user_id, entity_type="SystemSetting", action="update").count() == 1
    chain(sessions)


@pytest.mark.parametrize(
    "failure_point", ["flush", "audit", "commit"],
    ids=["after_flush", "after_audit", "before_commit"],
)
def test_pg_settings_failure_rolls_back_and_retry_persists_once(
    customer_pg_sessions, monkeypatch, failure_point,
):
    sessions = customer_pg_sessions
    user_id = create_actor(sessions, ["*"])
    with sessions.begin() as db:
        db.query(SystemSetting).filter_by(key="financial").delete(synchronize_session=False)
    original_writer = settings_service.write_settings_section
    original_audit = settings_service.log_action
    original_commit = Session.commit
    fail = {"armed": True}

    if failure_point == "flush":
        def fail_after_flush(db, **kwargs):
            row = original_writer(db, **kwargs)
            if fail["armed"]:
                fail["armed"] = False
                raise RuntimeError("synthetic failure after settings flush")
            return row
        monkeypatch.setattr(settings_service, "write_settings_section", fail_after_flush)
    elif failure_point == "audit":
        def fail_after_audit(db, *args, **kwargs):
            result = original_audit(db, *args, **kwargs)
            if fail["armed"]:
                fail["armed"] = False
                raise RuntimeError("synthetic failure after settings audit")
            return result
        monkeypatch.setattr(settings_service, "log_action", fail_after_audit)

    with sessions() as db:
        actor = db.get(User, user_id)
        if failure_point == "commit":
            def fail_first_commit(session):
                if session is db and fail["armed"]:
                    fail["armed"] = False
                    raise RuntimeError("synthetic settings commit failure")
                return original_commit(session)
            monkeypatch.setattr(Session, "commit", fail_first_commit)
        with pytest.raises(RuntimeError, match="synthetic"):
            _update(db, actor, "financial", {"default_currency": "UZS"})
        db.rollback()
        assert db.query(SystemSetting).filter_by(key="financial").count() == 0
        _update(db, db.get(User, user_id), "financial", {"default_currency": "UZS"})

    with sessions() as db:
        row = db.query(SystemSetting).filter_by(key="financial").one()
        assert row.value_json == {**_defaults("financial"), "default_currency": "UZS"}
        assert db.query(AuditLog).filter_by(user_id=user_id, entity_type="SystemSetting", action="update").count() == 1
    chain(sessions)


@pytest.mark.parametrize(
    "section", ["company_info", "financial", "preferences"],
    ids=["company_info_wire", "financial_wire", "preferences_wire"],
)
def test_pg_typed_route_persists_wire_defaults_null_and_audit(customer_pg_sessions, section):
    sessions = customer_pg_sessions
    user_id = create_actor(sessions, ["*"])
    with sessions.begin() as db:
        db.query(SystemSetting).filter_by(key=section).delete(synchronize_session=False)
    with _client(sessions, user_id) as client:
        defaults = client.get("/api/settings")
        assert defaults.status_code == 200
        assert defaults.json()[section] == _defaults(section)
        patch, expected = {
            "company_info": ({"phone": None}, {**_defaults(section), "phone": None}),
            "financial": ({"fiscal_year_start_month": 6}, {**_defaults(section), "fiscal_year_start_month": 6}),
            "preferences": ({"default_language": "ru"}, {**_defaults(section), "default_language": "ru"}),
        }[section]
        saved = client.patch(f"/api/settings/{section}", json=patch)
        assert saved.status_code == 200, saved.text
        assert saved.json() == expected
        assert client.get("/api/settings").json()[section] == expected
    with sessions() as db:
        row = db.query(SystemSetting).filter_by(key=section).one()
        audit = db.query(AuditLog).filter_by(
            user_id=user_id, entity_type="SystemSetting", entity_id=row.id, action="update",
        ).one()
        assert row.value_json == expected
        assert audit.old_value_json is None
        assert audit.new_value_json == {section: expected}
    chain(sessions)


def test_pg_typed_route_denials_invalid_and_unknown_have_no_writes(customer_pg_sessions):
    sessions = customer_pg_sessions
    denied_id = create_actor(sessions, [])
    allowed_id = create_actor(sessions, ["*"])
    with sessions.begin() as db:
        for section in _INPUTS:
            db.query(SystemSetting).filter_by(key=section).delete(synchronize_session=False)
        db.add(SystemSetting(key="financial", value_json=_defaults("financial")))
    with sessions() as db:
        before_rows = {row.key: row.value_json for row in db.query(SystemSetting)}
        before_audits = db.query(AuditLog).count()
    with _client(sessions, denied_id) as denied:
        response = denied.patch("/api/settings/financial", json={"default_currency": "UZS"})
        assert response.status_code == 403
    with _client(sessions, allowed_id) as allowed:
        assert allowed.patch("/api/settings/unknown", json={}).status_code == 404
        assert allowed.patch("/api/settings/unknown", json=None).status_code == 422
        assert allowed.patch("/api/settings/financial", json={"default_currency": None}).status_code == 422
        assert allowed.patch("/api/settings/preferences", json={"timezone": None}).status_code == 422
        assert allowed.patch("/api/settings/company_info", json={"name": None}).status_code == 422
        assert allowed.patch("/api/settings/preferences", json={"default_language": "xx"}).status_code == 422
        assert allowed.patch("/api/settings/company_info", json={"not_a_field": True}).status_code == 422
    with sessions() as db:
        assert {row.key: row.value_json for row in db.query(SystemSetting)} == before_rows
        assert db.query(AuditLog).count() == before_audits
    chain(sessions)


def test_pg_typed_route_uses_schema_writer_session_and_one_commit(
    customer_pg_sessions, monkeypatch,
):
    sessions = customer_pg_sessions
    user_id = create_actor(sessions, ["*"])
    original_writer = settings_service.write_settings_section
    original_audit = settings_service.log_action
    original_commit = Session.commit
    seen_sessions = []
    commits = []
    audit_sessions = []

    def inspect_writer(db, **kwargs):
        row = original_writer(db, **kwargs)
        assert object_session(row) is db
        seen_sessions.append(db)
        return row

    def inspect_audit(db, *args, **kwargs):
        assert seen_sessions == [db]
        audit_sessions.append(db)
        return original_audit(db, *args, **kwargs)

    def count_commit(db):
        if any(db is seen for seen in seen_sessions):
            commits.append(db)
        return original_commit(db)

    monkeypatch.setattr(settings_service, "write_settings_section", inspect_writer)
    monkeypatch.setattr(settings_service, "log_action", inspect_audit)
    monkeypatch.setattr(Session, "commit", count_commit)
    with _client(sessions, user_id) as client:
        response = client.patch("/api/settings/preferences", json={"timezone": "Asia/Tashkent"})
    assert response.status_code == 200, response.text
    assert len(seen_sessions) == 1 and commits == seen_sessions and audit_sessions == seen_sessions
    with sessions() as db:
        row = db.query(SystemSetting).filter_by(key="preferences").one()
        assert row.value_json["timezone"] == "Asia/Tashkent"
        assert db.query(AuditLog).filter_by(user_id=user_id, entity_id=row.id, action="update").count() == 1
    chain(sessions)
