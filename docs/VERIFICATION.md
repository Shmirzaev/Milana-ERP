# Verification after every runtime change

24 October 2026. Applies to each completed folder/operation migration, bug fix,
feature and database migration before it is marked ready or its old path removed.
Do not defer checks until the whole refactor ends. After the final edit, verify the
exact candidate again wherever the edit invalidated earlier evidence.

This is the team's required workflow, not a claim that CI enforcement is installed.

## 1. Make AI-generated tests capable of detecting mistakes

- Start from Shavkat's agreed business examples and the engineer's explicit contract,
  not an expected value copied from the implementation. Name input, actor, expected
  output, persisted effects, refusals and affected downstream workflow.
- Bug fix: reproduce the specific defect on the old revision, then show the same
  assertion passing on the fixed revision. A missing dependency or collection error
  is not a meaningful failing regression. Keep a small test fixture for the defect.
- Pure refactor: the approved behavior tests should pass before AND after. Compare
  independent fixtures and persisted effects. Do not invent a failure in good legacy
  behavior to claim test-driven development. Separate known defect corrections.
- For changed critical money, permission, quantity or transition rules, challenge
  the tests with a small deliberate fault in a disposable checkout: remove a guard,
  alter a boundary, or bypass idempotency. Show baseline pass -> relevant assertion
  failure with fault -> restored pass. Never mutate the shared/production checkout.
  Mutation testing helps measure detection; survivors require investigation, not
  automatic exemption or a meaningless 100% score target.
- Use parameterized boundary cases first. Where combinations or operation sequences
  matter, consider property/stateful tests for approved invariants: retrying one
  receipt cannot double stock; concurrent reservations cannot overspend available
  stock; an unauthorized operation makes no business-data change. Keep seeded or
  minimized failing examples. Property tests need correct business rules too.
- Mock external services where appropriate, not the business function, permission
  decision, ORM transaction or UI response being claimed as tested. No runtime app
  patch, swallowed exception, weakened assertion, silent skip or snapshot update
  merely to obtain green output. A changed expectation needs a reviewed contract reason.
- Use one fresh reviewer pass to challenge assertions against the requirements;
  AI review can assist, but the named engineer reviews the result. Start with focused
  tests and expand to affected integration/handoff coverage and required CI checks.
  Coverage percentage and number of tests are not evidence of correct outcomes.

## 2. Run the right automated checks

Run relevant unit/contract tests, API/integration tests and affected workflow
regressions. For moves, check old/new imports and duplicate definitions; for ORM
moves, model registration/Alembic metadata and no unexpected schema diff. Actual
storage migrations need compatibility and recovery checks on isolated PostgreSQL.

Repository evidence at f8719d19: pyproject.toml defaults test discovery to
backend/app/tests; that conftest configures SQLite. The concurrent adjustment test
backend/tests/test_stock_adjustment_postgres.py is outside that default collection
and skips without S06_POSTGRES_URL. tests/ also contains separate checks. Inspect
the affected tests and their configuration; run required PostgreSQL checks in their
correct isolated process/environment. SQLite cannot prove PostgreSQL row locking.
Do not invent credentials or print secrets. Report collected, passed, failed and
skipped tests; a required skipped test leaves its gate BLOCKED, not PASS.

## 3. Visually exercise the real end-to-end workflow

After technical checks, use the connected browser/computer tool against the exact
candidate in local/staging with isolated database, files and external effects.
Use the real UI and backend. Verify the test target and test accounts first.

- Log in as the relevant role; perform the changed workflow and the next department
  handoff. Also check an already-working related workflow that could regress.
- Actually inspect rendered screenshots with the agent's vision at meaningful
  checkpoints. Check visible quantities, statuses, errors, disabled/enabled actions,
  layout and loading/empty states. Saving a screenshot or reading a DOM alone is
  not a completed visual inspection. Record what was observed and where.
- Refresh/reopen the record and confirm persisted readback. Exercise invalid input,
  denied access and relevant partial operations. Inspect failed network requests
  and browser/backend errors; a successful toast is not enough.
- Check tablet/mobile, scanner/label/print and EN/RU/UZ behavior when affected.
  Use stable user-facing locators and isolated browser sessions in automated E2E.
- Reproduce any discovered issue, add its regression check, fix the cause and rerun
  the affected automated AND visual steps. If browser/vision/login/test data is
  unavailable, mark visual verification BLOCKED and state what is missing.
  Never substitute mocked UI, a screenshot filename or an AI claim for execution.

## 4. Challenge behavior under pressure

Every runtime change gets a bounded stress scenario appropriate to its affected
workflow after normal visual verification. Examples: repeat submissions/scans,
two users editing/reserving the same stock, retries after timeout, a slow response,
large realistic lists, or burst requests. Prefer deterministic concurrency tests
over unreliable rapid clicking for reproducing database races; inspect the UI too.

Before running, record workload, duration, maximum concurrency, data volume,
environment limits, expected outcome, latency/error limits and stop conditions.
Dilmurod prepares tooling; the feature engineer chooses the relevant scenario;
Mirshoir reviews limits for sensitive workflows. Do not invent universal user counts
or claim production capacity from a smaller staging system.

Start with a minimal smoke workload, then expected load, then bounded above-normal
load; use spike/soak tests when the change warrants them. Measure p95/p99 latency,
throughput, errors, DB lock waits/connections and CPU/memory where available. Compare
the same workload/environment/data with a baseline and honor DEPLOYMENT.md gates.
Under load AND after recovery, verify data integrity: no lost updates, double
receipts/payments, invalid balances, unauthorized writes or partial handoffs. Error
handling under overload must follow the agreed contract; fast responses alone fail
the test if the data is wrong. Check recovery when load is removed.

Run synthetic write/concurrency/load tests only on an isolated test environment;
an inactive deployment slot sharing production storage is not isolated. Stop on
the recorded bounds or corruption signals. No production stress or fabricated
factory transactions. Heavy capacity testing is a separate bounded exercise, not
a prerequisite for every unrelated file edit. k6 and mutation/property tools are
options to adopt where useful, not claimed installed or run by this documentation.

## 5. Record evidence and completion

Use one short record in the task/bug evidence; reuse the same format:

```text
Task / candidate commit / environment:
Engineer / reviewer / business acceptance owner:
Expected behavior and unaffected control workflow:
Automated: PASS | FAIL | BLOCKED; command, counts/skips, logs:
Test validity: old-fails/new-passes or refactor parity; fault challenge if relevant:
Visual E2E: PASS | FAIL | BLOCKED; roles, steps, viewed screenshots, readback:
Stress: PASS | FAIL | BLOCKED; scenario, limits, baseline/results, integrity/recovery:
Review and production acceptance: pending or named evidence/date:
Cleanup/rollback condition and remaining limitations:
```

Any required failed/blocked gate prevents calling the runtime change ready or
retiring its fallback. Fix and recheck; do not conceal retries or skipped checks.
Shavkat/operator acceptance and the engineer's technical evidence are still required
for production closure. AI visual approval is not the human's production approval.
Documentation-only changes use document/link/skill checks; visual/load gates are
NOT APPLICABLE with that explicit reason, never falsely reported as passed.

Feature engineers own all these checks. Dilmurod owns shared verification tooling;
the assigned reviewer checks evidence; Mirshoir owns release decisions. See
[team ownership](TEAM_OWNERSHIP.md). This guide creates no tools, CI jobs or schedules.

## Independent review before landing

The named reviewer checks the relevant diff and evidence for backend object/role
authorization, integrity under retries/concurrency, sensitive-data exposure, file
path/type/size validation, audit effects, recovery and API compatibility. Review
frontend loading/error/accessibility/translation states when affected. Run required
lint/type/build/security/dependency checks for the changed scope and investigate
findings. Coverage is supplementary; no substitute for the gates above.

Database changes require a reviewed Alembic migration when storage changes; a
source-only move must not alter metadata. Do not add production startup schema
patches: main.py rejects STARTUP_SCHEMA_SYNC for production/public deployment.
Preserve safe idempotent seeding and disabled-by-default production seed behavior.

This replaces the retired CODE_REVIEW.md without weakening required checks.

## Research informing these rules

- [Anthropic: explicit verification and independent review](https://code.claude.com/docs/en/best-practices).
- [Anthropic: test-first agent workflow](https://www.anthropic.com/engineering/claude-code-best-practices).
- [Playwright: user-visible behavior, isolated tests and resilient assertions](https://playwright.dev/docs/best-practices).
- [Hypothesis: stateful actions and invariants](https://hypothesis.readthedocs.io/en/latest/stateful.html).
- [mutmut: mutation testing](https://mutmut.readthedocs.io/en/latest/); current tool requires fork support, so Windows use needs WSL or a suitable Linux environment.
- [Grafana k6: performance-test strategy](https://grafana.com/docs/k6/latest/testing-guides/automated-performance-testing/) and [thresholds that fail the run](https://grafana.com/docs/k6/latest/using-k6/thresholds/).

The gate sequence and ERP examples above are this project's synthesis, not a claim
that these sources prescribe a universal folder structure or guarantee defect-free code.
