# Management / Admin Training Manual

Version: 1.0
Date: 2026-07-02
Department code: ADM
Default roles: Management, Admin

## Purpose

Management monitors the business process and approves exceptions. Admin manages normal application administration such as users, departments, audit review, settings, and operational corrections. Super Admin has additional controls documented separately.

## Main Pages

- Dashboard
- Process Tracking
- Traceability
- Forecasting
- Payroll Summary
- Users
- Departments
- Employees
- Audit Logs
- Settings
- Waste Dashboard
- Models
- Production Orders
- Tasks and Notifications

## Management Key Permissions

- `management.view`
- `management.approve`
- `finance.view`
- `admin.audit`
- `tasks.manage`
- `processes.view`
- `sewing.flows`
- `traceability.view`
- `traceability.export`
- `forecasting.view`
- `forecasting.manage`
- `payroll.view`
- `payroll.manage`
- `payroll.approve`
- `purchasing.approve`
- `production.override_deadline`

## Admin Key Permission

- `*`

The Admin role has full app access. Keep the number of Admin users small.

## Daily Management Workflow

1. Review dashboard KPIs.
2. Review Process Tracking for overdue or blocked orders.
3. Review production bottlenecks by stage.
4. Review waste, finance, and payroll signals.
5. Approve or reject waste disposal requests.
6. Approve payroll periods when ready.
7. Review forecasting recommendations.
8. Assign tasks and follow up.
9. Review audit logs when unusual activity is reported.

## User Management

Use Users page to:

1. Create user.
2. Assign role.
3. Assign department.
4. Activate/deactivate user.
5. Review activity: online recently, active this week, not using.
6. Reset password by editing user where policy allows.
7. Add extra permissions only when the role is not enough.

Rules:

1. Give the least access needed for the job.
2. Do not grant Admin or Super Admin access casually.
3. Deactivate users who leave the company.
4. Do not delete the last active admin.
5. Keep HR employee records aligned with user access.

## Extra Permissions

Extra permissions are for exceptions. Prefer role-based access first.

Examples:

1. A planner who also needs `purchasing.request`.
2. A supervisor who needs `payroll.scan`.
3. A manager who needs `traceability.export`.

Avoid giving `*` unless the person is truly an Admin.

## Department Management

Use Departments page to add or update department name/code.

Rules:

1. Department code should be short and stable.
2. Do not delete a department assigned to users, employees, or work orders.
3. Coordinate department changes with Admin and Planning before editing codes used by floor pages.

## Audit Logs

Audit Logs show who changed what and when.

Use filters:

1. Search text.
2. User ID.
3. Action.
4. Entity.
5. Entity ID.
6. Date range.

Open details to compare before/after values. Use audit logs for investigation, not for blame. The goal is to find the cause and correct the process.

## Settings

Settings include:

1. Company name, logo, address, phone, email.
2. Default currency and fiscal year start month.
3. Default language and timezone.
4. Model type options.
5. Require material reservation before cutting.

Change settings carefully because they affect all departments.

## Approvals And Exceptions

Management/Admin may approve:

1. Model approval.
2. Waste disposal.
3. Payroll period approval.
4. Package change or capacity exceptions.
5. Deadline overrides or production unblocks.

Approval rule: approve only after checking the related record, physical reality, and business reason.

## Process Tracking Supervision

1. Search by Production Order, Sales Order, customer, or model.
2. Check current stage.
3. Open stage details.
4. Check blocked stage and reason.
5. Open Production Order.
6. Assign or split sewing work if needed.
7. Print/save process report when needed.

## Tasks And Notifications

Use tasks for cross-department follow-up.

Good task examples:

1. Check shortage for a Sales Order.
2. Reprint missing package labels.
3. Approve disposal request.
4. Confirm wrong batch before production continues.

Notifications should be checked at the start and end of shift.

## Common Problems

| Problem | Likely cause | Action |
| --- | --- | --- |
| Employee cannot see page | Role/permission missing | Review user role and extra permissions. |
| User has too much access | Extra permission or Admin role | Remove extra access and assign correct role. |
| Department cannot be deleted | It is used by users/employees/work orders | Reassign records or keep department active. |
| Wrong production data | User saved incorrect record | Review audit log and correct through authorized workflow. |
| Cutting blocked by reservation | Setting requires full reservation | Resolve reservations or management exception. |

