# Team ownership and review

24 October 2026. The owner requested explicit allocation for all refactor folders
and new features. Service/DTO/database namespace separation is authorized;
planned business extractions remain subject to their operation agreements.

## Business folders

Each row has one accountable engineer and one default reviewer. That engineer owns
the complete feature: routes, service operations, DTOs, enums, database definitions,
related UI changes and tests. A folder owner is not permission to modify every mixed
legacy file; use the [source map](REFACTOR_MAP.md) to trace the particular operation.

| Service folder | Engineer | Reviewer | Responsibility |
| --- | --- | --- | --- |
| [models/identity](../backend/app/models/identity/README.md) | Dilmurod | Mirshoir | Authentication, accounts, RBAC and object/factory access. |
| [models/catalog](../backend/app/models/catalog/README.md) | Ismail | Mirshoir | Products, BOM, variants, partners and paid-operation definitions. |
| [models/purchasing](../backend/app/models/purchasing/README.md) | Ismail | Mirshoir | Requests, approvals, purchase orders and receiving coordination. |
| [models/sales](../backend/app/models/sales/README.md) | Ismail | Mirshoir | Sales orders, allowed edits, cancellation and ready-stock sales. |
| [models/inventory](../backend/app/models/inventory/README.md) | Ismail | Mirshoir | Material stock, movements, reservations, transfers, stocktake and waste. |
| [models/planning](../backend/app/models/planning/README.md) | Ismail | Mirshoir | Requirements, forecasts and costing; Mirshoir reviews production-plan policy. |
| [models/production](../backend/app/models/production/README.md) | Mirshoir | Ismail | Production orders, cutting, printing, sewing, bundles and stage handoffs. |
| [models/packaging](../backend/app/models/packaging/README.md) | Mirshoir | Ismail | Package contents, identities, allocations, corrections and labels. |
| [models/fulfillment](../backend/app/models/fulfillment/README.md) | Mirshoir | Ismail | Warehouse receipts, finished goods, shipments, returns and delivery. |
| [models/finance](../backend/app/models/finance/README.md) | Ismail | Mirshoir | Invoicing, payments, allocation and financial reports. |
| [models/people](../backend/app/models/people/README.md) | Dilmurod | Mirshoir | Employees, attendance and payroll; sensitive pay/locking changes reviewed by Mirshoir. |
| [models/work_management](../backend/app/models/work_management/README.md) | Dilmurod | Mirshoir | Tasks and notifications. |

## Shared layers and infrastructure

These are coordination owners for shared changes. Business definitions inside
these layers still belong to the relevant engineer above.

| Folder or part | Coordinator | Reviewer | Responsibility |
| --- | --- | --- | --- |
| backend/app/api/routes/ | Dilmurod | Mirshoir | Router composition and HTTP/error conventions; feature owner handles each endpoint. |
| backend/app/models/ | Mirshoir | Ismail | Group boundaries, public interfaces, dependency direction and cross-feature transactions. |
| backend/app/libs/dto/ | Ismail | Mirshoir | Input/update/output conventions and shared bases; review contract changes and caller compatibility. |
| backend/app/libs/enums/ | Ismail | Mirshoir | Fixed vocabulary conventions; Shavkat confirms business meaning. |
| backend/app/libs/types/ and libs/ | Ismail | Dilmurod | Shared internal contracts and library organization. |
| backend/app/schemas/; backend/app/db/; migration metadata | Mirshoir | Ismail | SQLAlchemy registration, transactions, database integrity and storage compatibility. |
| backend/app/core/ and shared service helpers | Dilmurod | Mirshoir | Shared auth, configuration and platform dependencies; business rules remain with feature owners. |
| backend/alembic/, backend/app/migrations/ and persistence-changing scripts | Mirshoir | Ismail | Review actual migration authority, compatibility, rollback and data effects. |
| tests/ and backend tests; .github/workflows/ | Dilmurod | Mirshoir | Shared fixtures, CI and architecture checks; each feature owner writes its regression tests. |
| deploy/, ops/, operational scripts and DEPLOYMENT.md | Dilmurod | Mirshoir | Release/recovery tooling; Mirshoir approves production releases. |
| connectors/ and shared frontend infrastructure | Dilmurod | Mirshoir | Integration contracts and shared UI infrastructure; coordinate domain rules with feature owners. |
| bugs/ | Ismail | Dilmurod | IDs, evidence and tracker organization; Shavkat verifies real business outcomes before closure. |
| Refactor/feature skills, AGENTS.md, CLAUDE.md and architecture guides | Mirshoir | Ismail | Maintain the agreed discipline; feature owners update their folder guidance. |

Shavkat owns business clarification, priority, acceptance examples and operator
verification for every group. He may prepare feature drafts with AI; he is not
assigned engineering review, database migrations or deployment operations.

## Working agreement

- Start each task with its business group, one engineer, reviewer, acceptance
  examples and affected paths. Cross-group work has one lead engineer; involve
  the other group's owner before changing its public contract or data.
- Mirshoir decides a new or unlisted responsibility. If he implements a change,
  Ismail reviews it; nobody approves their own engineering work.
- Shared route files such as production.py and catalog.py, and workflow_service.py have mixed
  responsibilities. Reserve the operation/files in the task record and serialize
  overlapping edits; do not assume separate folders remove current coupling.
- Use separate work directories, the shared clone_main integration line and one
  landing queue coordinated by Mirshoir. Reconcile urgent fixes before landing.
- Engineers verify technical behavior and the actual UI on isolated data. Shavkat
  records business/production acceptance with the operator; the technical owner
  verifies persisted effects and permissions. Closure follows bugs/finished_bugs.md.
- These named assignments are not GitHub CODEOWNERS enforcement or proof of review.
  No GitHub handles were guessed, review rules installed or teammates messaged.

See [the execution plan](REFACTOR_PLAN.md) and [shared skills](AGENT_SKILLS.md).

## Verification after each change

Follow [the shared verification gates](VERIFICATION.md) for every completed runtime migration,
bug fix and feature: validate AI-written tests, run relevant automated checks,
visually exercise actual end-to-end behavior, then challenge it with bounded
stress and verify data integrity/recovery. Record blocked checks honestly; they
do not count as passes. Documentation-only changes record runtime gates as not applicable.
