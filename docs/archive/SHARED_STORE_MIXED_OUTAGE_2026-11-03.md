# Shared-store outage: mixed policy — 3 November 2026

Owner Dilmurod; reviewer Ismail (`Ismoiljon1101`), explicitly assigned by the user.
Base: freshly fetched `origin/clone_main` `75cf9c53`; code checkpoint
`00cdcf9c94254f56911b02ff8bc7a6dfefd06b73` on
`codex/dilmurod-shared-store-mixed-20261103`.

## Approved behavior and scope

The user's 3 November decision is **mixed**: ordinary authenticated API requests
continue during a counter-store outage, with permission checks intact and a logged
warning that global limiting was skipped. Login, password-reset request and reset
completion instead return 503 with JSON detail:
`Authentication is temporarily unavailable. Try again later.`

The global limiter catches counter acquisition/increment/retry-TTL exceptions;
normal request authentication and authorization still run. Auth counter operations
map store failures to 503, preserving existing HTTP exceptions and healthy-store
429/Retry-After behavior. Reset completion performs a non-incrementing availability
probe before changing password/token/audit state. Its SQLite TTL operation can purge
expired counter rows; it is not strictly read-only I/O. No alternative store,
new driver timeout, credential, schema, DTO or permission contract is introduced.
Logout, password change and factory switching keep their existing behavior.

## Automated evidence

- Corrected fail-first on unchanged base runtime: **34 failed / 0 passed / 0 errors /
  0 skipped**. Both global availability and sensitive-route refusal were absent.
- Candidate focused auth/security/store/readiness/HTTP-isolation checks:
  **128 passed / 0 failed / 0 errors / 0 skipped**. An additional ordinary task-write,
  persisted readback and denied-assignment check: **1 passed / 0 failed / 0 skipped**.
  The new file now has 35 cases; the full suite includes that final file.
- Tests cover missing/disabled/invalid principals, denied permissions, all login
  aliases, reset request/completion, enabled/disabled global limiting, store
  construction/late operation failures, no session/password/token/audit side effects,
  and recovery of normal rate limiting. Ruff passes on the three changed Python files.
- Historical unadapted #322 attempts: **BLOCKED / incomplete; those attempts have
  no final totals**. Both reached PERF06 PostgreSQL fixture teardown, where
  `finalize_target` entered its deliberate `TARGET_DRAIN` lifecycle hold. The first
  process ignored SIGINT by design; a diagnostic abort with core dumps disabled
  captured the stack. Its output remains in `full-interrupted-attempt/full-suite.log`.
  The fresh run adds only pytest diagnostic output options and reproduces the hold;
  it is retained alive with its owned disposable database. No application/test/safety
  guard was changed or bypassed. HAProxy was installed only in disposable test
  containers; no tracked runner/dependency changed. Those unadapted attempts have
  no final reports for later cases or PostgreSQL gates. The completed **adapted**
  full-suite result and passing PostgreSQL gate reports are recorded below.
- All six unchanged PERF06 cases pass on exact base `75cf9c53` in a bounded separate
  process using the approved #322 PostgreSQL instance (6 passed, 0 failed/errors/skipped).
  The later exact-base diagnostic confirms an intermittent fixture-worker race; see
  the follow-up below.
  The lifecycle helper changed in base commit `03a2d067` since earlier `58bca549`
  full-suite evidence, so that historical green result does not establish this gate.
- Separately, exact current base S06 `test_concurrent_stock_adjustments[batch_delta]`
  reproduces its known `AttributeError: 'str' object has no attribute 'value'` in
  `stock_movement_persistence.py:68`: **0 passed / 1 failed / 0 errors / 0 skipped**,
  with one other case deselected. This is a baseline comparison, not a full-suite total.


The first local test attempt used `/api/admin/users` instead of the real `/api/users`
in two new assertions. That attempt is archived; the corrected fail-first was rerun
before restoring the candidate. No application change was made to satisfy a bad URL.

## Real three-minute outage and browser observation

Only the isolated Compose project `milana-sec04-local-5962e45e` was touched. Its
fresh PostgreSQL 16 database contains fake seed data, with no production import.
Backend API: `http://127.0.0.1:63150`; frontend: `http://localhost:63151/profile`.
The frontend uses **Next dev with webpack**, matching the #311 outage scenario;
this is not release-image or production-mode validation. Runtime backend source
hashes match the code checkpoint. A unique local auth-cookie name isolates sessions
from other local QA copies. Test credentials remain in a mode-600 local example
configuration, never in this report.

The real configured SQLite counter file was preserved and temporarily replaced by
a directory, causing genuine store I/O failures. An independent timer restored the
original file; the application was not restarted or pointed at a replacement store.

| Event | UTC | Asia/Seoul |
| --- | --- | --- |
| Store fault acknowledged | 2026-11-03 07:16:40.544566 | 2026-11-03 16:16:40.544566 |
| Original store restored | 2026-11-03 07:19:40.815812 | 2026-11-03 16:19:40.815812 |

**PASS, 180.271 seconds, 36 samples:** `/api/auth/me` 200, task list 200,
login 503 throughout the fault. Both reset operations also returned 503. An ordinary
permitted task write returned 201 and was read back after recovery. Login recovered
to 200 without restart; backend worker PID 8 and container start timestamp
`2026-11-03T06:54:49.772230376Z` remained identical. SQLite integrity was `ok` and a
pre-existing sentinel counter survived restoration.

Actual Chromium loaded/reloaded the profile and task drawer before, during and
after the outage, with the fake `Shared-store outage test task` visible. A separate
logged-out browser observed login's JSON 503; fresh API login succeeded on recovery.
All four screenshots were inspected. Existing client formatting shows
`503: 503:` before the friendly detail; this frontend formatting observation is a
follow-up, not a change here. An earlier observer waited on the wrong login alias;
its API outage passed but the browser observer failed. That attempt is retained;
the complete corrected browser-plus-API three-minute run above passed.

Local evidence, excluded from Git: task worktree
`.codex-work/outage-evidence/` contains before/after JUnit and summaries,
`ordinary-write.xml`, full-run output, and `technical/{events.jsonl,summary.json,
browser-results.json}` plus four screenshots. These reports contain no secret values.

## Remaining gates and integration limits

Independent read-only Codex review (`/root/acceptance_people_recipe`) found no
source, focused-test or three-minute-evidence blockers. The default unadapted
fixture hold remains a separate follow-up; the completed adapted full run below
records 5,947 passes and one known S06 failure, with both PostgreSQL gates passing.
Connected Chrome result is **PARTIAL**; human acceptance remains **PENDING**. The scheduled local
browser window completed with a timed three-minute fault and automatic restoration;
its exact plan and logs stay beside this run's evidence. The stack remains running for that checker until explicitly stopped.
This is not AI verification, acceptance, merge or deployment authorization.

Current base readiness checks PostgreSQL only. #311's proposed store-sensitive
readiness is not ported: routing must not remove every slot during this deliberately
permitted degradation. This PR does not close #311's readiness/visual/release gate.
Live Redis transport outages and indefinitely blocked drivers were not exercised;
existing store deadlines remain unchanged. Distributed global limiting is deliberately
unavailable during the fault, while login/reset refuse service.

No production host, shared application, secret store or real business data was
accessed. Production active/rollback release records are unchanged.

## Connected Chrome evidence received — PARTIAL

[Supplied browser report](evidence/PR373_2026-11-03/PR373_BROWSER_RESULTS_2026-11-03.md)
and its three screenshots are retained unchanged; all screenshots were inspected:
[17:35 baseline](evidence/PR373_2026-11-03/pr373_1735_login_baseline.jpg),
[17:39 login refused](evidence/PR373_2026-11-03/pr373_1739_login_refused_503.jpg),
[17:42 invalid login restored](evidence/PR373_2026-11-03/pr373_1742_login_recovered_401.jpg).

The checker never had a signed-in session. Login and reset request returned clean
JSON 503 during the scheduled fault; anonymous me returned 401 throughout 157
samples, and invalid login recovered to 401. **Signed-in `/profile`, Tasks drawer,
`/api/auth/me` and task-list 200 during outage were not covered in connected Chrome.**
The browser result is **PARTIAL**, not verified or accepted. Earlier automated
Chromium/API evidence remains separate and does not fill this connected-browser gap.
The isolated copy stays running for a redo; no additional outage window is armed.

The controller's second real outage logged baseline `08:35:01.075786Z`, fault
`08:39:00.300073Z`, original-store restore `08:42:00.711708Z` and recovery
`08:42:01.722743Z` (all 3 November). The 36 signed-in API samples were all me/tasks
200 and login 503; both reset refusals were 503. Restored integrity/sentinel and
worker PID 8/container start identity were unchanged. These are controller results,
not connected Chrome's missing signed-in results.

### One earlier anonymous me 500: frontend proxy reset

The label-checked backend log window `08:33:45Z–08:34:30Z` has no 500, traceback
or counter-store warning. It records normal me 401s at `08:34:13.288709Z`,
`08:34:24.718144Z`, and `08:34:29.338967Z`; no completed backend me request at the
reported `08:34:06Z`. The installed Next proxy error handler (`next/dist/server/lib/router-utils/proxy-request.js:80–84`)
logs its proxy error and assigns HTTP 500. The frontend log records
`Failed to proxy http://127.0.0.1:63150/api/auth/me Error: socket hang up`,
`code: ECONNRESET`. Thus the observed 500 is consistent with Next's proxy failure,
not a backend-generated HTTP 500. The frontend log has no absolute timestamps, so
its exact correspondence is inferred from the lone matching proxy failure and the
backend window; the underlying transport reset cannot be proven from these logs.
The controller was waiting until baseline and changed the store only at 08:39:00Z;
there was no early store fault. A transient dev-proxy connection failure remains a
follow-up; no speculative retry/proxy change is made here.

### Login formatting and retry follow-up (outside this PR's runtime scope)

`frontend/src/lib/api.ts:144–195` uses three login attempts for 500/502/503/504.
Its sleeps are 1,200 ms then 2,400 ms (3.6 seconds total), plus response/connection
and rendering time. This explains the prolonged Signing in state; exact extra
latency in the reported 6–10 seconds cannot be apportioned without browser timing.
At line 180 it saves `503: <detail>`; line 195 wraps that in `new ApiError(503, ...)`;
`frontend/src/lib/errorMessages.ts:174` prefixes the status again. The login page
renders `err.message` at `frontend/src/app/login/page.tsx:107`. That produces the
observed `503: 503:`. These frontend files are unchanged by #373. The retry/status
accumulation dates to `9fb7f1fc`/`4a9c98a3`, with the ApiError wrapping at `c88524c7`.
Keep the detail raw with its status stored separately; decide whether a deliberate
store-unavailable 503 should be shown immediately rather than retried. Both remain
follow-ups, not fixes in this backend-only policy PR.

### Requested S-09 register and stale-branch cleanup

The register published by #367 now explicitly records S-09's source fix in
`7f6d9e18638b49d7f416bd3ded54fb53488febdd`, an ancestor of current `clone_main`.
Compared the sole stale-branch commit `b415c382` and its three changed files with
the integrated typed `ProductionOrderUpdateIn(extra="forbid")`, reference checks,
workflow-status 409 guard and integrated regression coverage. The branch's internal
field protection is superseded. Its printing-metadata rejection and permissive
raw-status positive test are obsolete API differences, not missing security fixes:
printing metadata is explicitly validated/editable, and status transitions must use
workflow actions. Current integrated regressions: **43 passed / 0 failed/errors/skipped**.
`codex/s09-production-patch` was checked out in no worktree and had identical local
and remote tips; both refs were deleted as requested after recording this proof.
No production or business-data change; broader related findings retain their own gates.

## Teardown diagnosis and final full-run method

A separate exact-base `75cf9c53` PERF06 run reproduced `TARGET_DRAIN` on the
501-row PostgreSQL refusal case. Its observational diagnostic recorded the
original retained error: `ApprovedInstanceUnavailable: target workers are not
proven closed`; one new live `AnyIO worker thread`; **0 checked-out connections**.
The original guard then held unchanged. Thus this race is **pre-existing on the
PR's clone_main base**, not caused by the outage-policy change. A longer exact-base
prefix independently passed **3,432 cases / 0 failed/errors/skipped**, with 2,481
later cases deselected, confirming intermittency rather than a deterministic
prefix failure. The prefix is not represented as a full-suite total.

PERF06 joins its Uvicorn server thread and immediately calls the PostgreSQL
finalizer. A late AnyIO worker can still be exiting; the helper's immediate
all-thread drain check permanently retains the owner on failure. The guard's
protection is correct. The fixture needs bounded worker draining before finalization;
that pre-existing tracked-fixture change is outside the user's conditional
"fix it if it's ours" scope. No application or tracked PERF06 fixture fix is included.

Process isolation alone also reproduced the hold. To obtain a complete case total,
the final #322 run uses a **disclosed local PERF06 worker-drain adapter**, not an
unmodified default-run pass. The ignored pytest plugin wraps only PERF06's imported
finalizer: passively join actual `anyio._backends._asyncio.WorkerThread` instances
created after that target's baseline, using one total five-second deadline; then
invoke the original finalizer exactly once. It never stops/signals workers, changes
owner/baseline/errors, closes connections or bypasses thread/pool/identity/native-PG
drain checks. Unknown or still-live workers remain visible to the original guard.
An outer finally covers inspection, waiting and diagnostic logging. Two isolated
fault checks prove the original finalizer still runs when snapshot or logging fails.
Independent read-only review approved the corrected adapter; its source hash is
recorded in local `adapter-version.json`.

The early adapter-startup check was interrupted for that finally correction before
PERF06; its partial totals are retained separately and are not a full result.
The corrected complete run has finished; its separate final totals are below. The unadapted
holds remain retained; default-run cleanup is not claimed fixed.

### First complete adapted run and owned test correction

The first complete run with that adapter recorded **5,943 passed / 5 failed /
0 errors / 0 skipped**; required PostgreSQL groups and the 17-case supplement
passed. Four failures were #373's new parametrized warning-capture assertions:
all four HTTP status assertions passed at 200, but `caplog` was empty. Earlier
in-process migration tests invoke Alembic's `fileConfig`, whose default disables
existing loggers. `caplog.at_level` changes level but does not clear `disabled`.
This was our test's missing isolation, not an API-behavior failure. The fifth
failure was the independently reproduced baseline S06 string/enum error.

Checkpoint `8bc76945` adds only a monkeypatch re-enabling `main.log` inside the
warning test; teardown restores its prior disabled flag. All original warning
and private-detail assertions remain intact. Application/frontend/guard code is
unchanged. A deliberate disabled-logger focused run passes **129 / 0 failed/errors/
skipped**; Ruff and independent review pass. Normal app startup verifies the
migration state without executing Alembic's logging configuration.

The complete five-failure report remains in `full-first-complete-attempt/` and
JUnit directory `postgres-results-4e8e74fd`; totals are not combined with reruns.
The new complete #322 run on `8bc76945`, using the same reviewed local drain adapter,
completed with the separate final totals below.

Additional logging-order check: after applying the actual Alembic `fileConfig`, all four corrected warning cases pass (4 passed / 0 failed/errors/skipped). The isolated copy health check at 09:34:18Z confirms login/me/tasks 200, fixture visible, original store path/integrity ok, worker8 unchanged and zero container restarts. No new browser outage is armed.

## Final complete suite — checkpoint 8bc76945

**#322 with the disclosed local PERF06 passive worker-drain adapter:**
**5,947 passed / 1 failed / 0 errors / 0 skipped**, plus 36 passing subtests,
in 1,334.78 seconds. All **35** outage-policy cases pass, including the four
warning-capture cases corrected above. The sole failure is the previously
reproduced base S06 `test_concurrent_stock_adjustments[batch_delta]` string/enum
`.value` mismatch. The runner exits 1 for that failure; no all-green claim.

Required PostgreSQL gate: **PASS, 200 cases across 20 groups**. Supplement gate:
**PASS, 17 cases**. Those cases are selections from the full report, not extra
passes to add to 5,947. Full evidence is local/Git-excluded:
`full-drained.log`, `full-drained-summary.json`, and JUnit directory
`.codex-work/postgres-results-606bacef` (including backend/required/supplement XML).
The final run uses the corrected adapter hash in `adapter-version.json`; it
passively drained a real late worker and the original finalizer returned normally.
Default unadapted fixture behavior is still a separate pre-existing follow-up.

A final fetch found `origin/clone_main` `77d090f6`; its changes after the PR base
are frontend HR only, with no backend or runner overlap. No backend combined-source
change invalidated this run. Runtime application code remains unchanged from
`00cdcf9c`; the follow-up runtime-test change is only the scoped logger setup in
`8bc76945`. Independent review covers that setup and the local adapter.

The browser result remains **PARTIAL** and human acceptance remains pending.
The isolated copy is kept running; no merge/deployment or new outage window.

Final independent read-only review confirmed the final source, counts, adapter method and PARTIAL browser classification. Earlier blocked statements above refer only to the unadapted attempts, not the completed adapted report.

## Connected-browser rerun and interrupted re-arm — 3 November 2026

The [checker-supplied rerun](evidence/PR373_2026-11-03/PR373_BROWSER_RERUN_2026-11-03.md) is **NOT COMPLETED** as a signed-in browser outage check. The rebuilt `localhost:63151` frontend rendered "Internal Server Error" on `/login` and `/profile`. Its archived `frontend.log` reports missing `next-flight-client-entry-loader` and missing `frontend/node_modules/typescript/package.json`: the copied frontend's `node_modules` symlink pointed to the repository-root dependency directory, which was absent at inspection. API login, `/api/auth/me`, and `/api/tasks` still worked before the fault; the browser saw the test task.

The second controller **did** rename the shared SQLite store at **19:30:24 Seoul**. Its `events.jsonl` recorded two signed-in samples with me/tasks **200** and login **503**. At **19:30:30**, its password-reset request through the broken Next frontend returned a non-JSON 500; the controller's JSON parser raised, its `finally` restored the store, and the controller exited. Thus the intended three-minute window lasted about **six seconds**, and the browser's later dummy-login 401s and 429 lockout occurred with the store up. They are **not** outage evidence. The 429 followed the checker's own repeated invalid logins. This failed re-arm has no completed summary; retain its traceback and event log locally, separate from the earlier pass.

For signed-in outage behavior, the earlier real **180.412-second HTTP rehearsal** remains the evidence: **36** samples had `/api/auth/me` and `/api/tasks` at **200**, while login returned **503**; original-store integrity and the worker identity survived recovery (`scheduled/summary.json`, excluded local evidence). This is **HTTP evidence, not a connected-browser pass**. Connected-browser signed-in behavior remains **not covered**. Phone layout and RU/UZ inside the app remain not covered. No verification or acceptance state is advanced. The rebuilt isolated stack is to be removed after this note.
