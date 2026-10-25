# Purchasing

Business-service group guide, relocated into models/ on 24 October 2026. The
approved operation extraction of 25 October 2026 moved the purchasing routes'
orchestration into the three service modules below.

**Purpose:** Own purchase requests, approval, request-to-order conversion and receiving orchestration.

**Engineering owner:** Ismail. **Reviewer:** Mirshoir.
**Business acceptance:** Shavkat with operators.
This owner covers the feature's routes, DTOs, enums, database definitions and tests.
See [team ownership](../../../../docs/TEAM_OWNERSHIP.md) for shared-layer coordination.

## Service files

| File | Responsibility |
| --- | --- |
| [requests_service.py](requests_service.py) | Request directory, creation, creation from a sales order, approval, rejection, conversion, request photo. |
| [orders_service.py](orders_service.py) | Purchase order directory, its page and its creation. |
| [receiving_service.py](receiving_service.py) | Receive a purchase order, lock it, authorize it, replay it and write its stock in one commit. |
| [purchasing_service.py](../purchasing_service.py) | The core operations the three modules above call: request create/approve/reject/convert, order creation, receipt. |

The core operations stay in `purchasing_service.py`; the group modules own the
outer operation each route used to orchestrate - the query, the per-line
access check, the single commit and the refresh. The group modules call the
core operations; they never re-implement them.

## Other source pointers

- Routes: [purchasing.py](../../api/routes/purchasing.py) - HTTP binding only.
- Existing SQLAlchemy schema models: [PurchaseRequest](../../schemas/purchasing/purchasing.py#L9), [PurchaseRequestLine](../../schemas/purchasing/purchasing.py#L39), [PurchaseOrder](../../schemas/purchasing/purchasing.py#L71), [PurchaseOrderLine](../../schemas/purchasing/purchasing.py#L100).
- Existing Pydantic contracts: [purchase_request_input.py](../../libs/dto/purchasing/purchase_request_input.py), [purchase_request_output.py](../../libs/dto/purchasing/purchase_request_output.py), [purchase_order_input.py](../../libs/dto/purchasing/purchase_order_input.py), [purchase_order_output.py](../../libs/dto/purchasing/purchase_order_output.py).

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
*_service.py.

**DTOs and enums:** Purchase request/order statuses, with transition checks retained in the service. Reuse Create/In, Update and Read/Out contracts
where they exist. Add action-specific input only for a real action. Do not generate
three DTOs for every table or expose privileged fields through generic updates.

## Remaining exceptions

- `purchasing_service.py` still holds the core operations. It is the single
  write path for purchasing data; the group modules call into it.
- The purchase quantity bound and its two aliases live in
  [purchase_quantity.py](../../libs/dto/purchasing/purchase_quantity.py) because
  the request and the order inputs both use them.
- Purchasing exposes no update operation, so there is no `*_update.py` DTO
  module; an update contract would be unused.

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
