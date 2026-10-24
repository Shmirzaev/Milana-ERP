# Production execution

Documentation scaffold authorized on 24 October 2026. No Python package or business
logic has been created here. The files below are destinations for approved work.

**Purpose:** Own production orders, work orders and manufacturing-stage rules: cutting, printing, sewing, bundle handoffs and quality evidence.

**Engineering owner:** Mirshoir. **Reviewer:** Ismail.
**Business acceptance:** Shavkat with operators.
This owner covers the feature's routes, DTOs, enums, database definitions and tests.
See [team ownership](../../../../docs/TEAM_OWNERSHIP.md) for shared-layer coordination.

## Existing code to study first

- Routes: [production.py](../../api/routes/production.py), [production_extra.py](../../api/routes/production_extra.py), [bundles.py](../../api/routes/bundles.py), [cutting_passports.py](../../api/routes/cutting_passports.py), [sewing_bands.py](../../api/routes/sewing_bands.py), [sewing_corrections.py](../../api/routes/sewing_corrections.py), [sewing_daily_reports.py](../../api/routes/sewing_daily_reports.py), [sewing_flows.py](../../api/routes/sewing_flows.py), [usluga.py](../../api/routes/usluga.py).
- Services/helpers: [bundles.py](../bundles.py), [cutting_batch_delete.py](../cutting_batch_delete.py), [cutting_batch_guard.py](../cutting_batch_guard.py), [cutting_fabric_usage.py](../cutting_fabric_usage.py), [cutting_material_assignment.py](../cutting_material_assignment.py), [cutting_passport_reports.py](../cutting_passport_reports.py), [cutting_passport_usage.py](../cutting_passport_usage.py), [cutting_sewing_factory.py](../cutting_sewing_factory.py), [cutting_sheet.py](../cutting_sheet.py), [deferred_cutting_usage.py](../deferred_cutting_usage.py), [first_grade.py](../first_grade.py), [passport_nastil.py](../passport_nastil.py), [passport_sizes.py](../passport_sizes.py), [production.py](../production.py), [production_sizes.py](../production_sizes.py), [sewing_band_progress.py](../sewing_band_progress.py), [sewing_band_setup.py](../sewing_band_setup.py), [sewing_daily_report_exports.py](../sewing_daily_report_exports.py), [sewing_input.py](../sewing_input.py), [sewing_scope.py](../sewing_scope.py), [process_qr_export.py](../process_qr_export.py).
- Existing SQLAlchemy schema models: [CuttingPassport](../../models/cutting_passport.py#L14), [ProductionOrder](../../models/production.py#L49), [ProductionOrderMaterial](../../models/production.py#L114), [ProductionBatch](../../models/production.py#L142), [ProductionOrderItem](../../models/production.py#L164), [WorkOrder](../../models/production.py#L181), [CuttingRecord](../../models/production.py#L240), [CuttingMaterialUsage](../../models/production.py#L310), [CuttingBeikaMaterialUsage](../../models/production.py#L340), [PrintingRecord](../../models/production.py#L375), [SewingRecord](../../models/production.py#L395), [SewingReplacementRequest](../../models/production.py#L423), [QualityCheck](../../models/production.py#L502), [SewingAssignment](../../models/sewing_assignment.py#L13), [SewingDailyReport](../../models/sewing_daily_report.py#L11), [SewingFlow](../../models/sewing_flow.py#L8), [Bundle](../../models/tracking.py#L9), [BundleScanLog](../../models/tracking.py#L41).
- Existing Pydantic contracts: [production.py](../../schemas/production.py), [cutting_passport.py](../../schemas/cutting_passport.py), [cutting_material.py](../../schemas/cutting_material.py), [sewing_assignment.py](../../schemas/sewing_assignment.py), [sewing_daily_report.py](../../schemas/sewing_daily_report.py), [sewing_flow.py](../../schemas/sewing_flow.py), [tracking.py](../../schemas/tracking.py).

These are source pointers, not permission to move entire mixed files. Trace the
particular operation and every caller/write before choosing what belongs here.

## When making a service file

| Proposed file | Responsibility |
| --- | --- |
| `orders.py` | Production/work-order lifecycle. |
| `cutting.py` | Cutting records, passports and reconciliation. |
| `printing.py` | Printing output and stage readiness. |
| `sewing.py` | Shared sewing output/correction operations. |
| `bundles.py` | Bundle identity, scans and manufacturing handoff. |

Use snake_case filenames and operation names such as `create_*`, `record_*`,
`receive_*` or `approve_*`. A typed function is sufficient; a class is optional
when it owns real dependencies. Accept the Session, validated input and actor
explicitly. State the transaction owner, refusal rules and result contract.
Use the existing ORM models. Migrate existing schemas/ DTOs to libs/dto/<feature>/
with their callers; keep fixed values in libs/enums/. See [DTO conventions](../../libs/dto/README.md).
Do not import routers, call an endpoint, or commit inside a helper owned by another
transaction. Do not create an interface/repository or generic CRUD class by default.

**Import collision:** `app/services/production.py` already exists. Keep this directory documentation-only until its coordinated conversion is approved. Adding `__init__.py` now can shadow that module; creating child Python modules without a package conversion is not a working import strategy. Preserve or explicitly migrate every existing caller and export.

**First operation to study:** Pilot record_sewing_output: trace production.post_sewing, the band caller, corrections, receipts, locks, audit and idempotency. Keep all existing production.py operations during its package conversion.

**DTOs and enums:** Manufacturing/work-order/stage statuses. Enum membership does not authorize transitions or create replacement work. Reuse Create/In, Update and Read/Out contracts
where they exist. Add action-specific input only for a real action. Do not generate
three DTOs for every table or expose privileged fields through generic updates.

## Boundaries and verification

Inventory owns material balances; Packaging owns package contents; People/payroll owns earned-pay records. The approved outer operation coordinates a cross-group transaction. Do not import private route helpers.

Preserve 600 received -> 495 then 105 recorded without double counting. Keep Nastils independent, unfinished quantities reachable, optional stages correct and failed pieces traceable without replacement work. Visually check normal/band sewing, correction and the next department.

## Migration steps

Follow [the shared sequence](../README.md#migration-sequence): study route/DB/rules
and callers -> agree one operation -> capture baseline tests -> extract -> test
old/new separately -> test the real UI on isolated data -> reviewed switch -> human
production verification -> remove old code. Keep one write path per request.
Record the test result, visual evidence, approver and cleanup condition in the task.
Visual success alone does not prove permissions, concurrency or data correctness.
