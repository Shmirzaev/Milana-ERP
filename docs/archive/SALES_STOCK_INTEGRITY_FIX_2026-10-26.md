# Sales stock reservation integrity correction

This is a separate P1 bugfix after the approved boundary extraction and typed
result work (`747caa9` -> `8fe0905` -> `bae6802`). Independent PostgreSQL tests
reproduced both defects on integration base `a3c278d` and extraction `747caa9`:
a preloaded Session could reserve four pieces after another order had reserved
four from six, and simultaneous unkeyed requests could reserve one order's demand
twice. These are preexisting defects; the extraction is not credited with solving
them. The human-approved Sales/Fulfillment responsibilities are unchanged.

## Ownership and transaction sequence

1. Sales keeps authorization, idempotency/replay, order/line writes, audit,
   notifications and its outer commit/rollback. Its piece reservation coordinator
   locks the Sales order identity before reading outstanding reservations.
   Pack-count coordination retains its existing Sales order lock and replay guard.
   The scalar piece lock avoids overwriting unflushed create totals and notes.
2. Fulfillment retains package-before-stock locks and all existing attached-live-
   shipment exclusions, lock modes, deterministic ordering and bounded allocation
   queries. It never imports or locks a Sales mapped row. Direct public callers
   must hold their Sales order lock before invoking reservation.
3. Immediately before the existing locking reads, Fulfillment expires only clean
   columns of matching already-loaded Package/FinishedGoodsStock instances.
   A SQL row lock alone does not refresh SQLAlchemy's identity map. Primary keys
   and changed local columns are preserved; no blanket populate_existing or new
   flush/commit is introduced. Pending price/notes and earlier same-transaction
   reserved quantities therefore survive. Eligibility checks also honor retained
   local status/kind/quantity values rather than admitting rows solely because
   their older stored values matched SQL predicates.
4. Existing schema-owned writes remain the only stock/reservation persistence.
   Pending same-order StockReservation inserts count toward outstanding piece
   demand and the pack replay guard even when autoflush is disabled. Sales line
   IDs need not exist before reservation; request-local line attribution remains.
5. The existing metadata repair still runs in its prior scope and conditionally
   flushes only when it reports repairs. Stock freshness is applied after that
   stage and the existing-reservation join, immediately before locked allocation.
   The bugfix adds no Session-wide early flush or separate transaction.

## Preserved behavior and scope limits

Piece sales still allow standard/first-grade stock under existing rules; pack
sales still require standard intact bags. Whole-bag selection, legacy partial
remainder, mixed six-plus-two allocation, nullable display identity, zero-piece
refusal, strict positive pack counts and source defaults remain covered by the
existing business tests. No table, constraint, enum value, DTO or public signature
changes. No migration, runtime change, production write, push or deployment.

Shipment reopen/update paths can lock package/stock before SalesOrder. Reservation
queries continue excluding packages attached to non-cancelled shipments, which
screens the obvious shared-row cycle. No cross-workflow deadlock has been reproduced;
this review does not claim exhaustive proof for every shipment lifecycle operation.
Arbitrary caller edits to allocation quantities without owning the required locks
are not a supported substitute for these transaction responsibilities.

## Required evidence

The local handoff records immutable source hashes and actual result counts. The
existing Sales behavior, participant rollback/idempotency and query-budget tests
remain required. New real-PostgreSQL cases cover pending same-order piece demand,
pack replay before Sales line flush, and locally ineligible stock/package fields.
Independent acceptance additionally challenges stale Session stock and package
eligibility, real Sales concurrent unkeyed/shared-key/different-key requests,
observed blocking, participant cardinality, dirty metadata/new-row commit/rollback,
successive reservations, legacy metadata repair, read-only no-flush behavior and
actual create entrypoints. Keep red baseline evidence and each frozen fix separate.

Source/test review is not browser verification or human approval. Combined-source
review, actual browser actions/screenshots, persisted readback, bounded operation
stress and human visual acceptance remain open until recorded against the exact
candidate. This operation does not complete all Sales/Fulfillment or the system-wide
modular-monolith/enum/type/schema goal.
