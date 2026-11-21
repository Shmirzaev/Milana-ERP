# Eco fabric return persistence — 18 November 2026

Engineer owner Ismail; reviewer Mirshoir. Base b0a5473b2f96b60a9b56f34aec92e3023d49605e. Scope is eco_return_fabric, not the send operation or the complete Inventory domain.

A schema-owned operation now applies decided return metadata, restored batch quantity/archive fields and the return movement on the caller's Session. The service retains batch-before-custody lock order, quantity calculations, validation/refusal order, replay/key behavior, audit and its single commit. The immutable dispatch snapshot is preserved. Movement type uses canonical StockMovementType at storage boundary; other unknown/legacy vocabulary is not narrowed. No migration or intentional API behavior change.

Independent source and combined-interaction review found no concrete regression. Runtime results appear in the checkpoint below. Focused tests cover replay, rollback, archived batch restoration, immutable dispatch fields, and two-worker same-key return outcomes on approved disposable PostgreSQL. Concurrent starts check outcomes but do not prove deterministic lock waiting; broader stress and commit-finalization faults remain distinct gates.

Visual QA and persisted browser readback are blocked by unavailable qa_visual tools. Human acceptance is unrecorded. Keep draft; do not claim AI_VERIFIED_AWAITING_HUMAN or whole-domain completion. Prior-batch five HOLD lanes remain untouched. New memory-backed test PostgreSQL retains normal durability, identity and guard budgets.

Human QA: send and return an owned synthetic roll under allowed/denied roles; repeat the same key; reject invalid custody and conflicting returns; reopen/read back stock, archive state, custody metadata, movement and audit; compare dispatch snapshots. Verify surrounding stock availability and downstream selection.

## Verification checkpoint — 18 November 2026

VM107 baseline/candidate SQLite parity: 14 / 14 passed. Migrated identity-pinned PostgreSQL parity: 2 / 2 passed, including audit-finalization failure rollback/retry and bounded same-key return outcomes. Zero failures/errors/skips; normal target finalizers completed. Application hashes matched the reviewed frozen files. Concurrent starts do not establish deterministic lock waiting, and visual/browser, broader stress and human acceptance remain open.
