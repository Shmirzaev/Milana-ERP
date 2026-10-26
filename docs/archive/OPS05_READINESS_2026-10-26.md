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
