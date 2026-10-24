# Material inventory

Documentation scaffold authorized on 24 October 2026. No Python package or business
logic has been created here. The files below are destinations for approved work.

**Purpose:** Own material/accessory stock, material reservations, stock movements, transfers, stocktake and material waste records.

**Engineering owner:** Ismail. **Reviewer:** Mirshoir.
**Business acceptance:** Shavkat with operators.
This owner covers the feature's routes, DTOs, enums, database definitions and tests.
See [team ownership](../../../../docs/TEAM_OWNERSHIP.md) for shared-layer coordination.

## Existing code to study first

- Routes: [inventory.py](../../api/routes/inventory.py), [eco_transfers.py](../../api/routes/eco_transfers.py), [fabric_scans.py](../../api/routes/fabric_scans.py), [stocktake.py](../../api/routes/stocktake.py), [waste.py](../../api/routes/waste.py).
- Services/helpers: [inventory.py](../inventory.py), [inventory_access.py](../inventory_access.py), [inventory_reports.py](../inventory_reports.py), [material_rolls.py](../material_rolls.py), [stocktake.py](../stocktake.py), [eco_transfer_pdf.py](../eco_transfer_pdf.py).
- Existing SQLAlchemy schema models: [EcoFabricDispatch](../../models/eco_transfer.py#L8), [EcoFabricRoll](../../models/eco_transfer.py#L17), [FabricScan](../../models/fabric_scan.py#L10), [Item](../../models/inventory.py#L9), [Warehouse](../../models/inventory.py#L31), [StockBatch](../../models/inventory.py#L38), [StockMovement](../../models/inventory.py#L75), [MaterialReservation](../../models/inventory.py#L97), [ManualAccessoryIssue](../../models/inventory.py#L144), [WarehouseStocktake](../../models/stocktake.py#L9), [WarehouseStocktakeRow](../../models/stocktake.py#L18), [WasteRecord](../../models/waste.py#L9), [WasteSale](../../models/waste.py#L26), [WasteDisposalRequest](../../models/waste.py#L37).
- Existing Pydantic contracts: [inventory.py](../../schemas/inventory.py), [waste.py](../../schemas/waste.py).

These are source pointers, not permission to move entire mixed files. Trace the
particular operation and every caller/write before choosing what belongs here.

## When making a service file

| Proposed file | Responsibility |
| --- | --- |
| `stock.py` | Stock quantities and movement rules. |
| `reservations.py` | Reserve, consume and release materials. |
| `transfers.py` | Material/fabric transfers. |
| `stocktake.py` | Counting and reconciliation. |
| `waste.py` | Waste stock, sale and disposal lifecycle. |

Use snake_case filenames and operation names such as `create_*`, `record_*`,
`receive_*` or `approve_*`. A typed function is sufficient; a class is optional
when it owns real dependencies. Accept the Session, validated input and actor
explicitly. State the transaction owner, refusal rules and result contract.
Use the existing ORM models. Migrate existing schemas/ DTOs to libs/dto/<feature>/
with their callers; keep fixed values in libs/enums/. See [DTO conventions](../../libs/dto/README.md).
Do not import routers, call an endpoint, or commit inside a helper owned by another
transaction. Do not create an interface/repository or generic CRUD class by default.

**Import collision:** `app/services/inventory.py` already exists. Keep this directory documentation-only until its coordinated conversion is approved. Adding `__init__.py` now can shadow that module; creating child Python modules without a package conversion is not a working import strategy. Preserve or explicitly migrate every existing caller and export.

**First operation to study:** Trace an existing material issue or reservation operation and its concurrency locks. Reuse services/inventory.py and inventory_access.py rather than duplicating availability calculations.

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
