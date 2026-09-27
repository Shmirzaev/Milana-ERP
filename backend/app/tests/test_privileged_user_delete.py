"""Deletion must enforce the same administrator tier as account updates."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.core.deps import is_super_admin, user_permissions
from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.models import AuditLog, Employee, Notification, PasswordResetToken, Role, User
from app.services.audit import log_action


PRIVILEGED_KINDS = ["role_name", "role_permission", "extra_permission", "access_policy", "wildcard"]


def _create_user(kind="normal", *, active=True, can_manage=False):
    with SessionLocal() as db:
        role = None
        extra_permissions = []
        access_policy = None
        if kind == "role_name":
            role = Role(name="  sUpEr AdMiN  ", permissions=[])
        elif kind == "role_permission":
            role = Role(name=f"Privileged delete {uuid4().hex}", permissions=["admin.super"])
        elif kind == "extra_permission":
            extra_permissions = ["admin.super"]
        elif kind == "access_policy":
            access_policy = {"MIL": {"allow": ["admin.super"]}}
        elif kind == "wildcard":
            extra_permissions = ["*"]
        elif kind == "limited":
            extra_permissions = ["admin.users"]
        if can_manage:
            extra_permissions.append("admin.users")
        if role:
            db.add(role)
            db.flush()
        user = User(
            name=f"Delete boundary {kind}",
            email=f"delete-boundary-{uuid4().hex}@example.invalid",
            password_hash="unused-by-synthetic-token-test",
            role_id=role.id if role else None,
            extra_permissions=extra_permissions,
            access_policy=access_policy,
            factory_code="MIL",
            is_active=active,
        )
        db.add(user)
        db.commit()
        if kind in PRIVILEGED_KINDS and kind != "wildcard":
            assert is_super_admin(user)
            assert "*" not in user_permissions(user)
        return user.id


def _headers(user_id):
    return {"Authorization": f"Bearer {create_access_token(user_id, {'factory_code': 'MIL'})}"}


def _add_references(user_id):
    with SessionLocal() as db:
        employee = Employee(user_id=user_id, full_name="Preserved privileged employee")
        notification = Notification(user_id=user_id, title="Preserved notification")
        reset_token = PasswordResetToken(
            user_id=user_id,
            token_hash=uuid4().hex,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        db.add_all([employee, notification, reset_token])
        audit = log_action(db, db.get(User, user_id), "login", "User", user_id)
        db.commit()
        return [(User, user_id), (Employee, employee.id), (Notification, notification.id),
                (PasswordResetToken, reset_token.id), (AuditLog, audit.id)]


def _snapshot(references):
    with SessionLocal() as db:
        rows = {}
        for model, row_id in references:
            row = db.get(model, row_id)
            rows[model.__tablename__] = (
                {column.name: getattr(row, column.name) for column in model.__table__.columns} if row else None
            )
        rows["audit_count"] = db.query(AuditLog).count()
        return rows


@pytest.mark.parametrize("actor_kind", ["limited", "wildcard"])
@pytest.mark.parametrize("target_kind", PRIVILEGED_KINDS)
@pytest.mark.parametrize("active", [True, False])
def test_non_super_manager_cannot_delete_privileged_target_or_mutate_references(
    client, actor_kind, target_kind, active
):
    actor_id = _create_user(actor_kind)
    target_id = _create_user(target_kind, active=active)
    references = _add_references(target_id)
    before = _snapshot(references)
    writes = []
    with SessionLocal() as db:
        engine = db.get_bind()

    def capture_write(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().split(None, 1)[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            writes.append(statement)

    event.listen(engine, "before_cursor_execute", capture_write)
    try:
        headers = _headers(actor_id)
        update = client.patch(f"/api/users/{target_id}", json={"name": "Unauthorized change"}, headers=headers)
        response = client.delete(f"/api/users/{target_id}", headers=headers)
    finally:
        event.remove(engine, "before_cursor_execute", capture_write)

    assert update.status_code == 403, update.text
    assert response.status_code == 403, response.text
    assert response.json()["detail"] == "Only a super admin can delete administrator accounts"
    assert writes == [], "Authorization must fail before any database mutation"
    assert _snapshot(references) == before


@pytest.mark.parametrize("kind", ["limited", "extra_permission"])
def test_self_deletion_is_still_rejected(client, kind):
    user_id = _create_user(kind, can_manage=True)
    response = client.delete(f"/api/users/{user_id}", headers=_headers(user_id))

    assert response.status_code == 400
    assert response.json()["detail"] == "You cannot delete your own account"
    with SessionLocal() as db:
        assert db.get(User, user_id) is not None


@pytest.mark.parametrize("active", [True, False])
def test_limited_manager_can_still_delete_normal_target(client, active):
    actor_id = _create_user("limited")
    target_id = _create_user(active=active)

    response = client.delete(f"/api/users/{target_id}", headers=_headers(actor_id))

    assert response.status_code == 204, response.text
    with SessionLocal() as db:
        assert db.get(User, target_id) is None
        assert db.query(AuditLog).filter_by(action="delete", entity_type="User", entity_id=target_id).count() == 1


@pytest.mark.parametrize("target_kind", PRIVILEGED_KINDS)
@pytest.mark.parametrize("active", [True, False])
def test_explicit_super_admin_without_wildcard_can_delete_privileged_target(client, target_kind, active):
    actor_id = _create_user("extra_permission", can_manage=True)
    target_id = _create_user(target_kind, active=active)

    response = client.delete(f"/api/users/{target_id}", headers=_headers(actor_id))

    assert response.status_code == 204, response.text
    with SessionLocal() as db:
        assert db.get(User, actor_id) is not None
        assert db.get(User, target_id) is None
        assert db.query(AuditLog).filter_by(action="delete", entity_type="User", entity_id=target_id).count() == 1


def test_last_wildcard_administrator_is_still_protected(client):
    actor_id = _create_user("extra_permission", can_manage=True)
    target_id = _create_user("wildcard")
    with SessionLocal() as db:
        db.query(User).filter(User.id.notin_([actor_id, target_id])).update({User.is_active: False})
        db.commit()

    response = client.delete(f"/api/users/{target_id}", headers=_headers(actor_id))

    assert response.status_code == 400
    assert response.json()["detail"] == "Cannot delete the last active administrator"
    with SessionLocal() as db:
        assert db.get(User, target_id).is_active


def test_limited_manager_is_denied_before_last_super_admin_check(client):
    actor_id = _create_user("limited")
    target_id = _create_user("extra_permission")
    with SessionLocal() as db:
        db.query(User).filter(User.id.notin_([actor_id, target_id])).update({User.is_active: False})
        db.commit()

    response = client.delete(f"/api/users/{target_id}", headers=_headers(actor_id))

    assert response.status_code == 403
    assert response.json()["detail"] == "Only a super admin can delete administrator accounts"
    with SessionLocal() as db:
        assert db.get(User, target_id).is_active
