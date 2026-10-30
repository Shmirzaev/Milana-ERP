# Whole-ERP refactor coverage

## Current integration and active work — 30 October 2026

This checkpoint is as of 2026-10-30 11:25 UTC and is tied to the immutable
goal-state snapshot at
../../pr-review-20261027/REFACTOR_GOAL_STATE_SNAPSHOT_20261030T112519Z.json,
SHA-256 6b40cac1ce022a51e11cd32b462fcf8669434092384d763bf43957a6ad67bf1e.
It records a bounded status only. The historical 26 October inventory remains 97
tables and 1,303 columns; all 13 owner/domain queues remain INCOMPLETE. Current
operation receipts below do not complete a domain, close the system-wide type
ledger, grant human approval, or establish deployment.

clone_main remains verified at ff1542f02c137f24fc9fe78492aa69aa463a7293,
tree 649f430e01a1fabc6d97055d91c9bdd009bf7f3a. PR347 is merged but not deployed.
Draft PR348 at e6935401d477ac40bf82a28e4d23e1b76b482e5f combines Inventory
StockBatch UPDATE and Packaging selected print-run creation. Its exact 191-case
PG gate, backend/frontend CI and owned cleanup passed; release was skipped.
The 116 focused unit results belong to application-equivalent initial source
78de8944, not the later integrated commit. Computer/readback and postvisual checks
remain pending. Receipt: pr-review-20261027/PR348_CI_PG_ACCEPTANCE_E6935401_20261030.json.
The isolated PR353 candidate 1842ee729b07a8d7d47329953d9bc1c245d2614b retained
its exact 219-case PostgreSQL pass, full backend/frontend CI pass, lock evidence
and owned cleanup; Computer/readback and final combined acceptance remain pending.
Stacked Support draft PR354 at 693f7f473c3c26a72dd3994cb0b7478809501d84
passed 235 exact PG cases, the eight Support JSON lock witnesses, full backend/
frontend CI and cleanup; QA runtime artifacts and release were skipped. Settings
census, Computer/readback, postvisual and final acceptance remain pending.

PR353 receipts: pr-review-20261027/PR353_CI_PG_ACCEPTANCE_1842EE72_20261030.json
and PR353_FULL_CI_ACCEPTANCE_1842EE72_20261030.json; frontend artifact reuse is
separately bounded by PR353_FRONTEND_EQUIVALENCE_20261030.json. PR354 receipts:
pr-review-20261027/PR354_CI_PG_ACCEPTANCE_693F7F47_20261030.json (SHA-256
bab88806a6b7a481b813d71c275a60e1bb869830c411d7e0da5f72686fc2cc04) and
PR354_FULL_CI_ACCEPTANCE_693F7F47_20261030.json (SHA-256
04db10e6a041483263d09ffc487a92dda04ace5cc2f0d7333ef79022a54b18c1).
PR349-PR352 remain preserved component candidates; their PG totals overlap with
the PR353 combined union and must not be added together.

## Exact candidate evidence at the snapshot cut

| Operation | Frozen source and current evidence | Receipt paths from the snapshot ledger | Remaining gates |
| --- | --- | --- | --- |
| Planning alternate Production CREATE | 0d7e427f; 264 exact PG cases passed, full ERP passed (4,989 backend, 679 opt-in skips, 36 subtests); QA runtime and release skipped | pr-review-20261027/PLANNING_PAGINATION_FIX_CI_PG_SUCCESS_0D7E427F_41044164834.md (SHA-256 139988d4dce2e7810f49bd446de8e246a1da0ffae1f92f4ade5709a313e8e0b9); pr-review-20261027/PLANNING_PAGINATION_FIX_FULL_ERP_SUCCESS_0D7E427F_41044164703.md (SHA-256 94af9573bae47cf09162e28174a91c88e856b5c37471d2ad00385a2a33120f58) | Computer/readback, census and human acceptance |
| Catalog Model CREATE | bbd98a07; 250 exact PG cases passed with both family-lock witnesses and cleanup; full ERP passed (4,990 backend, 665 opt-in skips, 36 subtests); QA runtime artifacts and release skipped | pr-review-20261027/MODEL_CREATE_CI_PG_SUCCESS_BBD98A_41030723675.md (SHA-256 92569ffefc0b580d21d89ab0509ff8a86cf85821d519a7222377abef4e91ca1e); pr-review-20261027/MODEL_CREATE_FULL_ERP_SUCCESS_BBD98A_41030723706.md (SHA-256 306965a195acddbda61c01931e9c5205d7116efa8399519ed19181bab4717546) | Imported-status/value census, Computer/readback and human acceptance |
| Work-management Task CREATE | 245104eb; 246 exact PG cases and full backend/frontend CI passed; QA runtime stages and release skipped | pr-review-20261027/TASK_CREATE_CI_PG_ACCEPTANCE_245104EB_20261030.json; pr-review-20261027/TASK_CREATE_FULL_CI_ACCEPTANCE_245104EB_20261030.json (SHA-256 f857e5c7285cc29c521976052fa33ce6eb4fec0cef651d73172c3b910bcf294c) | Computer/readback and human acceptance |
| Work-management Task UPDATE | 0548058e; 261 exact PG cases and full backend/frontend CI passed; QA runtime stages and release skipped | pr-review-20261027/TASK_PATCH_CI_PG_ACCEPTANCE_054805_20261030.json (SHA-256 5d643ab4b86a2b58add8a1c5a7a6ebf3232f02132595184e7e287b134215c95a); pr-review-20261027/TASK_PATCH_FULL_CI_ACCEPTANCE_054805_20261030.json (SHA-256 cf5f0311aebe6f16d5453332a70cec4090ff896797def61f855a30f63ebbbffc) | Computer/readback and human acceptance |
| Work-management Task COMPLETE | 9597f580; 276 exact PG cases and full backend/frontend CI/owned cleanup passed; QA runtime stages and release skipped | pr-review-20261027/TASK_COMPLETE_CI_PG_ACCEPTANCE_9597F580_20261030.json (SHA-256 b7f542add40a90f5f9e207107f68ec3db3018ad8ddb2f158f3b408d70aff8622); pr-review-20261027/TASK_COMPLETE_FULL_CI_ACCEPTANCE_9597F580_20261030.json (SHA-256 600aae41bcf7b005dd58a90522479bd8cbb70a0a4c28aaf1e9498b697921dd0b) | Computer/readback and human acceptance |
| Work-management Task DELETE | 66cb7222; 287 exact PG cases and full ERP CI passed | pr-review-20261027/WRK_TASK_DELETE_PG_EXACT_HEAD_RECEIPT_20261030.md (SHA-256 b60d6b17ec12983a851fe87de997e0350d5e1f20c3c955ecbfcfe10bff05493a); pr-review-20261027/WRK_TASK_DELETE_ERP_EXACT_HEAD_RECEIPT_20261030.md (SHA-256 d309bc97ff6209a43908fcd8adf75c9f12ca2b42d53dbf845a87f9227a27be1d) | Computer/readback and human acceptance |
| Production Sewing output | 76bedae2; 255 exact PG cases and full ERP CI passed | pr-review-20261027/SEWING_CI_PG_ACCEPTANCE_76BEDAE2_20261030.json (SHA-256 6144b00243aaa63ff9084eeb95a42dabad2e7734415b5bf37fd89ac05c53c337); pr-review-20261027/SEWING_FULL_ERP_CI_ACCEPTANCE_76BEDAE2_20261030.json (SHA-256 a1899d20116636985aa5673d56c1a444c5b8378cfab061475dbbb6e8ce0da652) | Computer/readback and human acceptance |
| Catalog Model Image upload | 364d9ff4; 275 exact PG cases and full backend/frontend CI passed (4,999 backend, 683 opt-in skips, 36 subtests); QA runtime/release skipped | pr-review-20261027/CAT_MODEL_IMAGE_UPLOAD_PG_EXACT_HEAD_RECEIPT_20261030.md (SHA-256 2ee5202a835f2868570a001f6960d38a8957d157cfdaf5612bf898ea87aa1b98); pr-review-20261027/CAT_MODEL_IMAGE_UPLOAD_FULL_ERP_EXACT_HEAD_RECEIPT_20261030.md (SHA-256 40bb9f403da5c13d0fcde7d52bb98e0d11fec67b5e0a58adbe3865e4e4acc851) | Computer/readback and human acceptance |
| Catalog BOM UPDATE | b997f493; 276 exact PG cases passed with cleanup; full ERP run 41046549577 was still live at snapshot time | pr-review-20261027/BOM_CI_PG_ACCEPTANCE_B997F493_20261030.json (SHA-256 4430d0fa106182daf421838c6de81df7185e61e988227c8ac2b6f04db88ce42b) | Full ERP result, Computer/readback and human acceptance |
| Inventory accessory issue | 19e095c2; 14 PG cases defined, 36 offline CI guards passed; independent registration review was running and branch not pushed | refactor-accessory-issue-20261030/.codex-work/refactor-handoff/INVENTORY_ACCESSORY_ISSUE_OPERATION_PACKET_20261030.md; pr-review-20261027/INV_ACCESSORY_ISSUE_SOURCE_INDEPENDENT_REVIEW_20261030.md (SHA-256 901318dba9e43dd3257e470e295684b4da1c822b45e66ec19840a3debd949bff) | Registration review, hosted gates, Computer/readback and human acceptance |

BOM’s historical ae94 full-CI receipt is not a result for current b997. Likewise,
source/test-definition and static-guard passes do not substitute for hosted PG,
full ERP, browser/readback, or owner acceptance where those gates are pending.
The next-operation source studies and original 13-domain queue below remain
separate planning work, not evidence of completion.

Initial candidate-source ledger, 26 October 2026. **The architectural/type target is incomplete.**
Six Ismail pilots are rollout steps; the other owners remain in scope. Use the
[engineering workflow](ENGINEERING_WORKFLOW.md) and [ownership](TEAM_OWNERSHIP.md).

## Verified integration checkpoint — 28 October 2026

At merge `1f0022ad55d9f326212694e4ac5d4e16b63bb713` (tree
`c59b4624ffe0282384730a3dc33593a755d0d898`), scoped local and PostgreSQL
verification covers PR335's implicit branded Planning insert, PR336 Customer
create and Brand update, and PR337 Supplier create. Normal Planning UI exercises
the selected-order path, not the implicit branch. See [dated evidence](archive/VERIFIED_INTEGRATION_2026-10-28.md)
for exact candidates, GUI/readback scope and limitations. These results do not
close Catalog, Planning, any of the six areas, the remaining type ledger, or
human production acceptance. At this earlier checkpoint Customer UPDATE PR339,
dependency PR331 and tooling PR338 were pending.

The later canonical checkpoint merges CI tooling PR338 as `e6f597891489e38207e01b6bfcca3d8df1b7adea`
and Customer UPDATE PR339 as `61b1a7020c5e1465aa076acc238d94ea1ad7dd03`
(tree `a943af045834ff43227ddd4640504f11ddccb69b`). The Customer operation has
128 required and 17 supplemental PostgreSQL cases and separately scoped GUI
and readback evidence; the V23 write window failed its resource guard and V25
was read-only. See the dated evidence for exact source attribution. Supplier
UPDATE and dependency PR331 are separate candidates outside that dated checkpoint.
Full types, operations and production acceptance remain open.

The table and inventory below preserve earlier candidate-specific checkpoints;
they are not a current per-operation completion inventory.

For the source-bound Catalog and Inventory operation queue based on merged PR340 4238974, see [operation queue](REFACTOR_OPERATION_QUEUE.md).

## Execution resumed with Codex subagents

26 October 2026: Ismail explicitly requested "do the rest iwth codex subagents !".
Follow the [current execution rules](../AGENTS.md#implementation-execution): isolated
operation ownership, one integrator, independent review and unchanged human gates.
The preparation base is `148107825b7d25538d00da825efa3d3f7ee967c6`; it does not
replace the older discovery source or transfer its results to a new candidate.
This execution update makes no new runtime acceptance claim. The named-operation
states below are the preserved operation checkpoint, not a live worker-status feed.

## Inventory and evidence boundary

The [machine-readable ledger](REFACTOR_COVERAGE.json) contains all **97 mapped tables / 1,303 fields**
from candidate `3cdd6808ff7ced0717f337d17d4e530719d4a86f`. The reviewer's AST field sets, including
inherited fields, match offline SQLAlchemy metadata. No business values or production
database were read for this inventory. Later documentation commits do not change this source.

There are 37 fields with closed IN-check hints, 93 other vocabulary-name candidates,
44 structured JSON fields and 280 foreign-key references. These are discovery hints,
not enum decisions. Configurable rows can contain closed discriminators; references,
free text and configurable values must not become enums merely because of their names.

Every field inherits **PENDING** semantic, actual-value, DTO/internal/UI-consumer,
writer and verification review. The explicit override map starts empty. Existing
InvoiceStatus is a declaration to trace, not evidence that all finance consumers pass.
Migration-only/unmapped database objects and actual stored values require separate
database reconciliation. Do not conflate this offline count with a database snapshot.

## Non-persisted contracts also remain in scope

Every domain also has pending input/update/output DTOs, query and action parameters,
used internal commands/results and JSON discriminator coverage. The JSON ledger
records these separately for each owner. Session selection, report projections and
other operations can have contracts without a mapped table or database write.
Neither 97 table rows nor 1,303 field entries can close system-wide type adoption.

## Reproduce source discovery

Use the existing backend dependency environment, from the repository root:

```text
python backend/scripts/build_refactor_inventory.py --repo . --ref 3cdd6808ff7ced0717f337d17d4e530719d4a86f --output inventory.json
```

The [offline tool](../backend/scripts/build_refactor_inventory.py) extracts a fresh
temporary archive of that committed source, cross-checks inherited static fields
against ORM metadata, requires named ownership, and refuses Engine connections.
It imports schema registration under inert SQLite configuration, without app.main
or db.session. Constraint sorting makes repeated regeneration deterministic; record
the newly generated hash rather than assuming the original review artifact's
constraint iteration order was canonical. Static mapped_column classes are supported;
unresolved/duplicate classes, ownership or metadata mismatches fail. The committed
compact ledger is the shared initial field/owner artifact; regeneration supplies
full declarations, defaults and constraints. Actual values and consumer semantics
still require separate review. Fetch the source revision if it is absent locally.

## Named operation queue

Each row is a starting operation, not the complete domain backlog. Pilot states
describe drafts, not accepted migrations. Queued work requires its owner to agree
the public seam and examples before implementation. Shavkat owns business acceptance;
the listed engineer/reviewer own technical review. This queue does not add service
folders, set service counts or authorize new business behavior.

| Domain / tables | Engineer / reviewer | Next operation | State |
| --- | --- | --- | --- |
| catalog / 12 | Ismail / Mirshoir | CAT-01: Create standard/usluga paid process | CONTRACT_AND_VISUAL_PENDING |
| finance / 2 | Ismail / Mirshoir | FIN-01: Record invoice payment | FRONTEND_AND_VISUAL_PENDING |
| fulfillment / 10 | Mirshoir / Ismail | FUL-01: Reserve finished goods | QUEUED_FOR_OWNER_AGREEMENT |
| identity / 3 | Dilmurod / Mirshoir | IDN-01: Select authenticated session factory | QUEUED_FOR_OWNER_AGREEMENT |
| inventory / 14 | Ismail / Mirshoir | INV-01: Receive stock batch | FRONTEND_AND_INTEGRATION_PENDING |
| packaging / 9 | Mirshoir / Ismail | PKG-01: Create package | QUEUED_FOR_OWNER_AGREEMENT |
| people / 14 | Dilmurod / Mirshoir | PEO-01: Create employee | QUEUED_FOR_OWNER_AGREEMENT |
| planning / 3 | Ismail / Mirshoir | PLN-01: Create branded planning order | PILOT_REQUIRES_CORRECTION |
| production / 18 | Mirshoir / Ismail | PRD-01: Shared Sewing output | QUEUED_FOR_OWNER_AGREEMENT |
| purchasing / 4 | Ismail / Mirshoir | PUR-01: Create purchase request, direct and from Sales | AI_VERIFIED_AWAITING_HUMAN at 1a71f16 |
| sales / 2 | Ismail / Mirshoir | SAL-01: Create standard sales order | FULFILLMENT_BOUNDARY_PENDING |
| support / 4 | Dilmurod / Mirshoir | SUP-01: Patch one settings section | SOURCE_IMPLEMENTED_VERIFICATION_PENDING |
| work_management / 2 | Dilmurod / Mirshoir | WRK-01: Create task and notification | QUEUED_FOR_OWNER_AGREEMENT |

## Operation boundaries to agree and preserve

The [26 October operation checkpoint and local human checklist](archive/ISMAIL_OPERATION_CHECKPOINT_2026-10-26.md)
records exact revisions, scoped results and remaining gates. PUR-01 acceptance is
limited to request creation at `1a71f16`; no whole table/domain or human approval
is implied. Other draft results remain provisional. Initial field review defaults
above remain pending.

- **CAT-01 — Create standard/usluga paid process:** `backend/app/models/catalog/paid_processes_service.py::create_process`. Neutral 13-section canonical enum; final generated row.code is also a write; audit dependency.
- **FIN-01 — Record invoice payment:** `backend/app/models/payments_service.py::create_invoice_payment`. Payment and invoice-status writers plus same-Session audit/idempotency; actual InvoiceStatus contracts still need verification.
- **FUL-01 — Reserve finished goods:** `backend/app/api/routes/finished_goods.py::reserve`. Mirshoir owns stock/reservation public operation and persistence; trace Sales alternate caller plus repair_missing_brand_metadata writes, locks, grade refusal and release path.
- **IDN-01 — Select authenticated session factory:** `backend/app/api/routes/auth.py::switch_factory`. Dilmurod/Mirshoir reconcile FactoryCode across DTOs and access context; selected differs from assigned factory. Session selection needs no invented database write; users has no user_type column.
- **INV-01 — Receive stock batch:** `backend/app/models/inventory/stock_service.py::receive_stock`. Real QC Enum/member default and JSON/idempotency compatibility; batch/movement and every related mapped mutation.
- **PKG-01 — Create package:** `backend/app/api/routes/packages.py::create_pkg`. Preserve department scope, package items/allocations/identity, grade/capacity rules, audit and idempotency; trace create_package and mixed route/service cycle.
- **PEO-01 — Create employee:** `backend/app/api/routes/hr.py::create_employee`. Preserve selected-factory references, salary/private HR validation, employee-number uniqueness, audit and refusal rollback; classify actual status and JSON discriminators.
- **PLN-01 — Create branded planning order:** `backend/app/models/planning/branded_orders_service.py::create_branded_order`. Real party/status Enum consumers; avoid str(EnumMember); include numbering/audit and record alternate creation caller.
- **PRD-01 — Shared Sewing output:** `backend/app/api/routes/production.py::post_sewing`. Mirshoir agrees shared normal/band operation; preserve WorkOrder/assignment lock order, output limits, corrections, Packaging handoff and retry identity.
- **PUR-01 — Create purchase request, direct and from Sales:** `backend/app/models/purchasing/requests_service.py::create_purchase_request`. Typed command; legal draft/pending_approval creation subset; header/lines plus shared audit/notification persistence.
- **SAL-01 — Create standard sales order:** `backend/app/models/sales/orders_service.py::create_sales_order`. Real order/source enums; ready-stock reservation and metadata repair require Fulfillment ownership; no Sales-owned stock writer.
- **SUP-01 — Patch one settings section:** `backend/app/api/routes/settings.py::save_company_info`, `save_financial_settings`, and `save_system_preferences` delegate to Support service and schema persistence on one Session. PR354 at `693f7f47` passed exact-source full CI and 235 required PostgreSQL cases. Section discriminator and language contracts are canonical; currency/timezone/model types remain configurable. Stored-language census, actual Computer/readback, postvisual checks and acceptance remain pending; logo upload is separate.
- **WRK-01 — Create task and notification:** `backend/app/api/routes/tasks.py::create_task`. Single recipient and manager broadcast are one operation family; preserve recipient bounds, status/priority semantics and atomic task/notification/audit effects.

Fulfillment reservation work is an immediate dependency of the Sales pilot, not
a reason to hide Fulfillment writes inside Sales schemas. Shared audit/notification
and idempotency persistence are immediate pilot dependencies too: Purchasing is
the temporary audit/notification writer; Finance is the temporary idempotency writer.
Dilmurod/Mirshoir retain shared infrastructure ownership. No competing helper copies.

## Concrete isolation work packages

- **Catalog, Ismail / Mirshoir:** resolve the model_images_service ↔ model_family_images_service cycle through one agreed public owner for shared preview/image-identity rules; do not copy private helpers. This is separate from PaidProcess creation.
- **Identity, Dilmurod / Mirshoir:** resolve factory_scope_service ↔ user_access_service through an agreed context/policy boundary while preserving permissions. FactoryCode is MIL/BST/ECO; ALL/UNASSIGNED report filters remain separate.
- **Production/Packaging, Mirshoir / Ismail:** trace normal/band/correction and packaging route↔service calls; remove HTTP-handler/private-route reach-through at the approved operation seam. Deferred imports do not establish isolation.
- **Sales/Fulfillment, Mirshoir with Ismail:** owning public reservation/metadata operations must cover stock, reservation and brand/collection mutations with the same supplied Session and one outer transaction.
- **Shared support, Dilmurod / Mirshoir:** root helper imports require ownership review; a green check on grouped folders does not certify root/shared coupling.

## Advancing a row

Study old source and all callers → classify fields and supported values → agree
the operation → assigned Codex subagent implements schema-owned writers and actual Enum contracts
→ freeze source/hashes → technical and applicable PostgreSQL checks → actual browser
vision, persisted readback and bounded stress → independent AI review →
**AI_VERIFIED_AWAITING_HUMAN** → recorded human visual/technical approval.

Record converted, retained-with-reason and unresolved fields individually. Do not
advance a whole table/domain because its first operation passes. Operation-level
checkpoints update only their explicitly named scope/revision, not initial field
defaults. Publication, merging and deployment remain separate from runtime verification.

## Subsequent Ismail operations

These are named study/extraction queues, not accepted work or permission to skip
the current operation's human gate:

- Catalog: model creation/counter writes, then the shared image-preview ownership cycle.
- Purchasing: request approve/reject, conversion, purchase-order creation and receiving.
- Finance: invoice issuance through both existing entrypoints, customer advances,
  customer-ledger auto-invoicing and shipment delivery/reversal writers.
- Inventory: receipt edit/other CRUD, accessory returns, transfers, reservations,
  stocktake and waste handoffs; preserve each operation's distinct QC/retry rules.
- Planning: the alternate Production-creation writer, requirements and costing contracts.
- Sales: finish the agreed Fulfillment reservation/metadata seam, then update,
  cancellation and release paths. Mirshoir retains Fulfillment ownership.

## Remaining work by domain

All 13 domains remain **INCOMPLETE**. This queue expands the next-operation list;
it is neither exhaustive behavior coverage nor approval of a new public interface.
Study each operation's complete old call graph and table/field values before its
implementation. Record converted, retained-with-reason and unresolved contracts
individually, including DTO input/update/output, internal and frontend consumers.
No table/field override or human approval is added by this documentation update.

| Domain / tables | Human engineer / reviewer | Remaining work |
| --- | --- | --- |
| catalog / 12 | Ismail / Mirshoir | Paid-process corrected contracts and exact combined visual/readback gates; Model creation/counters; product/BOM/variant/partner consumers; image-preview ownership cycle. |
| finance / 2 | Ismail / Mirshoir | Payment frontend enum consumers and checker correction; exact combined visual/readback gates; Invoice issuance at both entry points; customer advances/ledger auto-invoicing; delivery/reversal writers. |
| fulfillment / 10 | Mirshoir / Ismail | Public reservation/metadata-repair seam used by Sales, owning schema writers, Session and locks; Receipts, finished-stock edits, release, shipment, returns and delivery callers. |
| identity / 3 | Dilmurod / Mirshoir | Selected versus assigned factory contract and factory-scope/user-access dependency cycle; Authentication, account/RBAC contracts and supported factory discriminator consumers. |
| inventory / 14 | Ismail / Mirshoir | Receipt QC internal/frontend contracts and exact combined visual/readback gates; Receipt edits/CRUD, accessory returns, transfers, reservations, stocktake and waste handoffs. |
| packaging / 9 | Mirshoir / Ismail | Package identity/public parser ownership and route/service cycle; Create/correct package, contents/allocations, receiving-group versus warehouse identity, labels and downstream callers. |
| people / 14 | Dilmurod / Mirshoir | Employee creation operation, selected-factory authorization and private HR fields; Attendance/device data, HR lifecycle and payroll contracts/writers; reconcile attendance user_type separately from users. |
| planning / 3 | Ismail / Mirshoir | Branded-order HTTP/frontend and derived-status contracts; exact combined verification; Alternate Production creation writer; requirements, forecasts and costing contracts. |
| production / 18 | Mirshoir / Ismail | Shared Sewing operation and normal/band/correction boundaries; Cutting deletion route-helper reach-through, all dependent writers/locks; production orders, cutting, printing, bundles and stage handoffs. |
| purchasing / 4 | Ismail / Mirshoir | PUR-01 named human approval for exact 1a71f16 remains pending; Approve/reject, conversion, purchase-order creation and receiving; preserve action subsets. |
| sales / 2 | Ismail / Mirshoir | Typed Fulfillment reservation seam and legal per-action stock-kind/quantity subsets; Order update, cancellation/release, alternate ready-stock callers and actual DTO/internal/frontend consumers. |
| support / 4 | Dilmurod / Mirshoir | Settings-section operation, JSON discriminators and unknown-field semantics; Shared audit/idempotency/settings/reference helpers and all participating writers; inspect root-helper ownership. |
| work_management / 2 | Dilmurod / Mirshoir | Task creation and notification operation with recipient/manager-broadcast bounds; Task transitions, priority, notification read/update and audit/notification participation in other domains. |

The 97-table inventory totals 1,303 fields, all still subject to explicit field
review. The eight non-persisted contract categories remain independently pending
for each domain. AST/name matches are discovery candidates; source declarations,
actual authorized database values and all consumers must be reconciled semantically.
An absent user_type field on users does not erase attendance_people.user_type;
likewise configurable role rows do not make every discriminator free text.

Every write trace includes inserts, updates, deletes, mapped/relationship changes,
cascades, raw/bulk SQL and audit/notification/idempotency participants. Routes call
dedicated services; cross-domain callers use the agreed owning public operation;
schema-owned writers share the outer service's Session and transaction. Keep lock
order, retry fingerprints, action subsets and external-effect timing explicit.

Freeze hashes before verification and record which combined revision actually ran.
Technical and applicable PostgreSQL tests, inspected connected-browser screenshots,
real actions, reopen/readback and bounded integrity/recovery checks must all pass
before independent `AI_VERIFIED_AWAITING_HUMAN`. A changed candidate needs affected
checks repeated. Named human visual/technical acceptance is a separate recorded gate.
