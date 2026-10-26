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
