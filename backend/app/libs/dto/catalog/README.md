# Catalog: DTO contracts

**Engineer:** Ismail. **Reviewer:** Mirshoir. **Business acceptance:** Shavkat.

Existing Pydantic definitions in this group:

- [catalog.py](catalog.py)
- [model_input.py](model_input.py)

Model paid-operation rows use `PaidOperationIn` for the dedicated operation
PATCH, whole-model PATCH and the separate `ModelCreateIn` details contract.
CREATE and PATCH retain unrelated unknown metadata while preserving omitted/null
row keys. They validate fixed catalog vocabularies while retaining unknown row
extension keys and omitted fields. Known editor identity, selection, rate,
quantity/copy/split, timing, currency and source metadata fields have explicit
optional scalar/list types; supplied scalar representations are retained.
Malformed known containers and noncanonical section/factory/mode values are
intentionally rejected with HTTP 422. Stored JSON read contracts remain
unchanged.

These describe accepted inputs and returned data. They do not execute database
writes, implement permissions or manage transactions. Existing filenames/class
names are retained; the folder move does not alter validation or defaults.

Before adding a file, find the existing contract and its router/service callers.
Keep creation fields/defaults, allowed update fields and response filtering distinct.
For updates preserve omitted versus explicit null; do not apply creation defaults.
Add action/query contracts only for actual operations. New <entity>_input.py, <entity>_update.py or
<entity>_output.py files are useful when the feature needs them, not a quota for every table.

Reuse shared bases from ../common.py and existing fixed values. Test validation,
serialization, denied/privileged fields and the consuming workflow; then perform
the required visual and release acceptance checks.

See [DTO rules](../README.md), [business services](../../../models/README.md),
[database definitions](../../../schemas/README.md) and
[ownership](../../../../../docs/TEAM_OWNERSHIP.md).
