# Super Admin Full Details Training Manual

Version: 1.0
Date: 2026-07-02
Department code: ADM
Role: Super Admin

## Purpose

Super Admin has the highest level of ERP access. Super Admin can do everything Admin can do, plus Super Admin-only features such as MCP Access and the raw Data Console.

Use this role only for trusted system owners. Do not use Super Admin for normal daily department work.

## Super Admin Access

Super Admin is identified by either:

1. Role name `Super Admin`.
2. Permission `admin.super`.

Seeded Super Admin permissions:

1. `*`
2. `admin.super`

The `*` permission grants full ERP application access. The `admin.super` permission unlocks Super Admin-only sections.

## Super Admin-Only Pages

- MCP Access
- Data Console

Super Admin also has access to all normal app pages, including users, departments, audit logs, settings, dashboards, production, finance, payroll, purchasing, inventory, traceability, and all department pages.

## First Admin Bootstrap

The seed process creates a Super Admin bootstrap user when configured.

Important rules:

1. `INITIAL_ADMIN_PASSWORD` must be set to activate the first admin.
2. Default shared demo/admin passwords are blocked for the real admin account.
3. `INITIAL_ADMIN_EMAIL` can set the first admin email.
4. Demo users are only created when `SEED_DEMO_USERS=true`.
5. Sample customers/material/models/orders are only created when `SEED_SAMPLE_DATA=true`.

## User Administration

Super Admin can create and manage Admin and Super Admin accounts. Normal Admins are restricted from assigning Super Admin control.

User creation:

1. Open Users.
2. Enter name and email.
3. Select role.
4. Select department.
5. Create user.
6. Confirm setup email/password process according to deployment policy.

User edit:

1. Open user edit.
2. Update name/email.
3. Set new password only when policy allows.
4. Change role.
5. Change department.
6. Add or remove extra permissions.
7. Activate/deactivate.
8. Save.

Super Admin rules:

1. Keep at least one active Super Admin/Admin account.
2. Do not assign `*` or `admin.super` to temporary users.
3. Disable accounts immediately when a person leaves.
4. Review last seen/last login for stale privileged accounts.
5. Avoid sharing a single Super Admin account.

## Permission Model

Roles contain permissions. Users may also have extra permissions.

Core permission categories:

1. Sales: `sales.orders`, `sales.customers`.
2. Planning: `planning.view`, `planning.requirements`, `planning.production`, `planning.reserve_materials`, `processes.view`, `sewing.flows`.
3. Modeling: `modeling.models`, `modeling.bom`, `modeling.brands`, `modeling.collections`, `modeling.approve`.
4. Production floor: `cutting.records`, `cutting.bundles`, `printing.records`, `printing.bundles`, `sewing.records`, `sewing.bundles`, `packaging.records`, `packaging.packages`, `production.override_deadline`.
5. Storage and shipment: `storage.receive`, `storage.transfer`, `storage.items`, `storage.suppliers`, `storage.packages`, `storage.shipment`.
6. Finance: `finance.view`, `finance.invoice`, `finance.payment`.
7. HR and payroll: `hr.employees`, `payroll.view`, `payroll.manage`, `payroll.approve`, `payroll.pay`, `payroll.scan`.
8. Purchasing: `purchasing.view`, `purchasing.request`, `purchasing.approve`, `purchasing.order`, `purchasing.receive`.
9. Waste: `waste.receive`, `waste.sell`, `waste.disposal`.
10. Management/Admin: `management.view`, `management.approve`, `admin.users`, `admin.audit`, `admin.super`, `tasks.manage`.
11. Traceability/forecasting: `traceability.view`, `traceability.export`, `forecasting.view`, `forecasting.manage`.
12. Inventory reservations: `inventory.reservations.view`, `inventory.reservations.create`, `inventory.reservations.release`, `inventory.reservations.consume`.

Use roles first. Use extra permissions only for deliberate exceptions.

## Seeded Departments

| Code | Department |
| --- | --- |
| SLS | Sales |
| PLN | Planning |
| STR | Fabric & Accessories Storage |
| CUT | Cutting |
| PRT | Printing |
| SEW | Sewing |
| MIL | Milana Sewing Factory |
| BST | Besttex Sewing Factory |
| PKG | Packaging |
| BPK | Besttex Textile Packaging |
| FGS | Ready Product Storage |
| FIN | Finance |
| MOD | Modeling / PLM |
| HR | HR |
| WST | Waste Department |
| ADM | Management / Admin |

## Seeded Roles

| Role | Main intent |
| --- | --- |
| Super Admin | Full system owner plus Super Admin-only tools. |
| Admin | Full app access without explicit Super Admin-only privilege. |
| Management | Dashboards, approvals, tracking, payroll/purchasing/forecasting oversight, emergency floor access. |
| Sales | Sales Orders, customers, tracking, traceability, forecasting read. |
| Planning | Production planning, reservations, purchasing requests/orders, forecasting. |
| Modeling | Models, BOM, brands, collections, approvals. |
| Storage | Inventory, suppliers, receiving, reservations, purchasing receiving, traceability. |
| Cutting | Cutting records, bundles, payroll scan, traceability. |
| Printing | Printing records, bundles, payroll scan, traceability. |
| Sewing | Sewing records, bundles, payroll scan, traceability. |
| Packaging | Packaging records, packages, payroll scan, traceability. |
| ReadyStorage | Storage packages, shipment, traceability export. |
| Waste | Waste receive/sell/disposal. |
| Finance | Finance view, invoices, payments, purchasing/payroll/forecasting visibility. |
| HR | Employees, payroll view/manage. |

## Data Console

Data Console is Super Admin-only and exposes database tables through `/api/admin/super-data`.

Capabilities:

1. List all tables.
2. View row counts.
3. Search rows.
4. Edit editable columns.
5. Delete rows.
6. View column type, primary key, foreign key, nullable, editable metadata.

Restrictions:

1. Primary keys are read-only.
2. Binary columns are read-only.
3. Tables without a single-column primary key cannot be edited/deleted through this console.
4. Database constraints can block updates/deletes.
5. Super Data updates and deletes are audit logged.

Data Console safety rules:

1. Prefer normal ERP pages for corrections.
2. Use Data Console only when no normal workflow exists.
3. Inspect related records before editing a foreign key.
4. Never delete production records casually.
5. Do not edit financial, payroll, or audit records without written approval.
6. Take a backup or export before risky bulk correction.
7. Change one row, verify, then continue.
8. Record the reason in an external change log or task.

## MCP Access

MCP Access is Super Admin-only and shows setup details for the Milana ERP AI GM Assistant.

The page shows:

1. Server name.
2. Display name.
3. ERP API base URL.
4. Transport.
5. Python module.
6. Package name.
7. Runtime access notes.
8. Environment placeholders.
9. Claude Desktop config.
10. Read tools.
11. Write tools.
12. Security notes.
13. Blocked actions.

MCP token rules:

1. Use a real ERP bearer token for the GM/Super Admin account only when required.
2. Do not paste live credentials into screenshots, tickets, or chat.
3. Rotate token/password if exposed.
4. MCP tools still obey ERP API permissions.
5. Blocked actions must stay blocked unless product owner explicitly changes policy.

## System Settings

Super Admin can update Settings:

1. Company name.
2. Company logo.
3. Address.
4. Phone.
5. Email.
6. Default currency.
7. Fiscal year start month.
8. Default language.
9. Timezone.
10. Model type options.
11. Require material reservation before cutting.

High-impact setting: require material reservation before cutting. When enabled, cutting can be blocked until BOM materials are reserved. Turn it on only after Storage, Planning, and Cutting are trained.

## Audit And Investigation

Audit Logs support:

1. Search.
2. Filter by user.
3. Filter by action.
4. Filter by entity type.
5. Filter by entity ID.
6. Filter by date range.
7. Show details with before/after values.
8. Hash-chain export/verify endpoints exist for audit integrity workflows.

Investigation process:

1. Identify affected entity and ID.
2. Open audit logs filtered to entity and ID.
3. Review timeline.
4. Compare before/after values.
5. Identify user, action, and root cause.
6. Correct using normal page where possible.
7. Use Data Console only if normal page cannot correct it.
8. Document the correction.

## Critical Business Process Supervision

Super Admin should know the full chain:

1. Sales Order.
2. Model/BOM approval.
3. Planning and Production Order.
4. Material reservations.
5. Purchase requests/orders/receiving.
6. Cutting records and bundles.
7. Bundle scans through Printing/Sewing.
8. Sewing records and assignments.
9. Packaging records and packages.
10. Package scans to storage.
11. Shipment package scans.
12. Finance invoices/payments.
13. Payroll scans/periods/approval/payment.
14. Waste receive/sell/disposal.
15. Traceability and audit review.

## Backup And Recovery Awareness

Super Admin should know where the production readiness, disaster recovery, security runbook, privacy/retention, and architecture docs are located:

1. `docs/PRODUCTION_READINESS.md`
2. `docs/DISASTER_RECOVERY.md`
3. `docs/SECURITY_RUNBOOK.md`
4. `docs/PRIVACY_RETENTION.md`
5. `docs/ARCHITECTURE.md`

Before risky data maintenance, confirm backup availability and rollback plan.

## Security Rules

1. Use strong passwords.
2. Do not share privileged accounts.
3. Keep Super Admin count minimal.
4. Review active privileged accounts regularly.
5. Disable inactive privileged accounts.
6. Protect integration tokens.
7. Do not bypass audit logs.
8. Use HTTPS/public deployment security settings when exposed to the internet.
9. Do not seed demo users in production.
10. Do not enable sample data in production.

## When To Use Super Admin

Use Super Admin for:

1. Creating or fixing Admin/Super Admin access.
2. Viewing MCP setup.
3. Emergency Data Console correction.
4. Investigating critical audit or data-integrity issues.
5. System-level settings.
6. Recovery coordination.

Do not use Super Admin for:

1. Normal sales entry.
2. Normal production output.
3. Normal payroll scanning.
4. Routine receiving.
5. Any action a department role can safely do.

## Super Admin Daily/Weekly Checklist

Daily:

1. Check system health and login availability.
2. Review any urgent access requests.
3. Review failed or blocked critical processes.
4. Check privileged account changes.
5. Review unresolved high-priority tasks.

Weekly:

1. Review Admin/Super Admin users.
2. Review users not using the system.
3. Review audit logs for deletes and privileged changes.
4. Check backup status.
5. Review settings changes.
6. Review integration health.
7. Confirm training gaps with department managers.

## Emergency Correction Checklist

1. Stop the affected physical process if needed.
2. Identify exact records and IDs.
3. Review audit logs.
4. Confirm desired correction with department owner.
5. Prefer normal page correction.
6. If Data Console is required, edit one row at a time.
7. Verify downstream records.
8. Add a task/note describing correction.
9. Notify affected departments.

## Common Super Admin Risks

| Risk | Prevention |
| --- | --- |
| Accidentally deleting linked production data | Prefer normal pages; check foreign keys and backups first. |
| Granting too much access | Use least privilege and role-based access. |
| Demo credentials in production | Keep `SEED_DEMO_USERS=false` and set strong initial admin password. |
| Exposed MCP/API token | Rotate credentials immediately. |
| Cutting blocked unexpectedly | Check material reservation setting and reservation status. |
| Payroll paid before approval | Enforce period status flow: open -> locked -> approved -> paid. |
| Finance values wrong | Validate BOM, stock costs, production output, package costs, and payroll source data. |

