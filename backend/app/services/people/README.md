# People, attendance and payroll

Documentation scaffold authorized on 24 October 2026. No Python package or business
logic has been created here. The files below are destinations for approved work.

**Purpose:** Own employee/department records, HR workflows, attendance ingestion and payroll. Keep those responsibilities in separate files.

**Engineering owner:** Dilmurod. **Reviewer:** Mirshoir.
**Business acceptance:** Shavkat with operators.
This owner covers the feature's routes, DTOs, enums, database definitions and tests.
See [team ownership](../../../../docs/TEAM_OWNERSHIP.md) for shared-layer coordination.

## Existing code to study first

- Routes: [hr.py](../../api/routes/hr.py), [hr_workspace.py](../../api/routes/hr_workspace.py), [attendance.py](../../api/routes/attendance.py), [payroll.py](../../api/routes/payroll.py), [admin.py](../../api/routes/admin.py).
- Services/helpers: [attendance_event_policy.py](../attendance_event_policy.py), [attendance_reports.py](../attendance_reports.py), [employee_aliases.py](../employee_aliases.py), [employee_export.py](../employee_export.py), [employee_names.py](../employee_names.py), [employee_reconciliation.py](../employee_reconciliation.py), [payroll_factory_scope.py](../payroll_factory_scope.py), [payroll_labels.py](../payroll_labels.py), [payroll_reports.py](../payroll_reports.py).
- Existing SQLAlchemy schema models: [AttendanceDevice](../../models/attendance.py#L11), [AttendancePerson](../../models/attendance.py#L39), [AttendanceEvent](../../models/attendance.py#L66), [Department](../../models/core.py#L15), [Employee](../../models/core.py#L43), [HrOrgUnit](../../models/hr.py#L11), [HrPosition](../../models/hr.py#L27), [HrEmployeeDocument](../../models/hr.py#L44), [HrRecruitmentCandidate](../../models/hr.py#L60), [HrCalendarEvent](../../models/hr.py#L91), [PayrollPeriod](../../models/payroll.py#L11), [PayrollRecord](../../models/payroll.py#L36), [PayrollQrLabel](../../models/payroll.py#L89), [PayrollAdjustment](../../models/payroll.py#L142).
- Existing Pydantic contracts: [payroll.py](../../schemas/payroll.py).

These are source pointers, not permission to move entire mixed files. Trace the
particular operation and every caller/write before choosing what belongs here.

## When making a service file

| Proposed file | Responsibility |
| --- | --- |
| `employees.py` | Employee/department and hr operations. |
| `attendance.py` | Attendance/device ingestion rules. |
| `payroll.py` | Period, work record and adjustment operations. |

Use snake_case filenames and operation names such as `create_*`, `record_*`,
`receive_*` or `approve_*`. A typed function is sufficient; a class is optional
when it owns real dependencies. Accept the Session, validated input and actor
explicitly. State the transaction owner, refusal rules and result contract.
Use the existing ORM models. Migrate existing schemas/ DTOs to libs/dto/<feature>/
with their callers; keep fixed values in libs/enums/. See [DTO conventions](../../libs/dto/README.md).
Do not import routers, call an endpoint, or commit inside a helper owned by another
transaction. Do not create an interface/repository or generic CRUD class by default.

**First operation to study:** Trace payroll.create_period/update_period and the inline EmployeeIn/EmployeeUpdate DTOs in routes/hr.py. Move contracts to schemas and rules to the appropriate operation while retaining locks and field permissions.

**DTOs and enums:** Employee, attendance and payroll-period states; fixed vocabulary does not permit client-controlled pay or bypass period approval. Reuse Create/In, Update and Read/Out contracts
where they exist. Add action-specific input only for a real action. Do not generate
three DTOs for every table or expose privileged fields through generic updates.

## Boundaries and verification

Identity owns login accounts/permissions; Production supplies work evidence. Payroll owns monetary accrual and approvals. Do not merge these into one large PeopleService class.

Verify overlapping periods, duplicate scans, locked/paid periods, reversals, factory scope and protected salary fields. Visually check employee editing, attendance reconciliation and payroll approval with allowed/denied roles.

## Migration steps

Follow [the shared sequence](../README.md#migration-sequence): study route/DB/rules
and callers -> agree one operation -> capture baseline tests -> extract -> test
old/new separately -> test the real UI on isolated data -> reviewed switch -> human
production verification -> remove old code. Keep one write path per request.
Record the test result, visual evidence, approver and cleanup condition in the task.
Visual success alone does not prove permissions, concurrency or data correctness.
