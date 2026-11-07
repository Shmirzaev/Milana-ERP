# Planning cutting-factory reassignment — 4 November 2026

Implementation worker: Codex `/root/planning_factory`. Engineering ownership:
Planning Ismail / reviewer Mirshoir; Production Mirshoir / reviewer Ismail.
Independent AI review and QA master are coordinated by root. No human acceptance
is inferred. Base `61cd16bd9591901e31f91682e26bc65a7cbe5c04`, dedicated worktree
`C:\ERP\.codex-work\planning-cutting-factory-20261104`, branch
`codex/planning-cutting-factory-20261104`. Scope and user approval are preserved
in the coordinator's `docs/PLANNING_FLOORS_BST_20261104.md`.

## Operation studied

Production creation calls `create_work_orders` (production_service.py), which
selects CUT or ECT and automatically starts Cutting when reservations permit.
There is no existing cutting-routing edit operation. The existing
`cutting_sewing_factory_service.change_sewing_factory` edits sewing destination,
bundles and assignments, and must not be reused for this different operation.
The Planning page already loads production orders for material reservations.
The new header action is available on Planning and branded Planning and opens
an order selector with current routing, server-authorized destination choices
and an explicit localized refusal message. It uses the existing loaded order
window (100 newest production orders); older orders are not offered by this UI.

Only cutting WorkOrder.department_id changes, with one append-only audit in the
same outer service transaction. No records, quantities, plans, reservations,
sewing/packaging destinations, assignment history, employees or migrations change.
The GET capability is read-only; PATCH rereads under nowait PO then ordered WO
locks. Repeating the same destination is an authorized no-op without another audit.

Permissions: current-session planning.production plus effective planning.production
in every cutting source and the destination. Factory-scoped grants and denials are
resolved by the existing factory_codes_with_permission operation. This deliberate
cross-factory Planning operation does not require switching the session to both
factories simultaneously. UI choices come from the server and backend rechecks.

Refuse missing/ambiguous/unsupported cutting routes; usluga or closed orders;
recorded cutting/passport/bundle/material consumption or downstream evidence;
downstream execution or cutting output. Automatically started Cutting alone is
allowed because that is the existing creation behavior. Preserve all work-order
and downstream start/deadline/quantity values. Planned Sewing assignments and
unconsumed material reservations are preserved and allowed; actual execution or
consumption refuses. Refuse lock contention with 409.

Table/type ledger: WorkOrder.department_id is a configurable Department FK and
stays integer; the action CUT/ECT discriminator uses canonical CuttingDepartmentCode.
Order/WO statuses and operation strings are read-only legacy fields, intentionally
retained (no whole-domain typing claim). Audit action is an extensible event name;
snapshot IDs remain integers and no new database vocabulary/DDL is introduced.

## Evidence

Implementation frozen for independent review. The exact commit is supplied in
the worker handoff; this packet is committed with that implementation.

| Check | Actual result |
| --- | --- |
| `python -m pytest -q app/tests/test_planning_cutting_factory.py app/tests/test_planning_cutting_factory_postgres.py app/tests/test_quality_check_factory_scope.py app/tests/test_work_order_factory_scope.py app/tests/test_factory_permission_scope.py app/tests/test_production_flow.py app/tests/test_nastil_factory_selection.py` | PASS: 249 cases, zero skips, 54.59s. Includes 40 new HTTP/SQLite cases and 9 real PostgreSQL cases. |
| `node --test scripts/test-planning-cutting-factory.mjs` | PASS: 9 actual component/controller + SSR cases, EN/RU/UZ, permissions, stale-order capability, read/pending/error states, saved routing/reopen, server refusal/retry and failed-refresh handling. Not connected-browser proof. Added to the existing frontend build check chain. |
| `node node_modules/typescript/bin/tsc --noEmit --pretty false` | PASS. Ignored `node_modules` junction reuses existing root frontend dependencies. |
| Targeted Ruff, compileall and `git diff --check` | PASS. |
| `audit_refactor_boundaries.py --root backend/app --path models/planning/cutting_factory_service.py --schema-writes` | PASS: zero errors; commit and rollback remain explicitly reviewed outer service ownership. |
| PostgreSQL persisted readback, bounded stress and failure recovery | PASS on uniquely owned synthetic PostgreSQL 16 container `milana-planning-cutting-qa-20261104`, loopback55441/database `planning_cutting_qa`, unique disposable schema. 10 rounds × two competing requests plus 10 no-op retries produced exactly10 audits; PO/Cutting/Sewing locks refused quickly and recovered; committed Cutting evidence won; stale-source Cutting/Bundle/Quality requests refused; injected audit-queue failure rolled back routing/audit. |
| Actual connected-browser desktop/phone visual QA | BLOCKED: root reported browser tab API timeoutMs bug and Windows fallback policy stop due uncertain browser URL. No bypass, visual pass or human acceptance claimed. |
| Independent AI review / combined revision tests / QA-master acceptance | PENDING coordinator. Not AI_VERIFIED_AWAITING_HUMAN yet. |

### Independent-review corrections and positive handoff

Independent reviewer `/root/floor_pictures` found additional stale-source writers
in the first freeze `99586121a`: material batch replacement authorized before its
locked refresh; passport creation's locked queries retained a cached Cutting
identity; work-order update/start and split/extra Nastil writers lacked a Cutting
routing interlock. The reviewer independently reproduced original frozen update
and passport failures on synthetic PostgreSQL by loading only those frozen
function bodies in memory. Those two witness passes confirm the defects, not the
feature's safety. Results accidentally run while fixes were moving were discarded.

The corrected follow-up reauthorizes material replacement after refresh, uses
`populate_existing` in locked passport order/work queries, and calls the narrow
`factory_scope_service.refresh_cutting_work_order_for_write` PO-then-WO lock/refresh
before authorization in Cutting update/start/split/extra actions. Other stage lock
behavior and all existing writer business rules remain unchanged. These interlocks
only close races created by the new routing action; they do not claim migration of
the legacy writer services to schema-owned persistence.

Final follow-up backend command includes the original seven files plus
`test_material_reservations.py`, `test_passport_nastil_sync.py`,
`test_work_order_command_scope.py` and `test_passport_cutting_submission.py`:
**PASS:326 cases, zero skips,73.75s**, including41 new HTTP/SQLite and15 real
PostgreSQL cases. Six new PostgreSQL cases cover every additional stale-source
writer family, verify403 and fresh-session absence of unauthorized changes.
Targeted Ruff, compileall and diff checks passed after the corrections; frontend
source/tests remain identical to the first freeze and their previous passes stand.

The added positive HTTP handoff uses public production creation twice: bornCUT
then correctedECT versus bornECT. A limited ECT operator sees the order on its
floor, while CUT floor excludes it and formerCUT submission refuses403. ECT saves
12-piece Cutting evidence/bundle. The existing, preserved MIL sewing destination
sees that incoming bundle; an ECT receipt attempt refuses403, a limited MIL receiver
accepts it, and MIL active floor plus fresh database readback prove12 received
pieces and unchanged Sewing/Packaging plans in both cases. This confirms the
existing logical bundle-CUT convention behaves identically for the corrected and
original ECT routes; it does not replace actual connected-browser/physical checks.

### Final association audit

The reviewer found that a valid WasteRecord can reference only a work order, with
null production_order_id. Root extended the table-level audit to sparse payroll,
daily-report and package references. The new waste HTTP test first reproduced
FAIL:200 rather than409 on the previous guard; no original test was relaxed.
The corrected guard follows these explicit relational paths:

| Evidence | Association followed |
| --- | --- |
| Cutting/Printing/Sewing/Packaging records and Quality checks | Required WorkOrder FK belonging to the order |
| Waste, payroll records/labels and daily Sewing reports | ProductionOrder FK or WorkOrder FK, including null-order rows |
| Packages, payroll records/labels and daily reports | ProductionBatch FK belonging to the order, including null-order rows |
| Package allocations | ProductionBatch FK belonging to the order |
| Daily Sewing report linked only to a planned assignment | Assignment FK whose work order or batch belongs to the order |
| Sewing assignments | WorkOrder or ProductionBatch FK, with actual-start/end/completion/finish evidence; untouched planned assignments remain allowed |
| Cutting passports | Direct order FK or reverse batch.cuttting_passport_id; batch.passport_actual_quantity also freezes recorded evidence |
| Finished stock | Direct order FK; package-linked rows are already frozen by the owning Package/BatchAllocation evidence |
| Packaging receipts, replacement requests and manual accessory issues | Required order FK |
| Material reservations | Required order FK and consumed_quantity greater than zero; unconsumed rows remain unchanged and allowed |

No fuzzy matching or rewriting of free-text legacy references is introduced.
The operation follows actual relational links, preserving the linked row even
when an optional parent snapshot is absent. PayrollQrLabel passport linkage is
already frozen by its referenced passport evidence. The guard adds no payroll,
waste or package write behavior.

Final focused exact-source verification: `test_planning_cutting_factory.py` plus
`test_planning_cutting_factory_postgres.py` **PASS:71 cases, zero skips,14.18s**
(52 HTTP/SQLite,19 PostgreSQL), followed by targeted Ruff/compileall/diff PASS.
This supersedes the earlier focused counts. The326-case broader regression run
belongs to24502957e before this last guard-only correction and is not relabeled
as a run on the final source. Ten extra sparse-reference cases assert guard refusal
and complete evidence/work-order conservation. Four additional real PostgreSQL
cases prove work-only waste, batch-only payroll, assignment-only daily report and
legacy-source batch-only package association/constraint handling on actual tables.
Browser verification and final combined-candidate review remain coordinator gates.

### Cutting write query-budget follow-up

Root's later combined full-suite run found six existing query-budget failures:
the unconditional post-refresh factory check added a Department SELECT (bundle
path43 rather than42; material path31 rather than30). Root interrupted that run
to isolate failures; it is not a full-suite pass. No performance assertion or test
budget was changed.

The correction captures the authorized department ID only after the initial scope
check succeeds. Following the existing PO lock and WO locked refresh, it reruns
factory authorization when that identity changed. Unchanged routing retains its
already established grant without another Department lookup. A concurrent CUT→ECT
move changes the identity and still triggers denial of the stale CUT actor before
Cutting evidence writes. The operation keeps the same locks/transaction and does
not cache permission across requests or accept an identity from the client.

Exact follow-up command: `python -m pytest -q
app/tests/test_cutting_packaging_write_query_growth.py
app/tests/test_planning_cutting_factory.py
app/tests/test_planning_cutting_factory_postgres.py` — **PASS:86 cases, zero skips,
17.75s**, including all15 collected existing query-growth cases and the71 Planning
cases with19 actual PostgreSQL cases. This retains the deliberate competing-move
regression and unchanged query-count caps together. Ruff on production.py,
compileall and diff checks also passed. The fresh owned synthetic PostgreSQL16
container was `milana-planning-cutting-query-qa-20261104` on loopback55441; no
migration or production data was used. Independent follow-up review and root's
combined/full-suite continuation remain separate gates.

PostgreSQL used ORM metadata only, no Alembic or production-schema migration.
Earlier test attempts are retained as failures: initial fixture errors used wrong
AuditLog/QualityCheck/SewingAssignment fields and timezone comparison (32 pass/4fail),
then one missing SewingFlow.code fixture (142pass/1fail), corrected without relaxing
business assertions; PG collection initially used the wrong BundleIn import, then
an unavailable psycopg driver. The actual final run used installed psycopg2 and all
249 cases passed. Initial TSC lacked local module resolution; an ignored junction
to already installed dependencies resolved it; no dependency files changed.

Public source map: routes production.py -> Planning cutting_factory_service.py ->
production/cutting_factory_persistence.py, with existing audit_service.py ->
core_persistence.py participating in the same Session. Thin route callers and
schema helper do not commit. Existing production.py Cutting POST rechecks scope
after lock/refresh; Cutting Quality POST locks PO then refreshes WO; bundles.py
create locks PO then loads refreshed Cutting before authorization/batch guard.
No dual write or fallback route exists. Targeted stale-cache/race cases prove
these adjacent guards; broader legacy writer migration remains outside this task.

Human checklist: verify header action on Planning and branded Planning, confirm
current factory/business order number in EN/RU/UZ and phone width, move one isolated
unrecorded CUT/ECT order, reopen/read back, confirm new floor routing and unchanged
Sewing/Packaging plans/reservations, and verify recorded/unauthorized/assigned cases
show refusal without changes. Use synthetic QA data only.

No production state/business data, source merge, push or deployment changed.
No migration files or migration execution were added. Root retains release
20261104_080711 and rollback20261104_093330 as previously verified pointers.
