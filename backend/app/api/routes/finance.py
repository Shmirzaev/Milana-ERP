from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends

from app.core.deps import DbSession, CurrentUser, require_permissions
from app.models import Invoice, Payment, SalesOrder, User
from app.schemas.sales import InvoiceIn, InvoiceOut, PaymentIn, PaymentOut
from app.services.audit import log_action
from app.services.numbering import next_invoice_no
from app.services.finance import (
    dashboard_summary, order_profit, branded_stock_value, waste_cost, waste_income,
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


@router.post("/invoices", response_model=InvoiceOut, status_code=201)
def create_invoice(payload: InvoiceIn, db: DbSession, current: User = Depends(require_permissions("finance.invoice", "*"))):
    if not db.get(SalesOrder, payload.sales_order_id):
        raise HTTPException(404, "Sales order not found")
    inv = Invoice(
        sales_order_id=payload.sales_order_id,
        invoice_no=next_invoice_no(db),
        amount=payload.amount,
        status="unpaid",
        issued_at=datetime.now(timezone.utc),
    )
    db.add(inv); db.flush()
    log_action(db, current, "create", "Invoice", inv.id, new_value={"invoice_no": inv.invoice_no})
    db.commit(); db.refresh(inv)
    return inv


@router.post("/payments", response_model=PaymentOut, status_code=201)
def create_payment(payload: PaymentIn, db: DbSession, current: User = Depends(require_permissions("finance.payment", "*"))):
    inv = db.get(Invoice, payload.invoice_id)
    if not inv: raise HTTPException(404, "Invoice not found")
    p = Payment(
        invoice_id=inv.id, amount=payload.amount, payment_method=payload.payment_method,
        paid_at=datetime.now(timezone.utc), notes=payload.notes,
    )
    db.add(p); db.flush()
    # update invoice status
    total_paid = sum(float(x.amount) for x in db.query(Payment).filter(Payment.invoice_id == inv.id).all())
    if total_paid >= float(inv.amount): inv.status = "paid"
    elif total_paid > 0: inv.status = "partially_paid"
    log_action(db, current, "create", "Payment", p.id, new_value={"amount": float(p.amount)})
    db.commit(); db.refresh(p)
    return p
