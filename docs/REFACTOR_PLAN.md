# Milana refactor: team agreement and execution plan

24 October 2026. The owner authorized moving services into models/, then completing
DTO separation into libs/dto/ and database definitions into schemas/ urgently. Business-logic extraction and production deployment
have not started through this task.
clone_main is the shared production branch. Multitenancy remains deferred.
This replaces the earlier plan's branch-level definition of Done with human
production verification before a bug becomes Finished.

## DTO/database separation: verification record

24 October 2026, source baseline 1dfd1c5: the owner requested urgent completion
before further feature work. Moved 22 Pydantic files to libs/dto/ first, validated
contracts, then moved 26 SQLAlchemy definition files and registration to schemas/.
Business services remain in models/. All direct callers, scripts, test patch
targets and Alembic discovery were updated. No storage migration was added.

- PASS: each phase's Python AST matches the intended namespace transformation;
  existing Base, frozen bootstrap and 149 migration revision files are unchanged.
- PASS: independent comparison of all 48 moved definition files finds identical
  non-import code, including fields, defaults, validators and helper bodies.
- PASS: both phases preserve the same 475-path OpenAPI and 97-table PostgreSQL
  DDL snapshot; all 88 business-service modules import successfully.
- PASS: Ruff and 46 real PostgreSQL tests covering fresh/existing migrations,
  ORM parity, later-Nastil Sewing and concurrent numbering on a disposable cluster.
- PASS: all 4,176 tests under backend/app/tests collect successfully. The two
  separate stock-adjustment PostgreSQL tests live under backend/tests; neither
  was removed. This is collection evidence, not full-suite execution.
- PASS: 177 focused workflow regressions covering authentication, access scope,
  numbering, invoicing, package writes, later-Nastil Sewing and packaging output.
  The earlier full-suite execution was interrupted; the completed run below
  supersedes that gap.
- PASS: the complete default backend suite on the same application source:
  `backend: python -m pytest -q app/tests` returned 3,868 passed, 308 skipped,
  11 warnings in 31m34s on 24 October 2026. Its conftest uses SQLite; skips are
  not PostgreSQL passes. The separate 46 real PostgreSQL checks above and two
  concurrent stock-adjustment tests cover their stated scopes only.
- PASS: MiniMax M3.1-Flash read-only reviews A1-A3 found no runtime break from
  the namespace move: 97 distinct mapped tables, 22 DTO modules with unchanged
  definitions, and no stale in-repository imports. B1 found that historical
  bugs.md paths could lead agents to the wrong layer; its path legend is corrected.
  Reports are retained in the Codex task workspace, outside this repository.
- PASS (local visual): disposable PostgreSQL was migrated to head and seeded;
  the real Next.js app and API were exercised in a browser. Admin created and
  updated a synthetic Sales user, then persisted readback confirmed the update.
  Sales could open Sales Orders; both UI and API denied Users and Sewing.
  Synthetic PO-0001 moved through Cutting, Sewing, partial Packaging, a later
  Nastil, receipt/assignment, resumed Sewing and Packaging. Browser screenshots
  first showed Sewing 256/256 complete and Packaging 248/256 with eight still
  ready; saving those final eight through the Packaging UI completed 256/256.
  Premature Packaging and premature Sewing completion were rejected; repeated
  receipt created no second assignment. PostgreSQL readback confirmed two
  batches, two Sewing records, one later assignment, three Packaging records,
  and final 256/256 piece totals.
- PASS (bounded local stress): 2 concurrent stock-adjustment PostgreSQL tests;
  100 authenticated order reads at up to 8 concurrent requests, 100 successful,
  p95 221 ms, no integrity change. Screenshots, test XML and stress logs are
  retained in the Codex task workspace, outside this repository.
- TRIAGE: the same synthetic extra-Nastil run showed negative polybag availability
  while the accessory plan said ready; see INV-LATER-NASTIL-20261024 in bugs.md.
  Business policy and cause need separate review. No namespace refactor code
  path was found to cause this existing workflow behavior.
- PENDING: remaining MiniMax guide reviews, named human technical/business
  review, required CI, and production activation. Local visual
  evidence does not establish production acceptance. Follow VERIFICATION.md and
  DEPLOYMENT.md before promoting an exact commit to production.

For a new feature, pull the latest clone_main before editing and use the current
layer guides. Existing unmerged work with old imports must be reconciled against
this move and tested; a shared branch does not automatically update another checkout.
The previous commit is the source rollback point. No database rollback is required
for this move because mapped storage is unchanged; application release rollback
still follows DEPLOYMENT.md and does not undo business data written afterward.

## Earlier service-folder move: verification record

24 October 2026, based on clone_main ec02b5f: 88 service modules relocated to
models/*_service.py; twelve business guides moved; services/ removed. Imports,
test patch targets and the permission scanner were updated. This is the owner's
requested namespace move, not business-logic extraction or a database migration.

- PASS: 884 Python files match the expected namespace/scanner transformation;
  all 27 original ORM Python files remain byte-identical.
- PASS: all 88 service modules import; 475 OpenAPI paths and 97 table definitions
  produce identical API/database contract snapshots before and after the move.
- PASS: Ruff; full backend collection of 4,178 tests; 177 focused regression tests;
  seven real PostgreSQL Sewing/numbering tests on a disposable database.
- NOT RUN: full backend execution and independent browser/visual E2E. Browser
  tools were unavailable in this session. Production activation/acceptance remains
  a separate release step; the source push does not claim those gates passed.

## Factory work this plan protects

Read this section for the business plan; [the source map](REFACTOR_MAP.md) links
each business area to its current files and proposed ownership.

| Work package | Operator outcome to preserve | Where the logic belongs | Engineer / reviewer |
| --- | --- | --- | --- |
| Sewing pilot (RF-005) | Normal and band operators record partial output and corrections consistently; later Nastils remain reachable; one Nastil's excess cannot complete another. | models/production: one output operation shared by routes/band callers; completion policy with one owner. | Mirshoir / Ismail |
| Cutting (RF-006) | Saving a passport, cutting a Nastil and receiving bundles preserve quantities, material usage and downstream readiness. | models/production cutting/passport operations; Inventory owns material balances. | Mirshoir / Ismail |
| Packaging (RF-007) | Packages consume the correct batch's available Sewing output; repeated scans do not create duplicate receipts or stock. | models/packaging operations; models/fulfillment owns warehouse receipt/dispatch. | Mirshoir / Ismail |
| Invoicing (RF-008) | Approved order/shipment flows issue the correct invoice without duplicate or premature financial effects. | models/finance issuance operation called through an agreed public contract. | Ismail / Mirshoir |
| User access (RF-009) | Allowed operators retain access; denied users cannot read/change another factory's records through an alternate endpoint. | models/identity access operation, enforced at the affected business service. | Dilmurod / Mirshoir |
| Enums and contracts (RF-011/012) | Existing forms, defaults, partial updates and responses continue working; fixed statuses have one definition. | libs/enums and libs/dto/<feature>; database mappings now live in schemas/<business-area>. | Ismail coordinates; feature engineer migrates callers; Mirshoir reviews shared conventions. |

Start with Sewing, prove its full handoff, then use the accepted approach for the
later work packages. The twelve folder groups are ownership destinations, not
twelve simultaneous migrations. Shavkat owns business meaning and acceptance.

For each package: study route/rules/DB talks -> record examples and contracts ->
extract one operation -> compare old/new on separate test data -> visually check
the real workflow and adjacent department -> bounded stress/integrity checks ->
reviewed switch -> human production acceptance -> remove the old implementation.
Only one implementation writes per request; never run both paths on factory data.

PR #304 merged into clone_main as ec02b5f on 24 October 2026. Before implementation,
refresh the baseline and retain its later-Nastil fixes and regression tests. This
service-folder relocation starts from clean clone_main baseline ec02b5f, preserving
those fixes. Its sewing_progress_service/workflow_service circular dependency is
a separate refactor item, not a
reason to undo Shavkat's accepted workflow or reopen a business decision.

## Read this first

Study one operation -> humans agree its service -> capture tests -> extract without
changing behavior -> test old/new separately -> test visually on isolated data ->
approve and switch -> verify in production -> remove the old path. Repeat for enums and DTO/model cleanup.

AI prepares and implements; humans decide business policy, service responsibilities,
interfaces and release acceptance. Folder guides and the shared skill preserve those
decisions across sessions. Passing tests and independent review still matter.

## Decisions already given and decisions still needed

Agreed: retain FastAPI/SQLAlchemy/PostgreSQL; thin routers; feature services; explicit
create/update/read contracts; enums for stable vocabulary; shared clone_main; short
agent instructions; bugs/bugs.md and bugs/finished_bugs.md; human production sign-off.

Before each operation, the team records its service name/responsibility, public
operation, transaction owner, permissions, compatibility promise and rollback choice.
The user authorized all twelve business-service and database-schema groups as
guides. Schema groups now contain the relocated definitions where files belong;
service groups remain guides for later extraction.
See the [full source/model map](REFACTOR_MAP.md) and [service directory guide](../backend/app/models/README.md).
Their move into models/ and the existing services' relocation as *_service.py are
authorized. Agree suggested new operations and ownership transfers before their
implementation; do not split by endpoint/table/line count merely to match a diagram.

## Mentor discipline translated to this stack

| Responsibility | Milana location | Rule |
| --- | --- | --- |
| Controller/router | backend/app/api/routes/ | HTTP input/context, service call, response/error mapping. |
| Service model | backend/app/models/ | Business decisions, authorized CRUD, one transaction owner. |
| Mongoose schema model equivalent | backend/app/schemas/ | SQLAlchemy definitions and registration; services perform CRUD with a Session. |
| Create / update / read contracts | backend/app/libs/dto/<feature>/ | Existing Pydantic inputs, allowed updates, outputs and action contracts. |
| Fixed vocabulary | backend/app/libs/enums/ | Explicit serialized values; domain-owned definitions. |
| Internal shared contracts | backend/app/libs/types/ | Only when a real internal contract needs a type different from a DTO/model. |

The target is Router -> models/*_service.py -> SQLAlchemy schema + Session -> PostgreSQL.
Pizza House calls its business-service folder models/; we use that name too.
There is one business-service layer. No separate services/ directory is needed.
SQLAlchemy mappings now live in schemas/ and Pydantic contracts in libs/dto/.
Services use the ORM directly; DTOs validate data and describe responses. The
mentor's Mongoose Schema is also defined in code: this is layer separation, not
a switch to database-first development or a new ORM/repository framework.

Namespace migration was ordered: move all existing DTO files/callers, compare
API/database contracts, then move ORM files/registration/Alembic imports. Business
services remain in models/. Existing definitions, table names and defaults are
preserved. Some legacy mapping files remain mixed; operation-level splitting is
separate work. No new enum values or RBAC policy were introduced by this move.
Do not turn configurable roles into enums. Read the affected layer's README.

DTO file convention: <entity>_input.py, <entity>_update.py and <entity>_output.py
(for example user_input.py). Import named classes from their full module path.
Existing combined files retain their names until a separately tested extraction.

## People and responsibilities

[TEAM_OWNERSHIP.md](TEAM_OWNERSHIP.md) assigns every service group and shared layer
to one engineer/coordinator and a named reviewer. Those allocations apply to new
features as well as refactoring. Use [the shared skills](AGENT_SKILLS.md) in this
repository; planning and release gates remain as described below.

| Person | Accountable work |
| --- | --- |
| Mirshoir | Technical lead; service/interface decisions; sensitive transactions and release approval; Sewing, Cutting, packaging and fulfillment. |
| Ismail (you) | Enum vocabulary and DTO/model conventions; stock/commercial features and API compatibility; related persistence changes with technical review. |
| Dilmurod | People/platform, RBAC infrastructure, CI/regression checks, rollback rehearsal and release tooling with Mirshoir's review. |
| Shavkat | Business rules, examples, priorities and operator acceptance. No technical review, database migration or operations ownership. |

Every code change has one engineer owner and another engineer reviewing it.
Ismail coordinates conventions across domains; each feature owner updates their
own callers/tests. Shavkat can request an urgent feature and use AI to prepare a
draft, but an engineer must review it before it enters the production release.
Existing tracker owner names are retained; no GitHub assignments were made.

## Sequence and deliverables

| Step / task | Owner | Deliverable before the next step |
| --- | --- | --- |
| 1. RF-001: establish baseline and map the pilot | Mirshoir | Confirm source and active release; identify route rules, every caller, writes, permissions, side effects and transaction. Propose service home/interface for team agreement. |
| 1. RF-002: business examples | Shavkat | Expected Sewing quantities, Nastil independence, corrections and department handoff. Engineers turn examples into checks. |
| 1. RF-003: reconcile relevant bug evidence | Ismail | Stable IDs, known fixed cases, unresolved reports and exact source. Historical Done does not become production approval. |
| 2. RF-004: verification foundation | Dilmurod | Baseline workflow/authorization/contract tests; planned dependency check; repair clone_main CI coverage in a separately approved tooling change. |
| 2. RF-013: prove recovery before cutover | Dilmurod; Mirshoir reviews | Rehearse application rollback on isolated infrastructure; identify signals, accountable operator and compatible old release. Specify/test any automatic rollback separately. |
| 3. RF-005: shared Sewing pilot | Mirshoir | Extract unchanged behavior into the agreed service, wire all approved callers through one selected path, demonstrate equivalent outcomes and human-approved rollout. |
| 4. RF-005 cleanup | Mirshoir | After acceptance/observation, remove retired route bodies and temporary selectors; keep contract/regression tests and retained release. |
| 5. RF-011: pilot enum vocabulary | Ismail | Inventory actual strings and consumers; get business meanings agreed; preserve values; prove validation/serialization and rollback compatibility. |
| 5. RF-012: pilot contracts and model discipline | Ismail | Reuse/refine create/update/read DTOs and ORM mappings; allow-list updates; preserve defaults, missing/null semantics, money and public responses. |
| 6. RF-006 then RF-007 | Mirshoir | Apply accepted process to Cutting reconciliation, then package lifecycle; coordinate edits to shared production files. |
| 6. RF-008 | Ismail | Invoice issuance: agreed shared rules and legitimate differences across callers. |
| 6. RF-009 | Dilmurod | One agreed user/access operation; preserve existing role/grant/deny/factory policy, with separate approval for policy fixes. |
| 7. RF-010 | Mirshoir | Review eliminated coupling/duplication, proven workflows and remaining exceptions; agree the next batch. |

RF-001/002/003 can be studied together. RF-004 follows agreed examples/baseline;
RF-013 must pass before RF-005 production cutover. RF-011/012 use the accepted
pilot interface; each has its own review and release evidence. The later three
feature streams start after pilot production acceptance. One active implementation
per engineer; one writer per shared operation. IDs are plan IDs, not created issues.
The [RF-001 source trace and proposed output interface](../backend/app/models/production/README.md#rf-001-sewing-output-seam-proposal-for-mirshoir)
are prepared for Mirshoir's decision; this is not RF-005 implementation approval.

### RF-003: Sewing pilot bug evidence prepared for Ismail

At source `e7e2ee5`, keep these separate when capturing the RF-005 baseline:

| Stable ID | Current evidence | Pilot implication |
| --- | --- | --- |
| [SEW-LATER-NASTIL-20261024](../bugs/bugs.md#sew-later-nastil-20261024--later-nastil-disappears-from-sewing) | The later-Nastil fix is deployed from `1fce86b5` in blue `20261024_093619`. Isolated MIL/BST/ECO, UI and PostgreSQL checks passed; the 38 historical statuses were separately reconciled. Named operator acceptance remains pending, so the bug stays active. | Retain exact-batch completion, reopening, assignment and audit behavior. Run `test_sewing_later_nastil_workflow.py` and `test_sewing_later_nastil_postgres.py` on the extraction candidate. Do not revert the deployed fix. |
| [INV-LATER-NASTIL-20261024](../bugs/bugs.md#inv-later-nastil-20261024--extra-nastil-can-leave-packaging-supply-negative) | A local extra-Nastil run exposed negative polybag availability while the plan said ready. No production occurrence or causal link to the namespace move is established. | Keep this inventory/packaging defect out of a behavior-preserving Sewing move. Shavkat must confirm the intended material rule; Inventory and Packaging owners review the accounting before a separate fix. |
| [WF12](../bugs/bugs.md) | The October 6 audit flags inconsistent parent/child lock order between daily reports and Sewing writes. Its historical `Present` label has not been freshly reverified at this source. | Trace both lock sequences before changing transaction boundaries; run `test_sewing_daily_report_lock_order.py`. Do not claim this risk fixed by relocating code. |

The historical October 6 tracker rows are leads, not current production verdicts.
This prepares RF-003 for Ismail's review; it does not close the bug, approve a
new business rule, or complete Mirshoir's RF-001 trace and RF-005 pilot.

## What to inspect first, and proposed service homes

At source 5c45531d: sewing_bands.py calls production.post_sewing; sewing_corrections.py
and cutting_batch_delete.py import private production-router helpers;
package_workflows.py imports packages._package_lookup_candidates.
These are concrete extraction candidates, not proof that every related bug remains.

Propose one shared record_sewing_output operation first. Consider models/production/sewing_service.py,
models/production/cutting_service.py and models/packaging/ operations only as their responsibilities are
agreed. Review existing package_identity_service.py and legacy_package_identity_service.py before
adding another parser. Keep invoice/access work with its actual feature owner.
These are logical groups within the monolith, not separately deployed services.

Production mappings are in schemas/production/production.py. Existing operations
live in models/production_service.py. models/production/ remains a guide until
approved extraction moves an operation there with all its callers.
The directory relocation does not extract the remaining business logic from routes.

## How each extraction works

1. Record route -> rule -> tables/writes -> caller -> test. Include status codes,
   response shape, pagination, defaults, auth and audit/idempotency behavior.
2. Confirm the smallest service interface with the humans. First test approved
   outcomes; record unexpected current behavior as a bug rather than blessing it.
3. Extract the logic with no storage/permission/behavior redesign in that change.
   A temporary server-controlled selector may keep the legacy path active while
   the service is tested. Its use/location and exact removal condition need agreement.
4. Compare independent old/new fixture runs, including database state and side
   effects. Use real isolated PostgreSQL for locks/constraints/concurrency. Staging
   that shares production storage is not a place for write comparisons. Then test
   the actual UI with the relevant user roles and check the affected department
   handoff and database readback; record visual and technical evidence.
5. Each request selects exactly one path before any write. Never run both write
   paths, shadow writes in production, or catch an error and retry the old path.
   Preserve shared idempotency semantics across switching and rollback.
6. After reviewed tests, deploy the immutable candidate into the inactive slot;
   follow DEPLOYMENT.md. Humans authorize cutover and accept the demonstrated result.
   Verify production through read-only evidence or an operator's authorized real
   workflow; do not invent stock, payroll or orders as live test fixtures.
7. After the observation window and production acceptance, remove legacy bodies,
   temporary switch and obsolete imports in a separate cleanup. Keep the previous
   compatible release for rollback. Track cleanup owner and deadline at approval.

If Shavkat's urgent feature changes the same operation, pause that extraction,
review/land the urgent change, update both temporary paths or disable the candidate,
then rerun affected checks on the combined source. Never deploy an old candidate
that silently removes a newer factory fix.

Preserve the known Sewing case: 600 received allows 495 then 105 without double
counting. Preserve independent Nastils and reachable unfinished quantities. The
deployed later-Nastil fix has exact-path checks; rerun them on the extraction
candidate, including the real UI and its persisted effects.

## Rollback and frequent deployment

The inspected source already has blue/green slots and an explicit manual rollback
procedure. It does NOT establish automatic recovery from arbitrary bugs:

- scripts/observe_release.py records probe failures and exits; it never switches slots.
- deploy/slotctl.py generates one active HAProxy server. activate() changes routing,
  then checks stable health; it has no compensating restore on a failed post-switch
  check. Actual routing/state must be reconciled after such a failure.
- .github/workflows/ci.yml push triggers include main and codex/**, not clone_main.
  PR/manual triggers also exist. A direct clone_main push must not be assumed tested.

RF-013 should rehearse both roles, partial activation failure and failure recovery;
verify that new writes remain readable by the previous application. Automatic
rollback, if chosen, needs explicit failure thresholds, a compatible healthy target,
a bounded attempt, evidence and escalation on failure; prevent switch-back loops.
Health checks cannot recognize every wrong quantity or business decision. Human
business checks remain necessary. No automation is implemented by this plan.

Application rollback preserves the current database; it cannot reverse incorrect
stock/payroll writes. Do not restore an old backup over new factory work as routine
rollback. Data repair is a separate reviewed operation. For this first refactor,
keep tables/columns/stored enum values unchanged. Any later storage migration needs
old/new compatibility, backup, isolated rehearsal and its own approval.

Frequent small deployments can be good practice. Unreviewed changes and unreliable
recovery are the problem. Keep urgent delivery possible with the same tests, review
and release identity, and a named available operator for the observation window.

## One shared branch without concurrent overwrites

Respect the current team choice: clone_main is the shared integration/release line;
no long-lived refactor branch. Each engineer/agent needs a separate working directory.
If all work directly on clone_main, serialize landing with one integration owner:
claim operation/files -> update from remote -> implement/review/test -> re-fetch ->
reconcile and test the combined revision -> fast-forward push -> release exact SHA.
Never force-push or allow agents to edit a shared checkout simultaneously. Coordinate
schema migrations and central auth/production files explicitly.

Short-lived task branches merged frequently are a recommended alternative if the
team later accepts them. Branches are not the source of conflicts: overlapping edits
and stale assumptions are. Single-branch work still needs reconciliation and review.
The owner authorized publishing this documentation to clone_main after local
validation. Publication of this plan does not deploy application changes. A branch
head is not proof of what is running live.

## Bug tracking and short task records

[bugs/bugs.md](../bugs/bugs.md) contains open work and items awaiting verification.
[bugs/finished_bugs.md](../bugs/finished_bugs.md) receives the same ID only after
recorded human production acceptance. Owner is a field; no per-person bug folders.
Historical rows remain intact and explicitly historical until reconciled.

Use: Open -> In progress -> Review -> Awaiting production verification -> Finished.
Blocked is an explicit status/reason. For refactors, track cleanup separately so
accepting the new behavior does not hide unfinished removal work.

Keep a short task card: ID; owner/reviewer; problem and expected example; source SHA;
approved service/interface and touched files; tests/results; rollback method;
status/next step; fix SHA/release; named human verification/date/evidence.
No automatic closing from merge, an AI completion claim or an old Done label.

## How every agent follows the same discipline

- Codex: use $milana-refactor from this repository. Canonical skill:
  [.agents/skills/milana-refactor/SKILL.md](../.agents/skills/milana-refactor/SKILL.md).
- Claude Code: use /milana-refactor; its small entry points to the same file.
- AGENTS.md and CLAUDE.md direct agents to the shared rules. Folder README.md
  files explain local responsibilities. Teammates receive these repository-local
  skills by pulling the published commit and running their agent in that checkout.
  No personal agent settings are changed on teammates' machines.
- Load relevant code and guides on demand. No folder-count or 40% deletion quota.
  Remove actual duplication; retain business rules, tests and useful constraints.
- RF-004 adds enforceable checks later: no new service-to-router imports, pilot
  routers without business writes, unchanged API contracts and workflow/RBAC tests.
  Baseline legacy exceptions explicitly. Required CI and independent review enforce
  rules; Markdown alone is guidance, not a guarantee.

## Research behind these choices

- [Fowler: Branch by Abstraction](https://martinfowler.com/bliki/BranchByAbstraction.html): keep delivery possible while replacing an implementation behind an interface.
- [DORA: trunk-based development](https://dora.dev/capabilities/trunk-based-development/): small changes, frequent integration and automated checks; frequent delivery is not inherently a fault.
- [AWS: rollback safety](https://aws.amazon.com/builders-library/ensuring-rollback-safety-during-deployments/): rehearse backward compatibility, including data written by the new version.
- [FastAPI: partial updates](https://fastapi.tiangolo.com/tutorial/body-updates/): use exclude_unset for partial input; define null and field permissions separately.
- [SQLAlchemy: Session basics](https://docs.sqlalchemy.org/en/20/orm/session_basics.html): explicit Session/transaction lifecycle around coordinated ORM work.
- [OpenAI: skills](https://learn.chatgpt.com/docs/build-skills): repository-local skills and loading detailed instructions only when needed.
- [Claude Code: skills](https://code.claude.com/docs/en/skills): project skill discovery and supported invocation.
- [Anthropic: context engineering](https://www.anthropic.com/research/effective-context-engineering-for-ai-agents): selective, relevant context rather than loading everything.
- [GitLab: engineering workflow](https://handbook.gitlab.com/handbook/engineering/workflow/#updating-workflow-labels-throughout-development): distinguish implementation, review, verification and completion.

Historical source for the initial findings: 5c45531db350ba79e2e0167b942530a5b0f9bef8.
The service-folder relocation uses ec02b5f, including merged PR #304. Live production
was not accessed or freshly certified by this change.

## Verification after each change

Follow [the shared verification gates](VERIFICATION.md) for every completed runtime migration,
bug fix and feature: validate AI-written tests, run relevant automated checks,
visually exercise actual end-to-end behavior, then challenge it with bounded
stress and verify data integrity/recovery. Record blocked checks honestly; they
do not count as passes. Documentation-only changes record runtime gates as not applicable.
