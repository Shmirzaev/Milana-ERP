# One package allocated to multiple open shipments

User request, 29 October 2026: choosing a partial quantity must immediately make
the unallocated remainder scannable into another shipment, before either ships.
Example: package PKG-2026-001240 has 60 pieces (10 in each of six sizes);
SH-2026-000178 selects 24 (4 per size), then SH-2026-000179 must claim 36 (6 per
size). Either may dispatch first. No actual production shipments are changed by
implementation or verification.

## Base, ownership and operation

- Clean worktree: C:\ERP\.codex-work\split-open-shipments-20261029;
  branch codex/split-open-shipments-20261029, clone_main base 4bdddf4f.
- Both live VM manifests verified before edits: green 20261029_083228, runtime
  24f4f231, manifest 95d3be61132307dc41ec13fff4e51965ad460ab7faa4e5725448db488a13cd59.
  Baseline JSON and Git agree; root checkout and prior task are preserved.
- Fulfillment engineer: Mirshoir; reviewer: Ismail; business acceptance: Shavkat
  and operators. Implementation: root Codex, independent AI verifier: separate
  independent_review agent. Named humans have not been impersonated or messaged.
- One operation: allocate/revise/release a shipment's per-size claim on existing
  physical package contents. Existing ShipmentPackage.quantity and
  Shipment.dispatch_snapshot.package_quantities store it. No new tables,
  business data, package identity, QR, schema migration or background backfill.

## Study and boundaries

Trace covers shipment create/auto-add/direct-add/add-ready/scan/replacement,
warehouse reservation preparation, partial selection, receipt correction,
dispatch, frozen invoice, detach/delete/cancel, delivery and reopen. Existing
sales/customer reservations and conservative returns remain enforced. Services
read other open claims without locking other shipments; each writer locks its
own shipment then sorted Package rows. New mapped claim mutations belong in
schemas/fulfillment; business calculations in models/fulfillment. No helper commits.

Per item: dispatched quantity plus all undeleted draft/created claims cannot
exceed original receipt quantity. Edits exclude their own previous claim. Every
new attachment freezes its exact per-size claim, so detach/cancel cannot expand
another shipment silently. Legacy whole-package claims remain supported;
ambiguous legacy partial claims fail closed. New allocation checks use canonical
shipment status vocabulary; existing unrelated status/discriminator strings,
audit/idempotency writers and mixed route mechanics are explicitly retained
legacy debt, not a system-wide type/persistence migration claim.

## Evidence and operation status

Application slice: **AI_VERIFIED_AWAITING_HUMAN**, subject to publication/build
checks below. No operator acceptance is invented. Changes apply to existing
package QR codes and existing valid frozen partial selections; no reprinting or
backfill is required. An ambiguous legacy partial link without size evidence
requires review. Customer holds and stock reserved for another Sales order still
refuse attachment. Cross-order reservation reassignment is outside this operation.

- Red regression on the baseline: second open scan refused as already attached,
  and returned physical quantity60 instead of its available36. Same assertion
  passes with the candidate. Both dispatch orders preserve frozen invoices.
- Targeted combined backend suite:170 passed,0 skipped. New tests cover duplicate
  scans, stale edits, per-size overdraw despite fitting total, third exhaustion
  without an empty link, reduce/detach/manual deletion releasing only own claim,
  permission refusal, malformed legacy partial evidence, direct attachment and
  standalone-dispatch bypass refusal. Full-selection receipt corrections remain
  supported; partial selections cannot change physical receipt evidence.
- Isolated real PostgreSQL:23 passed,0 skipped, including competing claims for
  last36, edit-versus-claim, dispatch-versus-claim, stale damaged/shipped refusal,
  and existing shipment-document planner checks. CI includes the new PG tests.
- New normal full-claim dispatch query checks at1/50/401 packages: item/other
  allocation/reservation reads are batched. PostgreSQL audits retain their
  existing transaction-finalized chain; SQLite audit emulation is unchanged.
- Actual connected Chrome: local candidate API18273/frontend18274 and owned
  ephemeral PG18272. Six-size package60: chose4each, saved24; second client scanned
  same QR and received6each/36 while first stayed created. Reload preserved both;
  independent PG readback proved each size totals10 and dispatched0. Shipped36
  first, rescanned first with24 unchanged, shipped24; invoices360.00/240.00 stayed
  distinct, original QR unchanged. Both then delivered; independent database
  readback verified posted invoices240.00/360.00, sold60 and available0. A third allocation was refused without a link.
  Screenshots inspected with vision; zero browser console errors/warnings.
- Bounded isolated API stress:80 duplicate scans,8 workers,10 third-claim refusals;
  median83.77ms,p95 107.08ms,max140.45ms (limits p95<2s, request timeout10s).
  Exactly two links24+36, each size conserved, reverse dispatch sold60/available0.
- Independent agent reviewed the application changes, identified3 issues, then
  confirmed all resolved and ran128 tests/0 skips; reviewed23 PG cases/0 skips.
  After full-suite compatibility fixes, its expanded independent run passed132
  cases/0 skips. Refreshed PG23/0 skips, browser and stress gates passed again.
  Findings: standalone dispatch bypass, stale readiness and unbatched reads.
- Ruff over backend/app and compileall passed; frontend typecheck and shipment
  contracts passed. Full backend/frontend production checks and publication are
  recorded separately when complete, not inferred from these targeted results.

Ignored local evidence: `outputs/qa/backend-results.xml`, `postgres-results.xml`,
`browser-readback-final.json`, `browser-final-delivery-readback.json`, `stress.json`,
`both-created-after-reload-final.png`, `second-shipped-first-open-final.png`,
`both-dispatched-final.png`. QA business fixtures existed
only in owned loopback PostgreSQL; its server and frontend were stopped afterward.

Human checklist: choose a partial per-size quantity on an open manual shipment;
scan that existing QR in another open shipment and verify only unallocated sizes;
reload, dispatch either shipment first and check separate invoice quantities;
confirm a third scan cannot overdraw. Never dispatch real stock merely for testing.

Recovery: code rollback does not undo existing multi-shipment claims. Blue's old
code already cannot write the live mixed Nastil scopes, and now also lacks open
allocation enforcement. Preserve blue containers/images, use health-only backend
maintenance for recovery, then restore compatible green before business writes.
No schema migration, production backfill or real-shipment edit is part of this fix.

Full-suite compatibility findings (preserved, not relabeled passes): the first
full run on the initial candidate reported4855passed,542opt-in skips,2failures.
The old full-package dispatch retained consumed StockReservation history; the
new full claim now does too, while partial claims still release the remainder.
Sales-order readiness now includes its own sole open shipment's frozen claim,
while excluding other claims. The existing failing tests pass with these fixes
in121 targeted cases; full suite/CI are rerun on the updated candidate. A fault
challenge disabling the per-size allocation guard produced the expected failing
200-versus-409 assertion, proving the overdraw regression can catch its removal.

Read-only live recheck on29 October at10:59UTC found SH-2026-000178/179 had been
cancelled/soft-deleted at10:40:40/10:40:35UTC, with no remaining package links.
PKG-2026-001240 still held60 available pieces,10 per size. These cancellations
were external to this task; no business data was changed by the agent. The
release check fingerprints these actual records instead of recreating shipments.
