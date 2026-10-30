# Production: DTO contracts

**Engineer:** Mirshoir. **Reviewer:** Ismail. **Business acceptance:** Shavkat.

Existing Pydantic definitions in this group:

- [besttex_cutting_output.py](besttex_cutting_output.py): released read-only list/page
  output; configurable references, display labels, image URLs, counts and dates.
- [cutting_material.py](cutting_material.py)
- [cutting_passport.py](cutting_passport.py)
- [production.py](production.py)
- [sewing_assignment.py](sewing_assignment.py)
- [sewing_daily_report.py](sewing_daily_report.py)
- [sewing_flow.py](sewing_flow.py)
- [traceability.py](traceability.py)

These describe accepted inputs and returned data. They do not execute database
writes, implement permissions or manage transactions. Existing filenames/class
names are retained; the source candidate documents the one intentional enum
typing/schema change below.

Production Order creation uses canonical `ProductionType` and retains the DTO's
existing two-value action subset (`client_order`, `branded_stock`) with an
explicit validator; the shared Usluga writer also uses `service_order`. The
alternate branded-stock CREATE endpoint has its own output DTO with its actual
one-operation enum contract; client-order Planning CREATE and generic standard
production CREATE likewise use action-scoped outputs that retain the canonical
enum annotations and constrain their known accepted subsets. Usluga keeps its
existing response shape, which omits these two discriminator fields. Global
`ProductionOrderOut` and `ProductionOrderDetail` reads keep
`production_type` as a lossless string because that mapped column has no CHECK
and historical stored values have not been reconciled. `source_type` remains
enum-typed because its mapped CHECK constrains the stored vocabulary. The
general creation input schema still documents only its two accepted values;
the general ProductionOrder GET endpoints remain on the broad read DTOs.
This source candidate does not classify the full ProductionOrder status set or
WorkOrder operation vocabulary; it does not claim global read-output enum
completion.

Before adding a file, find the existing contract and its router/service callers.
Keep creation fields/defaults, allowed update fields and response filtering distinct.
For updates preserve omitted versus explicit null; do not apply creation defaults.
Add action/query contracts only for actual operations. New <entity>_input.py, <entity>_update.py or
<entity>_output.py files are useful when the feature needs them, not a quota for every table.

## RF-012 Sewing record contract inventory (source `345b8fa`)

- Create: `SewingRecordIn` already lives in `production.py`; normal and band
  output both use it. Its zero defaults, optional assignment/batch/operator fields,
  size rows and quantity validator are part of the current request contract.
- Correction: `Correction`, `CorrectionSizeQuantity` and `DeleteInput` currently
  live in `api/routes/sewing_corrections.py`. PATCH requires version plus complete
  input/sewn/passed values, forbids unknown fields and does not let a caller edit
  failed/rejected/rework counts. DELETE requires the expected version. These are
  action-specific contracts, not a generic nullable partial-update DTO.
- Read: POST returns only `{"id": ...}`; GET `/api/sewing/records/{rid}` returns
  record fields; correction history includes `correction_version`, assignment
  accounting, timestamps and `locked_reason`. Preserve each response shape and
  separately verify object/factory authorization before an output DTO is wired.
- Storage: the one SQLAlchemy `SewingRecord` mapping remains in
  `schemas/production/production.py`. DTO files must not duplicate its table or
  perform writes.

After RF-005 approval, entity-prefixed `sewing_record_input.py`,
`sewing_record_update.py` and `sewing_record_output.py` are candidates only if
the actual callers move together. Keep the existing classes until their inputs,
OpenAPI schemas, default/omitted behavior and rendered UI are compared. Mirshoir
owns this production feature; Ismail coordinates the DTO convention.

Reuse shared bases from ../common.py and existing fixed values. Test validation,
serialization, denied/privileged fields and the consuming workflow; then perform
the required visual and release acceptance checks.

See [DTO rules](../README.md), [business services](../../../models/README.md),
[database definitions](../../../schemas/README.md) and
[ownership](../../../../../docs/TEAM_OWNERSHIP.md).
