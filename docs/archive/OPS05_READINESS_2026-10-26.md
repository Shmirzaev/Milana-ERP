# OPS05: shared-store readiness — 26 October 2026

## Scope and ownership

State: **BLOCKED** for complete verification; implementation and automated checks
are recorded below. Owner: Dilmurod. Assigned reviewer: Mirshoir (review pending).
Implementation: Codex GPT-6 session, isolated worktree
`.codex-work/ops05-readiness`, branch `codex/ops05-readiness`, base `f369ae2e`.
No independent AI or human approval is claimed.

Direct owner correction: `/health` and `/ready` are already correctly separated;
`/ready` already probes PostgreSQL. Add only the required shared-store check with
one bounded deadline and single-flight behavior. Concurrent callers must share
the in-flight result, including failures; a busy lock is not a dependency failure.
Do not copy donor `c275be7`'s busy-lock refusal. Run fail-first regressions, the
full suite, Ruff and lint before pushing. Gates 3 and 4 may remain BLOCKED.

## Operation and caller map

- `/ready` -> `_readiness_checks_within` -> `_probe_postgresql` (`SELECT 1`)
  and `_probe_shared_store` -> `get_shared_counter_store().ttl("readiness")`.
- The existing store factory enforces configured Redis/SQLite, or the permitted
  local in-memory fallback. Probe initialization and operations inside the deadline;
  merely obtaining an already-cached store would miss an outage.
- No protocol extension, configuration, dependency, business table/field/type,
  permission, UI, migration, business write or department handoff changes.
  The TTL operation creates no keys; SQLite retains its existing expired-counter
  housekeeping behavior. Auth/rate-limit counters are not incremented or set.
- Callers: `deploy/slotctl.py` backend health and warmup; its generated HAProxy
  check also uses `/ready`. Existing contract tests cover both. No caller edits.
- Preserve 200/503, `status=ready/not_ready`, and `checks.postgresql=ok/unavailable`;
  add only `checks.shared_store=ok/unavailable`. No exception details in responses.
- `/health` and rate-limit exemptions are unchanged. The liveness regression
  fails if either dependency probe is invoked.

## Deadline and concurrency contract

One two-second monotonic deadline covers both checks and any store initialization.
A brief process-local mutex publishes one flight: completion event, check results,
and deadline. The mutex is never held during dependency I/O or waiting. Joined
callers wait on that event with the same remaining budget. Completed results are
copied for each response; the next request after completion starts a fresh flight.
A dependency completing after the deadline cannot turn its result into `ok`.

A timed-out worker remains the only flight until it exits. Python cannot cancel
blocked synchronous I/O: at most one daemon probe thread per application worker
may remain stuck, and readiness stays unavailable until that operation exits or
the process restarts. No success cache or thread accumulation is introduced.
Sequential checks use the same budget; if PostgreSQL consumes it, the unprobed
store is conservatively unavailable. This does not claim a store-specific outage.

## Evidence

Runtime source SHA-256:
`f800ad1704e0b0f8e9de1d05281be37abfd10751a0e717c3cf40b7d0e330103d`
(`backend/app/main.py`). Tests SHA-256:
`15c98a3ef8aa3821eba3f72787551de2567b023de5a3bab32cb26d2c01db5c60`.
The commit containing this record identifies the complete candidate.

Commands use `/private/tmp/milana-sec04-20261025-venv/bin/python` (Python 3.12)
from the isolated worktree unless stated otherwise. Tests use disposable SQLite
and mocked dependency faults, never production storage.

- Gate 1, fail-first: **PASS**. `python -m pytest -q
  backend/app/tests/test_readiness.py` on unchanged baseline runtime with new
  tests: **8 failed, 2 passed**. Failures include store outage and initialization
  incorrectly returning 200, store hang not being probed, one deadline not being
  enforced across dependencies, and concurrent callers immediately failing while
  the first probe is blocked. Existing database timeout and liveness controls pass.
  Log: `/private/tmp/ops05-red.log`.
- Focused green: **13 passed** using `python -m pytest -q
  backend/app/tests/test_readiness.py backend/app/tests/test_shared_store.py
  backend/app/tests/test_slotctl_readiness_contract.py`.
  Log: `/private/tmp/ops05-green.log`.
- Initial full-suite attempt: **FAIL / interrupted**, 2 failed, 1864 passed,
  171 skipped before stopping. Both failures were missing Unicode fonts in PDF
  tests (`test_eco_transfers` and `test_inventory_master_data`). Log:
  `/private/tmp/ops05-full-suite.log`. Made the existing local font-support
  fixture available through a temporary `C:` symlink to
  `/private/tmp/milana-font-support/C:` (Arial/Arial Bold system fonts),
  without changing source or tests. The symlink is not committed.
- Gate 2, corrected full suite: **PASS**, 3870 passed, 312 skipped,
  13 warnings in 560.79 seconds; `python -m pytest -q`. Skips are
  infrastructure-specific tests outside OPS05; no skipped readiness test is
  counted as a pass. Log: `/private/tmp/ops05-full-suite-fonts.log`.
- Additional test trees: **16 passed, 4 skipped**, `python -m pytest -q tests
  backend/tests`; `/private/tmp/ops05-extra-suite.log`. Two skips require
  `S06_POSTGRES_URL`; two require isolated PostgreSQL binaries via `OPS_TEST_PG_BIN`.
- Ruff: **PASS**, `cd backend && python -m ruff check app`;
  `/private/tmp/ops05-ruff.log`.
- Compile: **PASS**, `cd backend && python -m compileall -q app scripts`.
- Frontend lint: **PASS**, `npm --prefix frontend run lint`: 0 errors,
  10 existing warnings. `/private/tmp/ops05-lint.log`. Reused the existing
  SEC04 worktree's node_modules after comparing identical package-lock files;
  no package or lockfile changes.
- Gate 3, actual visual E2E: **BLOCKED**. No isolated candidate runtime with
  real PostgreSQL/shared-store dependencies and browser verification was exercised.
- Gate 4, live bounded stress, integrity and recovery: **BLOCKED**. No isolated
  live dependency environment was exercised. Four-caller success/failure unit
  concurrency, stuck-probe reuse and bounded timeout tests are automated evidence,
  not live stress/capacity or real database readback evidence.
- Independent review and human technical/production acceptance: **PENDING**.
  Do not label AI_VERIFIED_AWAITING_HUMAN or close OPS05.

## Handoff and remaining verification

On an isolated candidate, verify `/health` remains 200 with dependencies down;
`/ready` is 200 with both up, then 503 within two seconds when either is blocked
or unreachable, without leaking credentials. Issue concurrent requests while
holding a probe, verify shared outcomes and one flight, remove the fault and
confirm fresh requests recover. Inspect the actual endpoint rendering/browser
network results. Record bounded live workload, latency/error limits and recovery
with Mirshoir before running gate 4; no production synthetic traffic or writes.

Publication target: `codex/ops05-readiness`. No merge or deployment
authorized/performed here.
No production data touched. Active/rollback slots were not queried or changed;
last recorded context remains blue `20261024_093619`, rollback green
`20261024_032622`, not fresh verification. Obsidian Windows mirror is inaccessible
from this macOS workspace. Preserve existing implementation until review and the
remaining gates/human acceptance; rollback is reverting this source-only change.

## Local browser and recovery stress — 30 October 2026

Verification-only follow-up requested by the user. Runtime tested:
`52cfa853818b657457fdbb439cbc6d1e7bf69a0a`, worktree
`.codex-work/ops05-readiness`, branch `codex/ops05-readiness`.
Owner Dilmurod; reviewer Mirshoir. Only this evidence document changes in the
follow-up commit. Earlier evidence remains intact. **No verified or accepted
status is assigned.**

### Isolated environment and fault method

Reused #319's `scripts/sec04_local_stack.py` / `sec04_local.compose.yml` from
`.codex-work/rf004-sec04-verification`, with temporary state and a fresh project
`milana-sec04-local-69359065`: PostgreSQL 16, required SQLite shared store,
one backend worker, API on `127.0.0.1:18080`. The exact candidate frontend ran
from a `git archive` copy on `127.0.0.1:3000`, with identical-lockfile dependencies
and Webpack dev. Browser requests to external hosts were blocked. Only the
existing synthetic SEC04 viewer/model/image fixture was created; no production
or shared environment, dump or business record was used.

The runtime hashes of main.py, shared_store.py and config.py matched the
candidate. main.py remained
`f800ad1704e0b0f8e9de1d05281be37abfd10751a0e717c3cf40b7d0e330103d`.
No response mocks, dependency monkeypatches, new app dependencies or source
changes were used. SQLite has no service process to stop. Initial chmod(000)
was an ineffective negative control: readiness stayed 200, consistent with
reuse of an open file handle; that was not counted as an outage. The actual
fault preserved the database under a temporary name and placed an empty
directory at its configured filename, making new SQLite opens fail. Restoring
the original file removed the fault; no replacement database was created.
WAL/SHM were retained. All faults had finally-based restoration.

### Actual browser and endpoint results

**PASS for the exercised local UI/endpoint behavior; full connected-browser
Gate 3 remains BLOCKED.** The connected Browser/Computer Use execution tool
was unavailable after tool discovery. Standalone Chromium exercised the real
candidate instead. Desktop 1280 x 900 and phone viewport 390 x 900 were inspected
personally; this is emulation, not physical-phone or connected-browser evidence.

- Healthy: `/ready` 200 with both checks ok; the fixture model/image rendered.
- Store path unavailable: `/ready` 503 with exactly
  `{"status":"not_ready","checks":{"postgresql":"ok","shared_store":"unavailable"}}`.
  Desktop/phone request times were 4.215 / 3.217 ms. `/health` remained 200,
  2.934 / 1.638 ms. Endpoint rendering exposed no exception details.
- The app showed a readable session-check error and Retry button, rather than
  silently logging the user out or rendering a blank page. However,
  `/api/auth/me` returned **500** while the required store was unavailable;
  this is the broader availability failure described below, not an API pass.
- After file restoration, `/ready` was 200 in 4.539 / 4.350 ms. Clicking the
  actual Retry button restored the model page on both sizes without a page
  reload, re-login or app restart. No uncaught browser page errors.
- PID 8 and its process start-time token `17435471` remained unchanged across
  browser, failure and recovery checks. No backend restart was used.

### Stress limits written before execution

`/private/tmp/ops05-gates-20261030/STRESS_PLAN.md` recorded the plan before load,
including the fault-method correction before stress and a separate diagnostic
plan after the mixed-load failure. Limits require Mirshoir's review; they are
local test bounds, not an approved production SLA.

1. Slow healthy check: external SQLite `BEGIN IMMEDIATE` held for 0.65 s;
   synchronized 16-caller readiness burst; release before the two-second budget.
   All callers must return 200; an already-running check must not cause 503.
2. Timeout/reuse: hold the real write lock for at most 4.2 s, below SQLite's
   existing five-second busy timeout. Two 16-caller waves, the second after the
   shared deadline; health controls between waves. Readiness must respond within
   2 s plus 350 ms scheduling/network allowance; no accumulating probe resources.
   Release the lock and require fresh readiness recovery within 5 s.
3. Mixed recovery load: 12-second paced window, eight readiness workers plus
   one health and one authenticated-read worker; 0.1 s pacing per worker.
   Caps: 1200 readiness, 150 health, 150 authenticated requests. Fault at 3 s,
   restore at 6 s. Request timeout 3 s; readiness p95 <=2350 ms/max <=2500 ms;
   health p95 <=500 ms/max <=1000 ms. Stop on unexpected errors, integrity
   mismatch, deadline violation or resource accumulation. Expected outage
   readiness 503s do not count as unexpected errors; authenticated 500s do.
4. After that run stopped, a separately declared readiness-only diagnostic
   repeated the bounded join/timeout checks and completed the same 12-second
   fault/recovery window with eight readiness workers plus one health worker.
   It excludes authenticated load and cannot replace its failed result.
   Overall bounded stress sequences stayed below the 60-second ceiling.

### Stress results

- **PASS: slow healthy sharing.** All 16 responses were 200 after the real
  lock delay; primary max 684.078 ms, diagnostic max 683.789 ms. No busy-lock
  false failure. Health remained 200 (6.625 / 6.334 ms).
- **PASS: bounded timeout and reuse.** Both 16-caller waves returned the same
  503/check fields. Primary first-wave max 2028.734 ms; subsequent-wave max
  25.461 ms. Diagnostic: 2027.269 / 31.033 ms. These include client scheduling
  and satisfy the declared allowance; they are not claimed as <=2000 ms
  client measurements. A completed late check did not promote its expired
  result: the first post-release poll was still 503, then a fresh poll was
  200. Recovery took 56.121 / 55.613 ms without restarting the app.
- **PASS within this bound: no observed probe accumulation.** In the diagnostic,
  the warmed backend had 22 threads, then 23 at all three observations across
  both timed-out waves (0.410, 2.032, 2.072 s). SQLite descriptors stayed at 15
  total / nine database-file descriptors; no descriptor read errors. This is
  bounded external resource evidence, not an exact count of Python function
  calls or proof for arbitrarily stuck drivers. The first root observer could
  not read descriptors; its zero values are unavailable observations, not
  evidence of zero descriptors. The corrected observer ran under the app UID.
- **FAIL: mixed application-availability load.** At 3.011 s the first
  authenticated request during outage returned `/api/auth/me` 500 with
  `{"detail":"Internal server error"}` in 9.758 ms. Scheduling stopped and
  the fault was restored immediately; total run including drain was 3.168 s.
  Before stopping: 200 readiness requests (192 x 200 / eight expected 503),
  28 health requests (all 200), 25 authenticated reads (24 x 200 / one 500).
  Readiness max 37.883 ms; health max 22.352 ms. Post-restore readiness,
  health and authenticated reads all returned 200 without restart.
- The error log shows `sqlite3.OperationalError: unable to open database file`
  in `backend/app/core/shared_store.py:142`, called by increment at `:170`.
  Non-exempt requests use this store in `backend/app/main.py:195`, via the
  global-rate-limit middleware at `:243`; `/health` and `/ready` are exempt
  at `:118`. The browser retry UI recovered, but **the requested “nothing
  else breaks” check did not pass**. No fix was applied and no plain-base
  reproduction was run; introduction/attribution is not established.
- **PASS: separate readiness-only recovery diagnostic.** 12-second scheduling
  window, 12.135 s including drain; fault at 3.001 s, restore at 6.006 s.
  792 readiness responses: 584 x 200 / 208 expected 503; p95 25.513 ms,
  max 242.443 ms. All 106 health requests were 200; p95 21.620 ms,
  max 243.973 ms. Stable healthy/outage/recovered samples were respectively
  192 x 200, 176 x 503, 384 x 200; transition samples were assessed separately.
  No unexpected error or false stable-phase readiness result. This diagnostic
  does not turn the failed mixed-load run into a pass.
- **PASS: bounded integrity readback.** Counts across all 98 PostgreSQL tables
  remained unchanged during each load run; the fixture model remained present.
  The SQLite sentinel retained its exact value, no readiness counter key was
  created, and final `PRAGMA integrity_check` returned `ok`. Original file mode
  0644 was restored and no outage placeholder remained. Runtime hashes and
  backend PID/start-time identity remained unchanged.

### Remaining decisions and handoff

Gate 4's readiness-specific bounded checks passed; the broader mixed-load
availability check **FAILED**. Gate 3's connected-browser requirement remains
**BLOCKED** despite actual standalone browser/screenshot evidence. No skipped
required check is called a pass; no verified/accepted state is assigned.

Mirshoir must review: the unavailable-store response policy for ordinary APIs
(currently 500 via rate-limit I/O), the proposed local deadline/latency/recovery
allowances, the SQLite path-fault model, fallback browser coverage, and the
one-worker concurrency bound. This is not sustained production capacity evidence.
Multi-worker behavior, Redis outages, indefinite driver hangs, PostgreSQL outage,
full-suite reruns and production health/slots were not exercised in this follow-up.
The earlier driver-timeout risks and independent/human acceptance remain pending.

Artifacts are local at `/private/tmp/ops05-gates-20261030/`: plan, scripts,
`browser-results.json`, `browser-results-reload.json`, `stress-results.jsonl`,
`diagnostic-results.jsonl`, `backend-outage.log`, `integrity.json`,
`stack-identity.json`, and screenshots `browser-{1280,390}-{healthy,outage,recovered}.png`
and `ready-{1280,390}-outage.png`. Logs/results are not uploaded or committed.
The temporary frontend and this run's Compose project/volumes were removed;
no production, shared or unrelated local service was touched. Only this document
is committed/pushed to #311's existing branch; earlier PR evidence is retained.
