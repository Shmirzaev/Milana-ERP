# Models: business services and working discipline

## Guidance publication and runtime scope

The 26 October guidance publication on `clone_main` at `b92ee8f` was
documentation-only; it did not integrate the runtime candidate in
[draft PR #308](https://github.com/Shmirzaev/Milana-ERP/pull/308). Later integration
candidates contain application changes that require their own exact-source evidence.
Historical results below belong to their named snapshots, not automatically to
this checkout, a new combined candidate or deployed production. Inspect current
code and the operation ledger before advancing a gate. Schema-owned writers,
system-wide enum/type adoption and human acceptance remain incomplete.

**Coordination owner:** Mirshoir. **Reviewer:** Ismail.

This is the business-service layer, following Pizza House's models/*.service.ts
convention. Its Python equivalents are *_service.py: business decisions,
authorization and workflow coordination. Writes run through schema-owned operations
with the supplied Session. There is no separate services/ folder. Follow the
[engineering workflow](../../../docs/ENGINEERING_WORKFLOW.md) for the layer contract.

The six Ismail groups below contain extracted service modules in the refactor
candidate: catalog, purchasing, sales, inventory, planning and finance. Schema-owned
writes and system-wide enum-typed contracts remain unfinished. Existing
shared helpers remain at this directory's root where their callers require them.
The other groups retain their guides for separately approved extractions.
Database definitions live in schemas/ and DTOs in libs/dto/. Current verification
and remaining acceptance are recorded in the plan; a source move is not a release.
Start with the relevant group below, then read only its affected code.
The complete source inventory is [the refactor map](../../../docs/REFACTOR_MAP.md).

| Business group | Directory | Engineer | Reviewer |
| --- | --- | --- | --- |
| [identity ](identity/README.md) | `identity/` | Dilmurod | Mirshoir |
| [catalog ](catalog/README.md) | `catalog/` | Ismail | Mirshoir |
| [purchasing ](purchasing/README.md) | `purchasing/` | Ismail | Mirshoir |
| [sales ](sales/README.md) | `sales/` | Ismail | Mirshoir |
| [inventory ](inventory/README.md) | `inventory/` | Ismail | Mirshoir |
| [planning ](planning/README.md) | `planning/` | Ismail | Mirshoir |
| [production ](production/README.md) | `production/` | Mirshoir | Ismail |
| [packaging ](packaging/README.md) | `packaging/` | Mirshoir | Ismail |
| [fulfillment ](fulfillment/README.md) | `fulfillment/` | Mirshoir | Ismail |
| [finance ](finance/README.md) | `finance/` | Ismail | Mirshoir |
| [people ](people/README.md) | `people/` | Dilmurod | Mirshoir |
| [work_management ](work_management/README.md) | `work_management/` | Dilmurod | Mirshoir |

Assignments include routes, contracts, persistence and tests for each feature.
See [team ownership](../../../docs/TEAM_OWNERSHIP.md) for shared-layer coordination.

## How to make a service file

1. Name the business operation and its owner. Use the group's guide to find existing
   implementations before adding a file. File names shown there are proposals, not
   a requirement to create every file or one class per table.
2. Write a short contract: input/actor, allowed behavior, output, known refusals,
   affected records, lock order, transaction owner and external side effects.
3. Use `snake_case_service.py` and explicit typed functions. Under Ismail's latest
   schema-first requirement, services call schema-owned persistence operations for
   inserts, updates and deletes; direct Session writes or mapped-field mutations
   in services are migration debt. Services retain business rules, authorization
   and workflow coordination. They accept a Session and actor/context, not
   FastAPI Depends, and never import HTTP handlers. Prefer a small explicit API.
4. Reuse the SQLAlchemy definitions in [schemas](../schemas/README.md) and the
   Pydantic contracts in [libs/dto](../libs/dto/README.md). Use [enums](../libs/enums/README.md)
   for fixed vocabulary and [types](../libs/types/README.md) only for a distinct
   internal contract. No generic repository tree is required.
5. The outer operation owns the transaction; participating helpers do not commit.
   Preserve existing SQLAlchemy autobegin behavior, row locks, audit/idempotency and
   side-effect timing. Do not blindly wrap an already-active Session in begin().
6. Services cannot import routes. Cross-group work uses agreed public operations.
   Keep dependency direction acyclic; put cross-group orchestration at the agreed
   use-case entry point rather than making two groups call each other's internals.
7. A pure move preserves behavior and public responses. Fixing a known defect or
   changing permissions is a separate identified change with explicit acceptance.

## Migration sequence

1. **Study.** Trace the router, every database read/write, business rule, permission,
   lock, commit, audit/notification and alternate caller. Capture actual and expected
   behavior; distinguish an existing defect from behavior to preserve.
2. **Agree.** Record the responsible service, operation contract, models/DTOs, scope,
   transaction owner and rollback/cleanup condition. Humans decide business policy
   and interfaces; AI implements the agreed task.
3. **Protect.** Run existing tests and add missing behavior/contract regressions.
   Include refusal paths, related workflows, retries and PostgreSQL locking where relevant.
4. **Extract.** Move one complete operation to its correct service. Keep storage,
   public values and permissions unchanged. An approved temporary selector defaults
   to the legacy implementation while the replacement is tested.
5. **Test technically.** Compare old/new behavior and database effects on independent,
   isolated fixtures. One request executes exactly one write path. Never compare by
   dual-writing or fall back to the old path after an uncertain failed write.
6. **Test visually.** In local/staging with isolated data, exercise the actual screen
   as the appropriate user: success, validation/refusal, affected handoff and readback.
   Check quantities/money/statuses, permissions, scanner/labels or device layout where
   relevant. Capture evidence; a screenshot alone is not proof of data correctness.
7. **Switch and verify.** Follow DEPLOYMENT.md for an authorized release, retain the
   previous compatible version, observe and obtain named human production acceptance.
   Production checks use read-only evidence or an operator's authorized real workflow.
   A code rollback does not undo incorrect database writes.
8. **Clean up.** Only after those gates pass, remove the retired route body, switch
   and unused imports. Retain behavior tests and deployment rollback capability.
   While both implementations exist, keep urgent fixes aligned or disable the candidate.

Apply the same cycle when introducing enums or refining DTOs/models. Do not combine
a service extraction with a table redesign, mass rename or new RBAC policy.

## Database definitions and import safety

SQLAlchemy definitions live in schemas/<business-group>/, with shared definitions
in schemas/core.py and schemas/order_reference.py. schemas/__init__.py registers
the mapped classes; models/__init__.py does not export ORM classes.

Import services from app.models.<name>_service and mapped classes from app.schemas
or their specific module. Never duplicate a mapped class or change table names to
match Python folders. Services use those classes for reads and call persistence
operations owned by the schema domain for writes, using the same existing Session.
The outer business operation owns the transaction; schema helpers must not commit
independently. This is the required target, not a claim that current services meet it.
Migrate one complete operation with all its writers, including audit/notification
participants; preserve atomicity, lock order, idempotency and refusal behavior.

Service-group directories remain guides until an operation's package conversion
is approved and all callers are updated. Their old ORM filename collisions have
been removed. This namespace move does not itself extract business logic from routes.
See [database rules](../schemas/README.md) and [ownership map](../../../docs/REFACTOR_MAP.md#existing-database-models).

## Shared helpers and queries

Keep existing audit, idempotency, numbering, email, image/print and barcode helpers
where they are until their own need is established. Reports normally stay with the
feature; dashboards/search/traceability compose read queries. They need no new table
or generic service hierarchy. `workflow_service.py` is mixed today: move stock and invoice
decisions to their owners, leaving only agreed orchestration rather than a new god service.

This is incremental, behavior-preserving refactoring. Temporary old/new implementations
behind one interface use [Branch by Abstraction](https://martinfowler.com/bliki/BranchByAbstraction.html).
Compatible interface expansion, caller migration and old-interface removal use
[Parallel Change (expand, migrate, contract)](https://martinfowler.com/bliki/ParallelChange.html).
Neither pattern requires microservices or a long-lived Git branch.

## Verification after each change

Follow [the shared verification gates](../../../docs/VERIFICATION.md) for every completed runtime migration,
bug fix and feature: validate AI-written tests, run relevant automated checks,
visually exercise actual end-to-end behavior, then challenge it with bounded
stress and verify data integrity/recovery. Record blocked checks honestly; they
do not count as passes. Documentation-only changes record runtime gates as not applicable.
