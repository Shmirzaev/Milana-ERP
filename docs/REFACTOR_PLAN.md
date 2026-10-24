# Milana refactor: team agreement and execution plan

24 October 2026. Documentation only; no implementation or deployment started.
clone_main is the shared production branch. Multitenancy remains deferred.
This replaces the earlier plan's branch-level definition of Done with human
production verification before a bug becomes Finished.

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
The user authorized scaffolding all twelve service groups with README guides.
See the [full source/model map](REFACTOR_MAP.md) and [service directory guide](../backend/app/services/README.md).
This approves the documentation folders, not every suggested file, interface or
ownership transfer. Agree each operation before implementation; do not split by
endpoint/table/line count merely to match a diagram.

## Mentor discipline translated to this stack

| Responsibility | Milana location | Rule |
| --- | --- | --- |
| Controller/router | backend/app/api/routes/ | HTTP input/context, service call, response/error mapping. |
| Service model | backend/app/services/ | Business decisions, authorized CRUD, one transaction owner. |
| Mongoose schema model equivalent | backend/app/schemas/ (target) | Migrate existing models/ mappings only after old schemas/ DTO imports retire. |
| Create / update / read contracts | backend/app/libs/dto/<feature>/ | Target for existing Pydantic DTOs; migrate from schemas/ with callers. |
| Fixed vocabulary | backend/app/libs/enums/ | Explicit serialized values; domain-owned definitions. |
| Internal shared contracts | backend/app/libs/types/ | Only when a real internal contract needs a type different from a DTO/model. |

The target is Router -> Service -> SQLAlchemy model + Session -> PostgreSQL.
Pydantic schemas validate data; they do not perform database writes. Services can
use the ORM directly. Reuse existing models/ definitions and migrate existing
schemas/ contracts into libs/dto/<feature>/; do not rewrite or duplicate them. This is not
a switch to database-first development; the mentor's Mongoose Schema is also
defined in code. No ORM replacement or generic repository layer is required.

The owner chose libs/dto/<feature>/, libs/enums/ and libs/types/, following
Meditech's explicit separation. Target schemas/ holds database schema models.
First move current schemas/ DTOs and all callers to libs/dto/, retire old DTO
compatibility imports and validate behavior. Then move existing models/ mappings
to schemas/ with imports, registration and Alembic metadata discovery. Preserve
one mapping per table and require no database-schema diff for this naming change.
Apply the technical/visual/human-acceptance gates to both phases; do not mix the
two meanings in the same namespace. Keep one authoritative DTO definition;
compatibility imports may re-export it temporarily. Do not turn configurable roles
into enums or move all assets into libs. Read the README.md in
each affected layer before editing it.

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

## What to inspect first, and proposed service homes

At source 5c45531d: sewing_bands.py calls production.post_sewing; sewing_corrections.py
and cutting_batch_delete.py import private production-router helpers;
package_workflows.py imports packages._package_lookup_candidates.
These are concrete extraction candidates, not proof that every related bug remains.

Propose one shared record_sewing_output operation first. Consider production/sewing.py,
production/cutting.py and packaging/ operations only as their responsibilities are
agreed. Review existing package_identity.py and legacy_package_identity.py before
adding another parser. Keep invoice/access work with its actual feature owner.
These are logical groups within the monolith, not separately deployed services.

services/production.py already exists beside the guide directory production/.
Do not add __init__.py there until a coordinated conversion preserves every supported
import and existing operation. A directory rename is not a business-logic refactor.

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
counting. Preserve independent Nastils and reachable unfinished quantities. A recent
second-Nastil fix claim still needs exact-path verification; do not presume failure.

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

Inspected source: 5c45531db350ba79e2e0167b942530a5b0f9bef8. Live production was
not accessed or freshly certified. Historical release records are unchanged.

## Verification after each change

Follow [the shared verification gates](VERIFICATION.md) for every completed runtime migration,
bug fix and feature: validate AI-written tests, run relevant automated checks,
visually exercise actual end-to-end behavior, then challenge it with bounded
stress and verify data integrity/recovery. Record blocked checks honestly; they
do not count as passes. Documentation-only changes record runtime gates as not applicable.
