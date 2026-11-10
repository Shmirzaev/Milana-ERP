"""RF-009 delivery and post-commit gaps kept separate from #345's baseline."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi import BackgroundTasks, HTTPException
from fastapi.testclient import TestClient

from app.core.deps import user_permissions
from app.libs.dto.catalog.catalog import UserIn
from app.main import app
from app.models.audit_service import verify_audit_hash_chain
from app.models.identity.users_service import create_user as create_user_service
from app.models.password_reset_service import notify_admins_about_password_email_failure
from app.schemas import Notification, PasswordResetToken, Role, User
from app.tests.test_create_user_characterization import counts, payload

pytest_plugins = ("app.tests.test_create_user_characterization",)


@pytest.mark.parametrize("delivery", ["false", "exception"])
def test_setup_delivery_failure_notifies_only_admins_without_link(h, monkeypatch, delivery):
    monkeypatch.setattr("app.models.password_reset_service.SessionLocal", h.db)
    with h.db() as db:
        expected = {
            admin.id for admin in db.query(User).filter(User.is_active.is_(True)).all()
            if "*" in user_permissions(admin) or "admin.users" in user_permissions(admin)
        }

    def sender(_email, _name, url):
        if delivery == "exception":
            raise RuntimeError(f"provider echoed {url}")
        return False

    monkeypatch.setattr("app.models.password_reset_service.send_password_setup_email", sender)
    response = h.client.post("/api/users", headers=h.actors["super"][1], json=payload(h, password=None))
    assert response.status_code == 201
    with h.db() as db:
        user = db.query(User).filter_by(email=h.email).one()
        assert db.query(PasswordResetToken).filter_by(user_id=user.id).count() == 1
        rows = db.query(Notification).filter(
            Notification.title == "Password setup email failed",
            Notification.message.contains(h.email),
        ).all()
        assert rows
        assert {row.user_id for row in rows} == expected
        assert all(row.link == "/admin/users" and "reset-password?token=" not in row.message
                   and "provider echoed" not in row.message for row in rows)


def test_refresh_failure_leaves_committed_rows_but_never_schedules_email(h, monkeypatch):
    before = counts(h)
    original = h.db.class_.refresh

    def fail_created_user_refresh(db, instance, *args, **kwargs):
        if isinstance(instance, User) and instance.email == h.email:
            raise RuntimeError("synthetic refresh failure")
        return original(db, instance, *args, **kwargs)

    monkeypatch.setattr(h.db.class_, "refresh", fail_created_user_refresh)
    response = TestClient(app, raise_server_exceptions=False).post(
        "/api/users", headers=h.actors["super"][1], json=payload(h, password=None),
    )
    assert response.status_code == 500
    after = counts(h)
    assert after == tuple(value + 1 for value in before)
    assert h.messages == []


def test_schedule_failure_leaves_committed_rows_without_delivery(h, monkeypatch):
    before = counts(h)

    def fail_schedule(*_args, **_kwargs):
        raise RuntimeError("synthetic scheduling failure")

    monkeypatch.setattr(BackgroundTasks, "add_task", fail_schedule)
    response = TestClient(app, raise_server_exceptions=False).post(
        "/api/users", headers=h.actors["super"][1], json=payload(h, password=None),
    )
    assert response.status_code == 500
    assert counts(h) == tuple(value + 1 for value in before)
    assert h.messages == []


def test_notification_writer_failure_rolls_back_its_separate_transaction(h, monkeypatch):
    monkeypatch.setattr("app.models.password_reset_service.SessionLocal", h.db)
    with h.db() as db:
        email = db.get(User, h.actors["super"][0]).email
        before = db.query(Notification).filter(Notification.message.contains(email)).count()

    from app.models import password_reset_service
    original = password_reset_service.add_notification_row
    calls = 0

    def fail_second_write(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("synthetic notification write failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(password_reset_service, "add_notification_row", fail_second_write)
    notify_admins_about_password_email_failure(
        h.actors["super"][0], "https://example.invalid/reset-password?token=secret",
        "synthetic provider failure", email_kind="setup",
    )
    assert calls == 2
    with h.db() as db:
        assert db.query(Notification).filter(Notification.message.contains(email)).count() == before


def test_public_service_rejects_actor_without_create_grant(h):
    before = counts(h)
    with h.db() as db:
        actor = db.get(User, h.actors["ordinary"][0])
        with pytest.raises(HTTPException) as error:
            create_user_service(db, UserIn.model_validate(payload(h)), actor)
        assert error.value.status_code == 403
        assert error.value.detail == "Missing permission. Need any of: ['admin.users', '*']"
    assert counts(h) == before


@pytest.mark.parametrize("creation_database", ["postgres"], indirect=True)
def test_postgres_duplicate_race_keeps_one_complete_creation(h, monkeypatch, creation_database):
    before = counts(h)
    from app.models.identity import users_service
    original_add = users_service.add_user
    after_duplicate_check = Barrier(2)

    def insert_after_both_checks(*args, **kwargs):
        after_duplicate_check.wait(timeout=10)
        return original_add(*args, **kwargs)

    monkeypatch.setattr(users_service, "add_user", insert_after_both_checks)

    def submit():
        return TestClient(app, raise_server_exceptions=False).post(
            "/api/users", headers=h.actors["super"][1], json=payload(h),
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(submit) for _ in range(2)]
        responses = [future.result(timeout=30) for future in futures]
    assert sorted(response.status_code for response in responses) == [201, 500]
    assert counts(h) == (before[0] + 1, before[1], before[2] + 1)
    with h.db() as db:
        assert db.query(User).filter_by(email=h.email).count() == 1
        assert verify_audit_hash_chain(db)["ok"]


@pytest.mark.parametrize("creation_database", ["postgres"], indirect=True)
def test_postgres_concurrent_unique_creations_keep_audit_chain(h, monkeypatch):
    before = counts(h)
    from app.models.identity import users_service
    original_audit = users_service.log_action
    before_audit = Barrier(4)

    def audit_after_all_user_flushes(*args, **kwargs):
        before_audit.wait(timeout=10)
        return original_audit(*args, **kwargs)

    monkeypatch.setattr(users_service, "log_action", audit_after_all_user_flushes)

    def submit(index):
        return TestClient(app, raise_server_exceptions=False).post(
            "/api/users", headers=h.actors["super"][1],
            json=payload(h, email=f"concurrent-{index}-{h.email}"),
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(submit, index) for index in range(4)]
        responses = [future.result(timeout=30) for future in futures]
    assert [response.status_code for response in responses] == [201] * 4
    assert counts(h) == (before[0] + 4, before[1], before[2] + 4)
    with h.db() as db:
        assert verify_audit_hash_chain(db)["ok"]


@pytest.mark.parametrize("creation_database", ["postgres"], indirect=True)
def test_postgres_role_deleted_after_validation_rolls_back_creation(h, monkeypatch):
    before = counts(h)
    from app.models.identity import users_service
    original = users_service.add_user

    def delete_role_then_insert(db, **values):
        with h.db() as concurrent:
            concurrent.delete(concurrent.get(Role, h.roles["reader"]))
            concurrent.commit()
        return original(db, **values)

    monkeypatch.setattr(users_service, "add_user", delete_role_then_insert)
    response = TestClient(app, raise_server_exceptions=False).post(
        "/api/users", headers=h.actors["super"][1],
        json=payload(h, role_id=h.roles["reader"]),
    )
    assert response.status_code == 500
    assert counts(h) == before
    assert h.messages == []
