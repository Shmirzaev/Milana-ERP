# Material inventory

Business-service group guide, relocated into models/ on 24 October 2026. This
directory remains README-only; existing implementations are the *_service.py files
linked below. The proposed files describe later approved operation extractions.

**Purpose:** Own material/accessory stock, material reservations, stock movements, transfers, stocktake and material waste records.

**Engineering owner:** Ismail. **Reviewer:** Mirshoir.
**Business acceptance:** Shavkat with operators.
This owner covers the feature's routes, DTOs, enums, database definitions and tests.
See [team ownership](../../../../docs/TEAM_OWNERSHIP.md) for shared-layer coordination.

## Existing code to study first

- Routes: [inventory.py](../../api/routes/inventory.py), [eco_transfers.py](../../api/routes/eco_transfers.py), [fabric_scans.py](../../api/routes/fabric_scans.py), [stocktake.py](../../api/routes/stocktake.py), [waste.py](../../api/routes/waste.py).
- Services/helpers: [inventory_service.py](../inventory_service.py), [inventory_access_service.py](../inventory_access_service.py), [inventory_reports_service.py](../inventory_reports_service.py), [material_rolls_service.py](../material_rolls_service.py), [stocktake_service.py](../stocktake_service.py), [eco_transfer_pdf_service.py](../eco_transfer_pdf_service.py).
- Existing SQLAlchemy schema models: [EcoFabricDispatch](../../schemas/inventory/eco_transfer.py#L8), [EcoFabricRoll](../../schemas/inventory/eco_transfer.py#L17), [FabricScan](../../schemas/inventory/fabric_scan.py#L10), [Item](../../schemas/inventory/inventory.py#L9), [Warehouse](../../schemas/inventory/inventory.py#L31), [StockBatch](../../schemas/inventory/inventory.py#L38), [StockMovement](../../schemas/inventory/inventory.py#L75), [MaterialReservation](../../schemas/inventory/inventory.py#L97), [ManualAccessoryIssue](../../schemas/inventory/inventory.py#L144), [WarehouseStocktake](../../schemas/inventory/stocktake.py#L9), [WarehouseStocktakeRow](../../schemas/inventory/stocktake.py#L18), [WasteRecord](../../schemas/inventory/waste.py#L9), [WasteSale](../../schemas/inventory/waste.py#L26), [WasteDisposalRequest](../../schemas/inventory/waste.py#L37).
- Existing Pydantic contracts: [inventory.py](../../libs/dto/inventory/inventory.py), [waste.py](../../libs/dto/inventory/waste.py).

These are source pointers, not permission to move entire mixed files. Trace the
particular operation and every caller/write before choosing what belongs here.

## When making a service file

| Proposed file | Responsibility |
| --- | --- |
| `stock_service.py` | Stock quantities and movement rules. |
| `reservations_service.py` | Reserve, consume and release materials. |
| `transfers_service.py` | Material/fabric transfers. |
| `stocktake_service.py` | Counting and reconciliation. |
| `waste_service.py` | Waste stock, sale and disposal lifecycle. |

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

**First operation to study:** Trace an existing material issue or reservation operation and its concurrency locks. Reuse models/inventory_service.py and inventory_access_service.py rather than duplicating availability calculations.

**DTOs and enums:** Movement/reservation/count statuses and fixed material categories; warehouses and stock-batch IDs remain data. Reuse Create/In, Update and Read/Out contracts
where they exist. Add action-specific input only for a real action. Do not generate
three DTOs for every table or expose privileged fields through generic updates.

## Boundaries and verification

Production supplies actual usage/defect evidence; Inventory owns material balances. Finished-goods availability belongs to Fulfillment. Finance determines monetary reporting, not stock quantities.

Verify reservations cannot overclaim, units stay consistent, corrections retain history and batch photos remain batch-local. Visually check receiving, reservation, issue/return and stocktake outcomes.

## Migration steps

Follow [the shared sequence](../README.md#migration-sequence): study route/DB/rules
and callers -> agree one operation -> capture baseline tests -> extract -> test
old/new separately -> test the real UI on isolated data -> reviewed switch -> human
production verification -> remove old code. Keep one write path per request.
Record the test result, visual evidence, approver and cleanup condition in the task.
Visual success alone does not prove permissions, concurrency or data correctness.
