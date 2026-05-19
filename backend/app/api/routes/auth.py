from fastapi import APIRouter, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from typing import Annotated
from fastapi import Depends
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import case, func

from app.core.deps import DbSession, CurrentUser, user_permissions
from app.core.dt import as_utc
from app.core.security import verify_password, create_access_token
from app.models import (
    User, SalesOrder, Payment, Task,
    CuttingRecord, PrintingRecord, SewingRecord, PackagingRecord,
)
from app.schemas.auth import LoginIn, TokenOut, UserMe

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenOut)
def login_oauth(form_data: Annotated[OAuth2PasswordRequestForm, Depends()], db: DbSession):
    """OAuth2-compatible login (form: username=email, password)."""
    email = form_data.username.lower()
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(401, "Invalid credentials")
    if not user.is_active:
        raise HTTPException(401, "User inactive")
    token = create_access_token(user.id)
    return TokenOut(access_token=token)


@router.post("/login-json", response_model=TokenOut)
def login_json(payload: LoginIn, db: DbSession):
    user = db.query(User).filter(User.email == payload.email.lower()).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "Invalid credentials")
    if not user.is_active:
        raise HTTPException(401, "User inactive")
    return TokenOut(access_token=create_access_token(user.id))


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
