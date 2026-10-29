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
in121 targeted cases; the final full suite/CI passed as recorded below. A fault
challenge disabling the per-size allocation guard produced the expected failing
200-versus-409 assertion, proving the overdraw regression can catch its removal.

Read-only live recheck on29 October at10:59UTC found SH-2026-000178/179 had been
cancelled/soft-deleted at10:40:40/10:40:35UTC, with no remaining package links.
PKG-2026-001240 still held60 available pieces,10 per size. These cancellations
were external to this task; no business data was changed by the agent. The
release check fingerprints these actual records instead of recreating shipments.

## Exact publication and production release

PR [346](https://github.com/Shmirzaev/Milana-ERP/pull/346) merged by the
owner-authorized fast-forward into `clone_main` at exact runtime
`1344b572f8bff6f458892d3c2c8022560f306dbb`. The final local full suite passed 4,857 cases with 542
opt-in skips. Release CI 40863423984 passed 4,874 backend cases with 544 opt-in skips
(different invocation inventory), Ruff/compileall, frontend lint/strict types,
contracts and immutable production build. Main P2 PostgreSQL passed 165/0 skips;
separate exact-source required PG CI 40863333910 passed 17+148=165/0 skips.
The earlier two failures remain above; only the final source is released.

Green `20261029_111113` is active on both VMs, manifest `93d632752aa355efad66fc67bf294fa6eb6321e90769106fc5de71c4cb6b7720`,
database `0149_besttex_cutting_access` unchanged after no-op schema verification.
Immutable images:

- Backend: `ghcr.io/shmirzaev/milana-erp-backend@sha256:8e34ba5727ac67e3730192b358f97615f52a175fb27c4679e1720df6f65e5566`.
- Frontend: `ghcr.io/shmirzaev/milana-erp-frontend@sha256:77c1d42f7fcfac22103c0bba36547914d10519fcd80a60e88fea6a23aee6a9c4`.

Verified pre-release backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20261029_111113.dump`,
97155265 bytes, SHA256 `eda4d90cbffcd3ca2e19e524060f4eec6f4f4b4c28bca7731d8be57f30b7e2dd`;
restore object/list size, mode and hash checks passed. No schema or business-data
migration was required. Root checkout and unrelated work remain untouched.

The GET-only candidate browser checked the existing SH-2026-000180 package 1240
editor, six size limits and immediate split instruction; no save was submitted,
and console errors/warnings were absent. Screenshot SHA256
`d447eeddc44bd1e6d866a2ed2f741de940c82660df2a1fcfde77fe05575c6be1`. A fresh repeatable-read snapshot
after HTTP GETs matched the pre-GET scoped fingerprint, including package items,
claims, shipment/deletion state, stock and reservations:
`477f4957c0d24ba31d41949a461b22e50d82e4947e482b03548c0c973c5b8186`. Candidate and public checks issued
zero HTTP write requests; no claim of zero global operator activity is made.
At those checks SH178/179 remained cancelled/deleted; independently created
SH180 held the full 60-piece claim, stock 60 available/sold 0, free claim 0. These
external changes were preserved. Operators must save a partial selection in SH180
before its remainder can be scanned elsewhere.

The signed-in public Chrome page was also checked after activation in Uzbek:
the same package editor, six limits and immediate split instruction were visible;
no values were changed or saved and console errors/warnings were absent.
The screenshot and its SHA256 are recorded in `evidence.json` under `browser_public`.

All five preserved endpoints passed paired and single public closing gates:
120 samples per endpoint, identical result counts/payloads, median <=+10% and
p95 <=+15%. No old latency exception was reused and no failed gate was resampled.
Raw preserved evidence: `outputs/deployment/performance-paired.json`,
`performance-closing.json`, `readonly-v2-{baseline,candidate,public}.json`,
`evidence.json`. Comparison percentages:

| Endpoint | Paired median | Paired p95 | Public median | Public p95 |
| --- | ---: | ---: | ---: | ---: |
| global_search | -2.63% | -15.28% | +1.09% | +0.76% |
| inventory_batches | -1.22% | -2.09% | -0.72% | -63.14% |
| inventory_stock | -3.72% | -2.51% | -0.64% | -7.23% |
| model_groups | +0.19% | -3.16% | +1.64% | +0.62% |
| model_options | +1.13% | +7.21% | +0.86% | +2.00% |

Both original blue containers/images/start times stayed unchanged. The live
isolated HAProxy recovery-guard test passed 11 probes, forwarding health only;
seven local recovery/readiness tests passed. Existing incompatible blue was
activated only with the backend application-maintenance guard while green was
replaced. Compatible green then became public. Four internal/public health
checks, source/image identities, two Uvicorn workers, database pool headroom,
router configuration, disk limits and runtime error checks passed. Exact temporary
candidate IDs were removed before closing public performance to match baseline
resource topology. No 30-minute monitoring was performed, per the owner's waiver.

Operation remains AI_VERIFIED_AWAITING_HUMAN for the named operator checklist.
Owner merge/deployment authorization is recorded separately from human business
acceptance. No real shipment was created, revised, dispatched or delivered for QA.
