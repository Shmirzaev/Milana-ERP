# Sales Training Manual

Version: 1.0
Date: 2026-07-02
Department code: SLS
Default role: Sales

## Purpose

Sales creates customer demand in the ERP and keeps customer-facing order information accurate. Sales Orders are the starting point for Planning, Purchasing, Production, Finance, and Shipment.

## Main Pages

- Dashboard
- Sales Orders
- New Sales Order
- Sales Order Detail
- Order History
- Customers
- Process Tracking
- Traceability
- Forecasting, read-only when permission is granted

## Key Permissions

- `sales.orders`
- `sales.customers`
- `processes.view`
- `traceability.view`
- `traceability.export`
- `forecasting.view`

## Daily Workflow

1. Check open customer requests.
2. Create or update the customer record.
3. Create the Sales Order with correct order type.
4. Add order lines with model, color, size, quantity, unit price, and printing requirement.
5. Add deadline and notes.
6. Upload printing files or add printing instructions when any line requires printing.
7. Save the order and review the Sales Order Detail.
8. Confirm or route the order to Planning according to local approval practice.
9. Use Process Tracking or Traceability for customer status questions.
10. Coordinate with Finance on invoice/payment status.

## Creating A Customer

Use Customers before creating a Sales Order when the buyer is new.

Required habits:

1. Search first to avoid duplicates.
2. Use the official customer name.
3. Add phone, email, and address when available.
4. Update an existing customer instead of creating a near-duplicate.

## Creating A Client Order

1. Open Sales Orders.
2. Select New Order.
3. Choose `Client order`.
4. Select customer and deadline.
5. Add one or more lines.
6. For each line, select model, color, size, quantity, unit price, and printing requirement.
7. Use the size helper when the same model/color needs multiple sizes.
8. If printing is required, enter clear instructions and attach artwork/specification files.
9. Review total quantity and total amount.
10. Save and open the created Sales Order detail page.

Do not create a client order with missing model, unknown size, unclear deadline, or incomplete printing information.

## Creating A Branded Stock Sale

Branded-stock sales reserve already finished stock.

1. Choose `Branded stock sale`.
2. Select brand and customer.
3. Select only models shown as available in storage.
4. Enter number of packs and pieces-per-pack.
5. Confirm the requested quantity does not exceed available finished stock.
6. Save the order.
7. Reserve stock from the Sales Order detail page when required.

If stock is insufficient, do not promise shipment without Planning and Ready Product Storage confirmation.

## Printing Details

When any line needs printing:

1. Add exact placement, color, technique, size, and sample notes.
2. Upload the file used by the print team.
3. Confirm attachments open correctly.
4. Mention customer approval status in notes if applicable.

Printing sees these details on the Printing work order page.

## Customer Status Questions

Use this order:

1. Open Process Tracking and search by Sales Order, Production Order, customer, or model.
2. Check current stage, overdue flag, and blocked stage.
3. If goods are already packed, open Traceability by package or production order.
4. If shipped, check Shipment status.
5. Give customers factual statuses only; do not guess completion dates without Planning.

## Finance Coordination

Sales can see customer order/payment context where permissions allow, but Finance owns invoice and payment records.

Escalate to Finance for:

1. Invoice creation.
2. Payment posting.
3. Advance payment handling.
4. Open balance questions.
5. Payment mismatch.

## Data Quality Checklist

Before saving or confirming:

1. Customer is correct.
2. Order type is correct.
3. Deadline is realistic.
4. Model exists and is approved where required.
5. Color and size are exact.
6. Quantity and unit price are correct.
7. Printing checkbox matches actual customer requirement.
8. Printing files and instructions are attached when needed.
9. Notes explain exceptions.

## Common Mistakes

| Mistake | Result | Fix |
| --- | --- | --- |
| Wrong order type | Planning/stock reservation follows wrong flow | Ask supervisor/Admin before changing downstream records. |
| Missing printing details | Printing team waits or prints incorrectly | Add instructions/files before production reaches printing. |
| Duplicate customer | Payment history splits across records | Ask Admin or supervisor how to merge/correct. |
| Quantity changed after production started | Production and costing can mismatch | Coordinate with Planning and Management before edits. |
