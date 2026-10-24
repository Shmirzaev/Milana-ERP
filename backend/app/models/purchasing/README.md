# Purchasing

Business-service group guide, relocated into models/ on 24 October 2026. This
directory remains README-only; existing implementations are the *_service.py files
linked below. The proposed files describe later approved operation extractions.

**Purpose:** Own purchase requests, approval, request-to-order conversion and receiving orchestration.

**Engineering owner:** Ismail. **Reviewer:** Mirshoir.
**Business acceptance:** Shavkat with operators.
This owner covers the feature's routes, DTOs, enums, database definitions and tests.
See [team ownership](../../../../docs/TEAM_OWNERSHIP.md) for shared-layer coordination.

## Existing code to study first

- Routes: [purchasing.py](../../api/routes/purchasing.py).
- Services/helpers: [purchasing_service.py](../purchasing_service.py).
- Existing SQLAlchemy schema models: [PurchaseRequest](../purchasing.py#L9), [PurchaseRequestLine](../purchasing.py#L39), [PurchaseOrder](../purchasing.py#L71), [PurchaseOrderLine](../purchasing.py#L100).
- Existing Pydantic contracts: [purchasing.py](../../schemas/purchasing.py).

These are source pointers, not permission to move entire mixed files. Trace the
particular operation and every caller/write before choosing what belongs here.

## When making a service file

| Proposed file | Responsibility |
| --- | --- |
| `requests_service.py` | Create, approve, reject and convert requests. |
| `orders_service.py` | Purchase order lifecycle. |
| `receiving_service.py` | Receive a purchase order and coordinate inventory. |

Use snake_case_service.py filenames and operation names such as `create_*`, `record_*`,
`receive_*` or `approve_*`. A typed function is sufficient; a class is optional
when it owns real dependencies. Accept the Session, validated input and actor
explicitly. State the transaction owner, refusal rules and result contract.
Use the existing ORM models. Migrate existing schemas/ DTOs to libs/dto/<feature>/
with their callers; keep fixed values in libs/enums/. See [DTO conventions](../../libs/dto/README.md).
Do not import routers, call an endpoint, or commit inside a helper owned by another
transaction. Do not create an interface/repository or generic CRUD class by default.

**Import collision:** `app/models/purchasing.py` still defines ORM mappings.
Keep this guide directory README-only: adding `__init__.py` could shadow that
mapping module. Preserve its exports and callers through the ordered ORM migration.
Business operations use distinct `*_service.py` filenames.

**First operation to study:** Reuse models/purchasing_service.py operations. Trace route authorization and commit ownership around create_purchase_order and receive_purchase_order before extracting the remaining route work.

**DTOs and enums:** Purchase request/order statuses, with transition checks retained in the service. Reuse Create/In, Update and Read/Out contracts
where they exist. Add action-specific input only for a real action. Do not generate
three DTOs for every table or expose privileged fields through generic updates.

## Boundaries and verification

Inventory owns stock facts. Receiving coordinates both changes under one transaction; do not create a second independent stock-writing implementation.

Verify partial/repeated receiving, kg versus metre quantities, item access, totals and rollback. Visually check purchase request approval, order receiving and the resulting stock batch.

## Migration steps

Follow [the shared sequence](../README.md#migration-sequence): study route/DB/rules
and callers -> agree one operation -> capture baseline tests -> extract -> test
old/new separately -> test the real UI on isolated data -> reviewed switch -> human
production verification -> remove old code. Keep one write path per request.
Record the test result, visual evidence, approver and cleanup condition in the task.
Visual success alone does not prove permissions, concurrency or data correctness.
