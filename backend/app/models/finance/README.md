# Finance

Business-service group guide, relocated into models/ on 24 October 2026. The
first approved extraction now lives here as `invoices_service.py`; the other
proposed files below describe later approved operation extractions.

**Purpose:** Own invoice issuance, payment allocation, balances and financial calculations.

**Engineering owner:** Ismail. **Reviewer:** Mirshoir.
**Business acceptance:** Shavkat with operators.
This owner covers the feature's routes, DTOs, enums, database definitions and tests.
See [team ownership](../../../../docs/TEAM_OWNERSHIP.md) for shared-layer coordination.

## Existing code to study first

- Routes: [finance.py](../../api/routes/finance.py), [sales.py](../../api/routes/sales.py), [partners.py](../../api/routes/partners.py), [shipments.py](../../api/routes/shipments.py).
- Services/helpers: [finance_service.py](../finance_service.py), [payments_service.py](../payments_service.py), [shipment_invoice_service.py](../shipment_invoice_service.py), [shipment_review_service.py](../shipment_review_service.py), [invoices_service.py](invoices_service.py).
- Existing SQLAlchemy schema models: [Invoice](../../schemas/sales/sales.py#L132), [Payment](../../schemas/sales/sales.py#L148).
- Existing Pydantic contracts: [sales.py](../../libs/dto/sales/sales.py), [price_calculation.py](../../libs/dto/planning/price_calculation.py).

These are source pointers, not permission to move entire mixed files. Trace the
particular operation and every caller/write before choosing what belongs here.

## When making a service file

| Proposed file | Responsibility |
| --- | --- |
| `invoices_service.py` | Invoice issuance/correction and lifecycle. |
| `payments_service.py` | Receipts, advances and allocation. |
| `reports_service.py` | Financial queries using authoritative facts. |

Use snake_case_service.py filenames and operation names such as `create_*`, `record_*`,
`receive_*` or `approve_*`. A typed function is sufficient; a class is optional
when it owns real dependencies. Accept the Session, validated input and actor
explicitly. State the transaction owner, refusal rules and result contract.
Use the existing ORM definitions in schemas/ and DTOs in libs/dto/<feature>/;
keep fixed values in libs/enums/. See [DTO conventions](../../libs/dto/README.md).
Do not import routers, call an endpoint, or commit inside a helper owned by another
transaction. Do not create an interface/repository or generic CRUD class by default.

**First operation to study:** Trace invoice creation across finance, sales, partners and workflow_service.ensure_invoice_for_delivered_shipment. Preserve legitimate differences before consolidating shared issuance rules.

### RF-008 source trace (candidate `dffde6d`, study only)

| Entry point | Current creation rule and transaction |
| --- | --- |
| `finance.create_invoice` | `finance.invoice` permission; locks the SalesOrder before the existing-invoice check; accepts an optional amount, bounds it to invoice cents/column size and derives payment status; audits and commits. Returns any existing invoice, including a void one. |
| `sales.generate_invoice_for_order` | Accepts `finance.invoice` **or** `sales.orders` (or wildcard); uses the same parent lock but restricts order statuses; uses order total and initial `unpaid`; audits and commits. Returns any existing invoice. |
| `partners.create_customer_payment` | `finance.payment` permission and a payment idempotency key; creates an `unpaid` invoice only when the customer's order has no invoices, then allocates payment/advance and commits once. It reads the order without the invoice endpoints' parent lock. |
| `shipments.deliver` via `shipment_review_service` | `storage.shipment` permission and delivery idempotency key; frozen shipments sum validated dispatch totals, reuse an invoice with the same amount, or reconcile one unpaid invoice without receipts. Mismatched paid or ambiguous ledgers are refused. Older shipments use the order total; manual dispatch may first create a SalesOrder. The delivery route owns the commit. |

These are four business contexts, not four interchangeable copies. Preserve their
current HTTP responses, audit records and outer transaction owners while testing
any shared issuance operation. Before extracting, Ismail and Mirshoir must agree
whether draft-order manual invoices, reversed-invoice reuse, zero/small-balance
status and the customer-payment lock gap are intended policy or separate defects.
Shavkat confirms business outcomes. The existing PostgreSQL race regression is
`test_invoice_creation_integrity.py`; money bounds, delivery reconciliation and
payment/idempotency cases need their own baseline comparisons. No RF-008 source
implementation or policy change is approved by this trace.

### RF-008 slice 1 — finance invoice issuance (extracted)

`POST /finance/invoices` calls `invoices_service.create_order_invoice(db, payload, actor)`.
The router keeps the `finance.invoice` permission, the `InvoiceOut` response model
and the HTTP errors. The service owns the parent `sales_orders` NO KEY UPDATE
lock, the existing-invoice check, the amount bound, the status derivation, the
invoice number, the audit row and the commit.

Preserved unchanged: the missing-order 404, an existing invoice returned as it is
(including a void one), the money bounds and their 422 body, the
`invoice_payment_status(amount, 0)` status, `INV-<year>-<n>` numbering, the
`create` audit action, one write path per request and the same permission.

Checks on this revision: 78 focused tests, no skip, including the PostgreSQL
race regression and the money-bounds storage proof. The source-text lock
assertion was replaced by an executed-statement check and a stale-order refetch
check; the two-connection race stays in `test_invoice_creation_integrity.py`.
No UI check, no business change, no migration.

Still undecided, unchanged here: draft-order manual invoices, reversed-invoice
reuse, the zero/small-balance status and the customer-payment lock gap.

**DTOs and enums:** Invoice/payment status vocabulary; currencies and policy rules require explicit business decisions, not assumptions. Reuse Create/In, Update and Read/Out contracts
where they exist. Add action-specific input only for a real action. Do not generate
three DTOs for every table or expose privileged fields through generic updates.

## Boundaries and verification

Sales owns commercial orders and Fulfillment owns delivery evidence. Finance consumes that evidence without rewriting quantities. Money-report queries may read across groups but must not hide writes.

Verify Decimal precision, received-payment revenue, advances/reversals, idempotency and authorization. Visually compare invoice, payment, debt and revenue screens for the same fixture transactions.

## Migration steps

Follow [the shared sequence](../README.md#migration-sequence): study route/DB/rules
and callers -> agree one operation -> capture baseline tests -> extract -> test
old/new separately -> test the real UI on isolated data -> reviewed switch -> human
production verification -> remove old code. Keep one write path per request.
Record the test result, visual evidence, approver and cleanup condition in the task.
Visual success alone does not prove permissions, concurrency or data correctness.
