# Purchasing: DTO contracts

**Engineer:** Ismail. **Reviewer:** Mirshoir. **Business acceptance:** Shavkat.

Existing Pydantic definitions in this group:

- [purchase_request_input.py](purchase_request_input.py) - request, approval and conversion input.
- [purchase_request_output.py](purchase_request_output.py) - request and line output.
- [purchase_order_input.py](purchase_order_input.py) - order and receipt input.
- [purchase_order_output.py](purchase_order_output.py) - order and line output.
- [purchase_quantity.py](purchase_quantity.py) - the shared purchase quantity bound and its two aliases.

These describe accepted inputs and returned data. They do not execute database
writes, implement permissions or manage transactions. Class names and validation
are unchanged by the split; the group now has one file per entity family
instead of one combined file.

Purchasing exposes no update operation, so there is no `*_update.py` file; an
update contract would be unused.

Before adding a file, find the existing contract and its router/service callers.
Keep creation fields/defaults, allowed update fields and response filtering distinct.
For updates preserve omitted versus explicit null; do not apply creation defaults.
Add action/query contracts only for actual operations. New <entity>_input.py, <entity>_update.py or
<entity>_output.py files are useful when the feature needs them, not a quota for every table.

Reuse shared bases from ../common.py and existing fixed values. Test validation,
serialization, denied/privileged fields and the consuming workflow; then perform
the required visual and release acceptance checks.

Purchase receipt lines use `StockBatchQcStatus`; the omitted and empty-string
inputs both store `passed`. The original empty spelling is retained for receipt
idempotency fingerprints. Nonempty unsupported, padded or case-changed values
now fail request validation with 422 instead of reaching the stock-batch CHECK
later; this is an intentional validation/OpenAPI change. Null remains invalid.

See [DTO rules](../README.md), [business services](../../../models/README.md),
[database definitions](../../../schemas/README.md) and
[ownership](../../../../../docs/TEAM_OWNERSHIP.md).
