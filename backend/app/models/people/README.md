# People, attendance and payroll

Business-service group guide, relocated into models/ on 24 October 2026. This
directory now contains the turnstile enrollment, edit details, private photo and simulator
services. Other existing implementations remain linked below; proposed files describe
later approved operation extractions.

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

**First operation to study:** Trace payroll.create_period/update_period and the
inline EmployeeIn/EmployeeUpdate DTOs in routes/hr.py. Move Pydantic contracts to
libs/dto/people/ and business rules to the approved models/people/ service
operation. Keep writes in schema-owned persistence operations using the same
supplied Session, retaining locks and field permissions.

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

## Simulator turnstile Add access, Edit details, Replace photo and Revoke access
Public operations are in [turnstile_access_service.py](turnstile_access_service.py),
[turnstile_photo_service.py](turnstile_photo_service.py), and
[turnstile_simulator_service.py](turnstile_simulator_service.py).
ENROLL, EDIT, PHOTO and REVOKE each own one outer request transaction and call explicit schema-owned
mutations with the same supplied Session. Photo upload owns its asset/file lifecycle;
the simulator coordinates separate claim, durable acceptance and readback transactions.
None of these operations writes HR employee details or attendance mirror/event rows. Existing
mirrored identities are refused until a separate adoption operation; reviewed employee
numbers prevent stale identity use and existing bindings cannot be remapped by HR changes.

Private simulator EDIT changes only the reviewed name on selected verified bindings.
The service checks each reviewed revision and profile hash against trusted complete
simulator evidence under locks, freezes the baseline and uses a conditional name update
at acceptance. It preserves each device's photo and external identity. Uncertain outcomes
are reconciled through readback; a public actor/factory/employee/action-scoped receipt
lookup resolves a saved request key without submitting a new operation. HR Save remains
independent. Adoption and live-device writes remain pending.

Private simulator PHOTO replaces only the photo on selected verified bindings. It uses
the shared reviewed baseline references and a validated immutable asset with manual
attestation. Each target retains its own frozen name and external identity; its previous
photo remains until that target durably accepts the replacement. Existing and new asset
rows and files are retained. The operation's full_name is an informational HR snapshot,
not the desired name on each target. Unknown simulator acceptance uses read-only
reconciliation; the scoped receipt lookup matches the saved action, asset and target
baseline references. PHOTO is AI_VERIFIED_AWAITING_HUMAN; prior human gates remain unrecorded.

Private simulator REVOKE requires selected trusted ACTIVE bindings and freezes each
reviewed complete baseline. A conditional update tombstones each accepted profile once;
a tombstone has `present=false` and retains historical name, identity and photo metadata.
An uncertain outcome is read-only: bare absence does not prove success. Revoked identity
is not recycled or automatically re-enrolled. HR archive and revocation are separate;
an already archived employee can still have verified gate access revoked. This slice is
**AI_VERIFIED_AWAITING_HUMAN** after automated, PostgreSQL, actual visual/data and independent review. The owner's latest
instruction places the QA master human check before deployment; it does not pause source
integration or the next slice.

See the [REVOKE packet](../../../../docs/TURNSTILE_REVOKE_20261104.md),
the historical [ENROLL evidence](../../../../docs/TURNSTILE_ACCESS_BACKEND_20261103.md),
the [EDIT task and evidence packet](../../../../docs/TURNSTILE_EDIT_DETAILS_20261103.md),
and the [PHOTO task packet](../../../../docs/TURNSTILE_PHOTO_REPLACEMENT_20261104.md).
Prior ENROLL, EDIT and PHOTO evidence remains historical; their human gates are unrecorded.

Payroll adjustments and reversals use `payroll_adjustments_service.py`; period totals and audit semantics are preserved.

`turnstile_live_service.py` owns the separate, default-off physical-device intent,
observation/adoption, single-use dispatch, result and recovery operations. Its
same-session mutations are in `schemas/people/turnstile_live_persistence.py`;
only the separate LAN worker performs device I/O. Revoke keeps credentials;
Delete requires completed native deletion and independent credential absence.
Simulator evidence cannot authorize live ownership. The local implementation
has code checks; new visual testing is owner-deferred and firmware/pilot gates
remain open. See [the packet](../../../../docs/TURNSTILE_LIVE_INTEGRATION_20261109.md).

`payroll_qr_service.py` also owns unscanned edit/split/batch deletion, preserving identity and history guards.
