# Production execution: database schema models

**Engineer:** Mirshoir. **Reviewer:** Ismail. **Business acceptance:** Shavkat.

Production orders, Nastils, cutting passports, work orders, bundles, Printing and Sewing evidence. Keep each Nastil traceable.

SQLAlchemy definitions now live under app/schemas/; Pydantic DTOs live in
app/libs/dto/. The links below show the authoritative definitions for this group's
records. Business services live in models/*_service.py.

## Authoritative definitions

- [CuttingPassport](cutting_passport.py)
- [ProductionOrder](production.py)
- [ProductionOrderMaterial](production.py)
- [ProductionBatch](production.py)
- [ProductionOrderItem](production.py)
- [WorkOrder](production.py)
- [same-Session creation persistence](production_persistence.py)
- [CuttingRecord](production.py)
- [CuttingMaterialUsage](production.py)
- [CuttingBeikaMaterialUsage](production.py)
- [PrintingRecord](production.py)
- [SewingRecord](production.py)
- [SewingReplacementRequest](production.py)
- [QualityCheck](production.py)
- [SewingAssignment](sewing_assignment.py)
- [SewingDailyReport](sewing_daily_report.py)
- [SewingFlow](sewing_flow.py)
- [Bundle](tracking.py)
- [BundleScanLog](tracking.py)

These links follow business ownership; some point to mixed files in another group
or shared core.py. Keep one authoritative mapping per table. Moving individual
classes out of mixed files is a separate approved change.

`production_persistence.py` owns focused constructors and mapped workflow-state
mutations for ProductionOrder, material/item children, ProductionBatch and
WorkOrder creation. It accepts typed values from the service, flushes using the
supplied Session at the preserved operation boundaries, and never commits. The
Production services continue to own eligibility, numbering, stock checks,
department selection and transition decisions. This helper file does not imply
that all Production writers or lifecycle operations are schema-owned or verified.

## How to make a file here

1. Trace the approved business operation in [the service guide](../../models/production/README.md),
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
