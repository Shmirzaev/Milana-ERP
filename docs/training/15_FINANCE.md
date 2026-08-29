# Finance Training Manual

Version: 1.0
Date: 2026-07-02
Department code: FIN
Default role: Finance

## Purpose

Finance reviews revenue, invoices, payments, customer balances, branded stock value, waste income/cost, COGS, payroll payable, purchasing visibility, and profitability.

## Main Pages

- Finance Dashboard
- Sales Order Detail, invoice action where available
- Customer Detail
- Payroll Summary
- Purchasing, read visibility
- Inventory Reservations, read visibility
- Forecasting, read visibility

## Key Permissions

- `finance.view`
- `finance.invoice`
- `finance.payment`
- `inventory.reservations.view`
- `purchasing.view`
- `payroll.view`
- `payroll.pay`
- `forecasting.view`

## Daily Workflow

1. Open Finance Dashboard.
2. Review revenue total, payments received, branded stock value, and waste cost/income.
3. Review recent invoices.
4. Record payments for unpaid or partially paid invoices.
5. Review revenue by period.
6. Review cost breakdown: fabric, labor, accessories, and total COGS.
7. Review customer balances when needed.
8. Review payroll periods awaiting payment.
9. Coordinate with Sales, Storage, Planning, and HR for mismatches.

## Invoice Creation

Invoices can be created from Sales Order context where the invoice action is available.

Rules:

1. Create invoice only for the correct Sales Order.
2. Confirm order amount and customer.
3. Do not create duplicate invoices. The backend returns existing invoice for the same Sales Order when present.
4. Check invoice status after creation.

## Recording Payment

1. Open Finance Dashboard.
2. Find recent invoice.
3. Select Record Payment on unpaid invoice.
4. Confirm invoice number/order number/customer/amount.
5. Enter amount received.
6. Enter payment date.
7. Select method: bank transfer, cash, or card.
8. Confirm and save.

Payments update invoice status automatically based on amount paid.

## Customer Payment History

Use Customer Detail for:

1. Order history.
2. Paid/open balances.
3. Advance credit.
4. Payment history.
5. Adding customer payment when permitted.

If payment exceeds invoice due amount, the system may treat excess as advance credit depending on current flow.

## Cost And Profit Review

Finance dashboard includes:

1. Branded stock value.
2. Waste report.
3. Revenue by period.
4. Cost breakdown.
5. Order profit endpoint where used.

Cost depends on BOM, stock batches, latest batch cost, packaging, payroll, and production output. If a cost looks wrong, check source data before asking departments to change history.

## Payroll Payment

Finance marks payroll paid only after payroll is approved.

1. Open Payroll Summary.
2. Filter the payroll period.
3. Confirm totals and adjustments.
4. Confirm status is approved.
5. Mark Paid when actual payment is made.

Do not mark payroll paid before payment execution.

## Purchasing And Inventory Visibility

Finance may review Purchasing and Inventory Reservations to understand expected spend and material commitments. Purchasing operations are owned by users with purchasing permissions.

## 1C Integration

The backend supports `POST /api/finance/integrations/1c/sync` with `X-1C-Token`. This is a system integration flow, not a normal user workflow.

Finance/Admin rules:

1. Keep the 1C token private.
2. Do not send token through chat or screenshots.
3. Validate synced records after configuration changes.
4. Report integration failures to IT/Super Admin.

## Common Problems

| Problem | Likely cause | Action |
| --- | --- | --- |
| Invoice missing | Not generated from Sales Order yet | Create invoice if order is ready. |
| Payment does not update status | Amount/date/method issue or duplicate submit | Review invoice and payment history. |
| COGS looks wrong | BOM or stock cost issue | Ask Modeling/Storage to verify source data. |
| Payroll cannot be paid | Period not approved | Ask HR/Management to complete approval. |
| Waste income missing | Waste sale not recorded | Ask Waste Department to check status. |

