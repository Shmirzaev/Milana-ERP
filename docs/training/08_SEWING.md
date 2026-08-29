# Sewing Training Manual

Version: 1.0
Date: 2026-07-02
Department code: SEW
Default role: Sewing

## Purpose

Sewing receives bundles, records sewn output, failed/rework/rejected quantities, and tracks work against sewing lines or assignments.

## Main Pages

- Sewing Floor
- Sewing Work Order
- Sewing Flows
- Scan Bundle
- Payroll Scan
- Process Tracking
- Traceability

## Key Permissions

- `sewing.records`
- `sewing.bundles`
- `payroll.scan`
- `traceability.view`

## Daily Workflow

1. Open Sewing Floor or assigned factory floor.
2. Review work assigned to your line/factory.
3. Receive bundles using Scan Bundle.
4. Open the Sewing Work Order.
5. Select production batch when required.
6. Select line/assignment.
7. Record input, sewn output, failed, rework, rejected, defect reason, and notes.
8. Save record.
9. Use payroll scan when required.
10. Confirm completed work is available for Packaging.

## Receiving Bundles

1. Open Scan Bundle for Sewing.
2. Scan bundle barcode.
3. Confirm model, color, size, quantity, current department, next department, and factory.
4. If status is `sent_to_sewing`, select Receive at factory.
5. If the bundle was created for direct sewing and the page allows receive, receive it.

Do not receive bundles for the wrong factory or wrong line.

## Line And Assignment Selection

The Sewing Work Order may show:

1. Assigned sewing flows.
2. Split assignments.
3. Remaining quantity per assignment.
4. Default Work Order sewing flow.
5. All available flows if no specific assignment exists.

Select the correct line before saving output.

## Recording Sewing Output

Fields:

1. Production batch, if the order is batched.
2. Input quantity.
3. Sewn/output quantity.
4. Failed quantity.
5. Rework quantity.
6. Rejected quantity.
7. Line name or assignment.
8. Defect reason.
9. Notes.

The system uses sewn output as passed quantity for Packaging.

## Quantity Rules

1. Input should not exceed upstream passed pieces.
2. Output should reflect physically sewn pieces.
3. Failed pieces should be counted separately.
4. Rework pieces should not be hidden.
5. Rejected pieces should be recorded with defect reason.

## Payroll Scan

Sewing commonly uses piecework payroll scans.

1. Open Payroll Scan.
2. Scan employee badge first.
3. Scan process/work QR second.
4. Confirm model, production, batch, operation, quantity, rate, and total.
5. Save the scan or Save All.
6. Do not scan the same work QR twice for the same payable operation.

## End Of Shift Checklist

1. All physical sewing output is saved.
2. Failed/rework/rejected quantities are entered.
3. Payroll scans are saved, not only stored in local session.
4. Bundles in progress are physically separated from completed bundles.
5. Supervisor knows about blocked or quality-risk bundles.

## Common Problems

| Problem | Likely cause | Action |
| --- | --- | --- |
| Cannot receive bundle | Previous department did not send it | Ask Cutting/Printing to send. |
| Wrong line shown | Assignment not set or wrong flow selected | Ask Planning/supervisor to update assignment. |
| Quantity error | Sewing input/output exceeds allowed upstream quantity | Check bundle/work order quantities and previous department records. |
| Payroll duplicate | Same work QR already saved | Review scan history and saved status. |

