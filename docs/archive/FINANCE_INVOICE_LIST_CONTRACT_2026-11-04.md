# Finance invoice list contract candidate

Base: `3ab946e31f9c73896ad834f7747cb589046a359c`. Engineer: Ismail;
reviewer: Mirshoir. Scope: GET `/api/finance/invoices` response only.

The route keeps `finance.view` / `*` authorization, search length and existing
pagination. `invoice_list_page` clamps limit and offset, applies the same search
to the page and exact count, and does not write or commit. It joins sales orders
and optional customers, computes payment-derived status and nonnegative balance,
and returns float money and an already formatted nullable ISO date string. The
finance page consumes these fields and canonical invoice status labels. The ORM
status column uses `InvoiceStatusType`, `ck_invoices_status` and `InvoiceStatus`;
the projected status uses the same enum. Customer and date are nullable; invoice
number and order number are non-null mapped fields. No payment-method vocabulary,
money precision, query, or transaction behavior is changed.

The new response DTO types that projected status as `InvoiceStatus`. OpenAPI now
describes the page and row, including the enum. Response validation now rejects
unknown statuses, missing required fields, and incompatible values; Pydantic
filters unexpected keys at both levels. Those are intentional contract changes;
the current producer constructs exactly the declared keys. Date remains a string
to preserve its existing spelling, including timezone offsets. Empty pages and
the existing float JSON representation are retained.

Open drafts #436 and #441 affect customer payment history and receipt HTTP tests,
respectively, with no overlapping files in this slice. Their eventual combined
candidate still requires reconciliation and checks. Converted: invoice list
projected status. Retained: float amounts and nullable formatted date for wire
compatibility; free-form customer/order labels. Unresolved: actual stored-value
audit and all system-wide fields beyond this read operation.

Candidate gates: automated tests, PostgreSQL, independent review, actual browser
and persisted-data checks, bounded integrity/stress and human pre-deployment QA
are PENDING. No tests or runtime were executed in this preparation lane. Existing
invoice paging and remaining-due tests cover search, pagination, status and
authorization; the new contract tests cover serialization, enum validation, extra
filtering and OpenAPI. The laptop integrator must verify the exact combined revision.
