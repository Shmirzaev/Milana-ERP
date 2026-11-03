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
- Full unmodified #322 runner: **BLOCKED / incomplete; no final passed/failed/skipped
  totals**. Both full attempts reached PERF06 PostgreSQL fixture teardown, where
  `finalize_target` entered its deliberate `TARGET_DRAIN` lifecycle hold. The first
  process ignored SIGINT by design; a diagnostic abort with core dumps disabled
  captured the stack. Its output remains in `full-interrupted-attempt/full-suite.log`.
  The fresh run adds only pytest diagnostic output options and reproduces the hold;
  it is retained alive with its owned disposable database. No application/test/safety
  guard was changed or bypassed. HAProxy was installed only in disposable test
  containers; no tracked runner/dependency changed. Later suite cases and required
  PostgreSQL/supplement gates have no final report and are **BLOCKED**, not passed.
- All six unchanged PERF06 cases pass on exact base `75cf9c53` in a bounded separate
  process using the approved #322 PostgreSQL instance (6 passed, 0 failed/errors/skipped).
  The full-run hold may involve process-wide fixture/thread lifetime; the exact
  retained failure is unknown. It is not claimed as a proven pre-existing failure.
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
source, focused-test or three-minute-evidence blockers. Full-suite completion is blocked by the lifecycle hold and remains
a separate gate. Connected Chrome checks and human acceptance remain **PENDING**. A separate local
browser window will begin at least ten minutes after handoff, with a timed three-minute
fault and automatic restoration; its exact plan and subsequent logs stay beside this
run's evidence. The stack remains running for that checker until explicitly stopped.
This is not AI verification, acceptance, merge or deployment authorization.

Current base readiness checks PostgreSQL only. #311's proposed store-sensitive
readiness is not ported: routing must not remove every slot during this deliberately
permitted degradation. This PR does not close #311's readiness/visual/release gate.
Live Redis transport outages and indefinitely blocked drivers were not exercised;
existing store deadlines remain unchanged. Distributed global limiting is deliberately
unavailable during the fault, while login/reset refuse service.

No production host, shared application, secret store or real business data was
accessed. Production active/rollback release records are unchanged.
