# Invoice reversal in shipment reopen — continuation, 4 November 2026

**AI_VERIFIED_AWAITING_HUMAN for the Finance participant only.** Current source base `af6dafad60b0765368ddbeefabcdf6aa53daa039`;
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
bind-mounted; lint used image `7c1142ee4f67`. The combined source and completed gates are recorded below. The six focused
skips subsequently passed on real PostgreSQL.

Verification checklist: meaningful old/new characterization and combined
shipment/finance checks, isolated real PostgreSQL four required cases and full required
gate with zero required skips, actual shipment history reopen on synthetic delivered
shipment, persisted invoice/order/stock/audit/idempotency readback, blocked paid/external
and permission paths, desktop/phone locale inspection, bounded concurrency and independent
review. A timeout after a mutation is HOLD, not permission to replay. Human QA before
deployment, production release and path retirement are distinct gates.

## Exact candidate and verification

Frozen application/gate candidate 60bcf909ee59488bfdf716f6a610a45d5e75a2af,
tree d9c98f124d63b43f2351259f2e797708c9c08d88, combines application commit
c8a66eb5 and the additive gate change; later publication edits are documentation
only. Codex terra_edit_backend implemented the Finance participant;
terra_edit_details_study owned the additive PostgreSQL gate;
terra_edit_independent_review independently reviewed source and evidence.
These are low-reasoning Terra workers. The root integrator owns final QA drivers,
screenshot inspection, shared documentation and publication. AI roles do not
replace the named human owners/reviewers.

- PASS: 13 clean-base characterization tests, 49 candidate focused tests, full
  configured backend Ruff and 24 PostgreSQL runner guard tests.
- PASS: 204 distinct real PostgreSQL cases, zero failures/errors/required skips:
  181 primary, 17 supplemental and six Finance persistence cases. The four new
  source-pinned cases cover same-Session/no-early-commit behavior, complete invoice
  preflight, injected audit rollback/recovery, and competing workers observed
  behind a held invoice lock, with conservation and audit-chain checks.
- PASS: strict Finance participant persistence audit, two paths/zero errors.
  **Full shipment coordinator audit remains FAIL** on the unchanged baseline
  PackageScanLog insertion in shipment_reopen_service.py. No checker bypass or
  exemption was introduced. Stock, scan, order, idempotency and shared audit
  extraction remain pending. This does not certify full Shipment conversion.
- PASS: actual website issued five one-shot synthetic requests: positive 200;
  paid/external/stale 409; restricted role 403. Every request has a durable receipt.
  Four refusals preserved tracked business data. Success persisted invoice
  VOID/Decimal zero, restored stock/reservation/package/order/shipment state,
  exactly one return scan and reopen audit, and only the matching idempotency
  invalidation. Full-row/per-column comparisons cover 20 tables, allowing only
  specifically witnessed actor login/seen timestamps. Audit chain passed.
- PASS: integrator visually inspected native desktop confirmation/saved views,
  refusals/access denied, refresh and EN/RU/UZ 390px dialogs and saved views.
  Phone scrolling reached status, scan/action controls and package checklist;
  document width stayed 390. Empty/short reason and return-confirmation validation
  were checked. This is bounded synthetic evidence, not a production census.
- PASS: final GET-only saved continuation had preparation 200, no blocked requests,
  page errors or HTTP errors and unchanged tracked business data. The separate
  phone-scroll continuation also passed integrity checks. No business replay.
- Frontend tree equals base af6dafad byte-for-byte. Its backend/frontend/required
  PostgreSQL hosted checks succeeded (release skipped); prior full frontend build
  covered 98 pages. No frontend/dependency change is included. Publication CI is
  a separate exact-commit check, not inferred from that base.

PostgreSQL evidence:
 /home/ismoil/workspaces/invoice-pg-runtime-20261104/evidence-60bc/
(primary.xml, supplemental.xml, finance-six.xml and controller/identity/results).
PG17.11 system identifier 7704136597392863274, no host DB port; all helper-owned
targets drained. The first startup qualification stopped before tests because
initdb's temporary server restarted; stable TCP identity was separately witnessed
before the known-safe controller resume. That failed qualification is retained.

Actual app QA: rootless project milana-invoice-reversal107, VM107 UI13279/API18279,
database invoice_reversal_qa, PG16.15 system identifier 7704138845675913250.
Backend dependency image df3cdf344d6973f2c4c57c985032546ac55f418467f0a0e0e5125ef14295a15b
binds exact candidate source read-only; startup seed/schema sync are disabled.
One synthetic database dump was restored once; six scenarios committed once.
Private credentials, journals and full row snapshots stay outside Git.

App evidence root:
 /home/ismoil/workspaces/invoice-reversal-runtime-20261104/evidence/
Original ui/, ui-counter-ready/ and ui-modal-ready/ failure/HOLD records remain.
First, a fresh counter volume UID mismatch stopped login before any financial
request; only its empty directory ownership was corrected. Second, a selector
assumed the actual Modal had a dialog role; it failed before financial requests.
Third, all five requests completed and passed DB checks, then an existing
preparation read failed because the copied synthetic schema lacked migration
0084's two generated Model columns despite recorded revision0153. The migration
and read path are unchanged by this candidate. A separately reviewed, witnessed
synthetic-only repair applied exact existing 0084 statements in one transaction.
Canonical row hashes normalized ONLY those two generated keys proved all 20 tables
unchanged and audit valid. Committed receipt and fresh readback are retained as
schema-parity-*.json. No Alembic history rewrite, fixture reset or production DDL.

ui-saved-readback/report.json and ui-phone-scroll/report.json record successful
read-only continuations after that known commit, with screenshots alongside.
Both known-drained owned browser lanes were closed with exact cleanup evidence;
other sessions/runtimes and formal HOLD lanes were preserved. The original failed
run stays HOLD; later records resolve its separate saved-view gate.

## Human checklist and remaining work

QA master records pre-deployment technical/visual review; Shavkat confirms business
outcomes. Use dedicated operator/restricted actors from the runtime's private
fixture file, never committed credentials. In Shipment history locate
INVREV-QA-20261104-positive and open its saved preparation: created, four pieces,
one package, prior scan retained and shipment timestamps cleared. Refresh and
inspect desktop/EN/RU/UZ phone views, including horizontal scrolling and package
checklist. The page's calculated order/invoice-entry amount remains 40.00 by
existing behavior; the voided historical invoice itself is zero. Inspect paid/
external refusals, denied-role evidence, return audit, stock and invoice readback.
Do not resubmit the already returned positive fixture; any new mutation rehearsal
needs its own fresh synthetic fixture.

Human production acceptance remains unrecorded. No deployment or path retirement
is authorized. Finance issuance/payment/ledger operations and Fulfillment's other
writers need separate operation/type/caller/verification ledgers. Invoice.amount's
retained float ORM annotation remains debt. Closed PR350 stays closed; no old PR
or QR dependency was reopened.
