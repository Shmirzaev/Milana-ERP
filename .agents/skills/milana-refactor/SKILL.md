---
name: milana-refactor
description: Plan and carry out approved Milana ERP monolith refactors using reversible service extraction, explicit contracts, and human acceptance.
---

# Milana refactor discipline

Keep the factory working while simplifying one business operation at a time.
Read the repository's AGENTS.md and the relevant folder's README.md. For scope,
ownership and sequence, read the relevant sections of [the team plan](../../../docs/REFACTOR_PLAN.md).
Read DEPLOYMENT.md only for release preparation or deployment work. Follow its
actual gates; this skill grants no deployment, push, migration or data-repair authority.

## Human decisions and agent execution

Humans decide business behavior, service responsibilities/count, public interfaces,
permission changes, database changes and production cutover. AI studies, proposes,
implements approved work, runs checks and reports evidence. Reuse recorded approval;
do not ask again for ordinary implementation details inside the approved scope.
If a design choice is unresolved, prepare the smallest concrete proposal for that
choice and continue independent authorized work. Do not implement the unresolved part.
Planning requests produce documentation, not application changes.

Mirshoir owns sensitive architecture/transactions and production workflows.
Ismail owns stock/commercial work and coordinates enums and DTO conventions.
Dilmurod owns people/platform and verification infrastructure. Every code change
has one engineer owner and another engineer reviewing it, including Mirshoir's.
Exact group/layer owners and reviewers are recorded in [team ownership](../../../docs/TEAM_OWNERSHIP.md).
For new behavior, also use [milana-feature](../milana-feature/SKILL.md); keep the
behavior change distinct from extraction.
Shavkat supplies business rules and operator acceptance; do not assign him technical
review, migrations or operations. An AI's own test result is not human approval.

For folder purpose and how to write files, use [the backend guide](../../../backend/app/README.md).
Use [the source/model map](../../../docs/REFACTOR_MAP.md) to locate a group; load only
the needed section. The six Ismail groups contain implemented candidate services;
other group guides retain proposals. A proposed name alone is not implementation
approval; the current owner-authorized batch covers all six Ismail groups.

## Study the complete affected old behavior

Start with the task ID, current source commit, its route, service, DTO, ORM model,
direct callers and relevant tests. Search for imports, callers and writes before
moving code. Include alternate entry points, database defaults/constraints and
stored vocabularies, permissions, side effects, UI and department handoffs. Study
the actual old behavior before selecting the seam; include recent working fixes.
Read source in bounded slices and record coverage rather than preloading the
entire repository or historical bug archive. Folder count and
line count are not quality goals; minimize unrelated context and hidden coupling.
Use the [task packet and operation ledger](../../../docs/VERIFICATION.md#0-study-the-old-behavior-and-give-the-agent-a-verifiable-task):
direct user scope/corrections, decisions, exact source, changed paths, converted/
retained/unresolved types, checks, rollback and next action. At handoff or context
compaction, reread that record and the current rules; do not inherit a "done" claim.

Ismail requires one business operation at a time: study -> approved move -> code
checks -> real visual/browser checks -> database readback and bounded stress ->
independent AI verification -> human visual approval. Freeze an operation-sized
patch/candidate and pass its gates before marking it AI-verified or moving that
worker to the next implementation step. Preserve already-mixed later changes in
separate slices. Parallel work is permitted only on isolated disjoint operations;
overlapping files/operations have one writer and require combined verification.

## Architecture contract

`HTTP router -> models/<group>/*_service.py -> schema-owned persistence + supplied Session -> PostgreSQL`

26 October 2026: the owner's explicit target puts write/update/delete mechanics in
schema-model operations. The namespace move is complete, but this write boundary
is not. Services retain business decisions, permissions, calculations and the outer
transaction. Use focused persistence functions in the existing schema domain or
methods on its mapped class; do not duplicate mappings or add a generic repository.
Include mapped field/relationship mutation and shared audit/notification/idempotency
writes in the same operation. Helpers use the supplied Session without hidden commits,
new transactions, business-policy changes or service/route imports. Preserve locks,
flush timing, audit-chain hooks and rollback; shared persistence has one writer.
Complete the first operation's gates before mass enum/type adoption. A shared enum
must serve its real schema/contract/service consumers; six workers do not prove
system-wide coverage or full mentor alignment.

- Routers bind/validate HTTP inputs, obtain authenticated context/session, call the
  service and map results/errors to HTTP. No new business calculations or ORM writes.
- Business services live in models/<group>/*_service.py, following Pizza House's service
  layer under models/. Do not recreate a parallel services/ folder.
  Services own business rules, object/factory authorization and coordinated CRUD.
  They accept the session/context explicitly. No service imports a router or calls
  an endpoint; cross-feature work uses an agreed operation, not a private helper.
- schemas/<business-group>/ holds SQLAlchemy database definitions; libs/dto/<group>/
  holds Pydantic input, update and output contracts. Their namespace separation is
  implemented. models/ contains services only; do not recreate the former locations.
  schemas/__init__.py registers ORM classes for application startup and Alembic.
  Keep the existing Base, one mapping per table, field/default/constraint semantics
  and public DTO contracts. Pure source moves require no database-schema diff.
  Some mapped files still span business groups; consult the map before splitting.
  Place new domain operations in their existing business group. Reuse shared
  legacy helpers at models/ root rather than duplicating them or adding forwarders.
- DTO filenames include their entity: user_input.py, user_update.py, user_output.py.
  Use explicit class imports, e.g. from app.libs.dto.user.user_input import UserIn.
  Retain existing mixed DTO files until an approved extraction updates every caller.
- Shared definitions live in libs/enums/ and libs/types/, as chosen by the owner.
  Keep API DTOs in libs/dto/; libs contains no services or persistence operations.
- Enums preserve existing string values. Configurable roles/permissions/factories
  remain data. Enums do not implement RBAC or legal state transitions.
- Audit the assigned database [table by table and field by field](../../../backend/app/libs/enums/README.md#table-by-table-audit),
  reconciling schema, actual authorized snapshot values, writers, readers, DTOs
  and UI. Account for every type candidate as converted, retained with a reason,
  or unresolved with an owner. Reconcile newly discovered fixed values before
  closing the operation. An enum file or a generic lifecycle set is not proof
  that every caller or action-specific subset has been migrated correctly.
- One outer operation owns the transaction; helpers cannot commit part of it.
  Inspect SQLAlchemy autobegin and existing auth/session use before changing scope.
  Preserve locking, audit, retries, idempotency and external side-effect timing.
- Preserve public behavior while extracting. An existing bug/security correction
  is a separate named change; do not silently preserve it as approved behavior.
- Do not add repositories, service interfaces, tables, DTO duplicates or a framework
  migration without an actual requirement. Multitenancy is deferred.

## Required verification for every completed change

Follow [the verification gates](../../../docs/VERIFICATION.md) after every completed
folder/operation migration, bug fix or feature, on the exact candidate revision.
Prove test validity (bug red/green, refactor parity, targeted fault challenges for
critical rules); run relevant real PostgreSQL checks and report required skips.
Then exercise the real UI end to end and actually inspect rendered screenshots
with vision, verify persisted effects and adjacent workflows, and run a bounded
relevant stress scenario with recorded limits, integrity and recovery checks.
Use isolated test data/infrastructure. Missing browser access or a required test
environment is BLOCKED, never PASS. Repeat invalidated checks after further edits;
no cleanup/readiness claim before required gates pass. Human production acceptance
remains separate. Documentation-only work records runtime gates as NOT APPLICABLE.
Use **AI_VERIFIED_AWAITING_HUMAN** only after the independent verification role
has checked all required evidence on the exact candidate. Give the human a local
visual checklist with roles, records, steps and expected saved results. Wait for
their recorded technical and visual/business approval of that candidate; do not
translate an AI pass into human approval, merge/deployment authority or permission
to retire the old path. Follow [the state/evidence rules](../../../docs/VERIFICATION.md#5-record-evidence-and-completion).

## Study -> extract -> prove -> switch -> retire

1. Trace one operation, including alternate callers, CRUD, permissions, transaction
   boundary and department handoff. Separate confirmed defects from design debt.
2. Propose its service home and interface, reuse existing code, and record the human
   decision before creating new service responsibilities. Do not split by line count.
3. Capture current contracts and approved outcomes in meaningful tests. Use isolated
   PostgreSQL for database constraints/locking; do not test writes on production.
4. Extract the approved operation with minimal behavior changes. When a temporary
   switch is approved, default to the legacy path; keep new behavior behind the
   agreed operation interface. Document owner, selection scope and removal condition.
5. Compare old/new results AND database changes on independent fixtures. Verify
   authorization failures, retries, partial quantities, concurrency and handoffs.
   Then exercise the actual UI on isolated local/staging data with allowed/denied
   roles and affected department handoffs. Capture outcomes and readback, not only
   screenshots. Visual checks supplement technical tests; they do not replace them.
6. Select exactly ONE implementation per request, before writes. Never dual-write,
   replay live writes for comparison, or automatically retry the legacy path after
   the new path fails: the first attempt may already have committed or sent effects.
7. Production cutover follows the approved release procedure with the previous
   compatible release retained. A release switch does not undo data already written.
   Do not claim automatic rollback exists unless its actual mechanism is verified.
8. Retire legacy bodies/switches after human production acceptance and the observation
   window; remove obsolete imports/tests for retired internals, retain behavior tests.
   While both paths exist, port urgent fixes to both or disable the candidate; recheck
   parity. Temporary duplication needs a named cleanup task, not indefinite maintenance.

Apply enums/DTO/model cleanup to the accepted operation in a separate reviewed
change using the same prove/switch/accept discipline. Preserve omitted-vs-null update
behavior, allowed fields, defaults, enum serialization and response shapes. Pure
source cleanup should not require a database migration. Any necessary storage change
needs its own compatibility/backfill/rollback plan and approval.
Keep creation and lifecycle vocabularies distinct: a user/order may have states
that are not permitted creation inputs. Record whether a change centralizes values,
adds a DTO/internal type, or deliberately changes validation. Do not silently narrow
free-form inputs or widen an action's accepted subset by using the full enum.

## Shared branch and completion

clone_main is the shared production/integration branch. Respect the user's single-
branch policy: separate working directories, one landing queue, no concurrent writers
to the same checkout or overlapping operation. Fetch/reconcile before landing, run
checks on the exact combined revision, and never force-push or overwrite a colleague.
Short-lived task branches are a recommendation only if the team accepts them; no
long-lived refactor branch. An urgent fix invalidates a stale candidate's evidence.
Production deploys an exact reviewed commit, not a moving branch name.

Update [active bugs](../../../bugs/bugs.md) with evidence. Move the same ID to
[finished bugs](../../../bugs/finished_bugs.md) only after recorded human production
verification. Retain history; reopen the same ID on regression. A passing build,
merged commit, AI message or old Done label does not establish that acceptance.

At handoff: outcome, changed paths, actual checks/skips, unresolved human decisions,
source/worktree/branch, and push/merge/deployment state. Keep the user summary short.
Rules in Markdown guide agents; automated checks and human review enforce them.
Do not claim proposed CI checks are already installed.
