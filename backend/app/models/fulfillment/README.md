# Warehouse and shipping

Business-service group guide, relocated into models/ on 24 October 2026. This
directory remains README-only; existing implementations are the *_service.py files
linked below. The proposed files describe later approved operation extractions.

**Purpose:** Own finished-goods receiving, placement, reservations, shipment, delivery and physical returns.

**Engineering owner:** Mirshoir. **Reviewer:** Ismail.
**Business acceptance:** Shavkat with operators.
This owner covers the feature's routes, DTOs, enums, database definitions and tests.
See [team ownership](../../../../docs/TEAM_OWNERSHIP.md) for shared-layer coordination.

## Existing code to study first

- Routes: [finished_goods.py](../../api/routes/finished_goods.py), [warehouse_reservations.py](../../api/routes/warehouse_reservations.py), [shipments.py](../../api/routes/shipments.py), [packages.py](../../api/routes/packages.py), [package_workflows.py](../../api/routes/package_workflows.py).
- Services/helpers: [finished_goods_service.py](../finished_goods_service.py), [package_dispatch_service.py](../package_dispatch_service.py), [package_returns_service.py](../package_returns_service.py), [packages_service.py](../packages_service.py), [package_workflows_service.py](../package_workflows_service.py), [warehouse_packages_service.py](../warehouse_packages_service.py), [warehouse_report_service.py](../warehouse_report_service.py), [shipment_review_service.py](../shipment_review_service.py), [shipment_reopen_service.py](../shipment_reopen_service.py), [shipment_invoice_service.py](../shipment_invoice_service.py), [shipment_invoice_excel_service.py](../shipment_invoice_excel_service.py).
- Existing SQLAlchemy schema models: [ManualPackageReceipt](../package_workflows.py#L10), [PackagingReceipt](../production.py#L479), [Shipment](../sales.py#L81), [ShipmentPackage](../sales.py#L106), [ShipmentScanLog](../sales.py#L119), [PackageQuantityAdjustment](../shipment_review.py#L9), [LegacyStockReceipt](../tracking.py#L128), [FinishedGoodsStock](../tracking.py#L233), [StockReservation](../tracking.py#L262), [WarehousePackReservation](../tracking.py#L276).
- Existing Pydantic contracts: [tracking.py](../../schemas/tracking.py), [sales.py](../../schemas/sales.py), [shipment_review.py](../../schemas/shipment_review.py), [package_workflows.py](../../schemas/package_workflows.py).

These are source pointers, not permission to move entire mixed files. Trace the
particular operation and every caller/write before choosing what belongs here.

## When making a service file

| Proposed file | Responsibility |
| --- | --- |
| `receiving_service.py` | Validated warehouse receipts. |
| `stock_service.py` | Finished-goods availability and reservations. |
| `shipments_service.py` | Dispatch, delivery and shipment corrections. |
| `returns_service.py` | Physical return/reopening operations. |

Use snake_case_service.py filenames and operation names such as `create_*`, `record_*`,
`receive_*` or `approve_*`. A typed function is sufficient; a class is optional
when it owns real dependencies. Accept the Session, validated input and actor
explicitly. State the transaction owner, refusal rules and result contract.
Use the existing ORM models. Migrate existing schemas/ DTOs to libs/dto/<feature>/
with their callers; keep fixed values in libs/enums/. See [DTO conventions](../../libs/dto/README.md).
Do not import routers, call an endpoint, or commit inside a helper owned by another
transaction. Do not create an interface/repository or generic CRUD class by default.

**First operation to study:** Trace receive_at_storage and ship_package currently in models/packages_service.py. Separate stock/shipment decisions from package identity while preserving a single transaction owner.

**DTOs and enums:** Shipment, receipt and finished-goods statuses with unchanged transition and evidence requirements. Reuse Create/In, Update and Read/Out contracts
where they exist. Add action-specific input only for a real action. Do not generate
three DTOs for every table or expose privileged fields through generic updates.

## Boundaries and verification

Packaging validates package identity/content; Finance owns invoice/payment mutations. Shipment invoice documents may display frozen logistics data without owning financial posting.

Reject stock without validated receipt, duplicate receipts and dispatch of reserved/invalid packages. Verify partial deliveries and returns. Visually scan a package through receiving, placement, reservation and shipment using isolated fixtures.

## Migration steps

Follow [the shared sequence](../README.md#migration-sequence): study route/DB/rules
and callers -> agree one operation -> capture baseline tests -> extract -> test
old/new separately -> test the real UI on isolated data -> reviewed switch -> human
production verification -> remove old code. Keep one write path per request.
Record the test result, visual evidence, approver and cleanup condition in the task.
Visual success alone does not prove permissions, concurrency or data correctness.
