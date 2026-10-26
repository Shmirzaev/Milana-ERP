# Inventory: DTO contracts

**Engineer:** Ismail. **Reviewer:** Mirshoir. **Business acceptance:** Shavkat.

One entity per file. Each file holds the contracts of a single entity:

- [item_input.py](item_input.py) — `ItemComposition`, `ItemIn`
- [item_image_input.py](item_image_input.py) — `ItemImageIn`
- [item_output.py](item_output.py) — `ItemOut`
- [warehouse_input.py](warehouse_input.py) — `WarehouseIn`
- [warehouse_output.py](warehouse_output.py) — `WarehouseOut`
- [stock_batch_input.py](stock_batch_input.py) — `StockBatchIn`
- [stock_batch_update.py](stock_batch_update.py) — `StockBatchUpdate`
- [stock_batch_roll_weights_input.py](stock_batch_roll_weights_input.py) — `StockBatchRollWeightsIn`
- [stock_batch_restore_input.py](stock_batch_restore_input.py) — `StockBatchRestoreIn`
- [stock_batch_output.py](stock_batch_output.py) — `StockBatchOut`
- [accessory_return_input.py](accessory_return_input.py) — `AccessoryReturnIn`
- [accessory_issue_input.py](accessory_issue_input.py) — `AccessoryIssueLineIn`, `AccessoryIssueIn`
- [accessory_issue_output.py](accessory_issue_output.py) — accessory issue plan, issue, summary and request rows
- [stock_movement_input.py](stock_movement_input.py) — `StockMovementIn`
- [stock_movement_output.py](stock_movement_output.py) — `StockMovementOut`
- [stock_quantity_adjustment_input.py](stock_quantity_adjustment_input.py) — `StockQuantityAdjustmentIn`
- [stock_quantity_adjustment_output.py](stock_quantity_adjustment_output.py) — `StockQuantityAdjustmentOut`
- [stock_line_output.py](stock_line_output.py) — `StockLine`
- [material_reservation_input.py](material_reservation_input.py) — reservation create, auto and consume inputs
- [material_reservation_output.py](material_reservation_output.py) — reservation, plan and status outputs
- [eco_fabric_transfer_input.py](eco_fabric_transfer_input.py) — Eco Cotton scan, send and return
- [fabric_scan_input.py](fabric_scan_input.py) — daily fabric scan
- [warehouse_stocktake_input.py](warehouse_stocktake_input.py) — count start, scan and deletions
- [waste_input.py](waste_input.py) — `WasteIn`
- [waste_output.py](waste_output.py) — `WasteOut`
- [waste_sale_input.py](waste_sale_input.py) — `WasteSaleIn`
- [waste_sale_output.py](waste_sale_output.py) — `WasteSaleOut`
- [waste_disposal_input.py](waste_disposal_input.py) — `WasteDisposalIn`
- [waste_disposal_output.py](waste_disposal_output.py) — `WasteDisposalOut`

These describe accepted inputs and returned data. They do not execute database
writes, implement permissions or manage transactions. Class names, fields and
validators are unchanged by the split, so the published OpenAPI component names
did not move; only the file each class lives in changed.

`StockBatchIn`, `StockBatchUpdate` and `StockBatchOut` use the canonical
`StockBatchQcStatus` enum. Input normalization still trims and lowercases text;
stored and serialized values remain `pending|passed|failed|rejected|hold`.
Unsupported input now deliberately returns request-validation HTTP 422 before
the service runs. Receipt null is also 422; update null retains its service 400,
while an omitted update leaves QC unchanged. Receipt defaults are actual PENDING
members. `AccessoryReturnIn` inherits this contract. The receipt captures raw QC
text privately for compatibility with already-recorded idempotency fingerprints;
this text must not replace the enum used by business code.

The enum change publishes the finite vocabulary in OpenAPI; do not restore broad
string annotations to match the historical schema. Storage remains String plus
the existing CHECK constraint. Other Inventory vocabularies and operations remain
separate pending ledger items, not implicitly converted by this receipt slice.

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
