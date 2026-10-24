# Production: DTO contracts

**Engineer:** Mirshoir. **Reviewer:** Ismail. **Business acceptance:** Shavkat.

Existing Pydantic definitions in this group:

- [cutting_material.py](cutting_material.py)
- [cutting_passport.py](cutting_passport.py)
- [production.py](production.py)
- [sewing_assignment.py](sewing_assignment.py)
- [sewing_daily_report.py](sewing_daily_report.py)
- [sewing_flow.py](sewing_flow.py)
- [traceability.py](traceability.py)

These describe accepted inputs and returned data. They do not execute database
writes, implement permissions or manage transactions. Existing filenames/class
names are retained; the folder move does not alter validation or defaults.

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
