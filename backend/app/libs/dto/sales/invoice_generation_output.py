"""The response contract of the sales entry point's invoice generation.

The sales endpoint returns the invoice fields plus `created_existing`, the flag
that says whether the order already had an invoice. The invoice fields are the
canonical `InvoiceOut`, so this contract only adds that flag.
"""

from app.libs.dto.sales.invoice_output import InvoiceOut


class InvoiceGenerationOut(InvoiceOut):
    """One issued invoice and whether it was reused from an earlier issuance."""

    created_existing: bool = False
