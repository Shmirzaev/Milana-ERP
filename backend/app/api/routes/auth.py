
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from typing import Annotated
from fastapi import Depends
from datetime import datetime, timezone
from pydantic import BaseModel, EmailStr

from app.core.config import settings
from app.core.proxy_trust import client_ip, effective_request_scheme
from app.core.deps import DbSession, CurrentUser, user_permissions
from app.core.dt import as_utc, utcnow
from app.core.shared_store import get_shared_counter_store
from app.core.security import (
    create_access_token,
    normalize_email,
    validate_password_strength,
    verify_password,
)
from app.schemas import (
    User, Notification, PasswordResetToken,
)
from app.libs.dto.identity.auth import ForgotPasswordIn, LoginIn, LoginOk, ResetPasswordIn, TokenOut, UserMe
from app.models.audit_service import log_action
from app.models.credentials_service import apply_password_credential_change, lock_user_for_credential_change
from app.models.factory_scope_service import assigned_factory_code, available_factory_codes, selected_factory_code
from app.models.identity.authentication_service import auth_counter_store, login_user, select_session_factory
from app.models.password_reset_service import (
    create_password_reset_token,
    password_reset_hash,
    password_reset_url,
    send_password_email_safely,
)

router = APIRouter(prefix="/auth", tags=["auth"])
session_router = APIRouter(prefix="/session", tags=["auth"])

class ProfileUpdateIn(BaseModel):
    name: str
    email: EmailStr


class FactorySwitchIn(BaseModel):
    factory_code: str


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str
    confirm_new_password: str


def _client_ip(request: Request) -> str:
    return client_ip(request)


def _enforce_reset_rate_limit(request: Request, email: str) -> None:
    with auth_counter_store(get_shared_counter_store) as store:
        client = _client_ip(request)
        keys = [f"ip:{client}", f"email:{normalize_email(email)}"]
        for key in keys:
            requests = store.increment(f"auth:reset:{key}", 60 * 60)
            if requests > 5:
                retry_after = store.ttl(f"auth:reset:{key}") or 60 * 60
                raise HTTPException(
                    status.HTTP_429_TOO_MANY_REQUESTS,
                    "Too many password reset requests. Try again later.",
                    headers={"Retry-After": str(retry_after)},
                )


def _is_https_request(request: Request) -> bool:
    return (
        settings.strict_security_required
        or effective_request_scheme(request) == "https"
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


@session_router.post("/login", response_model=LoginOk)
@router.post("/login", response_model=LoginOk)
def login_oauth(
    request: Request,
    response: Response,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: DbSession,
):
    """Browser login: set the HttpOnly auth cookie and do not expose the JWT to JavaScript."""
    user, _ = login_user(db, form_data.username, form_data.password, _client_ip(request), None, get_shared_counter_store)
    token = create_access_token(user.id)
    _set_auth_cookie(request, response, token)
    return LoginOk()


@session_router.post("/login-json", response_model=LoginOk)
@router.post("/login-json", response_model=LoginOk)
def login_json(request: Request, response: Response, payload: LoginIn, db: DbSession):
    user, factory_code = login_user(db, str(payload.email), payload.password, _client_ip(request), payload.factory_code, get_shared_counter_store)
    token = create_access_token(user.id, extra={"factory_code": factory_code})
    _set_auth_cookie(request, response, token)
    return LoginOk()


@session_router.post("/switch-factory", response_model=LoginOk)
@router.post("/switch-factory", response_model=LoginOk)
def switch_factory(request: Request, response: Response, payload: FactorySwitchIn, db: DbSession, user: CurrentUser):
    factory_code = select_session_factory(db, user, payload.factory_code)
    token = create_access_token(user.id, extra={"factory_code": factory_code})
    _set_auth_cookie(request, response, token)
    return LoginOk()


@router.post("/token", response_model=TokenOut)
def token_oauth(
    request: Request,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: DbSession,
):
    """Machine/API-client login: return a bearer token without setting browser cookies."""
    user, _ = login_user(db, form_data.username, form_data.password, _client_ip(request), None, get_shared_counter_store)
    return TokenOut(access_token=create_access_token(user.id))


@session_router.post("/logout")
@router.post("/logout")
def logout(request: Request, response: Response):
    _clear_auth_cookie(request, response)
    return {"message": "logged_out"}


@session_router.post("/forgot-password")
@router.post("/forgot-password")
def forgot_password(payload: ForgotPasswordIn, db: DbSession, background_tasks: BackgroundTasks, request: Request):
    email = normalize_email(str(payload.email))
    _enforce_reset_rate_limit(request, email)
    user = db.query(User).filter(User.email == email).first()
    if user and user.is_active:
        raw_token = create_password_reset_token(db, user)
        reset_url = password_reset_url(raw_token)
        background_tasks.add_task(send_password_email_safely, user.email, user.name, reset_url, user.id)
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


@session_router.post("/reset-password")
@router.post("/reset-password")
def reset_password(payload: ResetPasswordIn, db: DbSession):
    with auth_counter_store(get_shared_counter_store) as store:
        store.ttl("auth:reset-completion")
    if payload.new_password != payload.confirm_new_password:
        raise HTTPException(400, "New passwords do not match")
    try:
        validate_password_strength(payload.new_password)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e

    token_hash = password_reset_hash(payload.token.strip())
    user_id = db.query(PasswordResetToken.user_id).filter(PasswordResetToken.token_hash == token_hash).scalar()
    if user_id is None:
        raise HTTPException(400, "Invalid or expired reset link")

    # Sibling links must serialize on the same account, not individual tokens.
    # Re-read the token after acquiring the lock so a waiting reset observes the
    # first reset's invalidation even if this session already loaded the token.
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
        db,
        user,
        "reset_password",
        "User",
        user.id,
        new_value={"credential_changed": True, "reset_links_invalidated": True},
    )
    db.commit()
    return {"message": "password_reset"}


@session_router.get("/me", response_model=UserMe)
@router.get("/me", response_model=UserMe)
def me(user: CurrentUser, db: DbSession):
    user.last_seen_at = utcnow()
    db.commit()
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


@session_router.patch("/me", response_model=UserMe)
@router.patch("/me", response_model=UserMe)
def update_me(payload: ProfileUpdateIn, db: DbSession, user: CurrentUser):
    if len(payload.name) > 128:
        raise HTTPException(422, "Name must be at most 128 characters")
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


@session_router.post("/change-password")
@router.post("/change-password")
def change_password(payload: ChangePasswordIn, db: DbSession, user: CurrentUser):
    if payload.new_password != payload.confirm_new_password:
        raise HTTPException(400, "New passwords do not match")
    locked_user = lock_user_for_credential_change(db, user.id, require_active=True)
    if not locked_user:
        raise HTTPException(401, "Invalid credentials")
    if not verify_password(payload.current_password, locked_user.password_hash):
        raise HTTPException(400, "Current password is incorrect")
    try:
        validate_password_strength(payload.new_password)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    apply_password_credential_change(db, locked_user, payload.new_password)
    log_action(
        db,
        locked_user,
        "change_password",
        "User",
        locked_user.id,
        new_value={"credential_changed": True, "reset_links_invalidated": True},
    )
    db.commit()
    return {"message": "password_updated"}


@session_router.get("/login-panel")
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
