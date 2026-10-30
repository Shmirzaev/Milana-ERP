# Catalog and partners

Collection creation's typed status, persistence boundary and retained legacy
contracts are recorded in [COLLECTION_CREATE_CONTRACT.md](../../../../docs/COLLECTION_CREATE_CONTRACT.md).

Candidate BOM PATCH contract: `ModelBOMUpdate.material_role` and the used normalized partial-write type carry `BomMaterialRole | None`. The service preserves omitted fields, existing domain checks and legacy read projection, then calls the Catalog schema persistence helper for assignments on the same row and Session. The helper adds no flush or commit; the existing service owns audit and commit. Padded/case-varied supported roles normalize, while unsupported nonempty roles and blank roles are deliberately rejected by DTO validation with HTTP 422. Historical stored roles remain readable and are not rewritten by unrelated scalar edits. Renewed combined PG/browser checks remain pending; this is not completion of all Catalog operations.

Business-service group guide, relocated into models/ on 24 October 2026. The
approved product/model extraction now lives here as the service modules below;
the remaining proposed files describe later approved operation extractions.

**Purpose:** Own product/model definitions, BOM, variants and customer/supplier reference data. This group does not own user accounts or customer payments.

**Engineering owner:** Ismail. **Reviewer:** Mirshoir.
**Business acceptance:** Shavkat with operators.
This owner covers the feature's routes, DTOs, enums, database definitions and tests.
See [team ownership](../../../../docs/TEAM_OWNERSHIP.md) for shared-layer coordination.

## Implemented services

| File | Responsibility |
| --- | --- |
| [models_service.py](models_service.py) | Product models: list/options/details/families, approval, create/update/clone, variants, BOM, images and uploads, sizes and colours, guarded deletion, and the process-QR size setup. Also holds `_model_payload`, the usluga model preview payload. |
| [collections_service.py](collections_service.py) | Brand and collection reference data, collection seasons and collection-to-model membership. |
| [partners_service.py](partners_service.py) | Customer and supplier reference CRUD and their deletion guards. |
| [paid_processes_service.py](paid_processes_service.py) | Paid-operation definitions for the standard and usluga catalogues, not payroll settlement. |

### Model paid-operation updates

`update_model_paid_operations` accepts rows through `PaidOperationIn`, while
the two model PATCH routes use `ModelUpdateIn` with typed rows and open metadata.
Model CREATE uses a distinct `ModelCreateIn` contract for typed rows and open
unrelated metadata. `section`, `sewingFactory`, `quantityMode` and
`splitMode` use catalog enums. Other known editor fields (identity, selection,
rate, quantity/copy/split data, timing, currency and source metadata) have
explicit optional scalar/list contracts, preserving sent strings, numbers,
nulls and omissions without adding defaults. Non-factory legacy aliases remain
typed under their original keys so frontend and backend fallback behavior is
preserved. Recognized factory spellings normalize only at the factory field;
the legacy `company` hint stays opaque and does not become explicit factory
ownership. Genuine extension keys remain present. Invalid fixed values
or malformed known containers now return 422. Historical
`details_json` reads remain opaque and are not rewritten. The service retains
authorization, factory policy, family discovery/locking, merge, bounds checks,
audit and commit; `model_paid_operations_persistence.py` assigns prepared JSON
through the caller's Session without flushing or committing. Stored JSON
vocabulary has not been censused, so no database constraint or legacy-data
compatibility claim is made.

### Model CREATE persistence

Both standard and Usluga POST routes use `ModelCreateIn`; `ModelCreateCommand`
keeps catalog scope and paid-operation rows typed through service policy and
factory checks. Open `details_json` metadata remains intact, while recognized
paid-operation rows use the canonical row contract. `model_persistence.insert_model`
is the schema-owned Model insert and approval-inheritance writer: it serializes
typed rows at the mapped JSON boundary, adds and flushes on the caller's Session,
and never commits. The service still owns automatic number reservation,
code/identity rules, approval-family lock and selection, audit, one outer commit
and refresh. The CREATE response uses `ModelCreateOut`; historical GET output
remains opaque. The previous opaque-new-row case is replaced by valid canonical
CREATE, malformed-new-row 422 and unchanged historical opaque-read coverage.
`Model.status` remains a raw string because legacy importers and generic PATCH
accept pass-through values without a proven closed stored vocabulary; no status
enum or policy change is claimed. Required PostgreSQL/browser/readback checks
remain pending.

Every service function takes the acting user and the `Session` first, then the
operation input, and owns its own transaction: no helper commits and no
service imports a router. The routers in
[api/routes/](../../api/routes/) only bind HTTP input and authorization, call a
service and map the result to HTTP. `models_service.model_page_headers` holds
the pagination header names the catalog routers apply, so the header contract
has one home.

The shared helpers stay where they were owned:
[model_family_images_service.py](../model_family_images_service.py),
[model_images_service.py](../model_images_service.py),
[model_identity_service.py](../model_identity_service.py),
[paid_operations_service.py](../paid_operations_service.py),
[paid_process_catalog_service.py](../paid_process_catalog_service.py),
[variant_display_service.py](../variant_display_service.py),
[numbering_service.py](../numbering_service.py),
[image_storage_service.py](../image_storage_service.py),
[audit_service.py](../audit_service.py) and
[factory_scope_service.py](../factory_scope_service.py) are called, never
re-implemented.

## Existing code to study first

- Routes: [catalog.py](../../api/routes/catalog.py), [partners.py](../../api/routes/partners.py), [usluga.py](../../api/routes/usluga.py), [paid_processes.py](../../api/routes/paid_processes.py), [process_qr_setup.py](../../api/routes/process_qr_setup.py).
- Services/helpers: [model_family_images_service.py](../model_family_images_service.py), [model_identity_service.py](../model_identity_service.py), [model_images_service.py](../model_images_service.py), [paid_process_catalog_service.py](../paid_process_catalog_service.py), [paid_operations_service.py](../paid_operations_service.py), [variant_display_service.py](../variant_display_service.py).
- Existing SQLAlchemy schema models: [Brand](../../schemas/catalog/catalog.py#L13), [Collection](../../schemas/catalog/catalog.py#L21), [Model](../../schemas/catalog/catalog.py#L33), [CollectionModel](../../schemas/catalog/catalog.py#L111), [ModelImage](../../schemas/catalog/catalog.py#L117), [ModelSize](../../schemas/catalog/catalog.py#L129), [ModelColor](../../schemas/catalog/catalog.py#L137), [ModelBOM](../../schemas/catalog/catalog.py#L145), [PaidProcess](../../schemas/catalog/paid_process.py#L7), [UslugaPaidProcess](../../schemas/catalog/paid_process.py#L18), [Customer](../../schemas/catalog/partners.py#L7), [Supplier](../../schemas/catalog/partners.py#L16).
- Existing Pydantic contracts: the entity-named modules under
  [libs/dto/catalog/](../../libs/dto/catalog/). [catalog.py](../../libs/dto/catalog/catalog.py)
  keeps the identity-owned User/Role/Department contracts and re-exports the
  catalog contracts so the historical import path still resolves.

These are source pointers, not permission to move entire mixed files. Trace the
particular operation and every caller/write before choosing what belongs here.

## When making a service file

Use snake_case_service.py filenames and operation names such as `create_*`, `record_*`,
`receive_*` or `approve_*`. A typed function is sufficient; a class is optional
when it owns real dependencies. Accept the Session, validated input and actor
explicitly. State the transaction owner, refusal rules and result contract.
Use the existing ORM definitions in schemas/ and DTOs in libs/dto/<feature>/;
keep fixed values in libs/enums/. See [DTO conventions](../../libs/dto/README.md).
Do not import routers, call an endpoint, or commit inside a helper owned by another
transaction. Do not create an interface/repository or generic CRUD class by default.

Database definitions have moved to schemas/; business operations use
*_service.py. Convert this guide into a service package only as an approved
operation is extracted and all callers are updated.

**First operation to study:** Separate catalog product/BOM responsibilities from the user DTOs still sharing libs/dto/catalog/catalog.py. Trace usluga model versus order operations individually.

**DTOs and enums:** Stable product/model and approval categories, preserving current values; editable products, partners and paid-operation records are not enums. Reuse Create/In, Update and Read/Out contracts
where they exist. Add action-specific input only for a real action. Do not generate
three DTOs for every table or expose privileged fields through generic updates.

## Boundaries and verification

Sales uses customer/product references; Purchasing uses supplier/material references; Planning reads BOM. Finance owns payment posting. Model images use existing storage helpers.

`delete_bom` is the transaction owner for both the standard Catalog and Usluga
routes. It preserves model/BOM lookup and cutting-use refusal order, writes the
existing `ModelBOM` delete audit, then commits once. The mapped deletion itself
uses `schemas/catalog/bom_persistence.delete_model_bom` with the already-checked
row and the same Session; that helper does not query, flush, or commit. Existing
scope normalization and route authorization remain at their current boundaries.

Verify variant uniqueness, BOM quantities, image scope, approval rules and linked-record deletion guards. Visually check catalog editing, images, sizes/colors and downstream order selection.

## Migration steps

### Remaining operation and type coverage

The combined BOM update/delete source is a candidate awaiting its own combined
technical checks, actual browser/readback evidence and human acceptance. Its
presence does not complete Catalog or the system-wide enum migration.

`Model.status` remains an unresolved fixed-vocabulary audit item, not an approved
free-form field. Ismail owns the table/writer/DTO/consumer inventory; Mirshoir
reviews its eventual contract and action subsets. This integration does not add
an enum or change its stored values, defaults, permissions or transitions.

Follow [the shared sequence](../README.md#migration-sequence): study route/DB/rules
and callers -> agree one operation -> capture baseline tests -> extract -> test
old/new separately -> test the real UI on isolated data -> reviewed switch -> human
production verification -> remove old code. Keep one write path per request.
Record the test result, visual evidence, approver and cleanup condition in the task.
Visual success alone does not prove permissions, concurrency or data correctness.

## Callers of the moved helpers

`scripts/reconcile_xj3062_besttex_20260912.py` imports `_model_code_parts` and
`_model_group_payload` from `app.models.catalog.models_service`, the module that
owns them. The other catalog scripts and tests point at the same module.
