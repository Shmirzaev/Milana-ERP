# Warehouse and shipping

Business-service group guide, relocated into models/ on 24 October 2026.
`stock_service.py` now implements the approved Sales reservation boundary below.
Other proposed files remain future operation extractions; this is not full-area
verification or human acceptance.

**Purpose:** Own finished-goods receiving, placement, reservations, shipment, delivery and physical returns.

**Engineering owner:** Mirshoir. **Reviewer:** Ismail.
**Business acceptance:** Shavkat with operators.
This owner covers the feature's routes, DTOs, enums, database definitions and tests.
See [team ownership](../../../../docs/TEAM_OWNERSHIP.md) for shared-layer coordination.

## Approved Sales reservation operation

Ismail approved the revised mentor-based `reserve_pieces` / `reserve_packs`
boundary on 26 October. Both accept the caller's Session, scalar identities and
typed demands from `libs/types/stock_reservation.py`, never Sales mapped objects.
`reserve_pieces` uses canonical `PackageStockKind` with the STANDARD/FIRST_GRADE
subset; `reserve_packs` uses STANDARD internally. Selection/eligibility and exact
package/stock lock order remain here; stock/reservation/metadata writes use the
Fulfillment schema operations with no inner commit, rollback or transaction.

Sales keeps its order lock and pack replay refusal, line quantities, order totals,
status/notes, audit, idempotency and outer commit. Opaque request-local pack keys
map returned piece totals to even newly created unflushed Sales lines. The public
`has_order_reservations` query supports the Sales replay guard; the pure public
`is_any_stock_token` predicate preserves the existing seven-token vocabulary.

Existing option readers now call `ready_pack_candidates` at this owning module.
They still consume mapped read results; replacing that read interface with DTOs
is separately pending, not proof of full domain isolation. Receive/dispatch and
other writers remain separately pending. See the operation packet in
[the dated record](../../../../docs/archive/SALES_APPROVED_STOCK_BOUNDARY_2026-10-26.md).

## Existing code to study first

`shipment_allocation_service.py` owns per-item claims on an existing package
across open shipments. Callers lock their own Shipment, then sorted Package rows;
never lock another Shipment while holding a Package. Each attachment freezes its
claim through `schemas/fulfillment/shipment_allocation.py`. Availability subtracts
other undeleted draft/created claims from physical remaining contents. Dispatch
prefetches claims/items/reservations after package locks, and standalone package
dispatch refuses open shipment claims. Existing Sales/customer reservations are
still enforced; shared claims do not authorize taking another order's stock.
See [verification and limits](../../../../docs/archive/OPEN_SHIPMENT_PACKAGE_SPLIT_2026-10-29.md).

- Routes: [finished_goods.py](../../api/routes/finished_goods.py), [warehouse_reservations.py](../../api/routes/warehouse_reservations.py), [shipments.py](../../api/routes/shipments.py), [packages.py](../../api/routes/packages.py), [package_workflows.py](../../api/routes/package_workflows.py).
- Services/helpers: [finished_goods_service.py](../finished_goods_service.py), [package_dispatch_service.py](../package_dispatch_service.py), [package_returns_service.py](../package_returns_service.py), [packages_service.py](../packages_service.py), [package_workflows_service.py](../package_workflows_service.py), [warehouse_packages_service.py](../warehouse_packages_service.py), [warehouse_report_service.py](../warehouse_report_service.py), [shipment_review_service.py](../shipment_review_service.py), [shipment_reopen_service.py](../shipment_reopen_service.py), [shipment_invoice_service.py](../shipment_invoice_service.py), [shipment_invoice_excel_service.py](../shipment_invoice_excel_service.py).
- Existing SQLAlchemy schema models: [ManualPackageReceipt](../../schemas/packaging/package_workflows.py#L10), [PackagingReceipt](../../schemas/production/production.py#L479), [Shipment](../../schemas/sales/sales.py#L81), [ShipmentPackage](../../schemas/sales/sales.py#L106), [ShipmentScanLog](../../schemas/sales/sales.py#L119), [PackageQuantityAdjustment](../../schemas/fulfillment/shipment_review.py#L9), [LegacyStockReceipt](../../schemas/production/tracking.py#L128), [FinishedGoodsStock](../../schemas/production/tracking.py#L233), [StockReservation](../../schemas/production/tracking.py#L262), [WarehousePackReservation](../../schemas/production/tracking.py#L276).
- Existing Pydantic contracts: [tracking.py](../../libs/dto/packaging/tracking.py), [sales.py](../../libs/dto/sales/sales.py), [shipment_review.py](../../libs/dto/fulfillment/shipment_review.py), [package_workflows.py](../../libs/dto/fulfillment/package_workflows.py).

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
Use the existing ORM definitions in schemas/ and DTOs in libs/dto/<feature>/;
keep fixed values in libs/enums/. See [DTO conventions](../../libs/dto/README.md).
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
