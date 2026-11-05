from datetime import datetime

from pydantic import BaseModel, field_serializer


class CustomerPaymentHistoryOut(BaseModel):
    """The existing customer receipt history wire shape, including advances."""

    id: int
    row_key: str
    amount: float
    payment_method: str | None
    paid_at: datetime | None
    notes: str | None
    order_id: int | None
    order_no: str | None
    invoice_id: int | None
    invoice_no: str | None
    invoice_amount: float | None
    is_advance: bool

    @field_serializer("paid_at", when_used="json")
    def serialize_paid_at(self, value: datetime | None) -> str | None:
        # Match the previous dict/jsonable_encoder ISO spelling, including UTC offsets.
        return value.isoformat() if value is not None else None
