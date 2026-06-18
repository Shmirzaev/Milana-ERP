# Milana ERP Employee Training Guide

Version: 1.0
Date: 2026-06-13
Audience: employees, supervisors, department managers, and trainers

This guide explains how employees should use Milana ERP during daily work. It is written for people who need to understand the production workflow, know which screen to open, and enter clean data at the right time.

Use this guide during onboarding, department training, and daily refreshers.

## 1. What The System Is For

Milana ERP tracks garment production from customer order to shipment. The system connects Sales, Planning, Storage, Cutting, Printing, Sewing, Packaging, Ready Product Storage, Waste, Finance, HR, and Management.

The main goal is simple: every order, material batch, bundle, package, shipment, payment, and waste record should have one clear status and one trusted history.

## 2. Key Rules For Every Employee

1. Use your own account only. Do not share passwords.
2. Enter data when the physical action happens, not hours later.
3. Check quantity, model, color, and size before saving.
4. Scan barcodes or QR codes instead of typing whenever possible.
5. Do not skip statuses. The next department depends on your update.
6. If a button is missing, your role may not have permission or the item may be in the wrong status.
7. Report mistakes to your supervisor quickly. The audit log records who changed what and when.

## 3. Basic Words Used In The ERP

| Term | Meaning |
| --- | --- |
| Sales Order | Customer order or branded-stock sale created by Sales. |
| Production Order | Manufacturing plan created by Planning from a Sales Order or for branded stock. |
| Work Order | Department task created for cutting, printing, sewing, packaging, or storage transfer. |
| Bundle | Cut pieces grouped together with a barcode or QR code. Bundles move between departments. |
| Package | Finished goods packed into a box or bag with a package barcode or QR code. |
| Batch | Stock lot received into inventory, usually fabric or accessories. |
| Status | Current stage of an order, work order, bundle, package, shipment, invoice, or waste record. |
| BOM | Bill of Materials. The materials needed to produce one model. |
| Audit Log | System history showing every important user action. |

## 4. Main Workflow Overview

### Client Order Production

1. Sales creates the customer and Sales Order.
2. Modeling / PLM maintains models, sizes, colors, images, and BOM.
3. Planning reviews the Sales Order, checks material requirements, and creates a Production Order.
4. The ERP creates Work Orders for the required departments.
5. Storage receives fabric and accessories into inventory batches.
6. Cutting starts the cutting work, records cut quantities, and creates bundles with labels.
7. Printing receives bundles when printing is needed, records output, and sends bundles forward.
8. Sewing receives bundles, assigns or works through sewing flows, and records passed, failed, and rework quantities.
9. Packaging records packed quantities, creates packages, and prints package labels.
10. Ready Product Storage receives packages, stores them, and prepares shipments.
11. Shipment is created, packages are added, goods are shipped, and delivery is recorded.
12. Finance creates invoices, records payments, and reviews profit.
13. Waste is recorded, received by the waste department, sold, or disposed with approval.

### Branded Stock Production

1. Modeling creates and completes a model.
2. Management approves the model.
3. Planning creates branded-stock production without a customer Sales Order.
4. Production follows the same cutting, printing, sewing, packaging, and storage workflow.
5. Finished branded stock becomes available in warehouse stock.
6. Sales can later create a branded-stock sale and reserve available stock.

## 5. Logging In And Moving Around

1. Open the ERP website provided by IT.
2. Enter your work email and password.
3. Choose the language if needed. The system supports English, Russian, and Uzbek.
4. Use the left sidebar to open your department pages.
5. Use the top bar for your profile, language, notifications, tasks, and logout.

Important: if you cannot see a page, your role probably does not have access. Ask your supervisor or Admin.

## 6. Common Screen Types

### Tables

Most pages show a table of records. Use search, filters, status badges, and action buttons to find the right row.

Before clicking an action, check:

1. Order number.
2. Model.
3. Color and size.
4. Quantity.
5. Current status.

### Detail Pages

Detail pages show one order, work order, bundle, package, shipment, or model. Use these pages to review full history and open related records.

### Forms

Forms create or update records. Required fields must be filled before saving. If the system rejects a form, read the error message and correct the field shown.

### Scan Pages

Scan pages are used for bundles and packages. Put the cursor in the scan input, scan the barcode or QR code, then confirm the action shown on screen.

## 7. Process Tracking

The Process Tracking page is used by supervisors, Planning, Management, and departments to see live production status.

Use it to:

1. Search by Production Order, Sales Order, customer, or model.
2. See the current department stage.
3. Check whether work is blocked.
4. See overdue work.
5. Open the Production Order or department Work Order.
6. Export a PDF production status report when needed.

If a process is blocked, open the blocked stage and fix the missing previous action before continuing.

## 8. Department Inbox

Department pages such as Cutting Floor, Printing Floor, Sewing Floor, Packaging Floor, and Finished Goods show a department inbox.

Typical inbox sections:

1. Incoming work: work or bundles arriving from a previous department.
2. Pending work: work ready to start.
3. In progress work: work already started.
4. Ready or completed work: work waiting for the next step.

Daily habit: start from your department inbox, not from old browser tabs.

## 9. Department Guides

### Sales

Main pages:

1. Sales Orders.
2. Customers.
3. Process Tracking.

Daily work:

1. Create or update customers.
2. Create Sales Orders with correct customer, order type, model, size, color, quantity, price, and deadline.
3. Confirm orders when ready for Planning.
4. For branded-stock sales, reserve stock and review shortages.
5. Check Process Tracking for customer status questions.

Do not confirm an order if the quantity, deadline, customer, or item details are incomplete.

### Modeling / PLM

Main pages:

1. Models.
2. Brands.
3. Collections.

Daily work:

1. Create and maintain models.
2. Add sizes, colors, images, and model details.
3. Maintain BOM so Planning can calculate materials.
4. Submit models for approval.
5. Coordinate with Management for approval before branded production.

Important: branded stock production requires an approved model.

### Planning

Main pages:

1. Planning Dashboard.
2. Production Orders.
3. Process Tracking.
4. Sewing Flows.

Daily work:

1. Review confirmed Sales Orders.
2. Check material requirements from BOM and planned waste percentage.
3. Create Production Orders.
4. Confirm that Work Orders were generated for the correct stages.
5. Watch overdue or blocked production on Process Tracking.
6. Assign sewing work to flows when needed.
7. Communicate shortages to Storage, Sales, and Management.

Before releasing production, check that model, color, size, quantity, deadline, and required printing steps are correct.

### Fabric And Accessories Storage

Main pages:

1. Material Inventory.
2. Accessory Inventory.
3. Receive Stock.
4. Batches.

Daily work:

1. Receive fabric and accessories into stock.
2. Enter supplier, item, warehouse, quantity, unit cost, and batch information.
3. Review stock batches and movement history.
4. Notify Planning about shortages or incorrect stock.

Important: wrong batch or cost data affects production cost and finance reports.

### Cutting

Main pages:

1. Cutting Floor.
2. Cutting Passports.
3. Bundles.
4. Scan Bundle.

Daily work:

1. Open Cutting Floor and review pending work.
2. Open the cutting Work Order.
3. Record input, passed quantity, failed quantity, rework quantity, and notes.
4. Create bundles from the cut output.
5. Print or attach bundle labels.
6. Scan bundles when sending them to Printing or Sewing.
7. Record waste accurately when cutting creates waste.

Important: downstream departments cannot receive bundles that Cutting has not created and sent.

### Printing

Main pages:

1. Printing Floor.
2. Scan Bundle.

Daily work:

1. Receive bundles sent from Cutting.
2. Record printing output against the correct Work Order.
3. Enter passed, failed, and rework quantities.
4. Scan bundles when sending them to Sewing.

If the system will not receive a bundle, confirm that Cutting sent it to Printing first.

### Sewing

Main pages:

1. Sewing Flows.
2. Sewing Floor.
3. Milana Sewing.
4. Besttex Sewing.
5. Scan Bundle.

Daily work:

1. Review assigned sewing flow or department inbox.
2. Receive bundles from Cutting or Printing.
3. Open the sewing Work Order.
4. Record passed, failed, and rework quantities.
5. Track active work by line or factory.
6. Close daily work with accurate output numbers.

Important: sewing input cannot be higher than upstream passed quantity from Cutting or Printing.

### Packaging

Main pages:

1. Packaging Floor.
2. Packages.
3. Scan Package.

Daily work:

1. Open Packaging Floor and review ready work.
2. Record packaging output against the correct Work Order.
3. Create packages with correct model, color, size, and quantity.
4. Print or attach package labels.
5. Scan packages for Ready Product Storage.

Package rule: default capacity is 60 pieces. Over-capacity or mixed-model packages require Admin approval.

### Ready Product Storage

Main pages:

1. Finished Goods.
2. Warehouse Stock.
3. Scan Package.
4. Warehouse Map.
5. Shipments.

Daily work:

1. Receive finished packages by scanning package labels.
2. Confirm package status becomes received in storage.
3. Place goods in the correct warehouse location.
4. Create or open shipments.
5. Add ready packages to the shipment.
6. Mark shipped and delivered when the physical action happens.

Important: do not ship packages that were not received into Ready Product Storage.

### Waste Department

Main page:

1. Waste Dashboard.

Daily work:

1. Receive waste records from production departments.
2. Confirm whether waste is sellable or non-sellable.
3. Sell sellable waste and record the sale.
4. Request approval for non-sellable disposal.
5. Mark disposed only after approval and physical disposal.

Important: non-sellable waste requires Management approval before disposal.

### Finance

Main page:

1. Finance Dashboard.

Daily work:

1. Review revenue, payments, branded stock value, waste income, and order profit.
2. Create invoices for Sales Orders when required.
3. Record payments accurately.
4. Review partially paid and unpaid invoices.
5. Use order profit reports to understand material cost and margin.

Important: production quantity changes affect costing, so Finance should not ask production teams to edit history without a clear reason.

### HR

Main page:

1. Employees.

Daily work:

1. Add new employees.
2. Update department, position, phone, salary, and active status.
3. Coordinate with Admin when an employee also needs ERP login access.

### Management / Admin

Main pages:

1. Dashboard.
2. Process Tracking.
3. Users.
4. Departments.
5. Audit Logs.
6. Models.
7. Waste Dashboard.
8. Tasks.

Daily work:

1. Monitor active orders, late orders, waste, finance, and department performance.
2. Approve models.
3. Approve waste disposal requests.
4. Create, disable, or update users.
5. Assign roles and departments.
6. Review audit logs for unusual activity.
7. Assign and monitor tasks.
8. Approve exceptions such as package capacity override when justified.

Important: Admin has full access. Keep the number of Admin users small.

## 10. Barcode And QR Workflow

### Bundle Scanning

Bundles move through production by scan actions.

Common bundle actions:

1. Cutting creates bundle.
2. Cutting sends bundle to Printing, if printing is required.
3. Printing receives bundle.
4. Printing sends bundle to Sewing.
5. Sewing receives bundle.

If no printing is required, Cutting can send the bundle directly toward Sewing.

### Package Scanning

Packages move through storage and shipment by scan actions.

Common package actions:

1. Packaging creates package.
2. Ready Product Storage receives package.
3. Shipment adds package.
4. Shipment marks package shipped.
5. Shipment marks package delivered.

## 11. Tasks And Notifications

Use Tasks for work that needs follow-up across departments.

Good task examples:

1. "Check shortage for SO-2026-000123."
2. "Reprint missing package labels for PKG-2026-000045."
3. "Approve disposal request for cutting waste."

Notifications show system events and reminders. Check them at the start and end of each shift.

## 12. Daily Checklists

### Start Of Shift

1. Log in with your own account.
2. Check notifications and tasks.
3. Open your department inbox.
4. Review pending, incoming, and in-progress work.
5. Confirm scanner and label printer are working if your department uses them.

### During Shift

1. Update the ERP immediately after each physical step.
2. Scan labels instead of typing.
3. Enter failed and rework quantities honestly.
4. Add notes when something unusual happens.
5. Tell the next department when urgent work is sent.

### End Of Shift

1. Finish saving all records from the shift.
2. Check no completed physical work is left unrecorded.
3. Review open tasks.
4. Report blocked work to the supervisor.
5. Log out on shared computers.

## 13. Common Problems And Fixes

| Problem | What It Usually Means | What To Do |
| --- | --- | --- |
| Login fails | Wrong password, inactive account, or server issue | Ask Admin to check the user account. |
| Page is missing | Your role has no permission | Ask supervisor or Admin. |
| Button is disabled | Record is in the wrong status | Complete the previous step first. |
| Bundle cannot be received | Previous department did not send it | Ask previous department to scan/send. |
| Sewing quantity error | Sewing input is higher than upstream passed quantity | Correct quantity or ask previous department to record passed pieces. |
| Package capacity error | Package exceeds 60 pieces | Reduce quantity or request Admin override. |
| Stock shortage | Not enough available stock | Planning and Storage must review material or finished stock. |
| Label does not open | Browser blocked popups | Allow popups for the ERP site or open label again. |
| Wrong record saved | Human entry mistake | Tell supervisor. Admin can inspect audit log. |

## 14. Data Quality Standards

Every department should follow the same data quality standards:

1. Names should be clear and consistent.
2. Quantities must match physical count.
3. Failed, rework, and waste quantities must not be hidden.
4. Notes should explain exceptions, not repeat normal work.
5. Labels must stay attached to the correct bundle or package.
6. Do not create duplicate records to fix a mistake unless the supervisor tells you to.

## 15. Training Plan For New Employees

### Day 1: Overview

1. Explain the full workflow from Sales Order to Shipment.
2. Show login, language switcher, sidebar, tasks, and notifications.
3. Review the employee's department pages.
4. Explain statuses, quantities, and audit log responsibility.

### Day 2: Guided Practice

1. Use a training order or demo record.
2. Let the employee perform the department's main actions with a trainer watching.
3. Practice scanning labels.
4. Practice correcting common form errors.

### Day 3: Supervised Real Work

1. Employee works on real records.
2. Trainer checks every saved record.
3. Supervisor reviews output at end of shift.
4. Employee signs off that they understand the workflow.

## 16. Trainer Sign-Off Checklist

Trainer should confirm the employee can:

1. Log in and log out.
2. Change language if needed.
3. Open the correct department page.
4. Find an order or work item.
5. Read statuses and quantities.
6. Complete the department's main form.
7. Scan a bundle or package if required by the role.
8. Explain what to do when work is blocked.
9. Use tasks or notify a supervisor.
10. Follow data quality rules.

## 17. Who To Contact

| Issue | Contact |
| --- | --- |
| Login or password | Admin |
| Missing page access | Supervisor or Admin |
| Material shortage | Planning and Storage |
| Wrong production quantity | Department supervisor |
| Barcode or printer problem | IT or supervisor |
| Finance mismatch | Finance |
| Waste disposal approval | Management |
| Urgent customer status | Sales and Planning |
