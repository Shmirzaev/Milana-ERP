# Verification after every runtime change

26 October 2026. Applies to each completed folder/operation migration, bug fix,
feature and database migration before it is marked ready or its old path removed.
Do not defer checks until the whole refactor ends. After the final edit, verify the
exact candidate again wherever the edit invalidated earlier evidence.

This is the team's required workflow, not a claim that CI enforcement is installed.

## 0. Study the old behavior and give the agent a verifiable task

Ismail's direct instruction is study -> move one business operation -> code tests
-> substantial visual checks on his computer -> persisted readback and bounded
stress -> AI verification -> human visual approval. Treat those as ordered gates.
Before editing, study all source and dependencies relevant to the operation:
route/service entry points, direct and alternate callers, DTOs/validators, ORM and
actual database shape/values, reads/writes, permissions, transaction boundaries,
side effects, UI and the next department. Include earlier working fixes and tests.
Record the baseline's actual results and existing defects separately; passing an
existing bug through parity does not make its behavior approved.

Provide every implementation/review agent a durable task packet containing:

- The user's scope, latest corrections and approval references; operation ID/name,
  owner/reviewer, actual model/session, exact worktree/base and allowed changed paths.
- A route -> service -> DTO -> table/column -> UI/caller map, including alternate
  entry points and the [table/field vocabulary ledger](../backend/app/libs/enums/README.md#table-by-table-audit).
- Acceptance examples with input, actor, expected output, stored effects/refusals
  and unaffected control workflow. Identify create/update/read differences, state
  subsets, defaults, missing/null, whitespace, money/quantity boundaries and retries.
- Exact runnable checks discovered in this checkout, required isolated PostgreSQL
  setup, browser/test URL and fixtures, bounded load limits and evidence locations.
  Do not invent a universal command or treat SQLite as a PostgreSQL check.
- The next single operation, its allowed implementation seam, rollback/cleanup
  condition, unresolved decisions and the human's later visual acceptance steps.

Keep one operation ledger: ID, action/callers, tables/fields/type candidates,
converted, retained-with-reason, unresolved/owner, source identity, evidence and
status. Give tables outside this operation a named pending row; do not silently
drop them from a promised full audit. Freeze one reviewable operation slice before
verification. Preserve already-written later changes separately instead of
including an unverified whole-domain patch. Parallel disjoint work is allowed;
serialize overlapping writers and recheck the integrated source.

At a new session, handoff or context compaction, reread the user's current scope,
AGENTS.md, this procedure and the task/operation ledger; inspect Git/source changes
and revalidate the claimed current gate. Preserve exact commands, evidence paths,
hashes, blocked checks and next action. An earlier assistant's "done" is not evidence.
Read the complete affected source in bounded slices; coverage records, not loading
the entire repository into one context window, establish what has been studied.

## 1. Make AI-generated tests capable of detecting mistakes

For the owner's schema-owned write target, trace the complete operation, including
root/shared helpers, mapped assignments, relationship/cascade writes, raw SQL,
audit, notifications and idempotency. Schema persistence helpers participate in
the same Session; business decisions and one outer transaction remain services.
Prove refusal leaves no partial effects and preserve audit hooks/lock ordering.
`backend/scripts/audit_refactor_boundaries.py` is a conservative static tripwire;
its strict failures identify remaining work. It does not prove alias/dataflow,
attribute mutation, ownership or runtime integrity, and must not be weakened to
make unfinished source pass. Its function-entry counts are not approved service
counts or reviewed business operations. Verify one complete operation before
repeating the pattern or claiming broad enum/type readiness.

Verify enum fields by their actual annotations and runtime/schema behavior, not
their default values or imported class count. Known fixed-vocabulary input/update/
output DTOs and genuine internal contracts must use the canonical Enum; str, Any
or Enum|str is not a completed conversion. Check defaults, normalization, action
subsets, serialization and all direct/alternate consumers. Actual enum typing may
deliberately change OpenAPI or validation errors: identify the precise change and
test approved intended behavior against independent expectations. Preserve baseline
characterization separately; do not assert universal API equality or weaken tests
without explaining the new contract. Configurable rows can still have a fixed
discriminator. Track all ERP domains with owners and unresolved items; a passing
pilot is not system-wide completion.

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
- Give the independent reviewer the direct requirements, diff and evidence, and
  ask for omissions, unauthorized changes and concrete failure cases. Verify its
  findings; a second model's agreement is not an executable check. Enum tests need
  independent expected values and per-operation allowed/forbidden cases; deriving
  every expected value from the new enum can conceal a missing or misspelled member.

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

For local PostgreSQL coverage, install the backend test dependencies and run
`python3 scripts/run_local_postgres_tests.py` from the repository root. The runner
requires a local Unix-socket Docker daemon. It starts a disposable PostgreSQL 16
container on a random loopback port, sets `STABILIZATION_POSTGRES_URL` for the
default backend suite and `S06_POSTGRES_URL` for the separately collected
`backend/tests/test_stock_adjustment_postgres.py`. It also sets
`FN04_TEST_PG_ADMIN_URL` to the container's `postgres` database so the invoice
race fixture can create and drop its own temporary database. It then removes the
container. The first two URLs point to its isolated `milana_test` database;
all three are loopback-only and cannot target a serving database. The child
processes also receive a local `DATABASE_URL` so an inherited application URL
cannot redirect their imports. Report the two test
results and any remaining skips separately.

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
- Exercise each affected business part substantially: default/create, edit or
  partial action, refusal/denied role, refresh/reopen and downstream handoff where
  applicable. Record a coverage row for every affected screen/action, with the
  reason for any not-applicable case. Check statuses, quantities, money, labels,
  field validation and available actions, not merely that the page loads.
- For browser automation, prefer role/label locators and assertions that wait for
  an observed condition over fixed sleeps. Retain a failure trace/network/console
  record where supported; use it to diagnose failures rather than retrying until green.
  Mock only external dependencies outside the claimed workflow; keep its UI,
  authorization, business operation and persistence real.
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

Advance an operation through explicit states:

| State | Evidence needed |
| --- | --- |
| STUDYING | Old-source/caller/table map and acceptance examples being completed. |
| IMPLEMENTING | Approved operation scope recorded; candidate work is not verified. |
| AI_CHECKS_RUNNING | Candidate frozen; required code, visual, database, stress and independent review gates are still running. |
| AI_VERIFIED_AWAITING_HUMAN | All required gates passed on the identified candidate; mandatory type/table/operation gaps are resolved, with any exclusions justified by recorded user-approved scope; human checklist supplied. |
| HUMAN_APPROVED | Named human technical review and actual human visual/business acceptance recorded for that candidate and scope. |
| NEEDS_REWORK / BLOCKED | A failure, unresolved decision or required unavailable check is recorded with its owner/next action; no ready/approved claim. |

Only the independent verification role records AI_VERIFIED_AWAITING_HUMAN after
checking the evidence. Record implementation and verifier model/session identities;
the label describes completed checks, not a model's certification or confidence.
A worker cannot approve itself or invent a human signature. Separate gate outcomes
(PASS/FAIL/BLOCKED/NOT APPLICABLE) from these workflow states.
Retain a separate overall status when one operation passes but the requested
table-by-table audit or another operation remains unfinished. The agent cannot
shrink the owner's scope or exempt a required check merely to obtain this label.

Use one short durable record in the task/bug evidence:

```text
Task / operation / state / direct-user scope and corrections:
Baseline / candidate commit or frozen patch+file hashes / runtime build / environment:
Engineer / reviewer / business acceptance owner:
Implementation model/session / independent verification model/session:
Expected behavior and unaffected control workflow:
Operation/caller coverage and table/field/type ledger (converted/retained/unresolved):
Automated: PASS | FAIL | BLOCKED; command, counts/skips, logs:
Test validity: old-fails/new-passes or refactor parity; fault challenge if relevant:
Visual E2E: PASS | FAIL | BLOCKED; roles, steps, viewed screenshots, readback:
Stress: PASS | FAIL | BLOCKED; scenario, limits, baseline/results, integrity/recovery:
Independent review findings / resolution / outstanding requirements:
Human checklist: URL/build, role, records, steps, expected results and evidence locations:
Human technical and visual/business acceptance: PENDING or name/date/candidate/scope/result:
Merge / deployment / production operator acceptance: separate recorded states:
Cleanup/rollback condition and remaining limitations:
```

Any required failed/blocked gate prevents calling the runtime change ready or
retiring its fallback. Fix and recheck; do not conceal retries or skipped checks.
Shavkat/operator acceptance and the engineer's technical evidence are still required
for production closure. AI visual approval is not the human's production approval.
After AI verification, hold that operation for the human to visually repeat the
checklist on the identified build, confirm saved results, and approve or reject it.
Record disagreement and return the operation to NEEDS_REWORK; rerun invalidated
gates after a fix. An AI pass, silence, elapsed time, a merge or an old approval
cannot substitute for this human check. Unrelated approved operations may continue
in isolation while this one waits. Human approval itself does not imply merge or
release authorization; production acceptance remains a distinct later record.
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
- [Anthropic: long-running agent harnesses](https://www.anthropic.com/research/effective-harnesses-for-long-running-agents): incremental work, durable progress/acceptance records and actual end-to-end checks address premature completion and lost context.
- [OpenAI: harness engineering](https://openai.com/index/harness-engineering/): keep the entrypoint a concise map to versioned guidance and evidence; documentation alone does not install enforcement.
- [Playwright: user-visible behavior, isolated tests and resilient assertions](https://playwright.dev/docs/best-practices).
- [Hypothesis: stateful actions and invariants](https://hypothesis.readthedocs.io/en/latest/stateful.html).
- [mutmut: mutation testing](https://mutmut.readthedocs.io/en/latest/); current tool requires fork support, so Windows use needs WSL or a suitable Linux environment.
- [Grafana k6: performance-test strategy](https://grafana.com/docs/k6/latest/testing-guides/automated-performance-testing/) and [thresholds that fail the run](https://grafana.com/docs/k6/latest/using-k6/thresholds/).

The gate sequence and ERP examples above are this project's synthesis, not a claim
that these sources prescribe a universal folder structure or guarantee defect-free code.
Research reviewed 26 October 2026. Ismail's ordered gates and human visual approval
are owner requirements; the sources inform their implementation. This Markdown
update does not install hooks, CI checks or a database audit tool, and does not
claim any current runtime candidate has passed these gates.

The boundary-audit script mentioned above is available in [PR #308 at this revision](https://github.com/Shmirzaev/Milana-ERP/blob/3cdd6808ff7ced0717f337d17d4e530719d4a86f/backend/scripts/audit_refactor_boundaries.py).
It is not installed by this documentation-only clone_main update. Check
tool availability explicitly; missing automation does not waive manual
writer tracing or permit a claim that the gate passed.
