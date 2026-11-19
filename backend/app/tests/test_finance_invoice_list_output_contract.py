import pytest
from pydantic import ValidationError

from app.libs.dto.sales.invoice_list_output import InvoiceListPageOut
from app.libs.enums.finance import InvoiceStatus


def test_invoice_page_preserves_wire_values_and_all_statuses():
    rows = [
        {"id": i, "invoice_no": f"INV-{i}", "sales_order_id": 9,
         "order_no": "SO-9", "customer": None, "amount": 999999999999.99,
         "balance_due": 0.01, "status": status.value,
         "date": "2026-11-04T12:00:00+00:00" if i else None}
        for i, status in enumerate(InvoiceStatus)
    ]
    page = {"items": rows, "total": 12, "limit": 5, "offset": 7}
    model = InvoiceListPageOut.model_validate(page)
    assert [row.status for row in model.items] == list(InvoiceStatus)
    assert model.model_dump(mode="json") == page
    assert InvoiceListPageOut.model_validate({**page, "items": []}).model_dump(mode="json")["items"] == []


def test_invoice_page_rejects_unknown_status_and_documents_extra_filtering():
    row = {"id": 1, "invoice_no": "INV-1", "sales_order_id": 2,
           "order_no": "SO-2", "customer": None, "amount": 1.0,
           "balance_due": 1.0, "status": "unknown", "date": None}
    page = {"items": [row], "total": 1, "limit": 50, "offset": 0}
    with pytest.raises(ValidationError):
        InvoiceListPageOut.model_validate(page)
    row["status"] = "unpaid"
    row["extra"] = "filtered"
    page["extra"] = "filtered"
    result = InvoiceListPageOut.model_validate(page).model_dump(mode="json")
    assert "extra" not in result and "extra" not in result["items"][0]


def test_invoice_get_openapi_exposes_page_and_canonical_status(client):
    schema = client.get("/openapi.json").json()
    response = schema["paths"]["/api/finance/invoices"]["get"]["responses"]["200"]
    assert response["content"]["application/json"]["schema"]["$ref"].endswith("/InvoiceListPageOut")
    status = schema["components"]["schemas"]["InvoiceListRowOut"]["properties"]["status"]
    assert status["$ref"].endswith("/InvoiceStatus")
