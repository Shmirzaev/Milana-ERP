import time as time_module

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from typing import Annotated
from fastapi import Depends
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from pydantic import BaseModel, EmailStr
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import DbSession, CurrentUser, user_permissions
from app.core.dt import as_utc
from app.core.security import (
    create_access_token,
    hash_password,
    is_legacy_default_admin_login,
    normalize_email,
    validate_password_strength,
    verify_password,
)
from app.models import (
    User, Notification, SalesOrder, Payment, Task,
    CuttingRecord, PrintingRecord, SewingRecord, PackagingRecord,
)
from app.schemas.auth import ForgotPasswordIn, LoginIn, TokenOut, UserMe
from app.services.audit import log_action

router = APIRouter(prefix="/auth", tags=["auth"])

_DUMMY_PASSWORD_HASH = hash_password("dummy-login-password-0")
_LOGIN_FAILURES: dict[str, list[float]] = {}
_LOGIN_LOCKS: dict[str, float] = {}


class ProfileUpdateIn(BaseModel):
    name: str
    email: EmailStr


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str
    confirm_new_password: str


def _login_key(request: Request, email: str) -> str:
    client = request.client.host if request.client else "unknown"
    return f"{client}:{normalize_email(email)}"


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


@router.post("/login", response_model=TokenOut)
def login_oauth(
    request: Request,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: DbSession,
):
    """OAuth2-compatible login (form: username=email, password)."""
    user = _authenticate(request, db, form_data.username, form_data.password)
    token = create_access_token(user.id)
    return TokenOut(access_token=token)


@router.post("/login-json", response_model=TokenOut)
def login_json(request: Request, payload: LoginIn, db: DbSession):
    user = _authenticate(request, db, str(payload.email), payload.password)
    return TokenOut(access_token=create_access_token(user.id))


@router.post("/forgot-password")
def forgot_password(payload: ForgotPasswordIn, db: DbSession):
    email = normalize_email(str(payload.email))
    user = db.query(User).filter(User.email == email).first()
    if user:
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
                    "Open Admin / Users and set a new password."
                ),
                link="/admin/users",
            ))
        if recipients:
            db.commit()
    return {"message": "If this account exists, an admin has been notified."}


@router.get("/me", response_model=UserMe)
def me(user: CurrentUser):
    return UserMe(
        id=user.id,
        name=user.name,
        email=user.email,
        role=user.role.name if user.role else None,
        department=user.department.name if user.department else None,
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
    log_action(db, user, "change_password", "User", user.id)
    db.commit()
    return {"message": "password_updated"}


@router.get("/login-panel")
def login_panel(db: DbSession, tz: str | None = None):
    now = datetime.now(timezone.utc)
    try:
        client_tz = ZoneInfo(tz) if tz else timezone.utc
    except Exception:
        client_tz = timezone.utc

    today_local = now.astimezone(client_tz).date()
    start_local = datetime.combine(today_local, time.min, tzinfo=client_tz)
    end_local = start_local + timedelta(days=1)
    start_utc = start_local.astimezone(timezone.utc)
    end_utc = end_local.astimezone(timezone.utc)

    active_statuses = ["confirmed", "pending_sales_approval", "planning_approved", "planning", "production", "ready"]
    active_orders = db.query(func.count(SalesOrder.id)).filter(SalesOrder.status.in_(active_statuses)).scalar() or 0
    late_orders = db.query(func.count(SalesOrder.id)).filter(
        SalesOrder.deadline < now,
        SalesOrder.status.notin_(["delivered", "closed", "cancelled"]),
    ).scalar() or 0
    todays_receipts = db.query(func.coalesce(func.sum(Payment.amount), 0)).filter(
        Payment.paid_at >= start_utc,
        Payment.paid_at < end_utc,
    ).scalar() or 0

    first_local = start_local - timedelta(days=13)
    first_utc = first_local.astimezone(timezone.utc)
    buckets: dict = {}
    for i in range(14):
        day = (first_local + timedelta(days=i)).date()
        buckets[day] = 0.0

    def add_rows(model, qty_col) -> None:
        rows = db.query(model.created_at, qty_col).filter(
            model.created_at >= first_utc,
            model.created_at < end_utc,
        ).all()
        for created_at, qty in rows:
            if not created_at:
                continue
            day_local = as_utc(created_at).astimezone(client_tz).date()
            if day_local in buckets:
                buckets[day_local] += float(qty or 0)

    add_rows(CuttingRecord, CuttingRecord.passed_pieces)
    add_rows(PrintingRecord, PrintingRecord.passed_qty)
    add_rows(SewingRecord, SewingRecord.passed_qty)
    add_rows(PackagingRecord, PackagingRecord.packed_qty)

    priority_rank = case(
        (Task.priority == "urgent", 0),
        (Task.priority == "high", 1),
        (Task.priority == "medium", 2),
        else_=3,
    )
    open_tasks = db.query(Task).filter(
        Task.status.in_(["pending", "in_progress"]),
    ).order_by(priority_rank.asc(), Task.created_at.desc()).limit(4).all()

    return {
        "active_orders": int(active_orders),
        "todays_receipts": float(todays_receipts),
        "late_orders": int(late_orders),
        "production_14d": [round(v) for v in buckets.values()],
        "open_tasks": [
            {"title": t.title, "priority": t.priority, "status": t.status}
            for t in open_tasks
        ],
    }
