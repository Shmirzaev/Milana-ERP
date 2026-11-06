"""Authentication decisions and factory-switch auditing; token transport stays in routes."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import user_permissions
from app.core.dt import as_utc, utcnow
from app.core.security import hash_password, is_legacy_default_admin_login, normalize_email, validate_password_strength, verify_password
from app.core.shared_store import SharedCounterStore
from app.libs.dto.identity.auth import ChangePasswordIn, ProfileUpdateIn, ResetPasswordIn, UserMe
from app.models.audit_service import log_action
from app.models.credentials_service import apply_password_credential_change, lock_user_for_credential_change
from app.models.factory_scope_service import assigned_factory_code, authorize_login_factory, available_factory_codes, selected_factory_code
from app.models.password_reset_service import create_password_reset_token, password_reset_hash, password_reset_url
from app.schemas import PasswordResetToken, User
from app.schemas.core_persistence import add_notification_row
from app.schemas.identity.user_persistence import record_user_login_activity, record_user_seen, set_user_profile

_DUMMY_PASSWORD_HASH = hash_password("dummy-login-password-0")


@contextmanager
def auth_counter_store(provider: Callable[[], SharedCounterStore]) -> Iterator[SharedCounterStore]:
    try:
        yield provider()
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Authentication is temporarily unavailable. Try again later.",
        ) from None


def login_user(
    db: Session, email: str, password: str, client_ip: str,
    requested_factory: str | None, store_provider: Callable[[], SharedCounterStore],
) -> tuple[User, str | None]:
    """Authenticate, authorize an optional factory, and commit login activity once."""
    email_norm = normalize_email(email)
    key = f"{client_ip}:{email_norm}"
    with auth_counter_store(store_provider) as store:
        locked_ttl = store.ttl(f"auth:login-lock:{key}")
        if locked_ttl:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Too many failed login attempts. Try again later.",
                headers={"Retry-After": str(locked_ttl)},
            )

    user = db.query(User).filter(User.email == email_norm).first()
    password_hash = user.password_hash if user else _DUMMY_PASSWORD_HASH
    try:
        password_ok = verify_password(password, password_hash)
    except Exception:
        password_ok = False
    blocked_default = (
        is_legacy_default_admin_login(email_norm, password)
        and not settings.ALLOW_INSECURE_DEFAULT_ADMIN_LOGIN
    )
    if blocked_default or not user or not user.is_active or not password_ok:
        if settings.AUTH_MAX_FAILED_ATTEMPTS > 0:
            with auth_counter_store(store_provider) as store:
                failure_key = f"auth:login-fail:{key}"
                attempts = store.increment(failure_key, settings.AUTH_WINDOW_SECONDS)
                if attempts >= settings.AUTH_MAX_FAILED_ATTEMPTS:
                    store.set(f"auth:login-lock:{key}", "1", settings.AUTH_LOCKOUT_SECONDS)
                    store.delete(failure_key)
        raise HTTPException(401, "Invalid credentials")

    with auth_counter_store(store_provider) as store:
        store.delete(f"auth:login-fail:{key}", f"auth:login-lock:{key}")
    factory_code = authorize_login_factory(user, requested_factory) if requested_factory is not None else None
    record_user_login_activity(db, user, utcnow())
    db.commit()
    return user, factory_code


def request_password_reset(
    db: Session, email: str, client_ip: str, store_provider: Callable[[], SharedCounterStore],
) -> tuple[User, str] | None:
    """Commit the token and admin notices before the route queues delivery."""
    email_norm = normalize_email(email)
    with auth_counter_store(store_provider) as store:
        for key in (f"ip:{client_ip}", f"email:{email_norm}"):
            requests = store.increment(f"auth:reset:{key}", 60 * 60)
            if requests > 5:
                retry_after = store.ttl(f"auth:reset:{key}") or 60 * 60
                raise HTTPException(
                    status.HTTP_429_TOO_MANY_REQUESTS,
                    "Too many password reset requests. Try again later.",
                    headers={"Retry-After": str(retry_after)},
                )
    user = db.query(User).filter(User.email == email_norm).first()
    if not user or not user.is_active:
        return None
    raw_token = create_password_reset_token(db, user)
    reset_url = password_reset_url(raw_token)
    recipients = [
        admin for admin in db.query(User).filter(User.is_active.is_(True)).all()
        if "*" in user_permissions(admin) or "admin.users" in user_permissions(admin)
    ]
    for admin in recipients:
        add_notification_row(
            db, user_id=admin.id, title="Password reset requested",
            message=(
                f"{user.name} ({user.email}) requested a password reset. "
                "A reset email was queued."
            ),
            link="/admin/users",
        )
    db.commit()
    return user, reset_url


def complete_password_reset(
    db: Session, payload: ResetPasswordIn, store_provider: Callable[[], SharedCounterStore],
) -> None:
    with auth_counter_store(store_provider) as store:
        store.ttl("auth:reset-completion")
    if payload.new_password != payload.confirm_new_password:
        raise HTTPException(400, "New passwords do not match")
    try:
        validate_password_strength(payload.new_password)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error

    token_hash = password_reset_hash(payload.token.strip())
    user_id = db.query(PasswordResetToken.user_id).filter(PasswordResetToken.token_hash == token_hash).scalar()
    if user_id is None:
        raise HTTPException(400, "Invalid or expired reset link")

    # Lock the account before re-reading the token so sibling resets serialize.
    user = lock_user_for_credential_change(db, user_id, require_active=True)
    reset_token = (
        db.query(PasswordResetToken)
        .filter(PasswordResetToken.token_hash == token_hash)
        .populate_existing()
        .first()
    )
    now = datetime.now(timezone.utc)
    if (
        not reset_token
        or reset_token.used_at is not None
        or as_utc(reset_token.expires_at) < now
        or not user
        or not user.is_active
    ):
        raise HTTPException(400, "Invalid or expired reset link")

    apply_password_credential_change(db, user, payload.new_password, changed_at=now)
    log_action(
        db, user, "reset_password", "User", user.id,
        new_value={"credential_changed": True, "reset_links_invalidated": True},
    )
    db.commit()


def change_own_password(db: Session, user: User, payload: ChangePasswordIn) -> None:
    if payload.new_password != payload.confirm_new_password:
        raise HTTPException(400, "New passwords do not match")
    locked_user = lock_user_for_credential_change(db, user.id, require_active=True)
    if not locked_user:
        raise HTTPException(401, "Invalid credentials")
    if not verify_password(payload.current_password, locked_user.password_hash):
        raise HTTPException(400, "Current password is incorrect")
    try:
        validate_password_strength(payload.new_password)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    apply_password_credential_change(db, locked_user, payload.new_password)
    log_action(
        db, locked_user, "change_password", "User", locked_user.id,
        new_value={"credential_changed": True, "reset_links_invalidated": True},
    )
    db.commit()


def read_current_user(db: Session, user: User) -> UserMe:
    record_user_seen(db, user, utcnow())
    db.commit()
    return _user_me(user)


def update_current_profile(db: Session, user: User, payload: ProfileUpdateIn) -> UserMe:
    if len(payload.name) > 128:
        raise HTTPException(422, "Name must be at most 128 characters")
    email = normalize_email(str(payload.email))
    if email != user.email:
        raise HTTPException(400, "Email cannot be changed from Profile")
    old_value = {"name": user.name, "email": user.email}
    set_user_profile(db, user, name=payload.name.strip())
    log_action(db, user, "update_profile", "User", user.id, old_value=old_value,
               new_value={"name": user.name, "email": user.email})
    db.commit()
    db.refresh(user)
    return _user_me(user)


def _user_me(user: User) -> UserMe:
    return UserMe(
        sewing_band_id=user.sewing_band_id,
        id=user.id,
        name=user.name,
        email=user.email,
        role=user.role.name if user.role else None,
        department=user.department.name if user.department else None,
        department_code=user.department.code if user.department else None,
        extra_permissions=user.extra_permissions or [],
        permissions=user_permissions(user),
        access_configured=selected_factory_code(user) in (user.access_policy or {}),
        factory_code=selected_factory_code(user),
        assigned_factory_code=assigned_factory_code(user),
        available_factories=available_factory_codes(user),
    )


def select_session_factory(db: Session, user: User, requested_factory_code: str) -> str:
    if not 1 <= len(requested_factory_code) <= 3:
        raise HTTPException(422, "Factory code must be 1 to 3 characters")
    factory_code = authorize_login_factory(user, requested_factory_code)
    previous = selected_factory_code(user)
    if factory_code != previous:
        log_action(
            db, user, "switch_factory", "User", user.id,
            old_value={"factory_code": previous}, new_value={"factory_code": factory_code},
        )
        db.commit()
    return factory_code
