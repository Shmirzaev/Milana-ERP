# Material inventory: database schema models

**Engineer:** Ismail. **Reviewer:** Mirshoir. **Business acceptance:** Shavkat.

Fabric/accessory stock, batches, movements, reservations, transfers, stocktake and waste.

SQLAlchemy definitions now live under app/schemas/; Pydantic DTOs live in
app/libs/dto/. The links below show the authoritative definitions for this group's
records. Business services live in models/*_service.py.

## Authoritative definitions

- [EcoFabricDispatch](eco_transfer.py)
- [EcoFabricRoll](eco_transfer.py)
- [FabricScan](fabric_scan.py)
- [Item](inventory.py)
- [Warehouse](inventory.py)
- [StockBatch](inventory.py)
- [StockMovement](inventory.py)
- [MaterialReservation](inventory.py)
- [ManualAccessoryIssue](inventory.py)
- [WarehouseStocktake](stocktake.py)
- [WarehouseStocktakeRow](stocktake.py)
- [WasteRecord](waste.py)
- [WasteSale](waste.py)
- [WasteDisposalRequest](waste.py)

These links follow business ownership; some point to mixed files in another group
or shared core.py. Keep one authoritative mapping per table. Moving individual
classes out of mixed files is a separate approved change.

## How to make a file here

1. Trace the approved business operation in [the service guide](../../models/inventory/README.md),
   its route, current model, DTO, database writes and other callers.
2. Reuse Pydantic contracts from `libs/dto/<feature>/`; never define DTOs here.
   Find existing mapped classes before adding a new persistence definition.
3. Use a descriptive `snake_case.py` file for related existing model definitions.
   Reuse the existing SQLAlchemy Base and classes; preserve table/column names,
   keys, indexes, relationships, constraints, defaults and serialized enum values.
4. Keep persistence definitions and persistence operations here. Create/update/read validation belongs
   in DTOs; permissions, status transitions, calculations, queries and
   write coordination belong in business services under `models/`. Actual
   inserts, updates, deletes and mapped mutations belong in schema-owned
   operations using the supplied Session; helpers never commit independently.
   Follow the [engineering workflow](../../../../docs/ENGINEERING_WORKFLOW.md).
5. Update callers, model registration and Alembic discovery together. Require one
   mapping per table and no database-schema difference for a source-only move.
6. Check contracts and PostgreSQL behavior, visually exercise the affected factory
   workflow, then verify bounded stress/retries and adjacent department handoffs.
   Remove old paths only after the agreed acceptance and rollback conditions pass.

Only groups with actual definitions are Python packages. A guide without Python
files points to its existing definitions elsewhere; it is not a request to create
duplicate classes or empty implementation files.

See [schema migration rules](../README.md), [DTO conventions](../../libs/dto/README.md),
[the business plan](../../../../docs/REFACTOR_PLAN.md) and
[team ownership](../../../../docs/TEAM_OWNERSHIP.md).

Purchase-order receipt's public Inventory participant
`models.inventory.stock_service.record_purchase_order_stock_receipt` uses the
same stock receipt persistence functions as the Inventory endpoint, on
Purchasing's supplied Session. It flushes each batch only for its generated ID,
then stages the `PurchaseOrderLine` movement without a separate flush or commit.
Its required `internal_batch_no` preserves the PO number already stored by this
path; absent length/roll-length values retain the mapped defaults. The normal
Inventory `receive_stock` operation remains the transaction owner for its
endpoint and keeps its own idempotency scope and output contract.

The daily fabric scan register's `fabric_scan_persistence.add_fabric_scan`
operation maps a validated, server-built snapshot command into one `FabricScan`
row and attaches it to the supplied Session. It does not flush, commit, roll
back, query Inventory or create movements. The scan service retains duplicate
lookup, commit, and `IntegrityError` rollback/requery ownership.
