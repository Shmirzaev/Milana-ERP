# Sales participant in shipment reopening — 18 November 2026

Engineer owner Ismail; reviewer Mirshoir. Base b0a5473b2f96b60a9b56f34aec92e3023d49605e. This slice covers SalesOrder fields only; it does not complete shipment reopening or migrate its remaining Fulfillment/Packaging writes.

The existing coordinator now calls existing Sales schema persistence for the decided status and total. A manual order becomes CANCELLED with total zero before detachment; an order-linked shipment restores READY_TO_SHIP. Canonical enum values serialize through existing helpers to the same stored strings. Same Session, lock/query/write order, lack of helper flush/commit, invoice reversal, stock/package/idempotency/audit coordination and outer transaction remain unchanged. No migration, API change or new business policy.

Independent source/combined-interaction review found no concrete regression. Checkpoint below records runtime results. Baseline-compatible tests exercise the actual manual and standard coordinator paths, explicit rollback and committed Sales/shipment/audit readback. They do not prove HTTP authorization, invoice/payment variants, audit-finalization faults or lock contention.

Visual/browser readback, broader integrity/stress and human acceptance remain open. Keep draft until required gates pass; no AI_VERIFIED_AWAITING_HUMAN or whole-coordinator completion claim. Prior-batch PostgreSQL HOLD lanes remain preserved; new test lane is independent and retains normal guard budgets.

Human QA: reopen eligible manual and order-linked shipments with physical-return confirmation. Check Sales status/total/linkage, unchanged finance refusal behavior, package/stock restoration, old retry invalidation, audit and refreshed UI. Exercise stale/invalid confirmations and denied roles, verifying refused requests leave persisted state unchanged.

## Verification checkpoint — 18 November 2026

VM107 SQLite baseline/candidate parity: 18 / 18 passed. Migrated identity-pinned PostgreSQL manual and standard participant cases: 2 / 2 passed. Zero failures/errors/skips; normal target finalizers completed. Application hashes matched the reviewed frozen files. The tests exercise actual coordinator rollback/commit and Sales/shipment/audit readback; HTTP authorization, invoice variants, lock contention, full coordinator migration and visual/human acceptance remain open.
