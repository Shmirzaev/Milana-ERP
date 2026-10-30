# Catalog and partners: database schema models

**Engineer:** Ismail. **Reviewer:** Mirshoir. **Business acceptance:** Shavkat.

Garment models, colors, sizes, BOM, customers, suppliers and paid-process definitions.

SQLAlchemy definitions now live under app/schemas/; Pydantic DTOs live in
app/libs/dto/. The links below show the authoritative definitions for this group's
records. Business services live in models/*_service.py.

Brand creation uses `brand_persistence.insert_brand`; Brand update uses
`apply_brand_update` with the omitted/null-aware `BrandUpdateCommand`. Customer
and Supplier creation use `partners_persistence.insert_customer` and
`insert_supplier`. Customer update uses `apply_customer_update` with the
omitted/null-aware `CustomerUpdateCommand`. These helpers use the supplied Session and do not commit;
create helpers flush for audit IDs. Services retain validation/policy, audit,
outer commit and refresh. This source also uses `apply_supplier_update` with the
omitted/null-aware `SupplierUpdateCommand`; its verification is separate from the
dated integration checkpoint. The independent shipment customer creator and
seed/import writers remain separate paths. Customer DELETE uses `delete_customer_row`
on the supplied Session; the service retains lookup, refusal checks, audit and
outer commit. Candidate-specific verification remains pending. These helpers do not change the
existing duplicate-name race behavior.

## Authoritative definitions

- [Brand](catalog.py)
- [Collection](catalog.py)
- [Model](catalog.py)
- [Model paid-operation persistence](model_paid_operations_persistence.py)
- [Model CREATE persistence](model_persistence.py)
- [Model image upload persistence](model_image_persistence.py)
- [CollectionModel](catalog.py)
- [ModelImage](catalog.py)
- [ModelSize](catalog.py)
- [ModelColor](catalog.py)
- [ModelBOM](catalog.py)
- [PaidProcess](paid_process.py)
- [UslugaPaidProcess](paid_process.py)
- [Customer](partners.py)
- [Supplier](partners.py)

These links follow business ownership; some point to mixed files in another group
or shared core.py. Keep one authoritative mapping per table. Moving individual
classes out of mixed files is a separate approved change.

Model CREATE uses `model_persistence.insert_model` for the mapped row and
inherited approval assignments. The service keeps family selection/locking,
audit and the outer commit. Typed paid-operation rows serialize at this mapped
JSON persistence boundary; historical read rows are unchanged.

Model image upload uses `model_image_persistence.insert_uploaded_model_image`
for the primary-flag bulk update and new `ModelImage` row on the service's
worker-owned Session. The operation flushes for its ID and does not commit;
the service retains upload lifecycle, worker-session commit and audit. Both
multipart routes accept the nullable `ModelImageUploadType` form contract;
supported values still normalize case/whitespace and blank values remain null.
Unknown values now receive request validation HTTP 422 before upload work.
URL attachment retains its separate string-input/HTTP 400 validation edge,
and table-wide/historical image type storage remains string-valued.

## How to make a file here

1. Trace the approved business operation in [the service guide](../../models/catalog/README.md),
   its route, current model, DTO, database writes and other callers.
2. Reuse Pydantic contracts from `libs/dto/<feature>/`; never define DTOs here.
   Find existing mapped classes before adding a new persistence definition.
3. Use a descriptive `snake_case.py` file for related existing model definitions.
   Reuse the existing SQLAlchemy Base and classes; preserve table/column names,
   keys, indexes, relationships, constraints, defaults and serialized enum values.
4. Keep persistence definitions and persistence operations here. Create/update/read validation belongs
   in DTOs; permissions, status transitions, calculations, queries and
   write coordination belong in business services under `models/`. Actual
   inserts, updates, deletes and mapped mutations belong in schema-owned
   operations using the supplied Session; helpers never commit independently.
   Follow the [engineering workflow](../../../../docs/ENGINEERING_WORKFLOW.md).
   BOM insertion and the row deletion for the existing Catalog delete operation
   are focused examples in [bom_persistence.py](bom_persistence.py); the service
   keeps lookup, linked-cutting refusal, audit and the outer commit.
5. Update callers, model registration and Alembic discovery together. Require one
   mapping per table and no database-schema difference for a source-only move.
6. Check contracts and PostgreSQL behavior, visually exercise the affected factory
   workflow, then verify bounded stress/retries and adjacent department handoffs.
   Remove old paths only after the agreed acceptance and rollback conditions pass.

Only groups with actual definitions are Python packages. A guide without Python
files points to its existing definitions elsewhere; it is not a request to create
duplicate classes or empty implementation files.

See [schema migration rules](../README.md), [DTO conventions](../../libs/dto/README.md),
[the business plan](../../../../docs/REFACTOR_PLAN.md) and
[team ownership](../../../../docs/TEAM_OWNERSHIP.md).
