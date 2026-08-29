# Printing Training Manual

Version: 1.0
Date: 2026-07-02
Department code: PRT
Default role: Printing

## Purpose

Printing receives bundles from Cutting, follows customer print instructions, records printed output and rejects, then sends bundles to Sewing.

## Main Pages

- Printing Floor
- Printing Work Order
- Scan Bundle
- Process Tracking
- Traceability

## Key Permissions

- `printing.records`
- `printing.bundles`
- `payroll.scan`
- `traceability.view`

## Daily Workflow

1. Open Printing Floor.
2. Review incoming/pending printing work.
3. Receive bundles using Scan Bundle.
4. Open the Printing Work Order.
5. If the work order needs collection, use Collect to start/accept the plan with deadline.
6. Review Sales Order printing instructions and attachments.
7. Record input, printed output, rejected quantity, print type, defect reason, and notes.
8. Save printing record.
9. Send bundles to Sewing using Scan Bundle.

## Receiving Bundles

1. Open Scan Bundle for Printing.
2. Scan bundle barcode.
3. Confirm status is `sent_to_printing`.
4. Select Receive at Printing.
5. Confirm status becomes received at printing.

If the receive button is not available, Cutting probably has not sent the bundle to Printing or the bundle is in the wrong status.

## Collecting Printing Work

Some Printing Work Orders must be collected before output can be recorded.

1. Open the Printing Work Order.
2. Review current status and deadline.
3. Enter deadline and notes if needed.
4. Select Collect.
5. Record printing only after the work order is in progress.

## Printing Instructions

The Printing Work Order can show:

1. Sales Order lines requiring printing.
2. Model/color/size/quantity.
3. Customer notes.
4. Printing instructions.
5. Uploaded image/PDF/artwork files.

Do not print if instructions are unclear. Ask Sales or Planning before continuing.

## Recording Printing Output

Fields:

1. Production batch, if order is batched.
2. Input quantity.
3. Printed/output quantity.
4. Rejected quantity.
5. Print type.
6. Defect reason.
7. Notes.

Output quantity is treated as passed quantity for downstream Sewing.

## Sending To Sewing

1. Open Scan Bundle for Printing.
2. Scan each printed bundle.
3. Confirm status is `received_printing`.
4. Select Send to Sewing/factory.
5. Confirm current/next department changed correctly.

## Quality Rules

1. Count printed pieces before recording.
2. Record rejects immediately.
3. Use defect reason for repeated issues.
4. Keep printed and unprinted bundles separated.
5. Do not send unprinted or rejected pieces as passed output.

## Payroll Scan

If payroll QR labels are used:

1. Scan employee QR first.
2. Scan work/process QR.
3. Confirm operation and quantity.
4. Save payroll record when required.

## Common Problems

| Problem | Likely cause | Action |
| --- | --- | --- |
| Cannot receive bundle | Cutting did not send it | Ask Cutting to scan/send. |
| Output form locked | Work Order not collected/in progress | Use Collect if allowed. |
| Wrong print file | Sales uploaded wrong or old file | Stop and ask Sales/Planning. |
| Sewing cannot receive | Printing did not send bundle to Sewing | Scan and send bundle forward. |

