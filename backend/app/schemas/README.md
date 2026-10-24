# Schemas: target database schema-model folder

**Coordination owner:** Ismail for current DTO migration; Mirshoir for target database schema models. **Reviewer:** Mirshoir for DTO work; Ismail for Mirshoir's database work.
Retire DTO callers/shims before reusing the namespace. See [team ownership](../../../docs/TEAM_OWNERSHIP.md).

The twelve agreed business areas now have README-only schema folders, as requested.
They reserve destinations and explain ownership; they do not activate Python packages
or move database mappings. After the DTO namespace is vacated, migrate one approved
operation's definitions with one authoritative mapping per table and the existing Base.

| Business area | Schema guide | Engineer / reviewer |
| --- | --- | --- |
| Identity and access | [identity/](identity/README.md) | Dilmurod / Mirshoir |
| Catalog and partners | [catalog/](catalog/README.md) | Ismail / Mirshoir |
| Purchasing | [purchasing/](purchasing/README.md) | Ismail / Mirshoir |
| Sales | [sales/](sales/README.md) | Ismail / Mirshoir |
| Material inventory | [inventory/](inventory/README.md) | Ismail / Mirshoir |
| Planning and costing | [planning/](planning/README.md) | Ismail / Mirshoir |
| Production execution | [production/](production/README.md) | Mirshoir / Ismail |
| Packaging | [packaging/](packaging/README.md) | Mirshoir / Ismail |
| Warehouse and shipping | [fulfillment/](fulfillment/README.md) | Mirshoir / Ismail |
| Finance | [finance/](finance/README.md) | Ismail / Mirshoir |
| People, attendance and payroll | [people/](people/README.md) | Dilmurod / Mirshoir |
| Tasks and notifications | [work_management/](work_management/README.md) | Dilmurod / Mirshoir |

Shared AuditLog, SystemSetting, IdempotencyRecord and BusinessOrderAlias mappings
remain in their current files under Mirshoir's coordination. Do not duplicate them
across domains or invent a new business area for them.

Target responsibility: SQLAlchemy table definitions, columns, relationships,
constraints and defaults, equivalent to Meditech's schemas/Member.model.ts.
Today this directory still contains Pydantic DTOs; no DTO/ORM migration has begun.


This directory currently contains the application's DTO implementations. The owner
chose [libs/dto/<feature>/](../libs/dto/README.md) as their target location, matching
the mentor's explicit DTO organization. These DTO files have not moved yet.

For each approved operation, reuse and migrate the existing definition with its
callers. Preserve validation, aliases, defaults, optional/null semantics, response
filtering and inherited bases. A temporary compatibility import must re-export the
same class, not duplicate its definition. Remove it after callers migrate and the
operation passes technical, visual and human production acceptance.

Existing UserIn/UserUpdate/UserOut in catalog.py and payroll contracts are sources
to migrate, not a reason to write replacements from scratch. Move inline router
DTOs directly to their agreed libs/dto feature. Shared ORMModel, Page and validators
in common.py need their callers traced before relocation.

After ALL DTOs, callers and compatibility imports leave this namespace, migrate
only the existing SQLAlchemy definitions from [models/](../models/README.md) here.
Business services now use models/*_service.py and remain there; do not relocate
that whole folder or treat its service functions as database definitions.
Update imports, model registration and Alembic metadata discovery together. Reuse
the existing Base and table mappings; preserve names, constraints and defaults.
Do not add queries, workflow rules or transaction commits to schema definitions.
Verify imports, mapped tables and no database-schema diff, then test affected
workflows and follow the same visual/human-acceptance gates before cleanup.
Do not introduce ORM definitions here while legacy DTO imports still depend on it.
See [the DTO guide](../libs/dto/README.md) for input/update/output file conventions.
