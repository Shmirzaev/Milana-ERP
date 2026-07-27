import hmac
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends, Header, Query

from app.core.config import settings
from app.core.deps import DbSession, require_permissions
from app.models import Invoice, SalesOrder, User
from app.schemas.integrations import OneCSyncIn
from app.schemas.sales import InvoiceIn, InvoiceOut, PaymentIn, PaymentOut
from app.services.audit import log_action
from app.services.finance_1c import sync_from_1c
from app.services.numbering import next_invoice_no
from app.services.payments import create_invoice_payment
from app.services.idempotency import replay_idempotent_response, store_idempotent_response
from app.services.finance import (
    dashboard_summary, order_profit, branded_stock_value, waste_cost, waste_income,
    list_recent_invoices, revenue_by_period, cost_breakdown,
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
):
    return list_recent_invoices(db, limit=limit)


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
    so = db.get(SalesOrder, payload.sales_order_id)
    if not so:
        raise HTTPException(404, "Sales order not found")
    existing = db.query(Invoice).filter(Invoice.sales_order_id == payload.sales_order_id).order_by(Invoice.id.desc()).first()
    if existing:
        return existing
    inv = Invoice(
        sales_order_id=payload.sales_order_id,
        invoice_no=next_invoice_no(db),
        amount=float(payload.amount if payload.amount is not None else so.total_amount or 0),
        status="unpaid",
        issued_at=datetime.now(timezone.utc),
    )
    db.add(inv); db.flush()
    log_action(db, current, "create", "Invoice", inv.id, new_value={"invoice_no": inv.invoice_no})
    db.commit(); db.refresh(inv)
    return inv


@router.post("/payments", response_model=PaymentOut, status_code=201)
def create_payment(
    payload: PaymentIn,
    db: DbSession,
    current: User = Depends(require_permissions("finance.payment", "*")),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    fingerprint_payload = payload.model_dump(mode="json")
    replay = replay_idempotent_response(db, scope="finance.payments", key=idempotency_key, payload=fingerprint_payload)
    if replay:
        return replay
    inv = db.get(Invoice, payload.invoice_id)
    if not inv: raise HTTPException(404, "Invoice not found")
    p = create_invoice_payment(
        db,
        inv,
        amount=payload.amount,
        payment_method=payload.payment_method,
        paid_at=payload.paid_at,
        notes=payload.notes,
    )
    log_action(db, current, "create", "Payment", p.id, new_value={"amount": float(p.amount)})
    response = PaymentOut.model_validate(p).model_dump(mode="json")
    store_idempotent_response(
        db,
        scope="finance.payments",
        key=idempotency_key,
        payload=fingerprint_payload,
        response=response,
        user=current,
        status_code=201,
    )
    db.commit(); db.refresh(p)
    return response


@router.post("/integrations/1c/sync")
def sync_1c_finance(
    payload: OneCSyncIn,
    db: DbSession,
    x_1c_token: str | None = Header(default=None, alias="X-1C-Token"),
):
    expected = settings.INTEGRATION_1C_TOKEN.strip()
    if not expected:
        raise HTTPException(503, "1C integration token is not configured")
    if not hmac.compare_digest(str(x_1c_token or ""), expected):
        raise HTTPException(401, "Invalid 1C token")
    result = sync_from_1c(db, payload)
    db.commit()
    return result
