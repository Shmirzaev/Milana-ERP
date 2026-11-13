# WF02 — automatic Packaging availability and selected label counts

Date: 2026-11-13. Base: ba2ac53b74d26e4f535b67819cd4d1e3cc444640.
Worker: Codex /root/packaging. Named owner Mirshoir; default reviewer Ismail.
Independent AI reviewer: coordinating Codex agent (pending exact-candidate review).
Human/operator acceptance and deployment approval remain pending.
Worktree C:/ERP/.codex-work/factory-packaging-20261113, branch codex/factory-packaging-20261113.

## Requested behavior and studied seams

The owner requested automatic Sewing-to-Packaging availability, removal of the
manual acceptance UI, and choosing source batch(es) and how many packs to label.
No production data changes, historical cleanup, migration, deployment or permission
grant is included. Live release inherited from coordinator's reconciled evidence:
20261111_115200, manifest db9df64cbcf57e4ab93ac83ef677d7d394b07652a1a4cf3fe1815abc92adac28.

Studied production.py Sewing output/progress, Packaging input/progress/receipt and
queue endpoints; workflow_service advancement; package_sources_service;
packages_service and atomic package_workflows_service; packaging scope, routed
batch ownership and allocations; corrections/deletion and Sewing downstream
history guards; inbox awaiting-Packaging projection; Packaging record/label,
packages list/queue/receive UI and Sidebar consumers.

Defects: received-orders listed only explicit PackagingReceipt rows; the first
historical receipt made every batch receipt-limited, blocking later Nastils.
Single-batch planner appended every remaining partial pack regardless of Copies;
merged planner disabled Copies and always created all selected-source packs.
Zero-output planner could invent a fallback package request.

## Candidate behavior and compatibility

- New read-only sewing_availability_service groups actual passed Sewing records
  by effective batch (record batch, else dedicated WO batch), excluding cancelled
  Sewing WOs. Dedicated Packaging targets override shared ones across departments.
  Queue remains factory scoped and uses this authoritative output. Legacy JSON
  received_quantity/last_received_at names remain for compatibility, now meaning
  passed output/latest Sewing event; UI explicitly labels them accordingly.
- Passed Sewing less recorded Packaging input is the ceiling independently of old
  acceptance receipts. No receipts, PackagingRecords, packages, labels or warehouse
  stock are manufactured by reading the queue. No planned/WO counter fallback is used.
- Packaging progress now enforces backend Packaging department access. Actual
  record submission retains PO -> Sewing WOs -> Packaging WO locks and one outer
  transaction, material/waste usage, workflow/audit and physical output evidence.
  For old receipt-led WOs its input counter reconciles to the record ledger;
  no-receipt historical counters retain their existing increment behavior.
- Manual/scan acceptance endpoints and persisted historical receipt guards remain
  compatible. The removed UI is replaced by a bookmark-safe queue redirect; all
  Sidebar acceptance links and the packages-list acceptance action are removed.
  Existing package deletion history semantics are preserved (legacy receipt-led
  input counters can remain historical intake until the next record reconciles).
- Copies starts at one, remains editable for merged sources, accepts whole values
  1..500 and caps creation for both planners. Unselected batches and unused balances
  stay available; full/partial previews, source allocations and weights correspond
  to the chosen package plans. Existing atomic print-run/idempotent transport and
  backend allocation/quantity locks are unchanged. Physical Packaging output remains
  mandatory before normal label creation and stock remains backed by that output.

New code is a read-only service and typed dataclass projection. PackagingDepartment
and WorkOrderStatus use existing canonical enums. Configurable identifiers remain
numbers/strings. Operation strings and existing DTO/ORM output fields are deliberately
retained as legacy operation/type migration scope; this change does not claim that
Packaging's mixed route writer or schema-owned-write migration is complete.
No table, constraint, public input DTO, permission, stored enum value or migration
was added. Legacy endpoints retain their URLs and payload contracts.

## Evidence

PASS: new automatic-queue regression fails on exact base (no receipt means zero
queue rows); new real page-submit test fails on exact base (one selected pack
creates two). Exact files restored after baseline reproduction.

PASS: 79 focused Windows backend tests; four PostgreSQL-only tests skipped in that
run. Files: packaging_sewing_output, packaging_automatic_queue,
multi_nastil_packaging, packaging_nastil_completion, packaging_stale_counters,
packaging_payroll_routing, packaging_quantity_validation,
packaging_receive_options_query_growth.

PASS: 11 real PostgreSQL 17.10 tests in owned disposable Docker environment:
packaging_automatic_postgres, multi_nastil_packaging_postgres, package_write_postgres.
New competing 60+60 saves against 95 passed output produce one saved record and one
refusal; remaining 35 saves as 34 packed/1 damaged; persisted inputs total exactly95.
No receipt or package is auto-created. Existing multi-source concurrency/rollback,
allocation fallback and write-lock tests pass.

PASS: actual page submit/render regression for one/two packs, partial final pack,
zero available, explicit two-source selection, unselected third source and refresh.
PASS: selected Nastil planner's 2,500 varied allocation conservation scenarios.
PASS: user-access/real AuthGate+Sidebar tests and actual legacy redirect execution
for PKG/BPK/ECP/query-less bookmarks; no acceptance API dependency permitted.
PASS: strict TypeScript, scoped ESLint and Ruff on new backend files.
PASS: queue query-count regression remains constant from 1 to 50 Sewing records.

BLOCKED/PENDING: actual connected-browser visual inspection, saved result readback
through real browser flows and independent exact-candidate AI review are assigned
to root integration. No AI_VERIFIED_AWAITING_HUMAN claim is made here. Root owns
full combined build/regressions and final production-base recheck. No deployment,
push or shared-branch merge occurred.

## Reusable isolated fixture / human local checklist

backend/app/tests/packaging_workflow_fixtures.py::seed_packaging_workflow(db), caller
owns a disposable supplied Session/transaction. Never run on production. Returns:
- automatic: 95 passed, no receipt/PackagingRecord, queue95.
- legacy_later: Sewing80/70/90, Packaging35/40/0, one legacy receipt20 on first
  batch, queue remaining165; normal white/M model, batches named QA Nastil1..3.
  Select batches1+2 for one 60-piece pack: allocations35+25, batch2 retains15,
  batch3 remains untouched. For two packs: 60+15 and no third-batch allocation.

Inspect queue without acceptance; open work order; save a partial Packaging record;
reopen and reconcile input/output and queue. Select one batch and Copies1; ensure
one label only and remaining output persists. Select exactly two batches and Copies1
then inspect each allocation and remaining15. Print final partial separately.
Try the wrong factory and over-remaining input; verify refusals and unchanged rows.
Check EN/RU/UZ, phone/tablet form and the old receive bookmark redirect.

Follow-up exact-candidate evidence (e5a1cbc70, before any further source edit):
- 48 downstream backend tests passed: package_delete_reentry,
  package_evidence_integrity, sewing_later_nastil_workflow,
  packaging_receipt_query_growth. This includes partial/full label deletion,
  re-entry/reprint, damaged evidence and received sibling preservation.
- 30 tests passed in the owned Docker PostgreSQL environment:
  packaging_stale_counters and packaging_receive_options_query_growth. No skips;
  the four PostgreSQL-only checks skipped in the first Windows run are covered.
- Strengthened dedicated-factory regression verifies shared PKG cannot submit the
  exact ECP batch (409), ECP cannot submit the MIL batch (400), and MIL cannot read
  ECP batch progress (403); zero records are created by these crafted requests.
- Actual single-source page submit requested five packs against only75 pieces
  produces exactly60+15, never empty/phantom packs.
