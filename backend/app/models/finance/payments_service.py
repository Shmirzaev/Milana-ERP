"""Payment recording for the finance payment endpoint.

Contract for `record_invoice_payment`:
* input: a validated `PaymentIn`, the acting user and the optional idempotency key
* output: the stored `PaymentOut` snapshot as a dict
* refusals: 404 when the invoice does not exist, 409 when the same key is reused
  with a different payload or with an inconsistent owner
* records: one `payments` row, one `Payment` audit row and one idempotency row
* lock order: the invoice row, taken by the low-level payment write
* transaction owner: this operation
"""
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.libs.dto.sales.payment_input import PaymentIn
from app.libs.dto.sales.payment_output import PaymentOut
from app.models import payments_service as low_level_payments
from app.models.audit_service import log_action
from app.models.idempotency_service import replay_idempotent_response, store_idempotent_response
from app.schemas import Invoice, User


def record_invoice_payment(db: Session, payload: PaymentIn, actor: User, idempotency_key: str | None) -> dict:
    """Record one payment against an invoice, or replay the stored response.

    A replayed request returns the stored response as it is, without writing a
    second payment.
    """
    fingerprint_payload = payload.model_dump(mode="json")
    replay = replay_idempotent_response(db, scope="finance.payments", key=idempotency_key, payload=fingerprint_payload)
    if replay:
        return replay
    inv = db.get(Invoice, payload.invoice_id)
    if not inv:
        raise HTTPException(404, "Invoice not found")
    p = low_level_payments.create_invoice_payment(
        db,
        inv,
        amount=payload.amount,
        payment_method=payload.payment_method,
        paid_at=payload.paid_at,
        notes=payload.notes,
    )
    log_action(db, actor, "create", "Payment", p.id, new_value={"amount": float(p.amount)})
    response = PaymentOut.model_validate(p).model_dump(mode="json")
    store_idempotent_response(
        db,
        scope="finance.payments",
        key=idempotency_key,
        payload=fingerprint_payload,
        response=response,
        user=actor,
        status_code=201,
    )
    db.commit()
    db.refresh(p)
    return response
