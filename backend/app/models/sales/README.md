# Sales

Business-service group guide. Since 25 October 2026 this directory holds the
sales-order operations that used to live in
[api/routes/sales.py](../../api/routes/sales.py).

**Purpose:** Own sales-order creation, allowed edits, cancellation and ready-stock sales.

**Engineering owner:** Ismail. **Reviewer:** Mirshoir.
**Business acceptance:** Shavkat with operators.
This owner covers the feature's routes, DTOs, enums, database definitions and tests.
See [team ownership](../../../../docs/TEAM_OWNERSHIP.md) for shared-layer coordination.

## Service modules

| File | Responsibility |
| --- | --- |
| `orders_service.py` | Order CRUD, list and search, detail, first-grade and ready-stock options, confirm, notifications, reservation and idempotency, attachments. |
| `history_service.py` | Order-history assembly and history/query projection. Owns `_history_products` and `_stock_production_history`. |
| `ready_stock_service.py` | Sales reservation coordination: calls Fulfillment's typed operations, writes Sales status/notes via schema operations, and requests owned task/notification participants. |

`orders_service` depends on `ready_stock_service`; `history_service` depends on
`orders_service` for the shared order serializer. No service imports a router.

The route module is now HTTP-only: it binds input and permissions, calls one
service function and returns its result.

Candidate operation: `confirm_sales_order` sends the mapped status change through the existing `schemas.sales.sales_order_persistence.set_sales_order_status` operation using `SalesOrderStatus.CONFIRMED`. The service retains its existing business decisions and outer transaction, including its notification and audit participants on the supplied Session. This bounded operation does not certify other Sales writers. Combined PostgreSQL, browser/readback and human acceptance evidence must name the candidate source.

## Existing code to study first

- Routes: [sales.py](../../api/routes/sales.py).
- Services/helpers: [ready_stock_sales_service.py](../ready_stock_sales_service.py)
  retains the Sales order lock/replay guard and maps returned pack quantities to
  Sales lines. [Fulfillment stock_service.py](../fulfillment/stock_service.py)
  owns physical `reserve_pieces`, `reserve_packs` and candidate selection.
- Existing SQLAlchemy schema models: [SalesOrder](../../schemas/sales/sales.py#L9), [SalesOrderItem](../../schemas/sales/sales.py#L45).
- Existing Pydantic contracts: [sales_order_input.py](../../libs/dto/sales/sales_order_input.py),
  [sales_order_update.py](../../libs/dto/sales/sales_order_update.py),
  [sales_order_output.py](../../libs/dto/sales/sales_order_output.py).

## When making a service file

Use snake_case_service.py filenames and operation names such as `create_*`, `record_*`,
`receive_*` or `approve_*`. A typed function is sufficient; a class is optional
when it owns real dependencies. Accept the Session, validated input and actor
explicitly. State the transaction owner, refusal rules and result contract.
Use the existing ORM definitions in schemas/ and DTOs in libs/dto/<feature>/;
keep fixed values in libs/enums/. See [DTO conventions](../../libs/dto/README.md).
Do not import routers, call an endpoint, or commit inside a helper owned by another
transaction. Do not create an interface/repository or generic CRUD class by default.

**DTOs and enums:** Sales-order statuses and fixed sale categories. Preserve existing public values and cancellation rules. Reuse Create/In, Update and Read/Out contracts
where they exist. Add action-specific input only for a real action. Do not generate
three DTOs for every table or expose privileged fields through generic updates.

## Boundaries and verification

Planning evaluates requirements; Fulfillment owns physical dispatch; Finance owns invoices/payments. Do not write their records through private helpers.

Verify order totals, partial edits, cancellation restrictions, reserved stock and response pagination. Visually check order entry/detail and the affected planning or warehouse handoff.

## Remaining exceptions

- `POST /sales-orders/{sid}/generate-invoice` stays in the route and still calls
  `app.models.finance.invoices_service.generate_order_invoice`. Finance owns
  invoicing, so the sales services must not import it.
- The shipment Pydantic contracts remain in
  [app/libs/dto/sales/sales.py](../../libs/dto/sales/sales.py) with the invoice and
  payment aliases. Shipments are Fulfillment's entity; moving them is not a sales
  operation.

## Migration steps

Follow [the shared sequence](../README.md#migration-sequence): study route/DB/rules
and callers -> agree one operation -> capture baseline tests -> extract -> test
old/new separately -> test the real UI on isolated data -> reviewed switch -> human
production verification -> remove old code. Keep one write path per request.
Record the test result, visual evidence, approver and cleanup condition in the task.
Visual success alone does not prove permissions, concurrency or data correctness.
