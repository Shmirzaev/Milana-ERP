# Finance

Business-service group guide, relocated into models/ on 24 October 2026. This
directory remains README-only; existing implementations are the *_service.py files
linked below. The proposed files describe later approved operation extractions.

**Purpose:** Own invoice issuance, payment allocation, balances and financial calculations.

**Engineering owner:** Ismail. **Reviewer:** Mirshoir.
**Business acceptance:** Shavkat with operators.
This owner covers the feature's routes, DTOs, enums, database definitions and tests.
See [team ownership](../../../../docs/TEAM_OWNERSHIP.md) for shared-layer coordination.

## Existing code to study first

- Routes: [finance.py](../../api/routes/finance.py), [sales.py](../../api/routes/sales.py), [partners.py](../../api/routes/partners.py), [shipments.py](../../api/routes/shipments.py).
- Services/helpers: [finance_service.py](../finance_service.py), [payments_service.py](../payments_service.py), [shipment_invoice_service.py](../shipment_invoice_service.py), [shipment_review_service.py](../shipment_review_service.py).
- Existing SQLAlchemy schema models: [Invoice](../../schemas/sales/sales.py#L132), [Payment](../../schemas/sales/sales.py#L148).
- Existing Pydantic contracts: [sales.py](../../libs/dto/sales/sales.py), [price_calculation.py](../../libs/dto/planning/price_calculation.py).

These are source pointers, not permission to move entire mixed files. Trace the
particular operation and every caller/write before choosing what belongs here.

## When making a service file

| Proposed file | Responsibility |
| --- | --- |
| `invoices_service.py` | Invoice issuance/correction and lifecycle. |
| `payments_service.py` | Receipts, advances and allocation. |
| `reports_service.py` | Financial queries using authoritative facts. |

Use snake_case_service.py filenames and operation names such as `create_*`, `record_*`,
`receive_*` or `approve_*`. A typed function is sufficient; a class is optional
when it owns real dependencies. Accept the Session, validated input and actor
explicitly. State the transaction owner, refusal rules and result contract.
Use the existing ORM definitions in schemas/ and DTOs in libs/dto/<feature>/;
keep fixed values in libs/enums/. See [DTO conventions](../../libs/dto/README.md).
Do not import routers, call an endpoint, or commit inside a helper owned by another
transaction. Do not create an interface/repository or generic CRUD class by default.

**First operation to study:** Trace invoice creation across finance, sales, partners and workflow_service.ensure_invoice_for_delivered_shipment. Preserve legitimate differences before consolidating shared issuance rules.

**DTOs and enums:** Invoice/payment status vocabulary; currencies and policy rules require explicit business decisions, not assumptions. Reuse Create/In, Update and Read/Out contracts
where they exist. Add action-specific input only for a real action. Do not generate
three DTOs for every table or expose privileged fields through generic updates.

## Boundaries and verification

Sales owns commercial orders and Fulfillment owns delivery evidence. Finance consumes that evidence without rewriting quantities. Money-report queries may read across groups but must not hide writes.

Verify Decimal precision, received-payment revenue, advances/reversals, idempotency and authorization. Visually compare invoice, payment, debt and revenue screens for the same fixture transactions.

## Migration steps

Follow [the shared sequence](../README.md#migration-sequence): study route/DB/rules
and callers -> agree one operation -> capture baseline tests -> extract -> test
old/new separately -> test the real UI on isolated data -> reviewed switch -> human
production verification -> remove old code. Keep one write path per request.
Record the test result, visual evidence, approver and cleanup condition in the task.
Visual success alone does not prove permissions, concurrency or data correctness.
