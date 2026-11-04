# Invoice reversal in shipment reopen — continuation, 4 November 2026

**IN_PROGRESS.** Current source base `af6dafad60b0765368ddbeefabcdf6aa53daa039`;
preserved input `e1f7e016f45b42050f7711cdaf45b0dd3b7f95b0` is applied as an
operation-sized patch, not a merge of the closed PR. Finance owner Ismail; Fulfillment
owner and reviewer Mirshoir; business acceptance Shavkat. The owner authorized continued
refactoring and source integration after AI verification; QA master review remains
required before deployment. No human acceptance or production authority is inferred.

## Boundary and preserved behavior

`POST /shipments/{sid}/reopen` retains `storage.shipment` permission, `ShipmentReopen`
input, `ShipmentOut` response and the single route commit. Shipment service locks the
shipment, packages, stock, reservations, order and invoices in their existing order;
checks stale timestamp, return confirmation, stock conservation and every invoice before
mutations; rejects other live dispatches/order shipments, unsafe manual orders, payments,
external posting and ineligible status with the existing conflict responses. It restores
stock and packages, records return scans, updates order/shipment and matching idempotency
hashes, flushes, synchronizes production, writes the existing shipment audit and flushes.
Those non-invoice mapped writes remain explicit pending extraction; this is not full
Shipment completion.

The one converted participant is `void_invoices_for_shipment_reopen` in Finance service,
called only after all invoice preflight, using the caller's already locked rows and Session.
It calls schema-owned `void_invoice_for_shipment_reopen`, which stages `VOID` and
`Decimal('0.00')`; it acquires no lock, performs no flush, audit or commit. Existing
transaction boundaries, failure ordering and wire contract remain unchanged. No schema
migration or business-policy change is intended.

## Table and type ledger

`invoices`: ID and sales-order FK remain references, invoice number and external source/ID
remain free-form strings, amount remains NUMERIC(14,2); the existing ORM annotation `Mapped[float]` is retained
as debt although database values are Decimal, and the source integer zero is staged as
Decimal zero with storage parity to verify,
issued/due/timestamp fields retain their date/time behavior. Status uses canonical
`InvoiceStatus` as actual ORM `Mapped[InvoiceStatus]` and `InvoiceOut` type; stored values
are unpaid, partially_paid, paid, void and cancelled, with only unpaid/void/cancelled
eligible for this reopen. Existing type decorator's string adapter is retained at storage
boundary; no extra status/DTO narrowing is introduced. `payments` retains its invoice FK,
amount, free-form method/external references, timestamps and notes; any linked payment
blocks this operation. Shipment and order status and stock state strings remain existing contracts outside this
Finance participant; shipment/package/stock/reservation/order/scan/audit/idempotency
writes retain their existing ownership and are not claimed converted here. Existing
invoice issuance, payment allocation, reporting and shipment issuance are separate callers
and policies; no production distinct-value census is claimed.

## Provenance and remaining gates

The preserved old PR and its historical evidence remain closed. This candidate is a fresh
continuation on the current base; old PR checks do not certify it. Source paths: Finance
service and guide, shipment reopen service, Finance schema persistence and guide, and the
two shipment reopen test files. The shared PostgreSQL manifest/runner/guard changes have a
separate single owner and must be additively integrated; no old QR-code dependency change
is included. The clean base shipment characterization passed 13 tests in the rootless network-isolated
container (`/tmp/invoice-reversal-base-20261104.log`). The candidate shipment/finance
focused set passed 49 tests with six PostgreSQL-dependent skips, which are not PostgreSQL
evidence (`/tmp/invoice-reversal-focused-20261104.log`). Full configured backend Ruff
passed (`/tmp/invoice-reversal-ruff-20261104.log`). Tests used dependency image
`df3cdf344d6973f2c4c57c985032546ac55f418467f0a0e0e5125ef14295a15b` with source
bind-mounted; lint used image `7c1142ee4f67`. Exact combined candidate and remaining
gates must be recorded by the integrator after completion.

Required before AI verification: meaningful old/new characterization and combined
shipment/finance checks, isolated real PostgreSQL four required cases and full required
gate with zero required skips, actual shipment history reopen on synthetic delivered
shipment, persisted invoice/order/stock/audit/idempotency readback, blocked paid/external
and permission paths, desktop/phone locale inspection, bounded concurrency and independent
review. A timeout after a mutation is HOLD, not permission to replay. Human QA before
deployment, production release and path retirement are distinct gates.
