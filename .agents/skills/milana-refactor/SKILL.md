---
name: milana-refactor
description: Plan and carry out approved Milana ERP monolith refactors using reversible service extraction, explicit contracts, and human acceptance.
---

# Milana refactor discipline

Keep the factory working while simplifying one business operation at a time.
Read the repository's AGENTS.md and the relevant folder's .readme.md. For scope,
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
Shavkat supplies business rules and operator acceptance; do not assign him technical
review, migrations or operations. An AI's own test result is not human approval.

## Read a small, complete context

Start with the task ID, current source commit, its route, service, DTO, ORM model,
direct callers and relevant tests. Search for imports, callers and writes before
moving code. Expand into adjacent workflows only when a dependency requires it.
Do not preload the entire repository or historical bug archive. Folder count and
line count are not quality goals; minimize unrelated context and hidden coupling.
Keep a short task record with approved decisions, exact revision, changed paths,
checks, rollback mechanism and next step so another session can resume accurately.

## Architecture contract

`HTTP router -> feature service -> SQLAlchemy models + Session -> PostgreSQL`

- Routers bind/validate HTTP inputs, obtain authenticated context/session, call the
  service and map results/errors to HTTP. No new business calculations or ORM writes.
- Services own business rules, object/factory authorization and coordinated CRUD.
  They accept the session/context explicitly. No service imports a router or calls
  an endpoint; cross-feature work uses an agreed operation, not a private helper.
- Reuse models/ for SQLAlchemy mappings and schemas/ for Pydantic Create, Update
  and Read/Out DTOs. DTOs do not execute queries. No parallel dto/ hierarchy.
- Enums preserve existing string values. Configurable roles/permissions/factories
  remain data. Enums do not implement RBAC or legal state transitions.
- One outer operation owns the transaction; helpers cannot commit part of it.
  Inspect SQLAlchemy autobegin and existing auth/session use before changing scope.
  Preserve locking, audit, retries, idempotency and external side-effect timing.
- Preserve public behavior while extracting. An existing bug/security correction
  is a separate named change; do not silently preserve it as approved behavior.
- Do not add repositories, service interfaces, tables, DTO duplicates or a framework
  migration without an actual requirement. Multitenancy is deferred.

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
