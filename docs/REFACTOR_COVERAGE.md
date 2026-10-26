# Whole-ERP refactor coverage

Initial candidate-source ledger, 26 October 2026. **The architectural/type target is incomplete.**
Six Ismail pilots are rollout steps; the other owners remain in scope. Use the
[engineering workflow](ENGINEERING_WORKFLOW.md) and [ownership](TEAM_OWNERSHIP.md).

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
- **Identity, Dilmurod / Mirshoir:** resolve factory_scope_service ↔ user_access_service through an agreed context/policy boundary while preserving permissions. FactoryCode is MIL/BST/ECO; ALL/UNASSIGNED report filters remain separate.
- **Production/Packaging, Mirshoir / Ismail:** trace normal/band/correction and packaging route↔service calls; remove HTTP-handler/private-route reach-through at the approved operation seam. Deferred imports do not establish isolation.
- **Sales/Fulfillment, Mirshoir with Ismail:** owning public reservation/metadata operations must cover stock, reservation and brand/collection mutations with the same supplied Session and one outer transaction.
- **Shared support, Dilmurod / Mirshoir:** root helper imports require ownership review; a green check on grouped folders does not certify root/shared coupling.

## Advancing a row

Study old source and all callers → classify fields and supported values → agree
the operation → MiniMax implements schema-owned writers and actual Enum contracts
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
