# Shipment invoice persistence participant — 18 November 2026

Engineer owner Ismail; reviewer Mirshoir. Base b0a5473b2f96b60a9b56f34aec92e3023d49605e. This is a Finance participant extraction, not completion of the shipment coordinator.

The delivered-shipment invoice helper stages its Invoice through Finance schema persistence without adding a flush. Frozen-delivery reconciliation delegates its already-decided amount assignment, retaining its existing flush. Both use the caller's Session. Number allocation, locks, Decimal quantization, validation and conflict order, initial legacy float, InvoiceStatus member, audit, external notifications and outer commit remain in their existing callers. Manual posting, delivery, amount review and reopening callers were traced; Sales/order/package/stock/snapshot writes outside this participant remain separate work. No migration or deliberate API/value change.

Canonical InvoiceStatus is retained. Cross-domain shipment/posting statuses, free text, actual stored values and broader DTO/internal/frontend consumers remain outside this bounded slice. No system-wide enum completion is claimed.

Diff/syntax and independent source/combined-interaction review found no concrete regression. Detailed runtime results are recorded in the verification checkpoint below. Real PostgreSQL tests characterize staging visibility, flush, rollback/commit, reconciliation and queued-audit rollback/readback. They do not establish audit-finalization failure handling, manual-posting end to end or lock contention.

Required visual QA and persisted browser readback remain blocked by missing qa_visual tools. Human acceptance is unrecorded. Keep draft until all exact-source operation gates pass; no AI_VERIFIED_AWAITING_HUMAN, merge or production release is claimed. The five prior-batch PostgreSQL lifecycle HOLD lanes remain preserved; a separate new tmpfs lane uses unchanged identity/durability/guard budgets and does not resolve old unknown operations.

Human QA: manually post a priced shipment; deliver an order shipment with frozen amount; verify linked customer/order/invoice, cents/due date, audit and notification. Exercise pending-price and paid-invoice refusal, allowed/denied roles, reopen reversal, and persisted readback. Broader stress and recovery remain required where not explicitly evidenced.

## Verification checkpoint — 18 November 2026

Isolated VM107 checks passed: adjacent SQLite fixtures 55 baseline / 60 candidate; migrated identity-pinned PostgreSQL participant cases 4 baseline / 4 candidate. Zero failures/errors/skips. Normal PostgreSQL lifecycle finalizers completed. Application source hashes matched the reviewed frozen files. These counts describe separate suites and are not additive combined coverage. Visual/browser, broader contention/stress and human acceptance remain open.
