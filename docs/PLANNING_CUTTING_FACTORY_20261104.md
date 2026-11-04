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
