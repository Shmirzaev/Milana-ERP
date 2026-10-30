# Direct finished-goods reserve operation

Status: implementation candidate only; independent review, tests, visual work,
readback, bounded stress and human acceptance remain pending. This slice covers
only `POST /api/finished-goods/reserve` and its manual-package/piece-stock paths.
It does not extract release, Sales order reservation, or legacy metadata repair.

## Source and ownership

- Base: `clone_main` `ff1542f02c137f24fc9fe78492aa69aa463a7293`, tree
  `649f430e01a1fabc6d97055d91c9bdd009bf7f3a`.
- Isolated worktree: `refactor-direct-fg-reserve-20261030`, branch
  `codex/refactor-direct-fg-reserve-20261030`.
- Operation/domain owner: Mirshoir; reviewer: Ismail; AI implementer:
  cheap_catalog; integrator: root; business acceptance: Shavkat and warehouse
  operators.
- Route: `backend/app/api/routes/finished_goods.py::reserve`.
- Service: `backend/app/models/fulfillment/stock_service.py::reserve_direct_stock`.
- Persistence: existing same-session
  `backend/app/schemas/fulfillment/stock_persistence.py::reserve_stock_row`.
- Internal result contract: `backend/app/libs/types/stock_reservation.py`.
- Response contracts: `backend/app/libs/dto/fulfillment/stock_reservation_output.py`.

## Operation and data ledger

The route retains the `sales.orders` permission dependency and HTTP query
parameters. Its typed output union records the two existing response shapes;
piece reservations still omit `package_id`, manual-package reservations still
include it, and the OpenAPI response schema now documents those shapes. The
Fulfillment service preserves initial stock lookup, quantity
validation, package lock and classification order, manual-vs-piece branch,
refusal codes/messages and the single commit. The schema operation owns all
`FinishedGoodsStock` quantity/status mutations and `StockReservation` inserts.
The shared audit helper remains the existing participant and uses the same
Session; no notification or idempotency policy is introduced.

| Table/fields | Operation effect | Type/status |
| --- | --- | --- |
| `finished_goods_stock.available_qty`, `reserved_qty`, `status` | Updated through `reserve_stock_row`; `quantity` and `sold_qty` are read-only inputs to the manual-package balance checks. | Write boundary converted. Persisted `status` stays the existing VARCHAR and mapped `str`; changed statuses use canonical `FinishedGoodsStatus` and persist its exact `.value`. Partial piece reserves pass `None`, so an unchanged status is not assigned, preserving attribute-event semantics. Complete ORM runtime-enum adoption remains open. |
| `stock_reservations.sales_order_id`, `finished_goods_stock_id`, `package_id`, `quantity`, `reserved_by` | Inserted through `reserve_stock_row` in the same Session. Manual branch writes one row for each unsold size row; piece branch writes one row for the selected stock. | Write boundary converted; stored fields/values retained. |
| `audit_logs` | Existing `log_action` writes `reserve` with the original entity type, entity ID, actor and exact new-value payload. | Shared audit behavior retained and still participates in the same transaction. |
| `packages`, `package_items`, `sales_orders`, `shipments`, `shipment_packages` | Read and locked for selector, eligibility, linkage, balance and active-shipment checks. No mapped writes in this operation. | Retained. Package and item ownership remains in Packaging; order state remains Sales-owned. |
| Notifications/idempotency/files | No writes in the legacy direct reserve operation. | No change. |

For read-time decision fields, the service now converts the stored package
`status` and `stock_kind` to `PackageStatus` and `PackageStockKind`, manual
order `status` to `SalesOrderStatus`, shipment filters to `ShipmentStatus`, and
stock rows' `status` to `FinishedGoodsStatus`. Those mappings remain VARCHAR/
`str` columns with their existing `ck_packages_status`,
`ck_packages_stock_kind`, `ck_sales_orders_status`, `ck_shipments_status`, and
`ck_finished_goods_status` constraints. Enum conversion uses those bounded
stored vocabularies; there is no raw-string fallback or database migration.
The response `message` remains transport text (`"reserved"`), not a stock
status; partial stock continues to have status `available`.

Manual-package rules remain: whole remaining package quantity in one request;
open order; package/stock/item balance; no existing reservation; no active
shipment; package-before-items-before-stock locks. It reserves every unsold
stock row and retains the Package audit payload. Legacy/package-less piece
rules remain: package-before-stock locking where applicable, refreshed rows,
requested quantity no greater than available, existing stock status preserved
unless availability reaches zero, and FinishedGoodsStock audit payload only.
First/second-grade and returned-to-packaging selectors retain their existing
refusal precedence.

## Callers and surrounding workflows

The direct reserve route is distinct from Sales `reserve_pieces` / `reserve_packs`
and `/api/sales-orders/{id}/reserve-stock`. The latter remain in their existing
Sales/Fulfillment boundary and are not routed through this operation. Existing
`reserve_pieces` still calls `repair_missing_brand_metadata`; this slice does not
move that helper. The sibling `release-reservation` route remains a separate
mapped writer and is not claimed complete here.

Source inspection found no frontend caller of `/api/finished-goods/reserve`.
The Finished Goods page displays stock and warehouse exits; it has no reserve
control. The Sales Order page calls a different endpoint. Do not represent a
Sales-order reservation UI check as visual verification of this direct route.
The direct action has no frontend control; root will evaluate the existing API
explorer for the action and the Finished Goods page for adjacent readback. That
evaluation is pending and is not claimed as a browser pass. No permission or UI
changes are included.

## Test plan and evidence status

Focused existing tests in `test_manual_finished_goods.py` cover manual whole-pack
reserve/refusal, no-reuse, package/stock lock order, manual balance/shipment/order
refusals and legacy/package-less piece behavior. `test_finished_goods_reserve_integrity.py`
contains additional PostgreSQL reserve/release/dispatch/damage races, but its
legacy `STABILIZATION_POSTGRES_URL` fixture is not the approved fixture for this
slice. Added focused tests assert exact audit actors/payloads, same-session
schema-writer use, one commit, audit-fault rollback/retry, manual PostgreSQL
round-trip and competing piece reservations through the approved
`customer_pg_sessions` fixture.

No tests were run in this worktree under the RAM/runtime hold. No application,
PostgreSQL, browser, UI server, CI, or production environment was launched or
connected. These checks are pending on the exact reviewed combined source. The
later human checklist must use synthetic manual and legacy receipts, an operator
with and without `sales.orders`, assert manual whole-quantity and piece quantity
effects/refusals, and read persisted stock, reservations and audit rows. Browser
verification of a direct reserve action remains unavailable because no current
frontend caller exists.

## Remaining Fulfillment inventory

This is one operation slice, not fulfillment-wide or FUL-01 completion. Separate
pending writers include direct reservation release, receipt, metadata repair
ownership, finished-stock correction, shipment/dispatch, returns, delivery and
other package lifecycle operations. Fixed stock status values have a canonical
enum, but the ORM status field and remaining direct-writer consumers still need
table-by-table runtime type reconciliation.
