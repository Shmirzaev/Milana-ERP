# Stock batch edit refactor — 18 November 2026

Draft candidate based on b0a5473b2f96b60a9b56f34aec92e3023d49605e. Engineer owner: Ismail; reviewer: Mirshoir. Human review is not recorded.

PATCH /api/inventory/batches/{batch_id} previously performed batch assignments, material relinks and movement inserts directly in the service. These mechanics now use schema-owned operations with the existing Session. Catalog owns the ModelBOM relink; Inventory owns batch/movement/reservation and waste writes. The service retains permission and force checks, batch locking, normalization/refusal order, calculations, relink coordination, archive/audit calls, flush, commit and refresh. Query order and synchronize_session=False remain unchanged. No migration or intentional API/value change.

Movement types now use StockMovementType internally and unwrap at the existing storage boundary. Supplied-field update typing preserves omitted versus explicit null. Existing canonical QC handling is unchanged; normalized QC storage text remains a string in the partial write mapping. Free-form values, polymorphic references and whole-table stored-value/consumer review remain unresolved. This slice does not complete Inventory or system-wide enum adoption.

## Verification

On isolated VM107 rootless Docker, focused SQLite-fixture tests passed 199 cases on the baseline and 201 on the candidate, zero failures/skips. Added tests check movement-failure rollback and rollback after flushed batch/movement/reservation/BOM/waste relinks with unrelated controls. Independent source review found no concrete behavior regression. Diff and syntax checks passed.

PostgreSQL tests cover real queued-audit rollback/retry with all relinked rows and deterministic two-worker batch-lock contention with movement totals and audit readback. Access checks are stubbed in these transaction tests and are not certified by them. PostgreSQL execution did not complete: the identity-pinned lifecycle guard entered HOLD during DROP DATABASE teardown. No completed PostgreSQL JUnit exists; passing progress markers are not accepted as passes. Retained resources and diagnostic traceback remain in local task evidence; no uncertain operation was replayed or cleaned up. Combined-candidate acceptance remains unresolved.

Visual QA and persisted browser readback are blocked because qa_visual tools were unavailable. Audit-chain finalization/commit fault injection and complete archive/adjustment/transfer coverage remain open. This candidate is not AI_VERIFIED_AWAITING_HUMAN and must remain draft until required gates pass. No merge or production release is authorized by this evidence.

## Remaining human/QA checklist

Exercise edit/save/reopen under allowed and denied roles; metadata, positive/negative quantity and warehouse changes; reserved-stock limits; explicit nulls and QC normalization; inactive/current versus replacement material; force permissions and linked relinks. Verify movements, reservations, BOM, waste, archive and audit rows plus unaffected controls. Resolve the PostgreSQL HOLD through its established procedure and rerun exact-source lock/integrity cases before acceptance.
