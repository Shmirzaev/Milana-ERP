# Packaging

Business-service group guide, relocated into models/ on 24 October 2026. This
directory contains `manual_packages_service.py` for manual pack creation,
recovery and cancellation before warehouse receipt. Existing implementations
remain in the shared *_service.py files linked below; other proposed files
describe later approved operation extractions.

`print_runs_service.py` owns read-only print-run history queries: existing department
scope, full-history search/date/receipt filters, bounded paging and legacy list compatibility.

`package_origin_service.py` owns read-only business model/variant numbers and sewing-origin
projections for package scans, lists and Warehouse Inventory. Legacy sticker numbers
come from immutable receipt fields when present. Sewing origin uses positive sewing
records at the package batch/allocation grain, resolving the recorded assignment line
or its sewing department; packaging destination and planned routing are not evidence.
Mixed batch origins remain a list; missing evidence remains unknown. Factory filtering
runs before list counts/paging, and response projection loads origins in 400-row chunks.
No inventory or production data is changed by this projection.

`create_packages_service.py` coordinates direct order Packaging and exact print runs.
POST `/packages/print-runs/create-packages` explicitly opts in with `work_order_id`;
omitting it preserves the legacy saved-output-only contract and request fingerprint.
The direct action locks PO -> Sewing WOs -> Packaging WOs, reuses saved unlabelled
output, then records only the additional passed Sewing needed by the selected labels.
Selected sources must belong to the same active packaging department, and a supplied
customer-order reference must match the PO. Single-source damage participates in the
same action; `/packages/record-damage` handles all-damaged output without labels or
stock. Both actions use the existing keyed retry/reconciliation wrapper and one outer
commit. Helpers never commit or import routers. Sewing entry uses the same PO-first
lock order, including defect/waste writes.

`output_service.py` and schema-owned `packaging/output_persistence.py` share the
physical output writer between legacy record entry and direct actions. BOM material
consumption, waste, workflow, notification and audit operations participate in the
same Session. Direct counters are rebuilt from the output ledger; legacy entry keeps
its historical counter policy. Existing public package/workflow operations retain
some schema-write migration debt; this slice does not claim a full domain extraction.
No payroll, warehouse receipt, new table or automatic GET write is added.
Migration0157 adds nullable exact item evidence to existing batch allocation rows.
Finished-goods accounting rows retain existing package receipt/stock eligibility gates.

`direct_identity_service.py` validates configured order color/size membership and
actual cumulative Sewing sizes when complete authoritative evidence exists. Missing
actual sizes retain the ordinary operator recipe, without treating planned ratios as
actual output. Grade paths retain strict size confirmation and mixed-batch guards.
`allocation_items_service.py` now requires explicit operator-confirmed
`item_breakdown` (model/color/size/positive quantity) on every new mixed source.
It conserves each scalar source total and the complete package item identities;
single-source contents have one unique attribution and can be derived. Historical
mixed NULL remains unknown: metadata edits/read/labels never invent its matrix.
All create/direct/bulk and edit/approval/returned-correction paths validate the
same matrix. Approval rechecks under the PO lock. Exact cells consume original
production source sizes regardless of package lifecycle state; only deletion
releases production allocation. Adjusted legacy items cannot be treated as original
source evidence. Unknown historical mixed sizes reserve the greatest possible
consumption per source/size, which may conservatively refuse further packaging.
A complete actual Sewing size breakdown is enforced when available; missing sizes
retain the operator-confirmed recipe with `actual_size_verified=false`. Sewing does
not prove color-by-size distribution; that matrix remains the operator's declaration.

Exact matrices participate in immutable print-run/audit snapshots and label/source
readback. Old NULL snapshots omit the new key, so unchanged historical labels remain
valid. Quantity-changing shipment review refuses new exact mixed packs until an
attribution-aware Packaging correction; unchanged reviews and historical unknown
controls keep their existing behavior. Source `size_balances` reports known usage,
conservative legacy reservation and nullable actual remaining sizes. Query reads
are cached per package group, with allocation/business-label projections in400-row
chunks. New persistence is schema-owned and does not independently commit.

`package_sources_service.py` owns read-only GET `/packages/sources/{work_order_id}`:
authorize the anchor WO and expose same-department siblings. `available_to_package`
is saved unlabelled output plus unrecorded passed Sewing. `packed_qty` remains saved
physical output; `sewing_output_qty` and `available_input_qty` expose source evidence.
`unbatched_source` supports legacy orders without Nastils. Existing record progress
keeps its saved-output-only field and additionally exposes direct availability.

`sewing_availability_service.py` reads passed Sewing, saved output and exact package
allocation ledgers for the automatic queue. Saved output stays ready until labels
consume it. Historical acceptance receipts remain audit history, not another gate.
Usluga confirmation uses its own counters/JSON and leaves the queue after confirmation;
its customer-owned goods never enter warehouse print runs. Legacy unclassified WIP
(input greater than packed plus damaged) is not silently converted into available goods.

The type ledger retains canonical PackagingDepartment/WorkOrderStatus for this slice;
new UUID/ID/quantity fields are constrained data. Existing PackageIn stock-kind Literal,
free-form package type and shared wrapper operation-string vocabulary remain explicit
migration debt. Public mappings/storage values are unchanged. Preserve the historical
[7 November packet](../../../../docs/PACK_TWO_NASTILS_20261107.md) and
[WF02 evidence](../../../../docs/WF02_PACKAGING_20261113.md); they do not verify this
later direct-flow correction or establish human acceptance.

**Purpose:** Own package creation, contents/allocation, identity, change approval and production of valid labels.

**Engineering owner:** Mirshoir. **Reviewer:** Ismail.
**Business acceptance:** Shavkat with operators.
This owner covers the feature's routes, DTOs, enums, database definitions and tests.
See [team ownership](../../../../docs/TEAM_OWNERSHIP.md) for shared-layer coordination.

## Existing code to study first

- Routes: [packages.py](../../api/routes/packages.py), [package_workflows.py](../../api/routes/package_workflows.py), [packaging_reports.py](../../api/routes/packaging_reports.py), [usluga_packaging.py](../../api/routes/usluga_packaging.py), [production.py](../../api/routes/production.py).
- Services/helpers: [packages_service.py](../packages_service.py), [package_workflows_service.py](../package_workflows_service.py), [package_identity_service.py](../package_identity_service.py), [legacy_package_identity_service.py](../legacy_package_identity_service.py), [package_label_pages_service.py](../package_label_pages_service.py), [package_corrections_service.py](../package_corrections_service.py), [packaging_corrections_service.py](../packaging_corrections_service.py), [packaging_report_exports_service.py](../packaging_report_exports_service.py), [packaging_reports_service.py](../packaging_reports_service.py), [packaging_scope_service.py](../packaging_scope_service.py).
- Existing SQLAlchemy schema models: [PackagePrintRun](../../schemas/packaging/package_workflows.py#L19), [PackagePrintRunMember](../../schemas/packaging/package_workflows.py#L38), [PackagingRecord](../../schemas/production/production.py#L458), [Package](../../schemas/production/tracking.py#L54), [PackageBarcodeAlias](../../schemas/production/tracking.py#L157), [PackageItem](../../schemas/production/tracking.py#L176), [PackageBatchAllocation](../../schemas/production/tracking.py#L190), [PackageScanLog](../../schemas/production/tracking.py#L203), [PackageChangeRequest](../../schemas/production/tracking.py#L214).
- Existing Pydantic contracts: [tracking.py](../../libs/dto/packaging/tracking.py), [package_workflows.py](../../libs/dto/fulfillment/package_workflows.py), [production.py](../../libs/dto/production/production.py).

These are source pointers, not permission to move entire mixed files. Trace the
particular operation and every caller/write before choosing what belongs here.

## When making a service file

| Proposed file | Responsibility |
| --- | --- |
| `packages_service.py` | Package creation, contents and allocations. |
| `identity_service.py` | Canonical/legacy identifier resolution. |
| `corrections_service.py` | Package change requests and approvals. |
| `labels_service.py` | Label eligibility and print-run orchestration. |

Use snake_case_service.py filenames and operation names such as `create_*`, `record_*`,
`receive_*` or `approve_*`. A typed function is sufficient; a class is optional
when it owns real dependencies. Accept the Session, validated input and actor
explicitly. State the transaction owner, refusal rules and result contract.
Use the existing ORM definitions in schemas/ and DTOs in libs/dto/<feature>/;
keep fixed values in libs/enums/. See [DTO conventions](../../libs/dto/README.md).
Do not import routers, call an endpoint, or commit inside a helper owned by another
transaction. Do not create an interface/repository or generic CRUD class by default.

**First operation to study:** Trace package_workflows importing packages._package_lookup_candidates. Review package_identity.py and legacy_package_identity.py before selecting one supported identity operation.

**DTOs and enums:** Package/change-request/print-run lifecycle values, preserving existing barcode and API contracts. Reuse Create/In, Update and Read/Out contracts
where they exist. Add action-specific input only for a real action. Do not generate
three DTOs for every table or expose privileged fields through generic updates.

## Boundaries and verification

Fulfillment owns warehouse acceptance, stock reservations and dispatch. Package identity/content stays authoritative here. Rendering helpers remain reusable infrastructure; a printout is not proof of stock receipt.

Verify selected-batch quantities, partial packages, ambiguous codes, stale labels, permission checks and audit history. Visually check creation, correction approval, printed/scanned labels and receiving eligibility.

## Migration steps

Follow [the shared sequence](../README.md#migration-sequence): study route/DB/rules
and callers -> agree one operation -> capture baseline tests -> extract -> test
old/new separately -> test the real UI on isolated data -> reviewed switch -> human
production verification -> remove old code. Keep one write path per request.
Record the test result, visual evidence, approver and cleanup condition in the task.
Visual success alone does not prove permissions, concurrency or data correctness.
