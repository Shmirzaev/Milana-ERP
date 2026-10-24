# Catalog and partners

Documentation scaffold authorized on 24 October 2026. No Python package or business
logic has been created here. The files below are destinations for approved work.

**Purpose:** Own product/model definitions, BOM, variants and customer/supplier reference data. This group does not own user accounts or customer payments.

**Engineering owner:** Ismail. **Reviewer:** Mirshoir.
**Business acceptance:** Shavkat with operators.
This owner covers the feature's routes, DTOs, enums, database definitions and tests.
See [team ownership](../../../../docs/TEAM_OWNERSHIP.md) for shared-layer coordination.

## Existing code to study first

- Routes: [catalog.py](../../api/routes/catalog.py), [partners.py](../../api/routes/partners.py), [usluga.py](../../api/routes/usluga.py), [paid_processes.py](../../api/routes/paid_processes.py), [process_qr_setup.py](../../api/routes/process_qr_setup.py).
- Services/helpers: [model_family_images.py](../model_family_images.py), [model_identity.py](../model_identity.py), [model_images.py](../model_images.py), [paid_process_catalog.py](../paid_process_catalog.py), [paid_operations.py](../paid_operations.py), [variant_display.py](../variant_display.py).
- Existing SQLAlchemy schema models: [Brand](../../models/catalog.py#L13), [Collection](../../models/catalog.py#L21), [Model](../../models/catalog.py#L33), [CollectionModel](../../models/catalog.py#L111), [ModelImage](../../models/catalog.py#L117), [ModelSize](../../models/catalog.py#L129), [ModelColor](../../models/catalog.py#L137), [ModelBOM](../../models/catalog.py#L145), [PaidProcess](../../models/paid_process.py#L7), [UslugaPaidProcess](../../models/paid_process.py#L18), [Customer](../../models/partners.py#L7), [Supplier](../../models/partners.py#L16).
- Existing Pydantic contracts: [catalog.py](../../schemas/catalog.py).

These are source pointers, not permission to move entire mixed files. Trace the
particular operation and every caller/write before choosing what belongs here.

## When making a service file

| Proposed file | Responsibility |
| --- | --- |
| `models.py` | Product models, variants and bom. |
| `partners.py` | Customer and supplier reference data. |
| `paid_processes.py` | Paid-operation definitions, not payroll settlement. |

Use snake_case filenames and operation names such as `create_*`, `record_*`,
`receive_*` or `approve_*`. A typed function is sufficient; a class is optional
when it owns real dependencies. Accept the Session, validated input and actor
explicitly. State the transaction owner, refusal rules and result contract.
Use the existing ORM models. Migrate existing schemas/ DTOs to libs/dto/<feature>/
with their callers; keep fixed values in libs/enums/. See [DTO conventions](../../libs/dto/README.md).
Do not import routers, call an endpoint, or commit inside a helper owned by another
transaction. Do not create an interface/repository or generic CRUD class by default.

**First operation to study:** Separate catalog product/BOM responsibilities from the user DTOs currently in schemas/catalog.py. Trace usluga model versus order operations individually.

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
