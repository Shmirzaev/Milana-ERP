# Cutting Training Manual

Version: 1.0
Date: 2026-07-02
Department code: CUT
Default role: Cutting

## Purpose

Cutting converts reserved fabric into cut pieces and traceable bundles. Cutting accuracy controls the rest of production, because Printing and Sewing cannot receive bundles that were not created and sent correctly.

## Main Pages

- Cutting Floor
- Cutting Work Order
- Cutting Passports
- Bundle Inventory
- Bundles
- Scan Bundle
- Process Tracking
- Traceability

## Key Permissions

- `cutting.records`
- `cutting.bundles`
- `inventory.reservations.view`
- `payroll.scan`
- `traceability.view`

## Daily Workflow

1. Open Cutting Floor.
2. Review incoming/pending work.
3. Open the correct Cutting Work Order.
4. Check product information, model, order, color, size, planned quantity, and reservation status.
5. Select the correct production batch if the order is batched.
6. Select fabric batch.
7. Enter fabric input quantity and unit.
8. Enter cut pieces.
9. Enter waste quantity and unit.
10. Review or edit bundle plan.
11. Save and create bundles.
12. Print bundle labels.
13. Send bundles to Printing or Sewing using Scan Bundle.

## Before Cutting Starts

Confirm:

1. Work Order belongs to the right Production Order.
2. Model and size breakdown match physical marker/cutting plan.
3. Material reservation is ready or approved to proceed.
4. Fabric batch matches the material physically used.
5. Cutting table quantity matches planned batch/order quantity.
6. Printing requirement is known.
7. Sewing factory destination is correct: Milana or Besttex.

## Batch Planning Inside Cutting

If Planning did not already split the order, Cutting may define batches inside the work order when permission allows.

1. Use maximum pieces per batch.
2. Auto Split or add batch rows manually.
3. Enter batch name, quantity, start date, deadline, and notes.
4. Save batch plan.
5. After batches exist, select the correct batch before saving cutting output.

Do not use batch splitting to hide shortage or rework. It is for production planning and traceability.

## Recording Cutting Output

Required fields:

1. Production batch, if the order is batched.
2. Fabric batch.
3. Input quantity and unit.
4. Cut pieces.
5. Waste quantity and unit.
6. Bundle plan.
7. Notes when something unusual happened.

The system treats cut pieces as passed pieces for downstream bundle creation.

## Bundle Plan

Bundle plan rows include:

1. Color.
2. Size.
3. Pieces per bundle.
4. Bundle count.
5. Sewing factory.
6. Next department: Printing or Sewing.

Bundle quantity and count should match actual cut pieces. If the order includes printing, send to Printing. If no printing is needed, send to the correct sewing factory.

## Label Printing

After saving:

1. Review created bundle list.
2. Print all labels or print individual labels.
3. Attach each label to the correct physical bundle immediately.
4. Keep bundle labels visible and protected.

If a label is damaged, reprint it from the created bundle list or Bundles page. Do not create a duplicate bundle to replace a label.

## Bundle Scan Handoff

Use Scan Bundle for movement.

1. Scan or enter bundle barcode.
2. Confirm bundle number, model, color, size, quantity, current department, next department, and sewing factory.
3. If status is `created` and next is Printing, select Send to Printing.
4. If status is `created` and next is a sewing factory, select Send/Receive to factory according to the available action.
5. Confirm the status changed.

## Waste Recording

Cutting waste must be honest and timely.

1. Enter waste quantity during cutting record.
2. Use notes for unusual waste.
3. Send physical waste according to waste department procedure.
4. Do not reduce waste to make production look better.

## Payroll Scan

If cutting operations use payroll QR labels:

1. Scan employee QR first.
2. Scan the work/process QR.
3. Check employee, operation, quantity, and rate.
4. Save payroll records when required.

## End Of Shift Checklist

1. All cut work is saved.
2. All created bundles have labels.
3. Physical bundles match ERP bundle count.
4. Bundles sent forward have been scanned.
5. Waste is recorded.
6. Blocked or shortage work is reported.

## Common Problems

| Problem | Likely cause | Action |
| --- | --- | --- |
| Cannot save cutting record | Missing required batch/fabric/quantity or reservation block | Check required fields and reservation status. |
| Bundle count wrong | Bundle plan does not match cut pieces | Correct plan before saving, or ask supervisor if already saved. |
| Printing cannot receive bundle | Cutting did not send bundle to Printing | Scan bundle and send to Printing. |
| Sewing cannot receive bundle | Bundle next department/factory is wrong or not sent | Check bundle details and ask supervisor if destination is wrong. |

