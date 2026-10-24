# Team ownership and review

24 October 2026. The owner requested explicit allocation for all refactor folders
and new features. This is the team assignment; it does not start implementation.

## Business folders

Each row has one accountable engineer and one default reviewer. That engineer owns
the complete feature: routes, service operations, DTOs, enums, database definitions,
related UI changes and tests. A folder owner is not permission to modify every mixed
legacy file; use the [source map](REFACTOR_MAP.md) to trace the particular operation.

| Service folder | Engineer | Reviewer | Responsibility |
| --- | --- | --- | --- |
| [services/identity](../backend/app/services/identity/README.md) | Dilmurod | Mirshoir | Authentication, accounts, RBAC and object/factory access. |
| [services/catalog](../backend/app/services/catalog/README.md) | Ismail | Mirshoir | Products, BOM, variants, partners and paid-operation definitions. |
| [services/purchasing](../backend/app/services/purchasing/README.md) | Ismail | Mirshoir | Requests, approvals, purchase orders and receiving coordination. |
| [services/sales](../backend/app/services/sales/README.md) | Ismail | Mirshoir | Sales orders, allowed edits, cancellation and ready-stock sales. |
| [services/inventory](../backend/app/services/inventory/README.md) | Ismail | Mirshoir | Material stock, movements, reservations, transfers, stocktake and waste. |
| [services/planning](../backend/app/services/planning/README.md) | Ismail | Mirshoir | Requirements, forecasts and costing; Mirshoir reviews production-plan policy. |
| [services/production](../backend/app/services/production/README.md) | Mirshoir | Ismail | Production orders, cutting, printing, sewing, bundles and stage handoffs. |
| [services/packaging](../backend/app/services/packaging/README.md) | Mirshoir | Ismail | Package contents, identities, allocations, corrections and labels. |
| [services/fulfillment](../backend/app/services/fulfillment/README.md) | Mirshoir | Ismail | Warehouse receipts, finished goods, shipments, returns and delivery. |
| [services/finance](../backend/app/services/finance/README.md) | Ismail | Mirshoir | Invoicing, payments, allocation and financial reports. |
| [services/people](../backend/app/services/people/README.md) | Dilmurod | Mirshoir | Employees, attendance and payroll; sensitive pay/locking changes reviewed by Mirshoir. |
| [services/work_management](../backend/app/services/work_management/README.md) | Dilmurod | Mirshoir | Tasks and notifications. |

## Shared layers and infrastructure

These are coordination owners for shared changes. Business definitions inside
these layers still belong to the relevant engineer above.

| Folder or part | Coordinator | Reviewer | Responsibility |
| --- | --- | --- | --- |
| backend/app/api/routes/ | Dilmurod | Mirshoir | Router composition and HTTP/error conventions; feature owner handles each endpoint. |
| backend/app/services/ | Mirshoir | Ismail | Group boundaries, public interfaces, dependency direction and cross-feature transactions. |
| backend/app/libs/dto/ | Ismail | Mirshoir | Input/update/output conventions and shared bases; coordinate current DTO namespace migration. |
| backend/app/libs/enums/ | Ismail | Mirshoir | Fixed vocabulary conventions; Shavkat confirms business meaning. |
| backend/app/libs/types/ and libs/ | Ismail | Dilmurod | Shared internal contracts and library organization. |
| Current models/, target schemas/; backend/app/db/; migration metadata | Mirshoir | Ismail | SQLAlchemy registration, transactions, database integrity and ordered model relocation. |
| Current schemas/ DTO migration | Ismail | Mirshoir | Move DTOs/callers and retire shims before Mirshoir reuses the namespace for database models. |
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
- Shared files such as production.py, catalog.py and workflow.py have mixed
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
