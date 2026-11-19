# Finance

## FIN-MANUAL-INVOICE-CREATE — 27 October 2026 candidate

Manual `POST /finance/invoices` now follows route -> `create_order_invoice`
-> `schemas/finance/invoice_persistence.insert_order_invoice`. The supplied
Session and existing flush position are preserved. The service still owns the
parent lock, reuse decision, amount/status calculation, numbering, audit and
single outer commit. The schema operation only constructs, adds and flushes.
Sales generation, receipt auto-issuance and shipment issuance remain separate
pending writers; do not consolidate their differing policies implicitly.
See the [operation packet](../../../../docs/archive/FINANCE_MANUAL_INVOICE_CREATE_2026-10-27.md)
for the type ledger and outstanding independent/visual/human gates.

Candidate customer-order projection: the service helper returns canonical `CustomerOrderPaymentStatus`, the response DTO uses that actual type, and the customer page consumes the corresponding dedicated frontend vocabulary. This read-only summary preserves amount and payment-policy decisions, including partial-payment projection, and remains distinct from invoice status and payment status vocabularies. It introduces no persistence operation or invoice lifecycle policy. Combined frontend/browser and applicable backend checks must be recorded for the candidate before AI verification; human acceptance follows separately.

Business-service group guide, relocated into models/ on 24 October 2026. The
approved extractions now live here as `invoices_service.py`,
`payments_service.py` and `customer_ledger_service.py`. The shared money,
ledger and report calculations stay in
[finance_service.py](../finance_service.py) and
[payments_service.py](../payments_service.py); both are public seams used
outside this folder.

**Purpose:** Own invoice issuance, payment allocation, balances and financial calculations.

**Engineering owner:** Ismail. **Reviewer:** Mirshoir.
**Business acceptance:** Shavkat with operators.
This owner covers the feature's routes, DTOs, enums, database definitions and tests.
See [team ownership](../../../../docs/TEAM_OWNERSHIP.md) for shared-layer coordination.

Two modules share the basename `payments_service.py`: this folder owns the
Finance receipt operation, while `models/payments_service.py` owns shared
low-level writes used by customer receipts and shipments. Follow the full
import path when tracing either one.

Finance and Sales invoice entry points keep their existing different amount,
status and audit rules. The shared parent-order lock does not authorize
unifying those policies; Mirshoir and Shavkat still review that decision.

## Existing code to study first

- Routes: [finance.py](../../api/routes/finance.py), [sales.py](../../api/routes/sales.py), [partners.py](../../api/routes/partners.py), [shipments.py](../../api/routes/shipments.py).
- Services/helpers: [finance_service.py](../finance_service.py) (shared money/report primitives), [payments_service.py](../payments_service.py) (shared low-level payment write), [shipment_invoice_service.py](../shipment_invoice_service.py), [shipment_review_service.py](../shipment_review_service.py).
- Services in this folder: [invoices_service.py](invoices_service.py), [payments_service.py](payments_service.py), [customer_ledger_service.py](customer_ledger_service.py).
- Existing SQLAlchemy schema models: [Invoice](../../schemas/sales/sales.py#L137), [Payment](../../schemas/sales/sales.py#L153).
- Invoice/payment DTOs: [invoice_input.py](../../libs/dto/sales/invoice_input.py),
  [invoice_output.py](../../libs/dto/sales/invoice_output.py),
  [payment_input.py](../../libs/dto/sales/payment_input.py),
  [payment_output.py](../../libs/dto/sales/payment_output.py),
  [customer_payment_input.py](../../libs/dto/sales/customer_payment_input.py).
- Other contract: [price_calculation_request_input.py](../../libs/dto/planning/price_calculation_request_input.py),
  [price_calculation_request_update.py](../../libs/dto/planning/price_calculation_request_update.py),
  [price_calculation_request_output.py](../../libs/dto/planning/price_calculation_request_output.py).

These are source pointers, not permission to move entire mixed files. Trace the
particular operation and every caller/write before choosing what belongs here.

## Service files and their operations

Every operation takes the Session, the validated input and the actor
explicitly. One outer operation owns the transaction; helpers never commit.
`read-only` means the operation writes nothing and the caller keeps the
transaction.

| File | Operation | Input | Output | Refusals | Transaction owner |
| --- | --- | --- | --- | --- | --- |
| [invoices_service.py](invoices_service.py) | `create_order_invoice` | `Session`, `InvoiceIn`, actor | the `Invoice` row | 404 sales order not found; 422 amount not representable in `invoices.amount` | this operation (invoice row, audit row, commit) |
| [invoices_service.py](invoices_service.py) | `generate_order_invoice` | `Session`, sales order id, actor | `InvoiceGenerationOut` envelope | 404 sales order not found; 400 order status not invoiceable; 422 resolved total not finite or representable in nonnegative NUMERIC(14,2) cents | this operation (invoice row, audit row, commit) |
| [invoices_service.py](invoices_service.py) | `void_invoices_for_shipment_reopen` | `Session`, already-locked/preflighted `Sequence[Invoice]` | `None` | none; shipment coordinator owns all eligibility refusals | shipment reopen (same outer transaction; no flush or commit here) |
| [invoices_service.py](invoices_service.py) | `storable_invoice_amount`, `lock_sales_order` | value / session | bounded `Decimal` / locked order row | 422 from the amount guard | none (helpers of the operations above) |
| [payments_service.py](payments_service.py) | `record_invoice_payment` | `Session`, `PaymentIn`, actor, idempotency key | `PaymentOut` snapshot dict | 404 invoice not found; 409 key reused with another payload or owner | this operation (payment row, audit row, idempotency row, commit) |
| [customer_ledger_service.py](customer_ledger_service.py) | `list_customer_orders` | `Session`, customer id | order ledger rows | 404 customer not found | read-only |
| [customer_ledger_service.py](customer_ledger_service.py) | `list_customer_payments` | `Session`, customer id | receipt rows | 404 customer not found | read-only |
| [customer_ledger_service.py](customer_ledger_service.py) | `record_customer_payment` | `Session`, customer id, `CustomerPaymentIn`, actor, idempotency key | receipt dict | 404 customer or sales order not found; 400 amount not greater than zero; 409 idempotency conflict | this operation (invoice row when the order has none, payment and advance rows, audit row, idempotency row, commit) |
| [../finance_service.py](../finance_service.py) | `dashboard_summary`, `order_profit`, `branded_stock_value`, `waste_cost`, `waste_income`, `revenue_total`, `payments_total`, `revenue_by_period`, `cost_breakdown`, `list_recent_invoices`, `count_invoices`, `invoice_list_page` | `Session` plus the report arguments | report values, rows and page envelopes | none; the queries never raise a business error | read-only |
| [../payments_service.py](../payments_service.py) | `money_decimal`, `invoice_payment_status`, `invoice_paid_total`, `refresh_invoice_status`, `create_invoice_payment`, `create_customer_advance_payment` | `Session` where a read is needed | `Decimal`, `InvoiceStatus` member, `Payment` row | 409 payment against a reversed or cancelled invoice | none (the calling operation commits) |

Use snake_case_service.py filenames and operation names such as `create_*`,
`record_*`, `receive_*` or `approve_*`. A typed function is sufficient; a class
is optional when it owns real dependencies. Accept the Session, validated input
and actor explicitly. State the transaction owner, refusal rules and result
contract. Use the existing ORM definitions in schemas/ and DTOs in
libs/dto/<feature>/; keep fixed values in libs/enums/. See
[DTO conventions](../../libs/dto/README.md). Do not import routers, call an
endpoint, or commit inside a helper owned by another transaction. Do not create
an interface/repository or generic CRUD class by default.

**First operation to study:** Trace invoice creation across finance, sales, partners and workflow_service.ensure_invoice_for_delivered_shipment. Preserve legitimate differences before consolidating shared issuance rules.

### RF-008 source trace

| Entry point | Current creation rule and transaction |
| --- | --- |
| `finance.create_invoice` | `finance.invoice` permission; locks the SalesOrder before the existing-invoice check; accepts an optional amount, bounds it to invoice cents/column size and derives payment status; audits and commits. Returns any existing invoice, including a void one. |
| `sales.generate_invoice_for_order` | Accepts `finance.invoice` **or** `sales.orders` (or wildcard); uses the same parent lock but restricts order statuses; uses order total and initial `unpaid`; audits and commits. Returns any existing invoice. |
| `partners.create_customer_payment` | `finance.payment` permission and a payment idempotency key; locks the order with the invoice endpoints' parent lock, creates an `unpaid` invoice only when the customer's order has no invoices, then allocates payment/advance and commits once. |
| `shipments.deliver` via `shipment_review_service` | `storage.shipment` permission and delivery idempotency key; frozen shipments sum validated dispatch totals, reuse an invoice with the same amount, or reconcile one unpaid invoice without receipts. Mismatched paid or ambiguous ledgers are refused. Older shipments use the order total; manual dispatch may first create a SalesOrder. The delivery route owns the commit. |

These are four business contexts, not four interchangeable copies. Preserve their
current HTTP responses, audit records and outer transaction owners while testing
any shared issuance operation. Before extracting, Ismail and Mirshoir must agree
whether draft-order manual invoices, reversed-invoice reuse, zero/small-balance
status are intended policy or separate defects. The confirmed customer-payment
lock gap is addressed by the included FN04 follow-up; it changes no issuance policy.
Shavkat confirms business outcomes. The existing PostgreSQL race regression is
`test_invoice_creation_integrity.py`; money bounds, delivery reconciliation and
payment/idempotency cases need their own baseline comparisons. This trace does
not authorize changing those policies.

The typed Sales generation response deliberately serializes UTC datetimes with
`Z` instead of the previous `+00:00` spelling. Its invalid resolved total guard
deliberately responds 422 for nonfinite, negative, out-of-range or sub-cent
values; no valid stored NUMERIC regression has been demonstrated. The generator
continues to issue UNPAID for zero and subunit totals. Existing invoices are
checked after the order-status guard and reused even when reversed.

### RF-008 slice 1 — finance invoice issuance (extracted)

`POST /finance/invoices` calls `invoices_service.create_order_invoice(db, payload, actor)`.
The endpoint keeps the `finance.invoice` permission, the `InvoiceOut` response model
and the HTTP errors. The service owns the parent `sales_orders` NO KEY UPDATE
lock, the existing-invoice check, the amount bound, the status derivation, the
invoice number, the audit row and the commit.

Preserved unchanged: the missing-order 404, an existing invoice returned as it is
(including a void one), the money bounds and their 422 body, the
`invoice_payment_status(amount, 0)` status, `INV-<year>-<n>` numbering, the
`create` audit action, one write path per request and the same permission.

Historical extraction evidence (not current combined-candidate acceptance):
296 combined finance tests passed, including the PostgreSQL
race regression and the money-bounds storage proof. The source-text lock
assertion was replaced by an executed-statement check and a stale-order refetch
check; the two-connection race stays in `test_invoice_creation_integrity.py`.
The disposable local UI check covered invoice replay, partial and full payment,
and the resulting customer balance. No business rule or database migration changed.

Still undecided, unchanged here: draft-order manual invoices, reversed-invoice
reuse and the zero/small-balance status. The later FN04 follow-up implemented
the customer-payment parent lock separately from the original extraction.

### RF-008 slice 2 — receipt operations (extracted)

`POST /finance/payments` calls `finance/payments_service.record_invoice_payment`,
and the customer receipt endpoints call
`finance/customer_ledger_service.record_customer_payment` with the customer id.
Both replay a stored response for a repeated idempotency key before touching the
ledger, and both own their audit row, their idempotency record and their commit.

`record_customer_payment` creates an `unpaid` invoice only when the sales order
has no invoice at all. It takes the same parent-order `NO KEY UPDATE` lock as
both invoice issuance entrypoints before looking up invoices, then allocates
the amount to the payable invoice under
`FOR UPDATE`, and keeps the remainder as an advance. The paid sums of the
candidate invoices are read in grouped batches
(`_candidate_paid_totals`), not once per invoice.

Preserved unchanged: the 404/400/409 refusals, the `finance.payment` permission,
the USD settlement tolerance, the advance suffix in the receipt notes, the
`create` audit action on `Payment`, the customer-facing `payment_status`
projection (`no_invoice`, `unpaid`, `partial`, `paid`, `cancelled`, `void`) and
the payment ordering. The test patch targets point at the owning modules:
`app.models.payments_service.create_invoice_payment`
in `test_idempotency_identity.py`, and
`app.models.finance.customer_ledger_service._candidate_paid_totals` /
`_find_payable_invoice` in `test_customer_payment_query_growth.py`.

### RF-008 slice 3 — invoice page composition (extracted)

`GET /finance/invoices` calls `finance_service.invoice_list_page(db, limit=limit,
offset=offset, search=search)`. The route keeps the `finance.view` permission,
the `limit`/`offset`/`search` query binding and the `search` length limit; the
service owns the page bound (`INVOICE_LIST_MAX_LIMIT`), the page query, the
filtered count and the envelope.

Preserved unchanged: `limit=0` still falls back to the default page size of 50,
a negative limit is clamped to 1 and a negative offset to 0, `total` stays the
true count for the same filter rather than the page length, `search` still
narrows the page and the count together, and the rows keep their order and
labels. `list_recent_invoices` still returns a plain list for its direct
callers, and `count_invoices` is still importable from `app.models.finance_service`.

The two report envelopes that carry no query of their own stay in the router:
`GET /finance/branded-stock-value` answers `{"value": branded_stock_value(db)}`
and `GET /finance/waste-report` answers `{"cost": waste_cost(db), "income":
waste_income(db)}`. Moving an envelope alone into a service would add a pass-through
layer, not an extraction.

**DTOs and enums:** Invoice/payment status vocabulary; currencies and policy rules require explicit business decisions, not assumptions. Reuse Create/In, Update and Read/Out contracts
where they exist. Add action-specific input only for a real action. Do not generate
three DTOs for every table or expose privileged fields through generic updates.

## UI issue status and outstanding acceptance

These operator-visible issues retain separate source and acceptance status.
The accounting policy is preserved unchanged pending human decision; this guide
does not establish visual verification or human acceptance for a new candidate.

- **FIN-PARTIAL-CONFIRM-20261025** — historical reproduction on `ba70e0cb`:
  confirmation promised "mark as paid". Current source passes the chosen amount,
  and English, Russian and Uzbek messages describe recording that amount.
  Stored settlement policy is unchanged. Candidate visual and human closure
  remain separate required gates.
- **FIN-REVENUE-CHART-STALE-20261025** — the Finance revenue chart stays stale
  immediately after a Finance receipt until the page is reloaded, while the top
  payment totals do update. It is recorded in
  [the bug tracker](../../../../bugs/bugs.md) and stays active for human review.

## Remaining exceptions

### Shipment reopen Finance participant (partial extraction)

`models/shipment_reopen_service.reopen_shipment` owns the full shipment-return
operation and its outer route commits once. It locks and preflights every related
invoice before calling `finance.invoices_service.void_invoices_for_shipment_reopen`
with those same locked rows. Finance stages the existing `VOID` status and zero
amount through `schemas/finance/invoice_reversal_persistence.py`, using the
caller's Session. It does not acquire locks, flush, audit or commit. Payment,
external-posting, status and shared-shipment refusals remain in the shipment
coordinator; the current audit is still one Shipment `reopen_shipment` entry.

This extracts only ownership of the Finance invoice field writes. Shipment,
FinishedGoodsStock, Package, SalesOrder, scan and idempotency mutations in the
same operation remain in the existing coordinator; the shipment-reopen operation
is not thereby complete under the full schema-owned-write target. The Invoice
mapping and DTO were already typed as `InvoiceStatus`; this participant adds no
enum, DDL or API behavior.

- The customer-payment parent lock is implemented: `record_customer_payment`
  calls `lock_sales_order` before invoice lookup. Its automatic invoice,
  invoice-payment and customer-advance writes use Finance schema persistence
  operations. Other invoice writers remain separate work:
  `workflow_service.ensure_invoice_for_delivered_shipment` constructs an
  Invoice directly, and `shipment_review_service.invoice_for_frozen_delivery`
  directly reconciles `Invoice.amount`. Candidate visual and human gates remain
  open.
- The branded-stock-value and waste-report envelopes stay in the router, because
  moving an envelope alone would add a pass-through layer instead of an
  extraction. Their values come from `finance_service`.
- The four policy questions in the RF-008 trace are still open for Ismail,
  Mirshoir and Shavkat. Nothing in this extraction answers them.
- Partial-confirmation wording is corrected in source; revenue-chart refresh
  remains pending. Neither is human-accepted by this guide, and accounting
  policy is unchanged.

## Boundaries and verification

Sales owns commercial orders and Fulfillment owns delivery evidence. Finance consumes that evidence without rewriting quantities. Money-report queries may read across groups but must not hide writes.

Verify Decimal precision, received-payment revenue, advances/reversals, idempotency and authorization. Visually compare invoice, payment, debt and revenue screens for the same fixture transactions.

The concurrency, money-storage and query-growth proofs need real PostgreSQL
(`test_invoice_creation_integrity.py`, `test_finance_money_bounds.py`,
`test_idempotency_identity.py`, `test_customer_payment_query_growth.py`). They
skip on SQLite, so a combined verification run must execute them against
PostgreSQL before the domain is accepted.

## Migration steps

Follow [the shared sequence](../README.md#migration-sequence): study route/DB/rules
and callers -> agree one operation -> capture baseline tests -> extract -> test
old/new separately -> test the real UI on isolated data -> reviewed switch -> human
production verification -> remove old code. Keep one write path per request.
Record the test result, visual evidence, approver and cleanup condition in the task.
Visual success alone does not prove permissions, concurrency or data correctness.
