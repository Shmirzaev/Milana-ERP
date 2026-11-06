
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response
from fastapi.security import OAuth2PasswordRequestForm
from typing import Annotated
from fastapi import Depends
from pydantic import BaseModel, EmailStr

from app.core.config import settings
from app.core.proxy_trust import client_ip, effective_request_scheme
from app.core.deps import DbSession, CurrentUser, user_permissions
from app.core.dt import utcnow
from app.core.shared_store import get_shared_counter_store
from app.core.security import (
    create_access_token,
    normalize_email,
)
from app.schemas import User
from app.libs.dto.identity.auth import ChangePasswordIn, ForgotPasswordIn, LoginIn, LoginOk, ResetPasswordIn, TokenOut, UserMe
from app.models.audit_service import log_action
from app.models.factory_scope_service import assigned_factory_code, available_factory_codes, selected_factory_code
from app.models.identity.authentication_service import change_own_password, complete_password_reset, login_user, request_password_reset, select_session_factory
from app.models.password_reset_service import (
    send_password_email_safely,
)

router = APIRouter(prefix="/auth", tags=["auth"])
session_router = APIRouter(prefix="/session", tags=["auth"])

class ProfileUpdateIn(BaseModel):
    name: str
    email: EmailStr


class FactorySwitchIn(BaseModel):
    factory_code: str


def _client_ip(request: Request) -> str:
    return client_ip(request)


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
    delivery = request_password_reset(db, str(payload.email), _client_ip(request), get_shared_counter_store)
    if delivery:
        user, reset_url = delivery
        background_tasks.add_task(send_password_email_safely, user.email, user.name, reset_url, user.id)
    return {"message": "If this account exists, a reset link has been sent."}


@session_router.post("/reset-password")
@router.post("/reset-password")
def reset_password(payload: ResetPasswordIn, db: DbSession):
    complete_password_reset(db, payload, get_shared_counter_store)
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
    change_own_password(db, user, payload)
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
