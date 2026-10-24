# Models: business services and working discipline

**Coordination owner:** Mirshoir. **Reviewer:** Ismail.

This is the business-service layer, following Pizza House's models/*.service.ts
convention. Its Python equivalents are *_service.py: business decisions,
authorized CRUD and workflow coordination. There is no separate services/ folder.

The existing service/helper implementations moved here as *_service.py with their
callers. All twelve group directories are documentation scaffolds; grouping their
implementations and extracting business logic from routers remain future work.
Database definitions now live in schemas/ and DTOs in libs/dto/.
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
3. Use `snake_case_service.py` and explicit typed functions. A service may call SQLAlchemy
   directly. It accepts a Session and actor/context; it does not obtain them from
   FastAPI Depends or import HTTP handlers. Prefer the smallest useful public API.
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
match Python folders. Services use those classes and the existing Session for CRUD.

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
