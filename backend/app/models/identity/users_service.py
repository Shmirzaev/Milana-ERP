"""Create a user with the existing grant, audit, and setup-link contract."""

import secrets

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.deps import is_super_admin, normalize_permissions, require_permissions
from app.core.security import hash_password, normalize_email, validate_password_strength
from app.libs.dto.catalog.catalog import UserIn
from app.models.audit_service import log_action
from app.models.factory_scope_service import normalize_factory_code, selected_factory_code
from app.models.identity.access_service import (
    _assert_can_grant_permissions, _assert_can_grant_role, _assert_policy_change,
)
from app.models.password_reset_service import create_password_reset_token, password_reset_url
from app.schemas import User
from app.schemas.identity.user_persistence import add_user


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
    """Read all accounts in ID order after the existing management grant check."""
    require_permissions("admin.users", "*")(actor)
    return db.query(User).order_by(User.id).all()
