# Production execution

Business-service group guide, relocated into models/ on 24 October 2026. This
directory contains the released Besttex read-only compatibility service below;
other existing implementations remain the *_service.py files linked below.
The proposed files describe later approved operation extractions.

## Besttex read-only compatibility operation

`GET /api/besttex/cutting-orders` and `GET /api/besttex/cutting-orders/{record_id}/sheet`
delegate to [besttex_cutting_service.py](besttex_cutting_service.py). The coordinator
authorized porting this released operation from recorded production source
`439555a77ef583b1b212398e16ecd52ced786e45`, including grouped order/photo projections.
HTTP contracts live in [besttex_cutting_output.py](../../libs/dto/production/besttex_cutting_output.py).

Preserve `besttex.cutting_sheets`, selected-factory BST restriction/admin access,
exact batch and bundle ownership, approved positive cutting output, pagination,
escaped search, garment-family versus exact-variant photo identity and read-only
printing. Both entry points use the supplied Session and existing public renderer;
they own no writes or commits. Authentication's existing last-seen behavior is not
manufacturing mutation. Migration `0149_besttex_cutting_access` is separately
carried unchanged; adding the file is not authorization to apply it to a live DB.

Output strings are configurable identifiers, labels, references, image URLs and
size summaries, not status enums. Existing Production/WorkOrder/Bundle status and
operation predicates remain released literals in this compatibility slice; their
canonical enum conversion remains in Mirshoir's Production operation ledger.
This port does not complete Production, migration deployment or visual acceptance.
Run `test_besttex_cutting_sheets.py`, permission/access regressions and the dedicated
PostgreSQL lock/retry rehearsal; independently inspect the actual list, denied
roles, grouped photos and print sheets before human review.

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

### RF-001 Sewing output seam: proposal for Mirshoir

Source trace at `5603b5d`; this is a review proposal, not an approved extraction.

- `POST /api/sewing/records` enters `production.post_sewing` with
  `SewingRecordIn`, `sewing.records` permission and an optional Idempotency-Key.
  That route owns the WorkOrder lock, factory and batch checks, upstream/input and
  size limits, SewingRecord/assignment counters, defect waste, Packaging plan and
  notification, workflow advance, audit, idempotency save and final commit.
- `POST /api/sewing-bands/{aid}/output` authenticates a band through its assignment,
  requires final-only output and ECO received-bundle capacity, then imports and
  calls `production.post_sewing` directly. It uses the same `sewing:output` retry
  scope. Its WorkOrder-before-assignment refresh order must survive extraction.
  The band path currently uses `CurrentUser`, not the general route's permission
  dependency; the service must preserve its assignment-based access check.
- Sewing corrections PATCH/DELETE import five private production-route helpers,
  adjust records/assignment/work-order totals and commit independently. Bundle
  receipts, planned Nastils and line assignments invoke
  `sewing_progress_service.reconcile_sewing_order`; they do not call the output
  endpoint. These are adjacent operations to test, not extra callers to merge
  into one output function.

Proposed first public operation, subject to Mirshoir's interface decision:

```python
record_sewing_output(
    db: Session, *, actor: User, payload: SewingRecordIn,
    idempotency_key: str | None, band_assignment_id: int | None = None,
) -> dict[str, int]
```

`band_assignment_id` comes from the band URL and must match the payload and the
actor's active band; it must never act as a permission bypass. The operation
would select one write path, own the transaction and return today's `{"id": ...}`.
Both routes would retain their current URL, status code, replay scope, validation
errors and response shape while delegating the complete write to that operation.
Reuse the existing DTO/SQLAlchemy mappings and helpers; decide the service's
error-to-HTTP mapping before implementation. Move corrections and receipts only
as separately reviewed operations. Avoid a second business implementation or
production shadow writes.

Before Mirshoir approves this seam, confirm the normal-versus-band authorization,
one transaction owner, lock order and exact-batch rules with Shavkat's examples.
Compare old/new runs on independent PostgreSQL fixtures, including retries,
concurrent output, corrections, later Nastils, Printing loss and Packaging handoff;
then inspect the real UI and persisted effects. Freshly verify both production
manifests/slots before any release. The retained active release is the source
rollback path; a source rollback does not undo records already written.

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
