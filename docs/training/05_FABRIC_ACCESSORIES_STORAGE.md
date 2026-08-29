# Fabric & Accessories Storage Training Manual

Version: 1.0
Date: 2026-07-02
Department code: STR
Default role: Storage

## Purpose

Fabric & Accessories Storage owns raw material, accessories, packaging materials, suppliers, inventory batches, movements, and material reservation support.

## Main Pages

- Material Inventory
- Accessory Inventory
- Master Data
- Receive Stock
- Batches
- Purchase Receiving
- Planning reservations on Production Order Detail
- Traceability

## Key Permissions

- `storage.receive`
- `storage.transfer`
- `storage.items`
- `storage.suppliers`
- `inventory.reservations.view`
- `inventory.reservations.create`
- `inventory.reservations.release`
- `inventory.reservations.consume`
- `purchasing.view`
- `purchasing.receive`
- `traceability.view`
- `traceability.export`

## Daily Workflow

1. Check expected purchases and open Purchase Receiving lines.
2. Receive physical stock into the correct warehouse.
3. Maintain inventory item master data and supplier data.
4. Review stock batches and QC status.
5. Support Planning with reservation shortages.
6. Transfer stock when material moves between warehouses or floors.
7. Investigate stock questions through Batches and Traceability.

## Receiving Stock Manually

Use Receive Stock when material is not coming through a Purchase Order receiving flow.

1. Select item.
2. Select supplier.
3. Select warehouse.
4. Enter batch number.
5. Enter quantity and unit.
6. Enter cost per unit.
7. Enter color, width, GSM, or other batch details if applicable.
8. Set QC status.
9. Save receiving.

## Purchase Receiving

When a Purchase Order exists:

1. Open Purchase Receiving.
2. Select the correct Purchase Order line.
3. Receive only the physical quantity arrived.
4. Enter batch number, warehouse, supplier, and cost.
5. Save.
6. Confirm the new batch appears in Batches/Inventory.

## Master Data

Master Data controls inventory items and suppliers.

Inventory item checklist:

1. SKU is unique.
2. Name is clear.
3. Category is correct: fabric, accessory, packaging, waste, or other configured category.
4. Unit is correct.
5. Default cost is reasonable.
6. Batch tracking is enabled for items that must be traced.

Supplier checklist:

1. Supplier name is official.
2. Contact information is current.
3. Duplicate suppliers are avoided.

## Reservation Support

Storage helps Planning reserve and release stock.

1. Review reservation plan on Production Order Detail.
2. Check required, reserved, remaining, available, and shortage quantities.
3. Confirm actual stock location and QC.
4. If stock exists but cannot be reserved, check units, item SKU, or batch status.
5. Release reservations only when Planning confirms they are no longer needed.

## Batch Quality

Batch data affects production cost and traceability. Always verify:

1. Batch number.
2. Item/SKU.
3. Quantity and unit.
4. Color/width/GSM when applicable.
5. Warehouse.
6. Supplier.
7. Cost.
8. QC status.

## Common Problems

| Problem | Likely cause | Action |
| --- | --- | --- |
| Planning sees shortage but stock is present | Wrong item, unit, warehouse, reserved quantity, or QC | Compare reservation item with stock batch details. |
| Cost report is wrong | Receiving cost entered incorrectly | Notify Finance/Admin before reports are finalized. |
| Batch not available for cutting | Reservation missing or stock in wrong status | Review reservation and stock movement. |
| Duplicate SKU | Master data mistake | Stop using duplicate and ask Admin/Storage lead to correct. |

