# Sales: DTO contracts

**Engineer:** Ismail. **Reviewer:** Mirshoir. **Business acceptance:** Shavkat.

Existing Pydantic definitions in this group:

- [sales.py](sales.py) — sales order and shipment contracts
- [common.py](common.py) — validators shared inside this group
- [invoice_input.py](invoice_input.py) — `InvoiceIn`
- [invoice_output.py](invoice_output.py) — `InvoiceOut`
- [payment_input.py](payment_input.py) — `PaymentIn`
- [payment_output.py](payment_output.py) — `PaymentOut`
- [customer_payment_input.py](customer_payment_input.py) — `CustomerPaymentIn`

These describe accepted inputs and returned data. They do not execute database
writes, implement permissions or manage transactions. Class names, fields,
validators and defaults are unchanged; the invoice, payment and customer
payment contracts now live in their own entity-prefixed files.

## Import

Import each contract from the module that owns it:

```python
from app.libs.dto.sales.invoice_input import InvoiceIn
from app.libs.dto.sales.invoice_output import InvoiceOut
from app.libs.dto.sales.payment_input import PaymentIn
from app.libs.dto.sales.payment_output import PaymentOut
from app.libs.dto.sales.customer_payment_input import CustomerPaymentIn
```

`sales.py` still re-exports the four invoice/payment classes, so existing
`from app.libs.dto.sales.sales import InvoiceIn` callers keep working. Those
aliases are the same class objects, not second definitions; remove them when the
last caller imports the explicit module. `CustomerPaymentIn` has no `sales.py`
alias.

There is no `invoice_update.py` or `payment_update.py`: invoices and payments have
no update operation, so no update contract is defined.

Before adding a file, find the existing contract and its router/service callers.
Keep creation fields/defaults, allowed update fields and response filtering distinct.
For updates preserve omitted versus explicit null; do not apply creation defaults.
Add action/query contracts only for actual operations. New <entity>_input.py, <entity>_update.py or
<entity>_output.py files are useful when the feature needs them, not a quota for every table.

Reuse shared bases from ../common.py and existing fixed values. Test validation,
serialization, denied/privileged fields and the consuming workflow; then perform
the required visual and release acceptance checks.

See [DTO rules](../README.md), [business services](../../../models/README.md),
[database definitions](../../../schemas/README.md) and
[ownership](../../../../../docs/TEAM_OWNERSHIP.md).
