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

## Local UI/readback and bounded stress — 30 October 2026

Verification-only follow-up requested by the user; owner Dilmurod, reviewer
Mirshoir. Runtime candidate: `d415114e49594e997c56b1a3d8ce8e6946a2835c`,
worktree `.codex-work/api02-task-validation`, branch
`codex/api02-task-validation`. Only this evidence document changes in the
follow-up commit. No application/test source change, merge, deployment or
production/shared-environment access. Earlier evidence above is retained.
**No verified or accepted status is assigned.**

### Environment and coverage limits

Reused #319's `scripts/sec04_local_stack.py` and `sec04_local.compose.yml`
from `.codex-work/rf004-sec04-verification`, with a separate temporary state
directory and fresh project `milana-sec04-local-c9357893`. PostgreSQL 16 and
storage were disposable volumes; API bound only to `127.0.0.1:18080`; one backend
worker. Five runtime task files' SHA-256 hashes matched the candidate checkout
(route, DTO, task service, task persistence and enum).

Frontend ran from a `git archive` copy of the exact candidate on
`127.0.0.1:3000`, with the local API configured explicitly and external browser
requests blocked. Webpack dev was used because Turbopack rejected the temporary
copy's external node_modules symlink. No API/auth/permission/UI response mocks or
application monkeypatches were used. Fixtures followed the existing task tests:
synthetic manager, non-manager and recipient users, a model and target orders;
no production dump or real factory records. Setup-only fixture/locator retries
are excluded from the result counts below.

**Gate 3 remains BLOCKED as a complete required gate.** The connected Browser /
Computer Use execution tool was unavailable after tool discovery and reading
both skills. Standalone Chromium exercised the real running website instead;
this is useful actual-UI evidence, not a claim of connected-device verification.
Phone coverage is viewport emulation (390 x 900), not a physical phone. Desktop
was 1280 x 900. Mirshoir must decide whether this fallback is sufficient or require
another connected-browser run.

### UI and direct PostgreSQL readback

- **PASS: 12 UI cases**, manager/non-manager x EN/RU/UZ x desktop/phone. Created
  tasks with a valid date, completed and reopened each, then reloaded the page.
  Every saved task remained pending with the original date and null completed_at.
  A whitespace title received HTTP 422 and a visible inline refusal in all three
  languages. Manager-only All/assignee controls were absent for the non-manager.
  Non-managers can still create self-tasks; their lack of management permission
  is not a blanket denial of Tasks access. No uncaught page errors in this matrix.
- **PASS: six actual UI 403 cases**, EN/RU/UZ x desktop/phone. A manager created
  a fixture task assigned to the non-manager, then reassigned it to the authorized
  recipient while the old drawer remained open. Clicking Done on the stale row
  produced a visible localized 403 notice; refresh removed the inaccessible row.
  Direct database readback confirmed pending status, null completed_at and the
  new recipient, with only create/reassign audit rows (no refused-update audit).
- **PASS: direct readback of all 18 UI case records.** The 12 self-task cases
  each had exactly three audits (create, complete, reopen); each denied case had
  exactly two. No whitespace-title task persisted. Screenshots were visually
  inspected across both sizes and all three languages: forms, actions and notices
  were readable; phone actions wrapped without obscuring the refusal or submit.
- **PASS: 32 live HTTP checks** for valid states/dates/references, refresh reads,
  invalid states/priorities/numeric or impossible dates, unsupported/missing or
  partial create references, denied reference access/assignment/update/listing,
  and an invalid status filter. Refusals preserved the complete task snapshot and
  task/audit/notification counts. Updating one component of an already complete,
  unchanged reference remained accepted. No skipped scripted cases.
- **PASS: system-shortage path.** The helper preserved pending/high defaults and
  caller rollback. An actual `POST /api/sales-orders/{id}/reserve-stock` on a
  one-piece synthetic order without stock returned 200 with one shortage and
  committed exactly one planning task, pending/high, expected actor/recipient,
  description and 7 November due date. Its actual Tasks UI completed, reopened and
  refreshed successfully on desktop and phone; direct readback retained those
  values with null completed_at. Final audit-chain verification passed 156 rows.
- **BLOCKED for literal UI coverage:** the drawer has no entity-reference inputs,
  no arbitrary status text input and no edit-date form. Those valid/invalid input
  paths were tested through live HTTP plus direct DB readback, not falsely counted
  as UI actions. See `frontend/src/components/TasksDrawer.tsx:69`, `:74`, `:398`,
  `:484`, `:620`. Mirshoir must agree this UI/API coverage boundary.

### Stress plan recorded before execution

`STRESS_PLAN.md` in the local evidence directory preceded load. Four workers,
maximum six workflows each (24 tasks / 144 HTTP requests), workflow ceiling
30 seconds, request timeout/max latency 5 seconds, p95 limit 1500 ms. Each workflow
created a referenced task for an authorized recipient, changed state/date, read it
back, then attempted invalid create/update and an unauthorized update. Stop on
unexpected status/exception, timeout or integrity mismatch. Expected 403/422s
were refusals, not unexpected errors. No other test/browser load ran concurrently.

Separately bounded to five target-delete/create pairs and five task-delete/update
pairs, two operation workers; target races additionally used an observer and an
external holder of the existing audit advisory mutex. Maximum 20 seconds per pair,
120 seconds overall. No app patch: observed real PostgreSQL blocking before
releasing the mutex. Stop the phase on the first unexpected result.

### Stress outcomes: gate 4 FAIL

- **PASS: workflow burst**, 144 requests in 0.394 seconds: 24 x 201, 48 x 200,
  24 x expected 403, 48 x expected 422; zero unexpected errors. p50 8.63 ms,
  p95 19.24 ms, max 28.44 ms. Readback: exactly 24 unique correctly assigned tasks,
  48 audits and 24 assignment notifications. No lost, duplicate, unauthorized or
  partial writes in this phase; all states, dates and references matched.
- **PASS within the write-time contract: five target deletion races**, 0.185
  seconds total. Each target DELETE blocked while task creation waited at audit
  finalization, then completed only after task creation committed. Each task was
  committed once. The subsequent deletion left five orphan references, reproducing
  the already documented lack of a polymorphic FK; this does not prove protection
  against deletion after commit.
- **FAIL: task-row DELETE versus PATCH**, four serialized pairs passed
  (PATCH 200 / DELETE 204), then the fifth returned PATCH **500** / DELETE 204.
  Stopped at that first unexpected outcome. Exact server error:
  `sqlalchemy.orm.exc.StaleDataError: UPDATE statement on table 'tasks' expected to update 1 row(s); 0 were matched.`
  Stack points to `backend/app/api/routes/tasks.py:248`; the task is read without
  a row lock at `:209`, while deletion reads/deletes at `:255` and `:259`.
  Readback found the row absent, with two audits (create/delete) rather than a
  partial update; successful pairs had three audits. No fix was applied.
  Reproduction on plain clone_main was not run; introduction/attribution is
  unestablished. Dilmurod/Mirshoir must triage the operation's race outcome before
  treating bounded stress as passing.

These are small unpaced local bursts on one worker, not sustained-load or factory
capacity evidence. Mirshoir must review the proposed latency/stop bounds, remaining
post-commit orphan behavior, reopening policy and existing factory-scope limits.
The observed 500 prevents a passing stress gate regardless of the chosen latency
threshold. Human review/acceptance and the complete connected-browser gate remain
pending; nothing is marked verified or accepted.

### Evidence retained locally

`/private/tmp/api02-gates-20261030/`: `STRESS_PLAN.md`, `stack-identity.json`,
`api-results.json`, `browser-results.json`, `denial-results.json`,
`shortage-results.json`, `shortage-browser-results.json`, `readback.json`,
`final-readback.json`, `stress-results.jsonl`, `backend-race.log`, harness scripts
and screenshots (`{manager,denied}-{en,ru,uz}-{1280,390}-{refusal,reload}.png`,
`denied-{en,ru,uz}-{1280,390}-403.png`, `shortage-en-{1280,390}.png`). Artifacts
are local, not uploaded/committed. Earlier full-suite results were not rerun or
promoted to this candidate. The temporary frontend was stopped and this run's
Compose project/volumes removed; production and unrelated local stacks untouched.
