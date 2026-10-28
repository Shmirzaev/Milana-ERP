# FIN-MANUAL-INVOICE-CREATE

Base: `8a270cb9798b84b2f7f41012e227663dfb54d9ee`. Engineer: Ismail;
technical reviewer: Mirshoir; business acceptance: Shavkat/operators.
Codex implements this bounded operation under Ismail's renewed execution scope.
Independent AI review is assigned separately. This is not production acceptance.

## Complete operation

`POST /api/finance/invoices` binds InvoiceIn, checks `finance.invoice` or wildcard,
and returns the existing InvoiceOut/201 contract. Its sole first-party writer is
Sales order detail's Generate invoice action. The real API call now consumes
InvoiceIssueResponse, including canonical frontend InvoiceStatus; this changes
no JSON field or UI behavior. The route and service return the existing mapped
Invoice, whose status has the already-reviewed canonical enum adapter.

`create_order_invoice` still locks and refreshes SalesOrder under NO KEY UPDATE,
checks the newest invoice before resolving amount, calculates amount/status,
obtains the number, queues audit and commits once. Its new schema operation
`insert_order_invoice` constructs/adds/flushes using that same Session, at the
same point in the operation. The schema helper has no transaction, numbering,
permission, time or settlement-policy decisions and imports no service/router.
Audit enqueue/finalization still uses the existing schema-owned audit operations
in the service's transaction. There is no payment, notification or idempotency
participant in this manual issuance path. Reuse is not an Idempotency-Key API.

Preserved policies: missing order 404; latest invoice reused unchanged even if
void/cancelled, without an insert/audit/commit; draft orders accepted by this
endpoint; omitted/null amount falls back to the refreshed total; finite cents
from zero through 999999999999.99 only; amounts <= 1.00 initially PAID under the
existing USD tolerance. Other amounts start UNPAID. No new policy approval is
inferred from preserving these behaviors. Numbering precedes audit locking.

## Field and writer ledger

| Item | State |
| --- | --- |
| invoices.status | Existing five-member canonical InvoiceStatus in mapping, helper, calculation, output DTO and actual frontend result; unchanged stored strings/CHECK. |
| amount | InvoiceIn and schema helper use Decimal; existing output JSON is number. Shared Numeric mappings still annotate Mapped[float]; deliberately deferred across all consumers, not silently changed here. |
| IDs, invoice_no, issued_at/due_date | Integer IDs, free-form business number, datetime / nullable serialized datetime; no invented enum. Existing defaults/external fields unchanged. |
| manual Invoice insert | Converted to the Finance schema operation. |
| audit | Existing schema-owned row/hash operations retained in the same outer transaction. |
| Sales generate_order_invoice | Separate pending direct insert; its permitted order statuses, initial UNPAID, permissions and audit action differ. |
| customer receipt auto-invoice/advance | Separate pending direct writers. Existing parent-lock and converted invoice-payment helper are preserved. |
| shipment invoice fallback/reconciliation | Separate Fulfillment-owned transaction and due-date/reversal policies; pending, untouched. |
| startup schema_hotfix | Separately gated maintenance writer, not executed or changed. |

No table, column, mapping, metadata registration or migration changes. No broad
conversion of money mappings, currency vocabulary or payment-method strings.
No changes to the fixed payment form, status adapter or audit/receipt race fixes.

## Verification and acceptance

The unchanged base passed 86 characterization/regression cases, including real
PostgreSQL money bounds, invoice/receipt races in both winner directions,
rollback at invoice flush/audit enqueue/audit finalization, and observed advisory
numbering-lock contention between different orders. Source identity was checked
before/after. These baseline results do not certify the candidate.

The candidate passed 92 cases with no skips, including the schema helper's same-Session ownership,
flushed identity, lack of commit/visibility to another connection, rollback,
actual enum/Decimal values and exactly one outer service commit. Full frontend
TypeScript and 22 existing invoice enum/parity fault checks also passed. Worker results,
source hashes and frozen revision are in the coordinator's operation manifest;
missing checks must not be inferred from this packet.

Pending before AI verification: independent review of the frozen candidate,
combined-source verification, actual website exercise and inspected screenshots,
persisted readback and bounded retry/concurrency checks. Human approval remains
separate, as do push/merge/deployment. No shared QA/runtime or production write
was authorized for this implementation slice.

Visual checklist: use an allowed invoice role on a synthetic confirmed Sales
order, generate/repeat/reopen and inspect invoice number, amount and status in
Finance/customer views; use a denied role and verify refusal/no invoice; make
an adjacent payment and inspect balance/status/audit. The Sales action currently
uses its order-status subset without an explicit finance permission visibility
check, while the backend enforces finance.invoice. Preserve and report this
existing asymmetry; do not silently widen permission or claim it is fixed.
