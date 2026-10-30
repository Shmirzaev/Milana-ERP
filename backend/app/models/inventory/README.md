# Material inventory

Business-service group guide. Routes were extracted on 25 October 2026; that
namespace move is not full operation acceptance. Routers bind HTTP, context and
auth and delegate. Services own business rules and the outer transaction;
schema-model operations own mapped writes using that same supplied Session.
Receipt INV-OP-01 implements this write boundary; remaining operations below
still need their own extraction, tests, visual verification and human gate.

**Purpose:** Own material/accessory stock, material reservations, stock movements, transfers, stocktake and material waste records.

**Engineering owner:** Ismail. **Reviewer:** Mirshoir.
**Business acceptance:** Shavkat with operators.
This owner covers the feature's routes, DTOs, enums, database definitions and tests.
See [team ownership](../../../../docs/TEAM_OWNERSHIP.md) for shared-layer coordination.

## Routes

- [inventory.py](../../api/routes/inventory.py) — items, warehouses, stock view, receipts, accessory issue/return, reservations, transfers, batches.
- [eco_transfers.py](../../api/routes/eco_transfers.py) — Eco Cotton fabric dispatch register.
- [fabric_scans.py](../../api/routes/fabric_scans.py) — daily fabric scan register.
- [stocktake.py](../../api/routes/stocktake.py) — warehouse counts.
- [waste.py](../../api/routes/waste.py) — waste lifecycle.

No route in this group imports another route, queries the ORM, or commits. Every
endpoint below has one owning service function.

## Service files

This directory is the group's service package. Each module owns one responsibility:

| File | Responsibility | Owns |
| --- | --- | --- |
| [stock_service.py](stock_service.py) | Items, warehouses, stock view, stock adjustment, receipts, accessory issue/return, batch edits, archive/restore, batch list. | commits user-facing writes; accessory issue owns one supplied-Session operation and calls schema-owned manual/stock-consumption writers; public `record_purchase_order_stock_receipt` is a same-Session participant for Purchasing; batch row locks (`_locked_stock_batch_statement`, `_locked_active_batch_reservations_statement`); QC normalisation; image-URL policy; force-override refusal; materials-only scope. |
| [reservations_service.py](reservations_service.py) | Reserve, auto-reserve, release and consume material reservations, and the reservation plan. | commit for every write; idempotency scope `inventory.reservations.create`; failure audit for refused creates. |
| [transfers_service.py](transfers_service.py) | Material transfers between warehouses and the Eco Cotton fabric register (scan/send/return/report/PDF). | commit for every write; batch-before-item lock order; `inventory.transfer` idempotency scope; Eco ownership and outstanding-roll refusals. |
| [fabric_scans_service.py](fabric_scans_service.py) | Daily fabric scan register plus the shared roll-code parser `parse_roll` and the Tashkent business date. | Owns the authorization/validation and duplicate-query order, immutable roll snapshot, duplicate replay and one commit; it uses the schema-owned scan insert with the same Session. |
| [waste_service.py](waste_service.py) | Waste record, receipt, sale and disposal lifecycle. | commit for every write; sale idempotency scope `waste.sales.<user>.<wid>`; disposal parent-then-request lock order. |

The stocktake counts live in [stocktake_service.py](../stocktake_service.py). It
stayed at the models root because it is shared with
[legacy_package_identity_service.py](../legacy_package_identity_service.py), whose
public `package_snapshots` seam it owns. It owns count start, scan, undo,
completion, detail paging, CSV export and the REPEATABLE READ READ ONLY snapshot
those reads use.

Supporting services that stay the single source for their concern:
[inventory_service.py](../inventory_service.py) (availability, reservations,
accessory planning and the Sewing gate), [inventory_access_service.py](../inventory_access_service.py)
(materials-only scope), [inventory_reports_service.py](../inventory_reports_service.py)
(material reports), [material_rolls_service.py](../material_rolls_service.py) (roll
normalisation), [eco_transfer_pdf_service.py](../eco_transfer_pdf_service.py) (Eco PDF).

## Contract

- Inputs: the entity-named modules under [libs/dto/inventory](../../libs/dto/inventory/).
  The Eco/fabric/stocktake request models were inline in the routers and the
  Inventory/Waste contracts were mixed in two files; all of them now live in
  entity-named input/update/output modules. Class names, fields and validators are
  unchanged, so the published OpenAPI component names did not move.
- Receipt returns an actual `StockBatchOut` with canonical QC members on fresh
  and replay paths. Only the saved idempotency response is serialized to JSON;
  the route's return annotation and `response_model` both name `StockBatchOut`.
  Other operations retain their dictionaries/ORM results pending their own
  typed-contract migration; do not copy that unfinished shape into new work.
- Receipt, correction and output QC contracts use `StockBatchQcStatus`; input
  DTOs trim and lowercase strings and reject unknown values with HTTP 422.
  Explicit correction null retains HTTP 400; omitted QC remains unchanged.
  The service uses the canonical member and unwraps `.value` at the existing
  string storage/serialization boundary. Raw receipt QC text is retained solely
  for old idempotency fingerprint compatibility. See the [DTO guide](../../libs/dto/inventory/README.md).
- INV-OP-01 receipt delegates batch/movement inserts to
  `schemas/inventory/stock_receipt_persistence.py`, using the same Session as
  schema-owned audit/idempotency writers and one outer service commit. Other
  Inventory operations still contain direct writes and require their own study,
  extraction and verification; the service-folder move did not complete them.
- Purchase order receiving calls Inventory's public
  `stock_service.record_purchase_order_stock_receipt` participant with a typed
  normalized command. It stages Inventory's batch/movement pair in Purchasing's
  transaction; it does not duplicate Inventory's endpoint authorization, replay,
  audit or commit behavior.
- `POST /api/inventory/accessory-issues` is coordinated by
  `stock_service.issue_accessories`. It owns the outer commit and audit call,
  returns `AccessoryIssueOut`, and stages manual rows through
  `schemas/inventory/accessory_issue_persistence.py`. The shared workflow
  `consume_item_from_batches` preserves its FIFO row selection/locking and
  availability recheck while delegating each batch decrement plus `consume`
  movement to `schemas/inventory/stock_movement_persistence.py`. The existing
  Production schema setter continues to own Sewing gate mapped-field updates.
  This is source extraction evidence only; approved PostgreSQL, visual UI,
  persisted readback, stress and human acceptance gates remain pending.
  The issue path has no idempotency key/record or ProductionOrder lock, and each
  duplicate item line is checked against the pre-loop plan snapshot; no replay,
  cumulative-limit or new-lock policy is implied by this extraction. The
  inventory main page currently sends `manual: true` for extra rows even when
  an Item is selected, while the receive page sends planned stock-backed rows;
  preserve this existing distinction pending owner/business review.
- The daily fabric scan operation delegates its one register-row insert to
  `schemas/inventory/fabric_scan_persistence.py`. It never writes stock or
  movements. Its typed request/result/report use the fixed direction and
  department snapshots; the service keeps the outer commit and the existing
  duplicate `IntegrityError` rollback/requery behavior. `parse_roll` and
  `TASHKENT` remain shared with Eco transfer scans.
- Each service function is one outer operation: it accepts the session, the
  validated input and the actor, and it is the only place that commits. Helpers
  inside a service never commit.
- SQLAlchemy definitions are unchanged: [EcoFabricDispatch](../../schemas/inventory/eco_transfer.py#L8), [EcoFabricRoll](../../schemas/inventory/eco_transfer.py#L17), [FabricScan](../../schemas/inventory/fabric_scan.py#L10), [Item](../../schemas/inventory/inventory.py#L9), [Warehouse](../../schemas/inventory/inventory.py#L31), [StockBatch](../../schemas/inventory/inventory.py#L38), [StockMovement](../../schemas/inventory/inventory.py#L75), [MaterialReservation](../../schemas/inventory/inventory.py#L97), [ManualAccessoryIssue](../../schemas/inventory/inventory.py#L144), [WarehouseStocktake](../../schemas/inventory/stocktake.py#L9), [WarehouseStocktakeRow](../../schemas/inventory/stocktake.py#L18), [WasteRecord](../../schemas/inventory/waste.py#L9), [WasteSale](../../schemas/inventory/waste.py#L26), [WasteDisposalRequest](../../schemas/inventory/waste.py#L37).

## When making a service file

Use snake_case_service.py filenames and operation names such as `create_*`, `record_*`,
`receive_*` or `approve_*`. A typed function is sufficient; a class is optional
when it owns real dependencies. Accept the Session, validated input and actor
explicitly. State the transaction owner, refusal rules and result contract.
Use the existing ORM definitions in schemas/ and DTOs in libs/dto/<feature>/;
keep fixed values in libs/enums/. See [DTO conventions](../../libs/dto/README.md).
Do not import routers, call an endpoint, or commit inside a helper owned by another
transaction. Do not create an interface/repository or generic CRUD class by default.
Reuse models/inventory_service.py and inventory_access_service.py rather than
duplicating availability calculations.

## Boundaries and verification

Production supplies actual usage/defect evidence; Inventory owns material balances. Finished-goods availability belongs to Fulfillment. Finance determines monetary reporting, not stock quantities.

Verify reservations cannot overclaim, units stay consistent, corrections retain history and batch photos remain batch-local. Visually check receiving, reservation, issue/return and stocktake outcomes.

## Remaining exceptions

- The PostgreSQL-only tests in this group (real row-lock races, REPEATABLE READ
  snapshots, concurrent reservations) were not executed here. They are recorded as
  required verification for the combined run.

## Migration steps

Follow [the shared sequence](../README.md#migration-sequence): study route/DB/rules
and callers -> agree one operation -> capture baseline tests -> extract -> test
old/new separately -> test the real UI on isolated data -> reviewed switch -> human
production verification -> remove old code. Keep one write path per request.
Record the test result, visual evidence, approver and cleanup condition in the task.
Visual success alone does not prove permissions, concurrency or data correctness.
