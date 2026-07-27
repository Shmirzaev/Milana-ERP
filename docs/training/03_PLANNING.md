# Planning Training Manual

Version: 1.0
Date: 2026-07-02
Department code: PLN
Default role: Planning

## Purpose

Planning converts demand into controlled production. The Planning team checks material requirements, creates Production Orders, creates or manages batches, assigns sewing flows, monitors deadlines, and resolves shortage risks before work reaches the floor.

## Main Pages

- Planning Dashboard
- Forecasting
- Production Orders
- Production Order Detail
- Process Tracking
- Sewing Flows
- Purchase Requests
- Inventory Reservations
- Traceability

## Key Permissions

- `planning.view`
- `planning.requirements`
- `planning.production`
- `planning.reserve_materials`
- `inventory.reservations.view`
- `inventory.reservations.create`
- `purchasing.view`
- `purchasing.request`
- `purchasing.order`
- `processes.view`
- `sewing.flows`
- `forecasting.view`
- `forecasting.manage`

## Daily Workflow

1. Open Planning Dashboard.
2. Review confirmed or planning-ready Sales Orders.
3. Check material requirements and shortages.
4. Add estimated material code, amount, and unit before creating production.
5. Decide whether the order needs batch planning.
6. Create Production Order.
7. Create/cascade work-order deadlines.
8. Reserve materials for the Production Order.
9. Review shortage warnings and create purchase requests if needed.
10. Assign sewing flow or split sewing work across lines.
11. Use Process Tracking to monitor overdue and blocked work.

## Creating Production From A Sales Order

1. Open Planning Dashboard.
2. Find the confirmed Sales Order.
3. Select Create Production Order.
4. Enter material estimate: material code, amount, and unit.
5. Confirm model, quantity, customer deadline, and printing requirement.
6. Create production.
7. Open the Production Order detail page.
8. Review generated work orders for cutting, optional printing, sewing, packaging, and storage.

## Planning With Batches

Use batches when the order will be produced in smaller lots.

1. Select Plan Batches.
2. Enter maximum pieces per batch.
3. Use Auto Split or manually add batch rows.
4. For each batch, enter name, planned quantity, start date, deadline, and notes.
5. Confirm total batch quantity equals the order quantity.
6. Enter material estimate.
7. Create production with batches.

After batching, each floor page requires the operator to select the correct batch before saving output.

## Branded Stock Production

1. Open Planning Dashboard.
2. Use the branded production section.
3. Select an approved model.
4. Enter deadline.
5. Add color/size/quantity lines or use the size distribution helper.
6. Create branded plan.
7. Monitor production through normal stages.
8. Finished packages become branded stock available for later Sales Orders.

## Material Reservations

Reservations are the main control before Cutting.

1. Open Production Order Detail.
2. Review reservation summary: required, reserved, remaining, shortage.
3. Use Auto Reserve when permitted.
4. Review reserved batches.
5. If shortage remains, create purchase request or coordinate with Storage.
6. Release reservations only when production plan changes or material should be freed.

If the company setting requires full reservation before cutting, Cutting will be blocked until required BOM materials are reserved.

## Forecasting

Forecasting provides:

1. Branded stock production suggestions.
2. Item reorder suggestions.
3. Low-stock finished goods indicators.
4. Demand trend quantities.
5. Saved recommendations that can be accepted or dismissed.

Planning should treat forecasting as a planning aid, not as an automatic commitment. Confirm capacity, model approval, BOM, and actual demand before creating production.

## Sewing Flow Assignment

Use Production Order Detail or Sewing Flows to assign sewing work.

1. Open the sewing Work Order.
2. Assign a sewing flow/line.
3. If order is large, split quantity across assignments.
4. Check line utilization before assigning.
5. Avoid assigning to a full line.
6. Update planned start/end when known.

## Blocking And Unblocking Work

Planning/Management can block a Work Order when work should not continue.

Use blocking for:

1. Material shortage.
2. Wrong specification.
3. Customer hold.
4. Quality issue.
5. Deadline or capacity issue.

Always enter a clear block reason. Unblock only after the cause is resolved.

## Daily Planning Checklist

1. Confirm new Sales Orders are planned or intentionally waiting.
2. Review material shortages.
3. Review unreserved Production Orders.
4. Review overdue orders in Process Tracking.
5. Review blocked Work Orders.
6. Review sewing line utilization.
7. Review purchasing requests and receiving status.
8. Communicate changes to Sales, Storage, Production, and Management.

## Common Problems

| Problem | Likely cause | Action |
| --- | --- | --- |
| Cannot create branded plan | Model not approved | Ask Modeling/Management to approve after data is complete. |
| Reservation is empty | BOM missing | Ask Modeling to complete BOM. |
| Cutting cannot start | Required material reservation incomplete | Reserve materials or resolve shortage policy. |
| Sewing line full | Assigned capacity exceeded | Pick another line or split across flows. |
| Process Tracking shows blocked | Work Order block exists | Open Production Order and resolve the blocked stage. |
