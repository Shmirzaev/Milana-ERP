# Whole-ERP refactor coverage

## Dilmurod's source-classification slice — 7 November 2026

The following PRs land behavior-preserving code changes. The [23-table, 324-field source ledger](REFACTOR_DILMUROD_FIELD_REVIEW_20261107.json) classifies the current mapped declarations and records each field's source location and disposition. It is a **source-only review**: no authorized production-value snapshot was examined, so actual stored values, complete DTO/internal/frontend consumers, operation-level visual/integrity gates and human acceptance remain open. The historical 97-table/1,303-field inventory keeps its original defaults.

| Area | Code PR | Landed scope | Remaining code or decision |
| --- | --- | --- | --- |
| Identity | #546, #549 | Canonical factory-code type in session helpers and `/api/auth/me` output; Eco Band Role/User/flow-state writes through schema-owned functions | Input Enum validation would change 400/422 order; raw admin UserOut and actual stored values await production counts and a decision. Startup seed/reset writers are **excluded: not part of the running application (decision Dilmurod, 7 Nov)**. |
| People | #545 | CHECK-backed payroll output types, factory-code output types and optional HR GET backfill through the People service/schema writer | Input status typing would change 400/409 to 422; attendance vendor `user_type`, HR/JSON and unchecked legacy values await production counts and a decision. One-off employee consolidation is **excluded: not part of the running application (decision Dilmurod, 7 Nov)**. |
| Support | #547 | Bundle alias, Packaging notification and employee-alias setting writes moved to schema-owned operations with the same Session | Dynamic audit action/entity, reference namespace, idempotency response and per-key settings JSON need actual-value/consumer review before narrowing. |
| Work management | #544, #549 | Typed internal task reference kind and canonical completion value; task and notification reads moved from routes to their services | TaskOut legacy status/priority and notification-send input details await production counts and a decision. |

No row here is marked AI verified, production deployed, or human accepted. For source-only classifications, `retain` means preserve the current data type, not that every consumer has passed the full semantic audit; `needs_decision` means narrowing could affect existing values or errors.

The 47 `needs_decision` fields in the source ledger each have one local-only, read-only aggregate query in `prod_contract_check.sql`. Shavkat's acceptance list asks for the counts only. A zero count supports the proposed stored-value set; a non-zero count needs review. For dynamic JSON/text, even a zero count cannot establish the future contract. **No approved behavior-preserving code item remains in Dilmurod's four areas.** Production counts, contract decisions, full consumer review and recorded visual/integrity/human acceptance remain open.

The seed exclusion refers to the current running request/startup configuration: ordinary startup defaults `RUN_SEED_ON_STARTUP` to false (`backend/app/main.py:99-103`), and the release record says it was disabled (`docs/archive/PACK_CUSTOMER_FG_RELEASE_2026-11-03.md:73-80`). An operator can explicitly opt in later; that path is not certified by this exclusion. The employee reconciliation function has only test callers in the current source (`backend/app/models/employee_reconciliation_service.py:10`).

## Integrated Dilmurod operations — 6 November 2026

The following are **code-landed operation checkpoints**, not whole-domain completion, AI verification, production deployment or human acceptance. Stacked child PR code below landed through the named top PR: #468–#470 via #471; #487, #494 and #498–#499 via #506; the six missing #500–#505 extractions via #542; #492 and #495 via #497; #515–#534 via #535; #538–#540 via #541. Their original PR numbers identify the operation and the top PR identifies the integration merge. Source and status are the merged integration PRs; the historical inventory and initial field/type review defaults below remain historical.

| Area / slice | Code-landed operations (original PR number) | Integration |
| --- | --- | --- |
| Identity prerequisites and RF-009 | Access-policy helper split [#371]; create-user characterization [#345] and service extraction [#374] | #371, #345, #374 |
| Identity IDN-01 | Factory-switch characterization [#382], service extraction [#386], switch audit [#387] | #382, #386, #387 |
| Identity W1 auth | Login [#475]; password-reset request [#478]; reset completion [#479]; password change [#480]; current-session read [#485] | #475, #478, #479, #480, #485 |
| Identity profile and W5 access | Self-profile update [#487] and self-email lock [#494]; role list [#498]; role creation [#499]; access catalog [#500]; access preview [#501]; user list [#502]; user read [#503]; admin user update [#504]; user deletion [#505]; clear duplicate-role refusal [#506] | #506 for profile/roles; #542 recovered the six missing #500–#505 extractions |
| People PEO-01 and W3 HR | Employee creation [#447]; employee update [#451]; organization-unit creation [#452] and deletion [#453]; department creation [#454], update [#456] and deletion [#459]; staffing-position creation [#457] and update [#461]; employee archive [#462]; recruitment-candidate creation [#465] and update [#466]; HR document upload [#468] and deletion [#469]; HR calendar-event creation [#470]; HR-settings save [#471] | Individual PRs listed; #471 includes #468–#470 |
| People W7 attendance | Device creation [#481] and update [#484]; HR attendance reconciliation [#483]; connector-token rotation [#486]; people import [#488]; event-batch import [#489]; photo import [#490]; attendance overview [#491]; daily workbook [#492]; private photo lookup [#495]; photo cache protection [#497] | Individual PRs listed; #497 includes #492 and #495 |
| People payroll continuation | Period creation [#511], list [#512], update [#513], lock [#514], approval [#515] and payment [#516]; record list [#517]; order-QR status order list [#518] and report [#519]; sewing-production report options [#520], report [#521] and Excel [#522]; process-QR export [#523]; employee search [#524] and number resolve [#525]; QR token resolve [#526] and label list [#527]; summary [#528]; adjustment list [#529]; employee options [#530]; split-record label print [#531]; QR issuance [#532]; records and scans [#533]; adjustments and reversals [#534]; combined QR lifecycle [#535] | #511–#514 and #535; #535 includes #515–#534 |
| Support SUP-01 and W6 | Settings-section save [#446]; settings read [#472]; variant-reference writes [#473]; bundle-reference reservation [#474]; company-logo save [#477] | #446, #472–#474, #477 |
| Work management WRK-01 and W4 | Task creation and notification [#445]; task update [#448]; completion [#450]; deletion [#455]; notification send [#460], read [#464] and read-all [#467]; manager assignee list [#536] | #445, #448, #450, #455, #460, #464, #467, #536 |
| Shared RF-004 slices | Audit read/summary [#538]; shipment-reopen request-hash persistence [#539]; readiness probe lifecycle [#540]; reusable verification/JUnit/provenance/sanitization bodies [#541] | #541 includes #538–#540 |

These landings do not by themselves close the original 97-table/1,303-field audit or the non-persisted DTO/internal/frontend contract review. For Dilmurod's domains, open coverage still includes selected-versus-assigned factory and supported factory-discriminator consumers (Identity); private HR/attendance `user_type` and payroll contract/type review (People); shared audit/notification/idempotency/settings/reference writer and JSON/unknown-field review (Support); task/notification type and cross-domain writer review (Work management). Operation-specific visual, persisted, stress, independent and human acceptance remain separate gates where not recorded.

## Verified operation checkpoint - 4 November 2026

The [Finance invoice reversal participant](REF350_INVOICE_REVERSAL_20261104.md)
at 60bcf909 is AI_VERIFIED_AWAITING_HUMAN after 204 distinct PostgreSQL cases,
actual visual/refresh/EN-RU-UZ phone evidence, 20-table persisted checks and
independent review. It owns only eligible invoice VOID/zero writes inside shipment
reopen using the existing locked Session and outer transaction. Full coordinator
audit remains FAIL on unchanged legacy scan persistence. Stock/package/order/
audit/idempotency extraction, other Finance operations, amount typing and uncovered
domains remain in scope. QA master reviews before deployment; human acceptance
is unrecorded. The dated checkpoint below retains its original snapshot rather
than serving as a current branch or open-PR census.

## Historical integration and active work — 30 October 2026

`clone_main` is verified at `d235cf9e9a44b1de81428beb261f8fab837cbe87`, tree
`33b45e218c57e285e14df48bd166fe04309c95b9`. PR343 merged Supplier DELETE,
Inventory Item CREATE and Sales DELETE after exact-source CI, Computer visual
checks, persisted/audit readback, independent review, and 40 explicit PostgreSQL
cases with zero failures/errors/skips. Owned disposable targets and runtimes
were cleaned up. This is integration evidence, not deployment or personal human
production acceptance. PR341 also merged Customer DELETE; older pending wording
in the source-checkpoint queue must not be read as current status.

The owner explicitly resumed the full remaining scope on 30 October, requesting
cheap parallel subagents. This includes all 13 domains and shared writers; named
human accountability below is unchanged. Three isolated workers are preparing
Collection UPDATE, Finance payment-output typing and Purchasing costing-update
on the current base. The integrator owns shared notification persistence and
serializes combined-source verification. None of these new candidates is yet
runtime-verified or merged. Previously frozen candidates remain preserved.

| Remaining scope | Current next work / evidence required |
| --- | --- |
| Catalog | Collection UPDATE (including same-value attribute events and legacy status compatibility); paid-process, model/counter, BOM and image operations |
| Purchasing | Costing update and shared notification transaction; approval/rejection, conversion, orders and receiving |
| Inventory | Receiving/receipt edits, transfers, reservations, stocktake, accessory returns and waste handoffs |
| Sales | Create/update, cancellation/release and Fulfillment public operation/lock boundary |
| Planning | Broader order creation, alternate Production writer, requirements and costing contracts |
| Finance | Typed payment result/replay; invoice issuance/void/reopen, advances and ledger/shipment writers |
| Production | Shared Sewing and stage transitions, correction paths and route/private-helper reach-through |
| Packaging | Contents, allocation/identity, corrections, labels and lifecycle writers |
| Fulfillment | Receipts/finished stock, reservation/release, shipment/delivery/reversal and returns |
| Identity | Factory/auth context, user access and account operations |
| People | Employee/attendance/payroll contracts, writes and locking |
| Support | Settings, shared audit/idempotency and other root writers |
| Work management | Task CRUD/transitions and notification operations |

Every row retains operation-sized enum/type classification, caller/alternate
writer tracing, same-Session persistence, tests, actual visual/readback, bounded
integrity/stress and independent acceptance gates. This is an execution backlog,
not exhaustive source discovery or a completion percentage. The initial table/
field JSON inventory below remains historical and must not be relabelled current.

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
| support / 4 | Dilmurod / Mirshoir | SUP-01: Patch one settings section | QUEUED_FOR_OWNER_AGREEMENT |
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
- **SUP-01 — Patch one settings section:** `backend/app/api/routes/settings.py::save_settings_section`. Preserve section-specific schema/unknown-field handling, absent-row advisory lock, JSON merge and audit; section discriminator is distinct from configurable values.
- **WRK-01 — Create task and notification:** `backend/app/api/routes/tasks.py::create_task`. Single recipient and manager broadcast are one operation family; preserve recipient bounds, status/priority semantics and atomic task/notification/audit effects.

Fulfillment reservation work is an immediate dependency of the Sales pilot, not
a reason to hide Fulfillment writes inside Sales schemas. Shared audit/notification
and idempotency persistence are immediate pilot dependencies too: Purchasing is
the temporary audit/notification writer; Finance is the temporary idempotency writer.
Dilmurod/Mirshoir retain shared infrastructure ownership. No competing helper copies.

## Concrete isolation work packages

- **Catalog, Ismail / Mirshoir:** resolve the model_images_service ↔ model_family_images_service cycle through one agreed public owner for shared preview/image-identity rules; do not copy private helpers. This is separate from PaidProcess creation.
- **Identity, Dilmurod / Mirshoir:** the [policy-only prerequisite](archive/ACCESS_POLICY_HELPER_SPLIT_2026-11-03.md) landed in #371: three unchanged evaluators moved to `identity/access_policy_service.py`, removing the factory-scope/user-access back-edge while preserving legacy exports. IDN-01 and RF-009 code landed in #382/#386/#387 and #345/#374; remaining factory and access contract review is listed above. FactoryCode is MIL/BST/ECO; ALL/UNASSIGNED report filters remain separate.
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
| identity / 3 | Dilmurod / Mirshoir | #546 types selected/assigned factory output and session results; #549 routes Eco Band writes through Identity and Production schema operations. Factory input refusal order, admin UserOut and real stored values await counts/decisions. Startup seed/reset is excluded from the running application (Dilmurod, 7 Nov). Independent operation and human acceptance remain separate. |
| inventory / 14 | Ismail / Mirshoir | Receipt QC internal/frontend contracts and exact combined visual/readback gates; Receipt edits/CRUD, accessory returns, transfers, reservations, stocktake and waste handoffs. |
| packaging / 9 | Mirshoir / Ismail | Package identity/public parser ownership and route/service cycle; Create/correct package, contents/allocations, receiving-group versus warehouse identity, labels and downstream callers. |
| people / 14 | Dilmurod / Mirshoir | #545 types CHECK-backed payroll/factory outputs and moves optional employee GET backfill into the service/schema path. Input refusal order, vendor attendance_people.user_type and unchecked HR/JSON values await counts/decisions. One-off employee consolidation is excluded from the running application (Dilmurod, 7 Nov); operation and human acceptance remain separate. |
| planning / 3 | Ismail / Mirshoir | Branded-order HTTP/frontend and derived-status contracts; exact combined verification; Alternate Production creation writer; requirements, forecasts and costing contracts. |
| production / 18 | Mirshoir / Ismail | Shared Sewing operation and normal/band/correction boundaries; Cutting deletion route-helper reach-through, all dependent writers/locks; production orders, cutting, printing, bundles and stage handoffs. |
| purchasing / 4 | Ismail / Mirshoir | PUR-01 named human approval for exact 1a71f16 remains pending; Approve/reject, conversion, purchase-order creation and receiving; preserve action subsets. |
| sales / 2 | Ismail / Mirshoir | Typed Fulfillment reservation seam and legal per-action stock-kind/quantity subsets; Order update, cancellation/release, alternate ready-stock callers and actual DTO/internal/frontend consumers. |
| support / 4 | Dilmurod / Mirshoir | #547 moves residual bundle alias, Packaging notification and employee-alias setting writes to schema operations. Dynamic audit, idempotency and settings JSON/unknown-field contracts still require actual-value and caller review; operation and human acceptance remain separate. |
| work_management / 2 | Dilmurod / Mirshoir | #544 types the resolved task reference and completion value; #547 covers the Packaging notification writer; #549 moves task/notification reads into services. Legacy TaskOut values, reference aliases and NotificationSendIn refusal details await counts/decision. Operation and human acceptance remain separate. |

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

9 November local physical-turnstile candidate: three new mappings / 42 columns
plus `gate_employee_devices.mode` are inventoried with typed JSON consumers and
schema-owned writes in [the packet](TURNSTILE_LIVE_INTEGRATION_20261109.md#storage-and-vocabulary-inventory).
No production rows exist for these new tables in this task. Source, fake HTTPS
and disposable PostgreSQL evidence do not prove physical firmware behavior.
The owner explicitly deferred the new visual checks; the full AI/human/release
gates are not marked passed.
