"""Authentication decisions and factory-switch auditing; token transport stays in routes."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import user_permissions
from app.core.dt import utcnow
from app.core.security import hash_password, is_legacy_default_admin_login, normalize_email, verify_password
from app.core.shared_store import SharedCounterStore
from app.models.audit_service import log_action
from app.models.factory_scope_service import authorize_login_factory, selected_factory_code
from app.models.password_reset_service import create_password_reset_token, password_reset_url
from app.schemas import User
from app.schemas.core_persistence import add_notification_row
from app.schemas.identity.user_persistence import record_user_login_activity

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
