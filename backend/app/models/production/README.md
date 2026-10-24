# Production execution

Business-service group guide, relocated into models/ on 24 October 2026. This
directory remains README-only; existing implementations are the *_service.py files
linked below. The proposed files describe later approved operation extractions.

**Purpose:** Own production orders, work orders and manufacturing-stage rules: cutting, printing, sewing, bundle handoffs and quality evidence.

**Engineering owner:** Mirshoir. **Reviewer:** Ismail.
**Business acceptance:** Shavkat with operators.
This owner covers the feature's routes, DTOs, enums, database definitions and tests.
See [team ownership](../../../../docs/TEAM_OWNERSHIP.md) for shared-layer coordination.

## Existing code to study first

- Routes: [production.py](../../api/routes/production.py), [production_extra.py](../../api/routes/production_extra.py), [bundles.py](../../api/routes/bundles.py), [cutting_passports.py](../../api/routes/cutting_passports.py), [sewing_bands.py](../../api/routes/sewing_bands.py), [sewing_corrections.py](../../api/routes/sewing_corrections.py), [sewing_daily_reports.py](../../api/routes/sewing_daily_reports.py), [sewing_flows.py](../../api/routes/sewing_flows.py), [usluga.py](../../api/routes/usluga.py).
- Services/helpers: [bundles_service.py](../bundles_service.py), [cutting_batch_delete_service.py](../cutting_batch_delete_service.py), [cutting_batch_guard_service.py](../cutting_batch_guard_service.py), [cutting_fabric_usage_service.py](../cutting_fabric_usage_service.py), [cutting_material_assignment_service.py](../cutting_material_assignment_service.py), [cutting_passport_reports_service.py](../cutting_passport_reports_service.py), [cutting_passport_usage_service.py](../cutting_passport_usage_service.py), [cutting_sewing_factory_service.py](../cutting_sewing_factory_service.py), [cutting_sheet_service.py](../cutting_sheet_service.py), [deferred_cutting_usage_service.py](../deferred_cutting_usage_service.py), [first_grade_service.py](../first_grade_service.py), [passport_nastil_service.py](../passport_nastil_service.py), [passport_sizes_service.py](../passport_sizes_service.py), [production_service.py](../production_service.py), [production_sizes_service.py](../production_sizes_service.py), [sewing_band_progress_service.py](../sewing_band_progress_service.py), [sewing_band_setup_service.py](../sewing_band_setup_service.py), [sewing_daily_report_exports_service.py](../sewing_daily_report_exports_service.py), [sewing_input_service.py](../sewing_input_service.py), [sewing_progress_service.py](../sewing_progress_service.py), [sewing_scope_service.py](../sewing_scope_service.py), [process_qr_export_service.py](../process_qr_export_service.py).
- Existing SQLAlchemy schema models: [CuttingPassport](../../schemas/production/cutting_passport.py#L14), [ProductionOrder](../../schemas/production/production.py#L49), [ProductionOrderMaterial](../../schemas/production/production.py#L114), [ProductionBatch](../../schemas/production/production.py#L142), [ProductionOrderItem](../../schemas/production/production.py#L164), [WorkOrder](../../schemas/production/production.py#L181), [CuttingRecord](../../schemas/production/production.py#L240), [CuttingMaterialUsage](../../schemas/production/production.py#L310), [CuttingBeikaMaterialUsage](../../schemas/production/production.py#L340), [PrintingRecord](../../schemas/production/production.py#L375), [SewingRecord](../../schemas/production/production.py#L395), [SewingReplacementRequest](../../schemas/production/production.py#L423), [QualityCheck](../../schemas/production/production.py#L502), [SewingAssignment](../../schemas/production/sewing_assignment.py#L13), [SewingDailyReport](../../schemas/production/sewing_daily_report.py#L11), [SewingFlow](../../schemas/production/sewing_flow.py#L8), [Bundle](../../schemas/production/tracking.py#L9), [BundleScanLog](../../schemas/production/tracking.py#L41).
- Existing Pydantic contracts: [production.py](../../libs/dto/production/production.py), [cutting_passport.py](../../libs/dto/production/cutting_passport.py), [cutting_material.py](../../libs/dto/production/cutting_material.py), [sewing_assignment.py](../../libs/dto/production/sewing_assignment.py), [sewing_daily_report.py](../../libs/dto/production/sewing_daily_report.py), [sewing_flow.py](../../libs/dto/production/sewing_flow.py), [tracking.py](../../libs/dto/packaging/tracking.py).

These are source pointers, not permission to move entire mixed files. Trace the
particular operation and every caller/write before choosing what belongs here.

## When making a service file

| Proposed file | Responsibility |
| --- | --- |
| `orders_service.py` | Production/work-order lifecycle. |
| `cutting_service.py` | Cutting records, passports and reconciliation. |
| `printing_service.py` | Printing output and stage readiness. |
| `sewing_service.py` | Shared sewing output/correction operations. |
| `bundles_service.py` | Bundle identity, scans and manufacturing handoff. |

Use snake_case_service.py filenames and operation names such as `create_*`, `record_*`,
`receive_*` or `approve_*`. A typed function is sufficient; a class is optional
when it owns real dependencies. Accept the Session, validated input and actor
explicitly. State the transaction owner, refusal rules and result contract.
Use the existing ORM definitions in schemas/ and DTOs in libs/dto/<feature>/;
keep fixed values in libs/enums/. See [DTO conventions](../../libs/dto/README.md).
Do not import routers, call an endpoint, or commit inside a helper owned by another
transaction. Do not create an interface/repository or generic CRUD class by default.

Database definitions have moved to schemas/; business operations use
*_service.py. Convert this guide into a service package only as an approved
operation is extracted and all callers are updated.

**First operation to study:** Pilot record_sewing_output: trace production.post_sewing, the band caller, corrections, receipts, locks, audit and idempotency. Preserve existing production_service.py operations and schemas/production/production.py mappings during later extraction.

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
