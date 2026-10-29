# Finance payment form correction

Scope: independently observed payment-form defects on integration source
`d0920f6367b702f63c88d5940cf1b44155b34aec`. Engineering owner: Ismail;
engineering reviewer: Mirshoir. Codex sales_codex implements this isolated
correction; finance_codex and the coordinating agent independently review it.
No Customer detail page, payment policy, permissions or write ownership change.

## Old behavior and source trace

- `frontend/src/app/(app)/finance/page.tsx` opened the form with the original
  invoice amount even after partial receipts. It asked to mark the invoice paid
  regardless of the entered amount. Previous API errors stayed visible while
  a new confirmation opened and after changing amount/date/method.
- `api/routes/finance.py` binds the existing `finance.view` invoice-list read
  and the separate `finance.payment` receipt operation. Neither route changes.
- `models/finance_service.py:list_recent_invoices` already loads only the
  requested invoice page and groups receipts by those invoice IDs. It used the
  grouped totals for status but omitted a monetary balance from its response.
- `models/finance/customer_ledger_service.py` already projects invoice balance
  as nonnegative invoice amount less paid receipts. Customer advances without
  an invoice do not count as invoice receipts.
- `PaymentIn` validates positive cents and storage bounds; payment method remains
  free-form. The receipt service, shared money/status rules, schema writer,
  audit, idempotency and outer transaction remain unchanged. Overpayment remains
  supported and contributes credit. The existing one-dollar display settlement
  tolerance does not erase an actual monetary balance.
- `InvoiceOut` belongs to the separate invoice creation response and has no
  list-projection responsibility. It is not extended with a fictitious ORM field.

## Deliberate additive response field

The existing invoice-list row now includes numeric `balance_due`, calculated
with Decimal arithmetic as `max(invoice amount - grouped receipt total, 0)`
and serialized in cents. The query shape, grouping, pagination, search, existing
amount/status/date fields and permissions remain unchanged. This is an additive
field on an existing Finance read response, not a new endpoint or service seam.

The actual frontend InvoiceRow declares `balance_due: number`. Opening the form
uses that projection. If an older server omits it, the input stays blank instead
of inventing a remaining amount. No upper limit or overpayment rejection is added.

EN/RU/UZ confirmations state the entered amount and invoice without promising a
paid/partial/advance outcome before the server records the payment. Both generated
runtime base dictionaries and their source dictionary stay aligned. A new attempt
clears the previous error before confirmation; edits to amount/date/method also
clear it. Existing server validation still supplies new refusal messages.

## Evidence and acceptance gates

Run the actual-page component/render interaction test with
`bun test ./scripts/test-finance-payment-form.mjs` from frontend. It exercises
remaining defaults, all three languages, partial/full/overpayment payloads,
failed attempts, edits, retry/cancel, unchanged action visibility and API refusal.
Its deterministic SWR/dialog/hook adapters do not establish a real-browser pass.

Backend regression tests cover partial/full/overpaid and small remaining balances,
multiple invoices/payments, unrelated advances, paging/search, authentication and
absence of writes/flush/commit. Existing Finance contract, runtime enum, receipt,
money-bound and pagination tests remain required. Full TypeScript, canonical
invoice parity and locale consistency are checked against the frozen source.

Keep baseline failures and candidate results with source hashes in the task
handoff. Actual browser rechecks must reopen the 200 invoice after a 25 receipt
and observe a 175 default; confirm partial/full/overpayment wording, validate
error recovery, and inspect saved ledger effects. Independent combined-source
review and separate human visual approval remain open until recorded. No
AI_VERIFIED claim, production write, migration, push or runtime change follows
from component tests alone.
