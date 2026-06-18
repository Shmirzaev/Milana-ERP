import time as time_module
import hashlib
import ipaddress
import logging
import secrets

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from typing import Annotated
from fastapi import Depends
from datetime import datetime, timedelta, timezone
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import DbSession, CurrentUser, user_permissions
from app.core.dt import as_utc, utcnow
from app.db.session import SessionLocal
from app.core.security import (
    create_access_token,
    hash_password,
    is_legacy_default_admin_login,
    normalize_email,
    validate_password_strength,
    verify_password,
)
from app.models import (
    User, Notification, PasswordResetToken,
)
from app.schemas.auth import ForgotPasswordIn, LoginIn, LoginOk, ResetPasswordIn, TokenOut, UserMe
from app.services.audit import log_action
from app.services.email import send_password_reset_email

router = APIRouter(prefix="/auth", tags=["auth"])
log = logging.getLogger(__name__)

_DUMMY_PASSWORD_HASH = hash_password("dummy-login-password-0")
_LOGIN_FAILURES: dict[str, list[float]] = {}
_LOGIN_LOCKS: dict[str, float] = {}
_RESET_REQUESTS: dict[str, list[float]] = {}


class ProfileUpdateIn(BaseModel):
    name: str
    email: EmailStr


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str
    confirm_new_password: str


def _client_ip(request: Request) -> str:
    """Resolve the real client IP. Behind HF Spaces / Vercel the socket peer is
    the platform proxy (identical for every user), so rate-limit buckets keyed on
    it collapse into one global bucket. The platform sets X-Forwarded-For with the
    originating client as the left-most entry. Only trust proxy headers when the
    socket peer is a private/loopback proxy; otherwise a direct client could
    spoof X-Forwarded-For and bypass throttling."""
    peer = request.client.host if request.client else "unknown"
    peer_is_trusted_proxy = False
    try:
        peer_ip = ipaddress.ip_address(peer)
        peer_is_trusted_proxy = peer_ip.is_private or peer_ip.is_loopback
    except ValueError:
        peer_is_trusted_proxy = False

    if not peer_is_trusted_proxy:
        return peer

    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    real_ip = request.headers.get("x-real-ip")
    if real_ip and real_ip.strip():
        return real_ip.strip()
    return peer


def _login_key(request: Request, email: str) -> str:
    return f"{_client_ip(request)}:{normalize_email(email)}"


def _enforce_login_rate_limit(key: str) -> None:
    now = time_module.monotonic()
    locked_until = _LOGIN_LOCKS.get(key)
    if locked_until and locked_until > now:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many failed login attempts. Try again later.",
        )
    if locked_until:
        _LOGIN_LOCKS.pop(key, None)

    window_started = now - settings.AUTH_WINDOW_SECONDS
    failures = [ts for ts in _LOGIN_FAILURES.get(key, []) if ts >= window_started]
    if failures:
        _LOGIN_FAILURES[key] = failures
    else:
        _LOGIN_FAILURES.pop(key, None)


def _record_login_failure(key: str) -> None:
    if settings.AUTH_MAX_FAILED_ATTEMPTS <= 0:
        return
    now = time_module.monotonic()
    window_started = now - settings.AUTH_WINDOW_SECONDS
    failures = [ts for ts in _LOGIN_FAILURES.get(key, []) if ts >= window_started]
    failures.append(now)
    if len(failures) >= settings.AUTH_MAX_FAILED_ATTEMPTS:
        _LOGIN_LOCKS[key] = now + settings.AUTH_LOCKOUT_SECONDS
        _LOGIN_FAILURES.pop(key, None)
    else:
        _LOGIN_FAILURES[key] = failures


def _clear_login_failures(key: str) -> None:
    _LOGIN_FAILURES.pop(key, None)
    _LOGIN_LOCKS.pop(key, None)


def _enforce_reset_rate_limit(request: Request, email: str) -> None:
    now = time_module.monotonic()
    client = _client_ip(request)
    keys = [f"ip:{client}", f"email:{normalize_email(email)}"]
    window_started = now - 60 * 60
    for key in keys:
        requests = [ts for ts in _RESET_REQUESTS.get(key, []) if ts >= window_started]
        if len(requests) >= 5:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Too many password reset requests. Try again later.",
            )
        requests.append(now)
        _RESET_REQUESTS[key] = requests


def _authenticate(request: Request, db: Session, email: str, password: str) -> User:
    email_norm = normalize_email(email)
    key = _login_key(request, email_norm)
    _enforce_login_rate_limit(key)

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
        _record_login_failure(key)
        raise HTTPException(401, "Invalid credentials")

    _clear_login_failures(key)
    return user


def _password_reset_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _password_reset_url(token: str) -> str:
    base = settings.FRONTEND_BASE_URL.rstrip("/")
    return f"{base}/reset-password?token={token}"


def _is_https_request(request: Request) -> bool:
    proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    forwarded_ssl = request.headers.get("x-forwarded-ssl", "").strip().lower()
    host = request.headers.get("host", "").split(":", 1)[0].strip().lower()
    return (
        settings.strict_security_required
        or request.url.scheme == "https"
        or proto == "https"
        or forwarded_ssl == "on"
        or host.endswith(".vercel.app")
        or host.endswith(".hf.space")
    )


def _set_auth_cookie(request: Request, response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.AUTH_COOKIE_NAME,
        value=token,
        max_age=settings.JWT_EXPIRES_MINUTES * 60,
        httponly=True,
        secure=_is_https_request(request),
        samesite="lax",
        path="/",
    )


def _clear_auth_cookie(request: Request, response: Response) -> None:
    response.delete_cookie(
        key=settings.AUTH_COOKIE_NAME,
        httponly=True,
        secure=_is_https_request(request),
        samesite="lax",
        path="/",
    )


def _safe_reset_delivery_error(error: str) -> str:
    _ = error
    # Delivery/provider errors can echo the submitted email body, including the
    # reset URL. Never persist or log raw provider text for reset emails.
    return "Email delivery failed; provider details suppressed because they may contain reset-token material."


def _notify_admins_about_reset_email_failure(user_id: int, reset_url: str, error: str) -> None:
    _ = reset_url  # Never persist raw reset tokens in notifications or audit trails.
    safe_error = _safe_reset_delivery_error(error)
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return
        recipients = [
            admin for admin in db.query(User).filter(User.is_active.is_(True)).all()
            if "*" in user_permissions(admin) or "admin.users" in user_permissions(admin)
        ]
        for admin in recipients:
            db.add(Notification(
                user_id=admin.id,
                title="Password reset email failed",
                message=(
                    f"{user.name} ({user.email}) requested a password reset, but email delivery failed. "
                    "Do not share stored links; generate a fresh reset after email delivery is restored. "
                    f"Error: {safe_error}"
                ),
                link="/admin/users",
            ))
        if recipients:
            db.commit()
    except Exception:
        db.rollback()
        log.exception("Could not create password reset failure notification for user_id=%s", user_id)
    finally:
        db.close()


def _send_password_reset_email_safely(email: str, name: str, reset_url: str, user_id: int) -> None:
    try:
        if send_password_reset_email(email, name, reset_url):
            log.info("Password reset email sent to %s", email)
        else:
            log.warning("Password reset email not sent to %s: SMTP is not configured", email)
            _notify_admins_about_reset_email_failure(user_id, reset_url, "SMTP is not configured")
    except Exception as exc:
        log.warning(
            "Password reset email failed for %s (%s); details suppressed because they may contain reset-token material",
            email,
            type(exc).__name__,
        )
        _notify_admins_about_reset_email_failure(user_id, reset_url, str(exc))


def _mark_successful_login(db: Session, user: User) -> None:
    now = utcnow()
    user.last_login_at = now
    user.last_seen_at = now
    db.commit()


@router.post("/login", response_model=LoginOk)
def login_oauth(
    request: Request,
    response: Response,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: DbSession,
):
    """Browser login: set the HttpOnly auth cookie and do not expose the JWT to JavaScript."""
    user = _authenticate(request, db, form_data.username, form_data.password)
    _mark_successful_login(db, user)
    token = create_access_token(user.id)
    _set_auth_cookie(request, response, token)
    return LoginOk()


@router.post("/login-json", response_model=LoginOk)
def login_json(request: Request, response: Response, payload: LoginIn, db: DbSession):
    user = _authenticate(request, db, str(payload.email), payload.password)
    _mark_successful_login(db, user)
    token = create_access_token(user.id)
    _set_auth_cookie(request, response, token)
    return LoginOk()


@router.post("/token", response_model=TokenOut)
def token_oauth(
    request: Request,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: DbSession,
):
    """Machine/API-client login: return a bearer token without setting browser cookies."""
    user = _authenticate(request, db, form_data.username, form_data.password)
    _mark_successful_login(db, user)
    return TokenOut(access_token=create_access_token(user.id))


@router.post("/logout")
def logout(request: Request, response: Response):
    _clear_auth_cookie(request, response)
    return {"message": "logged_out"}


@router.post("/forgot-password")
def forgot_password(payload: ForgotPasswordIn, db: DbSession, background_tasks: BackgroundTasks, request: Request):
    email = normalize_email(str(payload.email))
    _enforce_reset_rate_limit(request, email)
    user = db.query(User).filter(User.email == email).first()
    if user and user.is_active:
        raw_token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.PASSWORD_RESET_TOKEN_MINUTES)
        db.add(PasswordResetToken(
            user_id=user.id,
            token_hash=_password_reset_hash(raw_token),
            expires_at=expires_at,
        ))
        reset_url = _password_reset_url(raw_token)
        background_tasks.add_task(_send_password_reset_email_safely, user.email, user.name, reset_url, user.id)
        recipients = [
            admin for admin in db.query(User).filter(User.is_active.is_(True)).all()
            if "*" in user_permissions(admin) or "admin.users" in user_permissions(admin)
        ]
        for admin in recipients:
            db.add(Notification(
                user_id=admin.id,
                title="Password reset requested",
                message=(
                    f"{user.name} ({user.email}) requested a password reset. "
                    "A reset email was queued."
                ),
                link="/admin/users",
            ))
        db.commit()
    return {"message": "If this account exists, a reset link has been sent."}


@router.post("/reset-password")
def reset_password(payload: ResetPasswordIn, db: DbSession):
    if payload.new_password != payload.confirm_new_password:
        raise HTTPException(400, "New passwords do not match")
    try:
        validate_password_strength(payload.new_password)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e

    token_hash = _password_reset_hash(payload.token.strip())
    reset_token = db.query(PasswordResetToken).filter(PasswordResetToken.token_hash == token_hash).first()
    now = datetime.now(timezone.utc)
    if (
        not reset_token
        or reset_token.used_at is not None
        or as_utc(reset_token.expires_at) < now
        or not reset_token.user
        or not reset_token.user.is_active
    ):
        raise HTTPException(400, "Invalid or expired reset link")

    reset_token.user.password_hash = hash_password(payload.new_password)
    reset_token.user.tokens_valid_from = now
    reset_token.used_at = now
    db.commit()
    return {"message": "password_reset"}


@router.get("/me", response_model=UserMe)
def me(user: CurrentUser, db: DbSession):
    user.last_seen_at = utcnow()
    db.commit()
    return UserMe(
        id=user.id,
        name=user.name,
        email=user.email,
        role=user.role.name if user.role else None,
        department=user.department.name if user.department else None,
        extra_permissions=user.extra_permissions or [],
        permissions=user_permissions(user),
    )


@router.patch("/me", response_model=UserMe)
def update_me(payload: ProfileUpdateIn, db: DbSession, user: CurrentUser):
    email = normalize_email(str(payload.email))
    if db.query(User).filter(User.email == email, User.id != user.id).first():
        raise HTTPException(400, "Email already exists")
    old_value = {"name": user.name, "email": user.email}
    user.name = payload.name.strip()
    user.email = email
    log_action(db, user, "update_profile", "User", user.id, old_value=old_value, new_value={"name": user.name, "email": user.email})
    db.commit()
    db.refresh(user)
    return UserMe(
        id=user.id,
        name=user.name,
        email=user.email,
        role=user.role.name if user.role else None,
        department=user.department.name if user.department else None,
        extra_permissions=user.extra_permissions or [],
        permissions=user_permissions(user),
    )


@router.post("/change-password")
def change_password(payload: ChangePasswordIn, db: DbSession, user: CurrentUser):
    if payload.new_password != payload.confirm_new_password:
        raise HTTPException(400, "New passwords do not match")
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(400, "Current password is incorrect")
    try:
        validate_password_strength(payload.new_password)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    user.password_hash = hash_password(payload.new_password)
    user.tokens_valid_from = datetime.now(timezone.utc)
    log_action(db, user, "change_password", "User", user.id)
    db.commit()
    return {"message": "password_updated"}


@router.get("/login-panel")
def login_panel(db: DbSession, tz: str | None = None):
    _ = db, tz
    # This endpoint is intentionally public for the login screen, so it must
    # never expose live orders, revenue, tasks, or operational volumes.
    return {
        "active_orders": 0,
        "todays_receipts": 0,
        "late_orders": 0,
        "production_14d": [0 for _ in range(14)],
        "open_tasks": [
            {"title": "Secure sign-in required", "priority": "medium", "status": "protected"}
        ],
    }
