"""Create a user with the existing grant, audit, and setup-link contract."""

import secrets
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.deps import is_super_admin, normalize_permissions, require_permissions, user_permissions
from app.core.security import hash_password, normalize_email, validate_password_strength
from app.libs.dto.catalog.catalog import UserIn, UserUpdate
from app.models.audit_service import log_action
from app.models.credentials_service import apply_password_credential_change, lock_user_for_credential_change
from app.models.factory_scope_service import normalize_factory_code, selected_factory_code
from app.models.identity.access_service import (
    _assert_can_grant_permissions, _assert_can_grant_role, _assert_policy_change, _user_access_values,
)
from app.models.password_reset_service import create_password_reset_token, password_reset_url
from app.schemas import User
from app.schemas.identity.user_persistence import add_user, set_user_credential_cutoff, apply_admin_user_changes


def require_strong_password(password: str) -> None:
    try:
        validate_password_strength(password)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


def create_user(db: Session, payload: UserIn, actor: User) -> tuple[User, str | None]:
    """Return a committed, refreshed account and its optional setup URL."""
    require_permissions("admin.users", "*")(actor)
    email = normalize_email(payload.email)
    password_provided = bool(payload.password)
    if password_provided:
        require_strong_password(payload.password)
    _assert_can_grant_role(db, actor, payload.role_id)
    extra_permissions = normalize_permissions(payload.extra_permissions)
    _assert_can_grant_permissions(actor, extra_permissions)
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(400, "Email already exists")
    factory_code = normalize_factory_code(payload.factory_code, default=selected_factory_code(actor))
    if not is_super_admin(actor) and factory_code != selected_factory_code(actor):
        raise HTTPException(403, "Only Super Admin can assign another factory")
    _assert_policy_change(db, actor, {**payload.model_dump(), "factory_code": factory_code})
    if len(payload.name) > 128:
        raise HTTPException(422, "User name must be at most 128 characters")
    if len(email) > 255:
        raise HTTPException(422, "User email must be at most 255 characters")
    setup_url: str | None = None
    user = add_user(
        db, name=payload.name, email=email,
        password_hash=hash_password(payload.password if password_provided else secrets.token_urlsafe(48)),
        role_id=payload.role_id, department_id=payload.department_id,
        factory_code=factory_code, extra_permissions=extra_permissions,
        access_policy=payload.model_dump().get("access_policy"), is_active=payload.is_active,
    )
    if not password_provided and user.is_active:
        setup_token = create_password_reset_token(db, user)
        setup_url = password_reset_url(setup_token)
    log_action(
        db, actor, "create", "User", user.id,
        new_value={"email": user.email, "password_setup_email_queued": bool(setup_url),
                   "role_id": user.role_id, "factory_code": user.factory_code,
                   "extra_permissions": user.extra_permissions, "access_policy": user.access_policy},
    )
    db.commit()
    db.refresh(user)
    return user, setup_url


def list_users(db: Session, actor: User) -> list[User]:
    require_permissions("admin.users", "*")(actor)
    return db.query(User).order_by(User.id).all()


def get_user(db: Session, user_id: int, actor: User) -> User:
    require_permissions("admin.users", "*")(actor)
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found")
    return u


def _count_active_admins(db: Session, exclude_user_id: int | None = None) -> int:
    count = 0
    for u in db.query(User).filter(User.is_active.is_(True)).all():
        if exclude_user_id is not None and u.id == exclude_user_id:
            continue
        if "*" in user_permissions(u):
            count += 1
    return count


def _count_active_super_admins(db: Session, exclude_user_id: int | None = None) -> int:
    count = 0
    for u in db.query(User).filter(User.is_active.is_(True)).all():
        if exclude_user_id is not None and u.id == exclude_user_id:
            continue
        if is_super_admin(u):
            count += 1
    return count


def _lock_active_user_memberships(db: Session) -> None:
    """Serialize changes that can remove the final administrator membership."""
    # NO KEY UPDATE still serializes membership mutations while allowing the
    # KEY SHARE lock used by a concurrent audit-log foreign-key insertion.
    # SQLite ignores the lock clause in disposable tests.
    db.query(User).filter(User.is_active.is_(True)).order_by(User.id).with_for_update(
        of=User, key_share=True
    ).populate_existing().all()




def update_user(db: Session, user_id: int, payload: UserUpdate, current: User) -> User:
    require_permissions("admin.users", "*")(current)
    # Lock memberships in stable order before taking a target credential lock.
    if {"role_id", "extra_permissions", "access_policy", "is_active", "factory_code"} & payload.model_fields_set:
        _lock_active_user_memberships(db)
    credential_change = bool(payload.password)
    u = (
        lock_user_for_credential_change(db, user_id, require_active=False)
        if credential_change
        else db.get(User, user_id)
    )
    if not u:
        raise HTTPException(404, "User not found")
    data = payload.model_dump(exclude_unset=True)
    old_access = _user_access_values(u)
    actor_is_super_admin = is_super_admin(current)
    if "factory_code" in data:
        data["factory_code"] = normalize_factory_code(data["factory_code"])
        if not actor_is_super_admin and data["factory_code"] != u.factory_code:
            raise HTTPException(403, "Only Super Admin can change a user's factory")
        if data["factory_code"] != u.factory_code:
            set_user_credential_cutoff(u, datetime.now(timezone.utc))
    if "extra_permissions" in data:
        data["extra_permissions"] = normalize_permissions(data["extra_permissions"])
    # Guard against self-escalation and self-lockout by a non-superadmin manager.
    if u.id == current.id and not actor_is_super_admin:
        if "role_id" in data and data["role_id"] != u.role_id:
            raise HTTPException(403, "You cannot change your own role")
        if "extra_permissions" in data and set(data["extra_permissions"]) != set(normalize_permissions(u.extra_permissions)):
            raise HTTPException(403, "You cannot change your own additional access")
        if data.get("is_active") is False:
            raise HTTPException(403, "You cannot deactivate your own account")
        if "access_policy" in data and (data["access_policy"] or {}) != (u.access_policy or {}):
            raise HTTPException(403, "You cannot change your own access")
    # A role change may only grant permissions the actor already holds.
    if "role_id" in data and data["role_id"] != u.role_id:
        _assert_can_grant_role(db, current, data["role_id"])
    if "extra_permissions" in data:
        _assert_can_grant_permissions(current, data["extra_permissions"], previous=u.extra_permissions)
    # Never let the last active administrator be demoted or deactivated.
    was_admin = "*" in user_permissions(u)
    was_super_admin = is_super_admin(u)
    future_subject = _assert_policy_change(db, current, {**old_access, **data}, old_access)
    future_permissions = user_permissions(future_subject)
    future_admin = "*" in future_permissions
    future_super_admin = is_super_admin(future_subject)
    if u.id != current.id and (was_admin or future_admin or was_super_admin or future_super_admin) and not actor_is_super_admin:
        raise HTTPException(403, "Only a super admin can manage administrator accounts")
    demoting_admin = was_admin and not future_admin
    demoting_super_admin = was_super_admin and not future_super_admin
    deactivating = data.get("is_active") is False and u.is_active
    if (demoting_super_admin or deactivating) and was_super_admin and _count_active_super_admins(db, exclude_user_id=u.id) == 0:
        raise HTTPException(400, "Cannot remove the last active super administrator")
    if (demoting_admin or deactivating) and was_admin and _count_active_admins(db, exclude_user_id=u.id) == 0:
        raise HTTPException(400, "Cannot remove the last active administrator")
    if "password" in data and data["password"]:
        require_strong_password(data["password"])
    if "email" in data and data["email"]:
        data["email"] = normalize_email(data["email"])
    if data.get("name") is not None and len(data["name"]) > 128:
        raise HTTPException(422, "User name must be at most 128 characters")
    if data.get("email") is not None and len(data["email"]) > 255:
        raise HTTPException(422, "User email must be at most 255 characters")
    if "password" in data and data["password"]:
        apply_password_credential_change(db, u, data.pop("password"))
    elif "password" in data:
        data.pop("password")
    apply_admin_user_changes(u, data)
    audit_new_value = dict(data)
    if credential_change:
        audit_new_value.update({"credential_changed": True, "reset_links_invalidated": True})
    log_action(db, current, "update", "User", u.id, old_value=old_access, new_value=audit_new_value)
    db.commit()
    db.refresh(u)
    return u
