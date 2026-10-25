from datetime import datetime
from fastapi import APIRouter, Depends, Header, Query

from app.core.deps import DbSession, require_permissions
from app.schemas import User
from app.libs.dto.sales.invoice_input import InvoiceIn
from app.libs.dto.sales.invoice_output import InvoiceOut
from app.libs.dto.sales.payment_input import PaymentIn
from app.libs.dto.sales.payment_output import PaymentOut
from app.models.finance.invoices_service import create_order_invoice
from app.models.finance.payments_service import record_invoice_payment
from app.models.finance_service import (
    dashboard_summary, order_profit, branded_stock_value, waste_cost, waste_income,
    list_recent_invoices, count_invoices, INVOICE_LIST_MAX_LIMIT, revenue_by_period,
    cost_breakdown,
)

router = APIRouter(prefix="/finance", tags=["finance"])


@router.get("/dashboard")
def dashboard(db: DbSession, _: User = Depends(require_permissions("finance.view", "*"))):
    return dashboard_summary(db)


@router.get("/order-profit/{sales_order_id}")
def get_profit(sales_order_id: int, db: DbSession, _: User = Depends(require_permissions("finance.view", "*"))):
    return order_profit(db, sales_order_id)


@router.get("/branded-stock-value")
def get_branded_value(db: DbSession, _: User = Depends(require_permissions("finance.view", "*"))):
    return {"value": branded_stock_value(db)}


@router.get("/waste-report")
def get_waste(db: DbSession, _: User = Depends(require_permissions("finance.view", "*"))):
    return {"cost": waste_cost(db), "income": waste_income(db)}


@router.get("/invoices")
def list_invoices(
    db: DbSession,
    _: User = Depends(require_permissions("finance.view", "*")),
    limit: int = 50,
    offset: int = 0,
    search: str | None = Query(None, max_length=120),
):
    """One page of invoices plus the exact filtered total.

    `total` is the true count for the same filter, not the page length, so the
    UI can say how many rows exist past the current page instead of silently
    stopping at `limit`.
    """
    safe_limit = max(1, min(int(limit or 50), INVOICE_LIST_MAX_LIMIT))
    safe_offset = max(0, int(offset or 0))
    return {
        "items": list_recent_invoices(db, limit=safe_limit, offset=safe_offset, search=search),
        "total": count_invoices(db, search=search),
        "limit": safe_limit,
        "offset": safe_offset,
    }


@router.get("/revenue-by-period")
def get_revenue_by_period(
    db: DbSession,
    _: User = Depends(require_permissions("finance.view", "*")),
    from_dt: datetime | None = Query(default=None, alias="from"),
    to_dt: datetime | None = Query(default=None, alias="to"),
):
    return revenue_by_period(db, from_dt=from_dt, to_dt=to_dt)


@router.get("/cost-breakdown")
def get_cost_breakdown(db: DbSession, _: User = Depends(require_permissions("finance.view", "*"))):
    return cost_breakdown(db)


@router.post("/invoices", response_model=InvoiceOut, status_code=201)
def create_invoice(payload: InvoiceIn, db: DbSession, current: User = Depends(require_permissions("finance.invoice", "*"))):
    return create_order_invoice(db, payload, current)


@router.post("/payments", response_model=PaymentOut, status_code=201)
def create_payment(
    payload: PaymentIn,
    db: DbSession,
    current: User = Depends(require_permissions("finance.payment", "*")),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    return record_invoice_payment(db, payload, current, idempotency_key)
