# Schemas: SQLAlchemy database definitions

**Coordination owner:** Mirshoir. **Reviewer:** Ismail.

These are persistence models: columns, relationships, indexes, constraints and
defaults. Business services in models/ use them with a Session to read/write.
Pydantic input/update/output DTOs live in libs/dto/, not here.

The 26 existing definition files were moved with callers and registration, without
changing mapped fields or tables. schemas/__init__.py registers all mapped classes
for application startup, scripts and Alembic. Keep the existing app.db.base.Base.

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

Shared definitions remain in core.py and order_reference.py. Some legacy files
span groups: sales/sales.py also contains invoices and shipments;
production/production.py and production/tracking.py include downstream records.
The linked group guides describe business ownership and point to the actual file.
Do not duplicate or split these classes just to populate every folder. identity/
and finance/ remain guides because their definitions still share those files.

## How to make or change a definition

1. Trace the existing table and every writer; agree the feature owner and fields.
2. Reuse its mapped class and existing Base. Use a descriptive snake_case.py file.
3. Keep workflow rules, queries, permissions and transaction commits in services.
   Create/update/read validation belongs in DTOs; database defaults are distinct.
4. Register a new mapping in schemas/__init__.py and update all direct imports.
5. A source-only move must preserve metadata exactly. A real storage change needs
   an explicitly reviewed Alembic migration, compatibility and rollback plan.
6. Test real PostgreSQL constraints/migrations and the affected workflow, followed
   by the shared visual, stress and human-acceptance gates before release completion.

See [DTO conventions](../libs/dto/README.md), [service discipline](../models/README.md),
[source map](../../../docs/REFACTOR_MAP.md) and [team ownership](../../../docs/TEAM_OWNERSHIP.md).
