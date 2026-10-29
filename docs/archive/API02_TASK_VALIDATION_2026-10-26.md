# API02 task validation candidate — 26 October 2026

Owner: Dilmurod. Reviewer: Mirshoir. Source: `codex/api02-task-validation` from
`origin/clone_main` `b92ee8ff`. This is a candidate, not a deployed change.

## Scope and contract

`POST /api/tasks`, `PATCH /api/tasks/{id}`, and the list status filter previously
accepted unknown states; create/patch also accepted invalid dates and dangling,
partial or unsupported target references. Task references are polymorphic
`entity_type`/`entity_id` pairs. Supported targets are SalesOrder,
ProductionOrder, WorkOrder, Bundle, Package, Shipment and Invoice. They have no
task-side FK. A missing target makes the notification link unusable; a target in
another factory can reveal or assign work the recipient cannot open.

The candidate validates input in `libs/dto/work_management`, resolves and locks
targets in `models/work_management/tasks_service.py`, and checks the actor and
recipient using existing target read permissions and factory helpers. New/changed
references must resolve; unrelated edits of legacy broken references remain
possible. The route still owns its transaction, audit and notifications. There
is no schema or production data migration. Historical invalid output values
remain readable while their cleanup is separately decided.

The donor commits `22593e7`, `31350dc` and `73d7ca4` predate the namespace move
`1dfd1c5d`: their `app.schemas.tasks` DTO and `app.services` imports no longer
fit. Their target access model was checked against current read routes, rather
than cherry-picked.

## Evidence and decisions

- Baseline existing task tests: 36 passed, 4 skipped without PostgreSQL.
- New API regressions on baseline: 18 failed, 1 passed on real task behavior.
- PostgreSQL deletion race on baseline: failed because target deletion committed
  before task creation. With the candidate: passed; the delete waited for the
  task transaction.
- Focused API tests after repair: 64 passed on disposable local PostgreSQL.
- Ruff and frontend lint passed; frontend lint emitted 10 pre-existing warnings.
- Full backend suite: 3,887 passed, 313 skipped, 13 warnings (exit 0). The
  separate PostgreSQL target test ran and passed with `STABILIZATION_POSTGRES_URL`
  against a disposable local server. Gates 3 (visual E2E) and 4 (bounded live
  stress/readback) are BLOCKED until the required environment and human workflow
  are available.

Business decision pending: approved state transitions, including whether a
completed task may be reopened. The candidate validates the allowed state set
and preserves existing reopening behavior; it does not invent transition rules.
Factory ownership for standard SalesOrder, Shipment and Invoice references is
not stored as a direct target field. Their current read endpoints do not apply a
target factory check; a broader policy needs a business/access design decision.

The key-share lock prevents deletion or key change before task commit. It does
not stop a later deletion; without an FK, that deletion can orphan a reference.
Active/rollback production releases and slots were not reverified for this
non-release candidate; no business data or deployment was touched.

## Re-aim after integration refactor — 29 October 2026

Engineer Dilmurod; reviewer Mirshoir. Codex implemented under the owner's explicit
exception to the local MiniMax setup. Base `425ec9fe`; existing PR #314 branch.
The reference validation and key-share locking remain in the work-management task
service alongside upstream's unchanged `create_stock_shortage_task` participant.
Removed duplicate `libs/enums/task.py`; DTOs/routes use the identical canonical
values in `libs/enums/work_management.py`. No transition, permission, reference,
lock ordering, or transaction behavior was changed by this re-aim.

The unchanged defect regressions on clean `425ec9fe` produced **21 failed / 3
passed / 0 skipped**. Invalid creates returned 201 rather than 422, invalid updates
returned 200, and the PostgreSQL race failed with `Reference row was deleted before
the task committed`. The final candidate's four task files produced **65 passed /
0 failed / 0 skipped**, including the real PostgreSQL deletion race. A new parity
check for upstream stock-shortage creation passes both sides: pending/high fields
are staged with no commit and caller rollback removes the row. Ruff and diff
whitespace checks pass. Tests used PostgreSQL 18 in a fresh local cluster through
`scripts/run_manual_packaging_pg.py --pg-bin /opt/homebrew/opt/postgresql@18/bin`;
no existing database or production service was used.

Commands: pytest `app/tests/test_task_input_validation.py`,
`app/tests/test_task_reference_lock_postgres.py`,
`app/tests/test_task_assignment_authorization.py`, and
`app/tests/test_task_broadcast_batching.py`. Baseline/fixed logs are retained at
`/private/tmp/api02-reaim-baseline.log` and `/private/tmp/api02-reaim-final.log`.
Earlier full-suite results above are historical, not re-aimed-candidate results.
Visual E2E and separate live stress remain BLOCKED; the PostgreSQL concurrency
check passed. Human review and production acceptance remain pending.
