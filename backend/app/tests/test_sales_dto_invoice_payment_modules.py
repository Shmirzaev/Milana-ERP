"""RF-012 — the invoice/payment contracts moved into entity-prefixed modules.

The money, idempotency and invoice suites already import `InvoiceIn`/`PaymentIn`
through the old `app.libs.dto.sales.sales` path, so they prove that path still
works.  They cannot see the two things this move could break silently:

* the old path returning a *second* class definition instead of the moved one;
* the published OpenAPI contract changing name when the module changed.
"""
from app.libs.dto.sales import invoice_input, invoice_output, payment_input, payment_output
from app.libs.dto.sales import sales as legacy_sales


def test_legacy_import_path_returns_the_same_class_objects():
    assert legacy_sales.InvoiceIn is invoice_input.InvoiceIn
    assert legacy_sales.InvoiceOut is invoice_output.InvoiceOut
    assert legacy_sales.PaymentIn is payment_input.PaymentIn
    assert legacy_sales.PaymentOut is payment_output.PaymentOut


def test_openapi_contract_still_names_and_references_the_invoice_and_payment_schemas():
    from app.main import app

    schema = app.openapi()
    for name in ("InvoiceIn", "InvoiceOut", "PaymentIn", "PaymentOut"):
        assert name in schema["components"]["schemas"], f"the OpenAPI schema lost {name}"

    invoices = schema["paths"]["/api/finance/invoices"]["post"]
    payments = schema["paths"]["/api/finance/payments"]["post"]
    assert invoices["requestBody"]["content"]["application/json"]["schema"]["$ref"] == "#/components/schemas/InvoiceIn"
    assert invoices["responses"]["201"]["content"]["application/json"]["schema"]["$ref"] == "#/components/schemas/InvoiceOut"
    assert payments["requestBody"]["content"]["application/json"]["schema"]["$ref"] == "#/components/schemas/PaymentIn"
    assert payments["responses"]["201"]["content"]["application/json"]["schema"]["$ref"] == "#/components/schemas/PaymentOut"
