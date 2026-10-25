# Schemas: SQLAlchemy definitions and owned persistence

**Coordination owner:** Mirshoir. **Reviewer:** Ismail.

These are persistence models: columns, relationships, indexes, constraints and
defaults. Ismail's latest schema-first requirement also places insert/update/delete
operations in the owning schema domain. Business services in models/ decide what
is allowed, then call those persistence operations with the existing Session.
Pydantic input/update/output DTOs live in libs/dto/, not here. Current direct service
writes are migration debt; moving mapped definitions did not complete this boundary.

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
3. Keep workflow rules, permissions and the outer transaction owner in services.
   Put inserts, updates, deletes and mapped-field mutations behind explicit typed
   operations in the owning schema domain. These operations use the supplied
   Session and never commit independently, import services or routes, or obtain
   request dependencies. Reads may remain in services. DTO validation, service
   transition checks and database constraints/defaults remain distinct safeguards.
4. Register a new mapping in schemas/__init__.py and update all direct imports.
5. A source-only move must preserve metadata exactly. A real storage change needs
   an explicitly reviewed Alembic migration, compatibility and rollback plan.
6. Test real PostgreSQL constraints/migrations and the affected workflow, followed
   by the shared visual, stress and human-acceptance gates before release completion.

See [DTO conventions](../libs/dto/README.md), [service discipline](../models/README.md),
[source map](../../../docs/REFACTOR_MAP.md) and [team ownership](../../../docs/TEAM_OWNERSHIP.md).

## Incremental enforcement of the write boundary

Trace one business operation from route through service and every affected table,
including shared helpers, bulk/raw SQL, attribute assignments, audit and notifications.
Move its persistence mechanics behind schema-owned operations while preserving
one transaction, current values, lock order, error behavior and side effects. Do not
create a second mapped class, copy an entire business service into schemas, or add
generic CRUD machinery merely to satisfy directory names. Register and test any
new imports without changing metadata as an incidental refactor.

The reviewer tool `backend/scripts/audit_refactor_boundaries.py --root backend/app
--path models/<group> --schema-writes` flags obvious direct write calls and reports
transaction/SQL sites for manual review. It cannot prove mapped-attribute or indirect
write coverage. Its nonzero result is evidence of open migration work, not permission
to delete checks. Required behavior tests, PostgreSQL checks, actual browser vision,
readback and bounded stress precede AI_VERIFIED_AWAITING_HUMAN; human approval stays
separate. Do not label a whole table, service or area complete from a partial pass.
