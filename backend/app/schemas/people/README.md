# People, attendance and payroll: database schema models

**Engineer:** Dilmurod. **Reviewer:** Mirshoir. **Business acceptance:** Shavkat.

Employees, departments, attendance evidence, payroll periods, earnings and adjustments.

SQLAlchemy definitions now live under app/schemas/; Pydantic DTOs live in
app/libs/dto/. The links below show the authoritative definitions for this group's
records. Business services live in models/*_service.py.

## Authoritative definitions

- [AttendanceDevice](attendance.py)
- [AttendancePerson](attendance.py)
- [AttendanceEvent](attendance.py)
- [Department](../core.py)
- [Employee](../core.py)
- [HrOrgUnit](hr.py)
- [HrPosition](hr.py)
- [HrEmployeeDocument](hr.py)
- [HrRecruitmentCandidate](hr.py)
- [HrCalendarEvent](hr.py)
- [PayrollPeriod](payroll.py)
- [PayrollRecord](payroll.py)
- [PayrollQrLabel](payroll.py)
- [PayrollAdjustment](payroll.py)

These links follow business ownership; some point to mixed files in another group
or shared core.py. Keep one authoritative mapping per table. Moving individual
classes out of mixed files is a separate approved change.

## How to make a file here

1. Trace the approved business operation in [the service guide](../../models/people/README.md),
   its route, current model, DTO, database writes and other callers.
2. Reuse Pydantic contracts from `libs/dto/<feature>/`; never define DTOs here.
   Find existing mapped classes before adding a new persistence definition.
3. Use a descriptive `snake_case.py` file for related existing model definitions.
   Reuse the existing SQLAlchemy Base and classes; preserve table/column names,
   keys, indexes, relationships, constraints, defaults and serialized enum values.
4. Keep persistence definitions and persistence operations here. Create/update/read validation belongs
   in DTOs; permissions, status transitions, calculations, queries and
   write coordination belong in business services under `models/`. Actual
   inserts, updates, deletes and mapped mutations belong in schema-owned
   operations using the supplied Session; helpers never commit independently.
   Follow the [engineering workflow](../../../../docs/ENGINEERING_WORKFLOW.md).
5. Update callers, model registration and Alembic discovery together. Require one
   mapping per table and no database-schema difference for a source-only move.
6. Check contracts and PostgreSQL behavior, visually exercise the affected factory
   workflow, then verify bounded stress/retries and adjacent department handoffs.
   Remove old paths only after the agreed acceptance and rollback conditions pass.

Only groups with actual definitions are Python packages. A guide without Python
files points to its existing definitions elsewhere; it is not a request to create
duplicate classes or empty implementation files.

See [schema migration rules](../README.md), [DTO conventions](../../libs/dto/README.md),
[the business plan](../../../../docs/REFACTOR_PLAN.md) and
[team ownership](../../../../docs/TEAM_OWNERSHIP.md).

## Simulator-only turnstile enrollment, edit, photo replacement and revocation
[turnstile.py](turnstile.py) defines scoped photo assets, immutable operation snapshots,
employee/device bindings, per-device targets and independent simulator records.
[turnstile_persistence.py](turnstile_persistence.py) owns typed mutations using the
caller's Session; it never commits. Migration 0151 adds the original tables and
prerequisite employee/device composite keys. Migration 0152 permits EDIT's null photo
asset and stores immutable per-target baseline and desired references, with constraints
on their presence and shape. Its downgrade refuses when EDIT or baseline data exists;
it does not discard history.

The EDIT conditional update matches the complete frozen simulator evidence and changes
only name, accepted revision/hash and write count. A mismatch cannot overwrite drifted
identity or photo. Existing attendance tables retain their behavior; no mirrored profile
or event writer was replaced. See the historical [ENROLL ledger](../../../../docs/TURNSTILE_ACCESS_BACKEND_20261103.md)
and the [EDIT evidence packet](../../../../docs/TURNSTILE_EDIT_DETAILS_20261103.md).

PHOTO reuses the 0152 per-target baseline and desired references; it requires a nonnull
immutable photo asset and introduces no migration. The existing 0152 downgrade guard
refuses to discard PHOTO baseline history. The conditional photo update compares the
complete frozen evidence and changes only photo hash, accepted revision/hash and write
count; it preserves each target's name and external identity. Prior and new photo asset
rows and files are retained, with the previous photo remaining until each target accepts.
The operation full_name is an informational HR snapshot, not a target desired name.
See the [PHOTO task packet](../../../../docs/TURNSTILE_PHOTO_REPLACEMENT_20261104.md);
verification is AI_VERIFIED_AWAITING_HUMAN.


REVOKE uses the frozen complete per-target baseline and a single conditional simulator
update. Migration 0153 allows REVOKE's null photo asset and adds the non-null `present`
flag; a false value is a durable tombstone, with historical profile metadata retained.
The typed readback distinguishes that tombstone from a missing row. A missing row alone
is never proof of success, and an uncertain revoke is reconciled by readback without
another write. Existing bindings remain reserved and cannot be automatically recycled.
The 0153 downgrade preflights before DDL and refuses REVOKE history, tombstones or
revocation evidence; evidence detection checks the exact JSON action, not profile text.
Compatible history can downgrade to the 0152 constraints. See the
[REVOKE packet](../../../../docs/TURNSTILE_REVOKE_20261104.md); this slice remains
**AI_VERIFIED_AWAITING_HUMAN** after independent source/evidence review.
