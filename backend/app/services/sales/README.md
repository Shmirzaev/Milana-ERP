# Sales

Documentation scaffold authorized on 24 October 2026. No Python package or business
logic has been created here. The files below are destinations for approved work.

**Purpose:** Own sales-order creation, allowed edits, cancellation and ready-stock sales.

**Engineering owner:** Ismail. **Reviewer:** Mirshoir.
**Business acceptance:** Shavkat with operators.
This owner covers the feature's routes, DTOs, enums, database definitions and tests.
See [team ownership](../../../../docs/TEAM_OWNERSHIP.md) for shared-layer coordination.

## Existing code to study first

- Routes: [sales.py](../../api/routes/sales.py), [usluga.py](../../api/routes/usluga.py).
- Services/helpers: [ready_stock_sales.py](../ready_stock_sales.py).
- Existing SQLAlchemy schema models: [SalesOrder](../../models/sales.py#L9), [SalesOrderItem](../../models/sales.py#L45).
- Existing Pydantic contracts: [sales.py](../../schemas/sales.py).

These are source pointers, not permission to move entire mixed files. Trace the
particular operation and every caller/write before choosing what belongs here.

## When making a service file

| Proposed file | Responsibility |
| --- | --- |
| `orders.py` | Sales order lifecycle and item rules. |
| `ready_stock.py` | Sales from available finished goods. |

Use snake_case filenames and operation names such as `create_*`, `record_*`,
`receive_*` or `approve_*`. A typed function is sufficient; a class is optional
when it owns real dependencies. Accept the Session, validated input and actor
explicitly. State the transaction owner, refusal rules and result contract.
Use the existing ORM models. Migrate existing schemas/ DTOs to libs/dto/<feature>/
with their callers; keep fixed values in libs/enums/. See [DTO conventions](../../libs/dto/README.md).
Do not import routers, call an endpoint, or commit inside a helper owned by another
transaction. Do not create an interface/repository or generic CRUD class by default.

**First operation to study:** Trace one sales order create/update operation, its item writes and downstream planning links. Do not move invoice or shipment logic into a general SalesService.

**DTOs and enums:** Sales-order statuses and fixed sale categories. Preserve existing public values and cancellation rules. Reuse Create/In, Update and Read/Out contracts
where they exist. Add action-specific input only for a real action. Do not generate
three DTOs for every table or expose privileged fields through generic updates.

## Boundaries and verification

Planning evaluates requirements; Fulfillment owns physical dispatch; Finance owns invoices/payments. Do not write their records through private helpers.

Verify order totals, partial edits, cancellation restrictions, reserved stock and response pagination. Visually check order entry/detail and the affected planning or warehouse handoff.

## Migration steps

Follow [the shared sequence](../README.md#migration-sequence): study route/DB/rules
and callers -> agree one operation -> capture baseline tests -> extract -> test
old/new separately -> test the real UI on isolated data -> reviewed switch -> human
production verification -> remove old code. Keep one write path per request.
Record the test result, visual evidence, approver and cleanup condition in the task.
Visual success alone does not prove permissions, concurrency or data correctness.
