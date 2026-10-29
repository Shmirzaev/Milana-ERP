# Local PostgreSQL runner adaptation — 29 October 2026

Task: PR #322; Dilmurod owns, Mirshoir reviews. Codex implemented under the user's
explicit exception to Ismail's local MiniMax setup. Base `425ec9fe`; existing
`codex/local-postgres-race-runner` worktree. No CI workflow or application behavior
was changed. The two previously approved local fixture fixes remain intact.

## Implementation

`python3 scripts/run_local_postgres_tests.py` builds the existing backend Docker
image, installs its existing development requirements in a disposable test
container, and launches PostgreSQL 17 matching the new CI gate. The containers
share a network namespace: PostgreSQL binds only its internal loopback and has
no published host port. This satisfies the actual server-identity check rather
than weakening `pg_approved_instance.py` for Docker port forwarding.

The launcher reads the new cluster's identity independently through `docker exec`
and supplies `MILANA_TEST_PG_INSTANCE` and `MILANA_REQUIRE_TEST_PG=1`. The internal
preflight reuses the approved-instance loader/verifier; child processes use
`sanitized_pg_environment`. Both existing gate report validators and the supplement's
node-ID helper are reused. All three legacy variables remain supplied:
`STABILIZATION_POSTGRES_URL`, `S06_POSTGRES_URL`, `FN04_TEST_PG_ADMIN_URL`.
Payment, Sales-list and Forecast-create opt-in groups also receive isolated URLs.
No inherited application URL or host PostgreSQL endpoint is used.

The default collection on this revision already includes S06, so the runner
runs S06 separately only if it is absent from the first JUnit report. Final totals
therefore count each executed case once. Required groups and the 17-case supplement
are validated separately from unrelated suite failures. Any failure, error or skip
fails the runner. Reports remain under `.codex-work/postgres-results-*`; owned
containers and the test image are removed, and cleanup failures are reported.

## Actual results

- Real full default collection: **5,375 passed / 1 failed / 0 skipped**, 854.46 seconds.
- Required operation groups: **171 passed / 0 failed / 0 skipped**, all required
  identities present. Isolated Purchasing/Fabric supplement: **17 passed / 0 failed /
  0 skipped**. These cases are subsets of the full collection, not additional totals.
- Launcher tests: **6 passed**; existing instance-guard checks: **33 passed**;
  existing gate-validator tests: **21 passed**. Ruff and whitespace checks pass.
- The four historical font failures did not occur in the backend Docker environment.
- Full log: `/private/tmp/322-adapt-complete.log`; original JUnit:
  `.codex-work/postgres-results-60c156af/backend.xml`.
- The first runner iteration generated an incorrect legacy username and was stopped;
  a second was stopped early to enable the newly discovered Sales/Forecast opt-ins.
  Neither aborted attempt is counted as verification. The completed iteration
  initially reran S06 redundantly (1 pass / 1 failure); that duplicate invocation
  was removed. Final report orchestration was checked against the captured real
  JUnit, preserving the failure and validating all required case identities without
  rerunning or fabricating application results. The final internal-mode safety
  preflight was also exercised against the live disposable cluster.

The sole unique failure is
`backend/tests/test_stock_adjustment_postgres.py::test_concurrent_stock_adjustments[batch_delta]`.
It directly passes `movement_type="adjustment"` to
`models/inventory/stock_service.py::_apply_batch_tracked_stock_adjustment`.
The refactored signature requires `StockMovementType`; the persistence helper
reads `.value`. The stale direct test call raises
`AttributeError: 'str' object has no attribute 'value'`. The application call uses
the enum contract. The absolute-target race case passes. Clean `425ec9fe` independently reproduced
the same one-failure/one-pass result on a fresh local PostgreSQL 18 cluster, with
zero skips (`/private/tmp/322-s06-clean-baseline.log`). This test-contract issue
is left for the Inventory owner; it is not silently repaired in the runner PR.

The default suite remains **FAIL**, despite zero skips and passing required groups.
Human review remains pending. No production database, serving host or shared
storage was used. Browser/visual E2E and separate application stress were not
rerun for this tooling change; no AI-verified or production-acceptance claim is made.
