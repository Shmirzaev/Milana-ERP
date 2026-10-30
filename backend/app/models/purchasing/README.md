# Purchasing

Business-service group guide, relocated into models/ on 24 October 2026. The
approved operation extraction of 25 October 2026 moved the purchasing routes'
orchestration into the three service modules below.

**Purpose:** Own purchase requests, approval, request-to-order conversion and receiving orchestration.

**Engineering owner:** Ismail. **Reviewer:** Mirshoir.
**Business acceptance:** Shavkat with operators.
This owner covers the feature's routes, DTOs, enums, database definitions and tests.
See [team ownership](../../../../docs/TEAM_OWNERSHIP.md) for shared-layer coordination.

## Service files

| File | Responsibility |
| --- | --- |
| [requests_service.py](requests_service.py) | Request directory, creation, creation from a sales order, approval, rejection, conversion, request photo. |
| [orders_service.py](orders_service.py) | Purchase order directory, its page and its creation. |
| [receiving_service.py](receiving_service.py) | Receive a purchase order, lock it, authorize it, replay it and write its stock in one commit. |
| [purchasing_service.py](../purchasing_service.py) | The core operations the three modules above call: request create/approve/reject/convert, order creation, receipt. |

The core operations stay in `purchasing_service.py`; the group modules own the
outer operation each route used to orchestrate, including per-line access checks
and the single commit. Order creation and conversion refresh the flushed order
and validate a typed snapshot before committing, returning it after commit succeeds.
PostgreSQL commit-time effects and response parity require separate verification.
Other operations retain their own refresh behavior. The group modules call the
core operations; they never re-implement them.

## Other source pointers

- Routes: [purchasing.py](../../api/routes/purchasing.py) - HTTP binding only.
- Existing SQLAlchemy schema models: [PurchaseRequest](../../schemas/purchasing/purchasing.py#L9), [PurchaseRequestLine](../../schemas/purchasing/purchasing.py#L39), [PurchaseOrder](../../schemas/purchasing/purchasing.py#L71), [PurchaseOrderLine](../../schemas/purchasing/purchasing.py#L100).
- Existing Pydantic contracts: [purchase_request_input.py](../../libs/dto/purchasing/purchase_request_input.py), [purchase_request_output.py](../../libs/dto/purchasing/purchase_request_output.py), [purchase_order_input.py](../../libs/dto/purchasing/purchase_order_input.py), [purchase_order_output.py](../../libs/dto/purchasing/purchase_order_output.py).

## When making a service file

Use snake_case_service.py filenames and operation names such as `create_*`, `record_*`,
`receive_*` or `approve_*`. A typed function is sufficient; a class is optional
when it owns real dependencies. Accept the Session, validated input and actor
explicitly. State the transaction owner, refusal rules and result contract.
Use the existing ORM definitions in schemas/ and DTOs in libs/dto/<feature>/;
keep fixed values in libs/enums/. See [DTO conventions](../../libs/dto/README.md).
Do not import routers, call an endpoint, or commit inside a helper owned by another
transaction. Do not create an interface/repository or generic CRUD class by default.

Database definitions have moved to schemas/; business operations use
*_service.py.

**DTOs and enums:** Purchase request/order statuses, with transition checks retained in the service. Reuse Create/In, Update and Read/Out contracts
where they exist. Add action-specific input only for a real action. Do not generate
three DTOs for every table or expose privileged fields through generic updates.

## Remaining exceptions

- `purchasing_service.py` still holds the core operations. The group modules
  call it; request creation and approval delegate their mapped writes to
  `schemas/purchasing/purchase_request_persistence.py`. Other operation writes
  remain migration work, not an exception to the schema-owned write rule.
- The purchase quantity bound and its two aliases live in
  [purchase_quantity.py](../../libs/dto/purchasing/purchase_quantity.py) because
  the request and the order inputs both use them.
- Purchasing exposes no update operation, so there is no `*_update.py` DTO
  module; an update contract would be unused.

## Purchase request approval (PUR-APPROVE)

The HTTP approval DTO maps explicitly to the used approval command in
`libs/types/purchasing.py`. Its lines remain required over HTTP; the internal
command permits omission only to retain the existing direct approved-retry
caller. No client status field was added. The service's approvable subset and
decided transition use canonical `PurchaseRequestStatus`; String storage stays
in the existing mapping and the schema writer serializes the status value.

The root operation retains the request row lock, already-approved return,
exact line-ID checks, stripping, supplier existence checks and their order.
Schema operations apply each line's material/photo/supplier and the header's
status/actor/time using the same supplied Session, without flush or commit.
Audit and PLN notifications retain their existing shared schema writers; the
dedicated service checks every item's authorization and commits once. A late
403 or participant failure must roll back all participants together. Unknown
stored statuses still return409 before enum parsing, and legacy empty requests
remain approvable with empty lines. Rejection and conversion policy is unchanged.

`test_purchase_request_approval_operation.py` verifies the consumed types,
same-Session write sequence, real participant failure/rollback/retry and direct
approved retry. PostgreSQL characterization additionally covers HTTP validation,
late denial and actual approve/approve and approve/reject row-lock contention.
Exact-candidate test evidence, independent review, connected-browser approval
and fresh persisted readback, operator handoff and human acceptance are separate
gates. This extraction does not complete Purchasing or its remaining operations.

## Purchase request rejection (PUR-REQUEST-REJECT)

The core operation locks the request, returns 404 before transition checks,
and permits rejection only from draft, pending_approval or approved. The
rejectable subset is canonical `PurchaseRequestStatus`; membership is checked
before enum parsing so unknown stored values retain the 409 refusal. The
schema-owned rejection writer applies the decided `REJECTED` value to the
locked row in the same Session. The core then records the existing audit
payload. The outer requests service keeps item-access checks after the core
operation and commits once, so access or participant failures roll back the
request and audit together. The writer never flushes or commits.

## Boundaries and verification

Inventory owns stock facts. Receiving coordinates both changes under one transaction; do not create a second independent stock-writing implementation.

Receipt QC uses `StockBatchQcStatus` in the HTTP contract and validated command;
storage stays a plain string. Empty input retains the historical `passed`
fallback and its original idempotency fingerprint. Unsupported nonempty QC
values now receive 422 at request validation rather than failing a later
database CHECK. The only production caller of the core is the typed receiving
service; supported direct legacy test values pass through an explicit
Purchasing adapter to the canonical enum. An unsupported value supplied by an
internal direct caller now raises `ValueError` during an all-lines preflight,
before any receipt write is staged, instead of reaching the old database CHECK
and raising an integrity error. The old CHECK rejects these values, so no
accepted QC value is removed. The HTTP request's original
QC text remains private to the replay fingerprint. PO receipt stock writes enter
Inventory through `record_purchase_order_stock_receipt` on the caller's Session;
Purchasing retains the single outer commit. Inventory owns batch/movement
construction; Purchasing's schema operations own line and header mutations. The
participant does not perform access checks, replay, audit or commit.

The receive route and replay snapshot use `PurchaseOrderReceiptOut` with
`PurchaseOrderStatus`; it preserves the existing five wire strings. General
`PurchaseOrderOut` remains string-typed because its readers historically accept
custom stored values. The mapped status is an unconstrained `String(32)` and no
authorized production snapshot was read for this operation. An existing test's
`historical_custom` value documents acceptance at the general read contract, but
does not establish production prevalence. The receipt DTO intentionally rejects
values outside the canonical enum; resolving historical data remains a separate
source/value reconciliation item, with no coercion or storage rewrite here.

### Receipt operation value ledger

- Converted consumers: the receive command uses its existing canonical
  `StockBatchQcStatus`; the Inventory participant command also uses that enum.
  Receiving checks and writes use `PurchaseOrderStatus` for the receivable subset
  and decided header status. The receive route and its saved response use
  `PurchaseOrderReceiptOut.status: PurchaseOrderStatus`.
- Preserved storage and wire values: QC and order status remain String columns;
  enum `.value` is used at the schema boundary. The route's raw QC spelling is
  retained only for the original idempotency fingerprint; direct core callers'
  supported raw QC strings are adapted at the Purchasing boundary.
- Intentional invalid internal-input change: an unsupported direct-core QC
  value now raises `ValueError` in the all-lines preflight before any receipt
  participant is called. Previously it reached the database CHECK and raised
  an integrity error; the constraint rejects it, and the typed production
  caller cannot provide such a value. A regression test covers a valid first
  line followed by invalid QC, no staged/committed effects, rollback and one
  successful retry.
- Retained general read contract: list/create/conversion consumers that use
  `PurchaseOrderOut` keep its historical `status: str` projection. Its old
  `historical_custom` characterization remains valid. Actual production values
  outside `PurchaseOrderStatus` were not inspected; the receipt-specific DTO
  rejects such values without coercion, leaving real historical prevalence open.
- Retained free-form values: `StockBatch.color_status`, descriptive batch text,
  and identifiers remain strings. Movement type is serialized by Inventory's
  stock persistence writer as canonical `StockMovementType.RECEIVE`.

Verify partial/repeated receiving, kg versus metre quantities, item access, totals and rollback. Visually check purchase request approval, order receiving and the resulting stock batch.

## Migration steps

Follow [the shared sequence](../README.md#migration-sequence): study route/DB/rules
and callers -> agree one operation -> capture baseline tests -> extract -> test
old/new separately -> test the real UI on isolated data -> reviewed switch -> human
production verification -> remove old code. Keep one write path per request.
Record the test result, visual evidence, approver and cleanup condition in the task.
Visual success alone does not prove permissions, concurrency or data correctness.
