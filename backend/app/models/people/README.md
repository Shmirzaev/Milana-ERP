# People, attendance and payroll

Business-service group guide, relocated into models/ on 24 October 2026. This
directory remains README-only; existing implementations are the *_service.py files
linked below. The proposed files describe later approved operation extractions.

**Purpose:** Own employee/department records, HR workflows, attendance ingestion and payroll. Keep those responsibilities in separate files.

**Engineering owner:** Dilmurod. **Reviewer:** Mirshoir.
**Business acceptance:** Shavkat with operators.
This owner covers the feature's routes, DTOs, enums, database definitions and tests.
See [team ownership](../../../../docs/TEAM_OWNERSHIP.md) for shared-layer coordination.

## Existing code to study first

- Routes: [hr.py](../../api/routes/hr.py), [hr_workspace.py](../../api/routes/hr_workspace.py), [attendance.py](../../api/routes/attendance.py), [payroll.py](../../api/routes/payroll.py), [admin.py](../../api/routes/admin.py).
- Services/helpers: [attendance_event_policy_service.py](../attendance_event_policy_service.py), [attendance_reports_service.py](../attendance_reports_service.py), [employee_aliases_service.py](../employee_aliases_service.py), [employee_export_service.py](../employee_export_service.py), [employee_names_service.py](../employee_names_service.py), [employee_reconciliation_service.py](../employee_reconciliation_service.py), [payroll_factory_scope_service.py](../payroll_factory_scope_service.py), [payroll_labels_service.py](../payroll_labels_service.py), [payroll_reports_service.py](../payroll_reports_service.py).
- Existing SQLAlchemy schema models: [AttendanceDevice](../../schemas/people/attendance.py#L11), [AttendancePerson](../../schemas/people/attendance.py#L39), [AttendanceEvent](../../schemas/people/attendance.py#L66), [Department](../../schemas/core.py#L15), [Employee](../../schemas/core.py#L43), [HrOrgUnit](../../schemas/people/hr.py#L11), [HrPosition](../../schemas/people/hr.py#L27), [HrEmployeeDocument](../../schemas/people/hr.py#L44), [HrRecruitmentCandidate](../../schemas/people/hr.py#L60), [HrCalendarEvent](../../schemas/people/hr.py#L91), [PayrollPeriod](../../schemas/people/payroll.py#L11), [PayrollRecord](../../schemas/people/payroll.py#L36), [PayrollQrLabel](../../schemas/people/payroll.py#L89), [PayrollAdjustment](../../schemas/people/payroll.py#L142).
- Existing Pydantic contracts: [payroll.py](../../libs/dto/people/payroll.py).

These are source pointers, not permission to move entire mixed files. Trace the
particular operation and every caller/write before choosing what belongs here.

## When making a service file

| Proposed file | Responsibility |
| --- | --- |
| `employees_service.py` | Employee/department and hr operations. |
| `attendance_service.py` | Attendance/device ingestion rules. |
| `payroll_service.py` | Period, work record and adjustment operations. |

Use snake_case_service.py filenames and operation names such as `create_*`, `record_*`,
`receive_*` or `approve_*`. A typed function is sufficient; a class is optional
when it owns real dependencies. Accept the Session, validated input and actor
explicitly. State the transaction owner, refusal rules and result contract.
Use the existing ORM definitions in schemas/ and DTOs in libs/dto/<feature>/;
keep fixed values in libs/enums/. See [DTO conventions](../../libs/dto/README.md).
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
