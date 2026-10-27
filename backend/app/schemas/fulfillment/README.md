# Warehouse and shipping: database schema models

**Engineer:** Mirshoir. **Reviewer:** Ismail. **Business acceptance:** Shavkat.

Finished-goods receipts, available stock, reservations, shipments and shipment scans. Preserve package identity through dispatch.

SQLAlchemy definitions now live under app/schemas/; Pydantic DTOs live in
app/libs/dto/. The links below show the authoritative definitions for this group's
records. Business services live in models/*_service.py.

## Authoritative definitions

- [ManualPackageReceipt](../packaging/package_workflows.py)
- [PackagingReceipt](../production/production.py)
- [Shipment](../sales/sales.py)
- [ShipmentPackage](../sales/sales.py)
- [ShipmentScanLog](../sales/sales.py)
- [PackageQuantityAdjustment](shipment_review.py)
- [LegacyStockReceipt](../production/tracking.py)
- [FinishedGoodsStock](../production/tracking.py)
- [StockReservation](../production/tracking.py)
- [WarehousePackReservation](../production/tracking.py)

These links follow business ownership; some point to mixed files in another group
or shared core.py. Keep one authoritative mapping per table. Moving individual
classes out of mixed files is a separate approved change.

## How to make a file here

1. Trace the approved business operation in [the service guide](../../models/fulfillment/README.md),
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
