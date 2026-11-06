from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError

from app.api.routes import partners
from app.libs.dto.sales.customer_payment_output import CustomerPaymentHistoryOut
from app.models.finance.customer_ledger_service import _serialize_customer_payment


@pytest.mark.parametrize("advance", [True, False])
@pytest.mark.parametrize("paid_at", [None, datetime(2026, 1, 2, 3, 4),
                                    datetime(2026, 1, 2, 3, 4, tzinfo=timezone.utc),
                                    datetime(2026, 1, 2, 3, 4, tzinfo=timezone(timedelta(hours=5)))])
def test_receipt_history_preserves_existing_json_shape_and_dates(advance, paid_at):
    payment = SimpleNamespace(id=7, amount=Decimal("12.50"), payment_method="legacy custom method",
                              paid_at=paid_at, notes=None)
    invoice = None if advance else SimpleNamespace(id=9, invoice_no="I-9", amount=Decimal("19.25"))
    order = None if advance else SimpleNamespace(id=11, order_no="S-11")
    original = _serialize_customer_payment(payment, invoice, order)
    typed = CustomerPaymentHistoryOut.model_validate(original)
    assert typed.model_dump(mode="json") == jsonable_encoder(original)
    assert list(typed.model_dump(mode="json")) == list(original)
    assert typed.invoice_amount == (None if advance else 19.25)
    assert typed.payment_method == "legacy custom method"


def test_missing_history_field_fails_response_contract():
    with pytest.raises(ValidationError):
        CustomerPaymentHistoryOut.model_validate({"id": 1})


def test_customer_payment_get_openapi_and_json(client, auth_headers, monkeypatch):
    row = _serialize_customer_payment(
        SimpleNamespace(id=7, amount=Decimal("12.50"), payment_method=None,
                        paid_at=datetime(2026, 1, 2, tzinfo=timezone.utc), notes=None),
        None, None,
    )
    monkeypatch.setattr(partners, "list_customer_payments", lambda db, cid: [row])
    response = client.get("/api/customers/123/payments", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == [jsonable_encoder(row)]
    schema = client.get("/openapi.json").json()["paths"]["/api/customers/{cid}/payments"]["get"]
    assert schema["responses"]["200"]["content"]["application/json"]["schema"]["items"]["$ref"].endswith("/CustomerPaymentHistoryOut")
