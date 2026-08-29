# Milana ERP Full Process Overview

Version: 1.0
Date: 2026-07-02
Audience: all departments

Milana ERP controls the garment production process from customer demand to delivered goods. The system connects Sales, Modeling / PLM, Planning, Purchasing, Fabric & Accessories Storage, Cutting, Printing, Sewing, Packaging, Ready Product Storage, Waste, Finance, HR, Management, Admin, and Super Admin.

The most important operating rule is simple: update the ERP at the same time the physical action happens.

## Core Records

| Record | Meaning |
| --- | --- |
| Sales Order | Customer order or branded-stock sale created by Sales. |
| Model | Product definition with code, name, sizes, colors, images, BOM, and approval status. |
| BOM | Bill of Materials used by Planning and Inventory to estimate requirements and shortages. |
| Production Order | Manufacturing plan created by Planning for a customer order or branded stock. |
| Work Order | Department work step for cutting, optional printing, sewing, packaging, or storage transfer. |
| Production Batch | Internal split of one order when work is produced in smaller lots. |
| Bundle | Cut pieces grouped with barcode or QR label; bundles move through Cutting, Printing, and Sewing. |
| Package | Finished goods package with package barcode or QR label; packages move to storage and shipment. |
| Stock Batch | Inventory lot for fabric, accessories, packaging material, or purchased goods. |
| Material Reservation | Planned stock commitment against a Production Order before cutting starts. |
| Shipment | Outbound delivery record linked to ready packages. |
| Payroll Record | Piecework scan record created from employee QR and process/work QR. |
| Audit Log | System history of important changes, approvals, deletes, and transitions. |

## Everyone's Rules

1. Use only your own account.
2. Do not share passwords or QR labels.
3. Start from your department page, not an old browser tab.
4. Check order number, model, color, size, quantity, batch, and status before saving.
5. Scan QR/barcodes when available instead of typing.
6. Do not skip a status or handoff scan.
7. Record failed, rejected, rework, damaged, and waste quantities honestly.
8. Add notes for exceptions, not for normal work.
9. Tell the supervisor quickly when a mistake is saved.
10. Log out on shared computers.

## Main Customer Order Flow

1. Sales creates the customer and Sales Order.
2. Sales enters order type, customer, model, color, size, quantity, unit price, deadline, and printing details when required.
3. Modeling / PLM maintains approved models, sizes, colors, images, and BOM.
4. Planning reviews confirmed Sales Orders, estimates materials, optionally splits into batches, and creates Production Orders.
5. Planning reserves materials and checks shortages.
6. Purchasing creates purchase requests or purchase orders when material is short.
7. Storage receives purchased stock into batches with supplier, warehouse, quantity, unit, cost, and QC status.
8. Cutting records material input, fabric batch, cut pieces, waste, and bundle plan.
9. Cutting creates bundle labels and sends bundles to Printing or directly to Sewing.
10. Printing receives bundles, reviews print instructions/files, records output/rejections, and sends bundles to Sewing.
11. Sewing receives bundles, records output/failed/rework/rejected quantities, and tracks work by line or factory.
12. Packaging records packed/damaged quantities, creates package labels, and prints package labels.
13. Ready Product Storage scans packages, receives them into storage cells/shelves, prepares shipments, scans before shipping, then marks shipment shipped and delivered.
14. Finance generates invoices, records payments, reviews profit, waste income, inventory value, and payroll payables.
15. Waste Department receives production waste, sells sellable waste, or requests disposal approval for non-sellable waste.
16. Management monitors dashboards, process tracking, approvals, exceptions, and audit logs.

## Branded Stock Flow

1. Modeling creates or updates a model.
2. Management approves the model.
3. Planning creates branded-stock production from an approved model.
4. Production follows the same Cutting -> optional Printing -> Sewing -> Packaging flow.
5. Finished packages become available in Warehouse Stock.
6. Sales creates a branded-stock sale and reserves available finished goods.
7. Ready Product Storage ships reserved stock.

## Purchasing Flow

1. Planning or Purchasing reviews material shortages from confirmed/planning orders.
2. Purchasing creates a request manually or from a Sales Order shortage.
3. A purchasing approver approves or rejects the request.
4. Purchasing converts approved requests to Purchase Orders.
5. Storage/Purchasing Receiving receives Purchase Order lines into inventory stock batches.
6. Planning refreshes reservations and releases production only when required materials are available or shortage is accepted by management.

## Payroll Flow

1. HR keeps employees active and assigned to the correct department.
2. Supervisors create or print employee payroll QR badges and process/work QR labels where needed.
3. Payroll scanner user scans employee first, then process/work QR.
4. The scan page calculates piecework by quantity and rate.
5. Payroll records are saved to the backend.
6. HR/Payroll creates payroll periods, reviews records, applies bonuses/deductions, locks periods, and routes approval/payment.
7. Management approves payroll periods.
8. Finance marks approved payroll paid.

## Traceability Flow

Traceability can search by package barcode, package number, bundle, production order, or shipment. It shows product identity, linked order, warehouse/shipment, timeline, material origin, packages, gaps, and printable product passport where export permission allows.

Use Traceability when:

1. A customer asks where an order is.
2. A package is found without paperwork.
3. A defect investigation needs material batch or production history.
4. Shipment, package, or bundle scans do not match expected status.

## Process Tracking Flow

Process Tracking shows live production order progress across stages. It supports search, status filter, sorting, stage detail, batch tracking, blocked-stage warnings, audit link, and print/save-as-PDF export.

Daily supervisor use:

1. Filter active orders.
2. Check current stage, assigned sewing flow, deadline, overdue flags, and blocked stages.
3. Open the Production Order when a stage needs action.
4. Resolve the blocked previous step before asking the next department to continue.

## Handoff Rules

| Handoff | Required ERP action |
| --- | --- |
| Sales -> Planning | Sales Order must be complete and confirmed/planning-ready. |
| Planning -> Storage/Purchasing | Material requirements and shortages must be reviewed. |
| Storage -> Cutting | Required material batches or reservations must be ready. |
| Cutting -> Printing | Bundle scan sends bundle to Printing. |
| Cutting -> Sewing | Bundle scan sends or directly receives bundle at sewing factory when no printing is needed. |
| Printing -> Sewing | Printing records output, then bundle scan sends to Sewing. |
| Sewing -> Packaging | Sewing records passed/rework/failed quantities. |
| Packaging -> Ready Storage | Package label is created and package is scanned into storage. |
| Storage -> Shipment | Package is received in storage, added to shipment, scanned before shipping, then marked shipped/delivered. |

## Start Of Shift Checklist

1. Log in.
2. Check notifications and tasks.
3. Open the department inbox or main department page.
4. Review incoming, pending, in-progress, blocked, and overdue work.
5. Test scanner and label printer if your role uses them.
6. Confirm you are looking at today's active work.

## End Of Shift Checklist

1. Save all physical work done during the shift.
2. Check no scanned bundle/package is still waiting in a local queue.
3. Review failed, rework, rejected, damaged, and waste entries.
4. Report blocked records to the supervisor.
5. Clear shared scanner input and log out.

## Common Problems

| Problem | Likely cause | Action |
| --- | --- | --- |
| Page is missing | Missing permission | Ask supervisor/Admin to review role and extra permissions. |
| Button is disabled | Wrong status or missing permission | Check previous step and your role. |
| Bundle cannot be received | Previous department did not send it | Ask previous department to scan/send. |
| Package cannot be received | Package is not packed or is already moved/shipped | Check package status and history. |
| Material reservation shows shortage | Stock is not available or BOM demand exceeds stock | Planning, Storage, and Purchasing must review. |
| Cutting blocked | Required material reservation may be incomplete | Check reservation status on Production Order. |
| Payroll scan duplicates | Same work QR was scanned already | Check saved/duplicate status before rescanning. |
| Audit history looks wrong | A user action changed the record | Management/Admin should review audit logs. |

