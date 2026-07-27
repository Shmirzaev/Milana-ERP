# Ready Product Storage Training Manual

Version: 1.0
Date: 2026-07-02
Department code: FGS
Default role: ReadyStorage

## Purpose

Ready Product Storage receives finished packages, places them on the warehouse map, manages warehouse stock, prepares shipments, scans packages before shipping, and marks shipment progress.

## Main Pages

- Finished Goods
- Warehouse Stock
- Scan Package
- Warehouse Map
- Shipments
- Packages
- Traceability

## Key Permissions

- `storage.packages`
- `storage.shipment`
- `traceability.view`
- `traceability.export`

## Daily Workflow

1. Receive packed packages from Packaging.
2. Open Scan Package.
3. Scan package labels into the queue.
4. Select storage cell and shelf.
5. Receive selected packed packages.
6. Move packages on the warehouse map if needed.
7. Review Warehouse Stock and Finished Goods.
8. Create or open shipments.
9. Add ready packages to shipment.
10. Scan packages before shipping.
11. Mark shipment shipped and then delivered when physical actions happen.

## Receiving Packages Into Storage

1. Open Scan Package.
2. Scan package barcode.
3. Confirm package number, order, model, quantity, status, and current cell.
4. Add all physical packages to the queue.
5. Select packed packages.
6. Select storage cell and shelf.
7. Select Receive Selected.
8. Confirm package status and map placement.

Only packages with status `packed` can be received into storage.

## Moving Packages On Map

1. Scan or select packages.
2. Select new storage cell and shelf.
3. Select Move Selected.
4. Confirm warehouse map updated.

Do not move packages that are shipped, delivered, or damaged.

## Warehouse Map

Use Warehouse Map to:

1. See occupied cells.
2. Find packages by model.
3. Place or move packages.
4. Support picking for shipment.

Always keep the map aligned with physical storage.

## Shipment Workflow

1. Open Shipments.
2. Create shipment for eligible order if not already created.
3. Add ready packages manually or add all ready packages.
4. Use scan check before shipping.
5. Scan every required package.
6. Mark as shipped only after packages leave physically.
7. Mark as delivered only after delivery confirmation.

## Shipment Scan Rules

1. Scan the package in the active shipment.
2. Do not ship packages missing from scan check.
3. Do not scan packages for another customer/order.
4. Investigate mismatch before marking shipment shipped.

## Traceability

Use Traceability for:

1. Package passport.
2. Shipment passport.
3. Package history and material origin.
4. Customer delivery questions.
5. Warehouse location questions.

## Common Problems

| Problem | Likely cause | Action |
| --- | --- | --- |
| Package not found | Wrong barcode or label damaged | Search by package number or ask Packaging to reprint label. |
| Cannot receive package | Status is not packed | Ask Packaging to check package creation/status. |
| Cannot move package | Status shipped/delivered/damaged | Do not move; review package history. |
| Shipment scan mismatch | Wrong package scanned | Stop and compare shipment package list. |
| Customer asks where goods are | Need shipment/package history | Use Traceability and Shipments. |
