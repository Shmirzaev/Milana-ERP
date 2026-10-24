# People, attendance and payroll: database schema models

**Engineer:** Dilmurod. **Reviewer:** Mirshoir. **Business acceptance:** Shavkat.

Employees, departments, attendance evidence, payroll periods, earnings and adjustments.

Documentation scaffold only. Existing SQLAlchemy classes still live in `app/models/`;
existing Pydantic DTOs still live in the parent `app/schemas/` files. No ORM or DTO
code moves in this scaffold. Business services live in `models/*_service.py`.

## Existing definitions to migrate

- [AttendanceDevice](../../models/attendance.py)
- [AttendancePerson](../../models/attendance.py)
- [AttendanceEvent](../../models/attendance.py)
- [Department](../../models/core.py)
- [Employee](../../models/core.py)
- [HrOrgUnit](../../models/hr.py)
- [HrPosition](../../models/hr.py)
- [HrEmployeeDocument](../../models/hr.py)
- [HrRecruitmentCandidate](../../models/hr.py)
- [HrCalendarEvent](../../models/hr.py)
- [PayrollPeriod](../../models/payroll.py)
- [PayrollRecord](../../models/payroll.py)
- [PayrollQrLabel](../../models/payroll.py)
- [PayrollAdjustment](../../models/payroll.py)

These are the ownership map's proposed destinations, not permission to move a whole
mixed source file. Keep one authoritative mapping for each existing table.

## How to make a file here

1. Trace the approved business operation in [the service guide](../../models/people/README.md),
   its route, current model, DTO, database writes and other callers.
2. First migrate current Pydantic DTOs and callers to `libs/dto/<feature>/`.
   Retire all old DTO imports/shims before activating ORM code under `schemas/`.
3. Use a descriptive `snake_case.py` file for related existing model definitions.
   Reuse the existing SQLAlchemy Base and classes; preserve table/column names,
   keys, indexes, relationships, constraints, defaults and serialized enum values.
4. Keep only persistence definitions here. Create/update/read validation belongs
   in DTOs; permissions, status transitions, calculations, queries and coordinated
   writes belong in business services under `models/`. Schema classes do not commit transactions.
5. Update callers, model registration and Alembic discovery together. Require one
   mapping per table and no database-schema difference for a source-only move.
6. Check contracts and PostgreSQL behavior, visually exercise the affected factory
   workflow, then verify bounded stress/retries and adjacent department handoffs.
   Remove old paths only after the agreed acceptance and rollback conditions pass.

Do not add `__init__.py` or Python implementation files during this scaffold step.
Some group names collide with current DTO `.py` modules; package conversion must
be coordinated, not silently shadow those modules.

See [schema migration rules](../README.md), [DTO conventions](../../libs/dto/README.md),
[the business plan](../../../../docs/REFACTOR_PLAN.md) and
[team ownership](../../../../docs/TEAM_OWNERSHIP.md).
