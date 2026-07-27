# Purchasing Training Manual

Version: 1.0
Date: 2026-07-02
Department: Purchasing workflow, usually operated by Planning, Storage, Finance, or Management depending on permission

## Purpose

Purchasing turns material shortages or manual stock needs into approved purchase requests, purchase orders, and received stock.

## Main Pages

- Purchasing
- Purchase Receiving
- Planning Dashboard
- Material Inventory
- Accessory Inventory
- Suppliers
- Inventory Batches

## Key Permissions

- `purchasing.view`
- `purchasing.request`
- `purchasing.approve`
- `purchasing.order`
- `purchasing.receive`
- `storage.suppliers`
- `storage.receive`

## Purchasing Page Workflow

The Purchasing page shows shortage rows and purchase requests.

Use it to:

1. Review shortages for planning-ready Sales Orders.
2. Create a request from a Sales Order shortage.
3. Create a manual request for an item.
4. Approve or reject purchase requests.
5. Convert approved requests to purchase orders.
6. Open Purchase Receiving.

## Creating Request From Shortage

1. Open Purchasing.
2. Review shortage rows: order number, SKU, item name, required quantity, available quantity, shortage, and unit.
3. Select Create Request for the shortage.
4. Confirm the generated request number.
5. Notify the approver if approval is required.

## Creating A Manual Request

1. Open Purchasing.
2. Select item.
3. Enter requested quantity.
4. Review available quantity shown by the system.
5. Select preferred supplier when known.
6. Add notes.
7. Create request.

Use manual requests for stock needs not tied to a Sales Order shortage.

## Approval And Order Conversion

Approvers should:

1. Confirm the shortage or business reason.
2. Check supplier and quantity.
3. Approve or reject the request.
4. Add communication outside the ERP if purchasing policy requires it.

Purchasing/order users should:

1. Convert approved requests to Purchase Orders.
2. Confirm supplier and cost details are correct.
3. Monitor open Purchase Orders until received.

## Purchase Receiving Workflow

1. Open Purchase Receiving.
2. Review pending Purchase Order lines.
3. Select Receive on the correct line.
4. Enter received quantity.
5. Enter batch number.
6. Select storage warehouse.
7. Select supplier if not already set.
8. Enter cost per unit.
9. Save receiving.

Receiving creates inventory stock batches. Wrong cost, batch, or warehouse will affect Inventory and Finance.

## Receiving Rules

1. Receive only physically arrived material.
2. Do not receive more than remaining quantity unless the purchasing policy allows over-receipt and the system supports it.
3. Use supplier delivery document number in notes or batch number when helpful.
4. Use consistent batch numbers.
5. Send questionable goods to QC status according to warehouse practice.

## Status Meaning

| Status | Meaning |
| --- | --- |
| draft/pending_approval | Request is waiting for approval. |
| approved | Request may be converted to order. |
| rejected | Request should not be ordered. |
| converted | Request has become a Purchase Order. |
| sent/approved | Purchase Order can be received. |
| partially_received | Some quantity received, remaining still open. |
| received | Purchase Order is fully received. |
| cancelled | Purchase Order is no longer active. |

## Common Problems

| Problem | Likely cause | Action |
| --- | --- | --- |
| No shortages shown | No planning-ready shortage or requirements not calculated | Ask Planning to review material requirements. |
| Cannot approve | Missing `purchasing.approve` | Ask Admin/Management to review access. |
| Cannot receive | Missing `purchasing.receive` or no open PO line | Check permission and Purchase Order status. |
| Wrong warehouse selected | Human selection error | Notify Storage/Admin immediately before stock is used. |
| Duplicate request | Same shortage requested twice | Approver should reject duplicate or coordinate correction. |
