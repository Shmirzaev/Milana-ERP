# Catalog and partners

Business-service group guide, relocated into models/ on 24 October 2026. This
directory remains README-only; existing implementations are the *_service.py files
linked below. The proposed files describe later approved operation extractions.

**Purpose:** Own product/model definitions, BOM, variants and customer/supplier reference data. This group does not own user accounts or customer payments.

**Engineering owner:** Ismail. **Reviewer:** Mirshoir.
**Business acceptance:** Shavkat with operators.
This owner covers the feature's routes, DTOs, enums, database definitions and tests.
See [team ownership](../../../../docs/TEAM_OWNERSHIP.md) for shared-layer coordination.

## Existing code to study first

- Routes: [catalog.py](../../api/routes/catalog.py), [partners.py](../../api/routes/partners.py), [usluga.py](../../api/routes/usluga.py), [paid_processes.py](../../api/routes/paid_processes.py), [process_qr_setup.py](../../api/routes/process_qr_setup.py).
- Services/helpers: [model_family_images_service.py](../model_family_images_service.py), [model_identity_service.py](../model_identity_service.py), [model_images_service.py](../model_images_service.py), [paid_process_catalog_service.py](../paid_process_catalog_service.py), [paid_operations_service.py](../paid_operations_service.py), [variant_display_service.py](../variant_display_service.py).
- Existing SQLAlchemy schema models: [Brand](../../schemas/catalog/catalog.py#L13), [Collection](../../schemas/catalog/catalog.py#L21), [Model](../../schemas/catalog/catalog.py#L33), [CollectionModel](../../schemas/catalog/catalog.py#L111), [ModelImage](../../schemas/catalog/catalog.py#L117), [ModelSize](../../schemas/catalog/catalog.py#L129), [ModelColor](../../schemas/catalog/catalog.py#L137), [ModelBOM](../../schemas/catalog/catalog.py#L145), [PaidProcess](../../schemas/catalog/paid_process.py#L7), [UslugaPaidProcess](../../schemas/catalog/paid_process.py#L18), [Customer](../../schemas/catalog/partners.py#L7), [Supplier](../../schemas/catalog/partners.py#L16).
- Existing Pydantic contracts: [catalog.py](../../libs/dto/catalog/catalog.py).

These are source pointers, not permission to move entire mixed files. Trace the
particular operation and every caller/write before choosing what belongs here.

## When making a service file

| Proposed file | Responsibility |
| --- | --- |
| `models_service.py` | Product models, variants and bom. |
| `partners_service.py` | Customer and supplier reference data. |
| `paid_processes_service.py` | Paid-operation definitions, not payroll settlement. |

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

Verify variant uniqueness, BOM quantities, image scope, approval rules and linked-record deletion guards. Visually check catalog editing, images, sizes/colors and downstream order selection.

## Migration steps

Follow [the shared sequence](../README.md#migration-sequence): study route/DB/rules
and callers -> agree one operation -> capture baseline tests -> extract -> test
old/new separately -> test the real UI on isolated data -> reviewed switch -> human
production verification -> remove old code. Keep one write path per request.
Record the test result, visual evidence, approver and cleanup condition in the task.
Visual success alone does not prove permissions, concurrency or data correctness.
