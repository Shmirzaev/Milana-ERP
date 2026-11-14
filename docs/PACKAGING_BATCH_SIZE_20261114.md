# Exact mixed-package attribution and Packaging wording — 14 November 2026

## Request, baseline and ownership

Owner request: “Fix Mixed packages lack exact size-by-batch traceability. Find why
Some Received and Packed wording is still confusing.” Implement and verify locally;
no deployment, merge or publication is requested.

Worktree `C:/ERP/.codex-work/factory-workflows-20261113`; branch
`codex/factory-workflows-20261113`; task base
`76820b9a26a28d54efd6c703e6f6fb376e8f39ef`. This branch contains the withdrawn
seven-fix ancestry and the subsequent local direct-Packaging correction. It is
not a packaging-only release candidate from live source. Legacy C:/ERP is untouched.
Fresh fetch still identifies clone_main as `3053788f2e17bd5585bccf8cd4547a62cc297516`.

Public health on 14 November returns ok/release `20261111_115200`; recorded active
blue source is `46ddd5c7864f0a68bd9a3c884d835a2a5dbf9bfb`, manifest
`db9df64cbcf57e4ab93ac83ef677d7d394b07652a1a4cf3fe1815abc92adac28`, schema0156.
Both-host/source identity remains the prior rollback evidence: no fresh SSH check
is claimed. Withdrawn green094409/e538 remains off traffic, not a known-good fallback.
No production business writes, migrations, merge, push or deployment occurred.

Engineering owner Mirshoir; human reviewer Ismail; business acceptance Shavkat.
Codex backend writer /root/packaging; root owns mixed create/edit/detail UI and
integration; /root/cutting_reports owns wording; /root/eco_fabric independently
reviews exact source and QA readbacks. No human signature is presumed.

## Implemented contract and causes

Old mixed allocations stored only source totals, so a 60-piece M30/L30 package
could say A35/B25 without saying which sizes came from either source. New nullable
`PackageBatchAllocation.item_breakdown` JSON stores typed
`{model_id,color,size,quantity}` rows per source. Historical NULL stays explicitly
unknown; no backfill, planned ratios or automatic guesses are presented as evidence.

All new mixed generic/direct/bulk/no-anchor writes must conserve each source total
and every package model/color/size. Single-source contents are uniquely inferred
from actual package items. Ambiguous mixes require operator entry. The UI shows
all selected sources and derives scalar allocations from cells, rather than forcing
the old FIFO proposal. Combined requests enforce total and known actual-size budgets
across all packs/colors. Stale plans clear/refuse stale matrices, never rescale them.
The server rechecks authoritative balances inside the existing locked transaction.

Metadata-only edits preserve stored exact matrices or legacy NULL. Physical-content
changes require valid replacement attribution, including delayed approvals and
returns/corrections. Audit and immutable print-run snapshots carry the matrix;
label HTML, traceability and package detail read it. Detail calls it “Originally
packed contents by Nastil and size”: current warehouse quantities can differ after
dispatch. New exact mixed quantity-changing shipment reviews refuse with
`MIXED_PACKAGE_QUANTITY_REQUIRES_PACKAGING_CORRECTION`, directing an attribution-aware
Packaging correction. No-op/metadata and historical controls remain supported.
Mixed First/Second Grade creation stays disabled by existing policy; exact ordinary
mixed consumption is included in grade balances.

Wording causes were separate: the shared header used bundle receipt or actual
input as “Received”, and queue “Packed” meant saved good Packaging output, not
necessarily labelled packages. Packaging now says “Packaging input recorded” in
pieces (including damage and zero), while genuine Sewing/warehouse receipt labels
remain. Queue columns say “Passed Sewing output”, “Packaging output recorded”,
“Available for Packaging”. The hint explains that availability includes unprocessed
Sewing and recorded good output awaiting labels. EN/RU/UZ supported; no quantity
formula changed and no labelled total was invented.

## Storage, transaction and type ledger

- Migration0157 follows0156 and adds nullable JSON on the existing allocation only:
  no default, backfill, new table or index. NULL-only down/up is safe. Downgrade
  refuses once exact evidence exists; a code rollback cannot erase that evidence.
- New DTO rows enforce positive integer quantities, bounded IDs/text and forbidden
  extra fields. Absent/None matrix keys are omitted to preserve old nested request
  fingerprints and legacy snapshot replay. Existing configurable identities stay data.
- Allocation insert/replacement mechanics are schema-owned; services validate using
  the supplied Session and existing outer operation, locks, audit and idempotency.
  No new route business logic, permission or stock-minting path was added.
- This narrow data matrix introduces no fixed enum vocabulary. Existing stock-kind
  Literal/wrapper strings and broader fixed-vocabulary adoption remain migration debt.
  Existing package/BOM/waste/audit/notification writers are not claimed schema-owned.

## Evidence on the frozen candidate

Paths below are worktree-relative ignored QA evidence; no private account file or
credential is staged. Source manifests identify exact bytes, independent of the
later documentation/checkpoint commit:

| Evidence | Result |
| --- | --- |
| Backend25-path manifest `outputs/mixed-packaging-backend-20261114/backend-source-sha256.txt` | SHA256 a0775de14062c13f0418eda22e9f6fe299f7ec29e7edac603e151069d4ec7da8 |
| Frontend551-file snapshot `outputs/batch-size-qa-20261114/frontend-source-manifest.json` | SHA256 f9e72ecbfcb782b39c4ba0d1e86043c8ba0e41111c05d7238b917d4fbc703cf8 |
| Backend focused final regression/query suite | 213 PASS, 0 failures/skips,82.75s; includes21 matrix cases and seven bounded query files |
| Independent current API/real PostgreSQL rerun | 21 API +3 PG PASS,13.71s; eight-worker distinct-key size race, same-key retry and migration guard |
| Earlier direct-lock/recovery PG selection | 7 PASS before last read-reuse refinements; not reported as seven rerun on frozen source |
| Backend red challenge | Exact76820 create callable only in isolated pytest process gives old201/200/201 with no matrix;3 expected regressions fail; current409 |
| Frontend checks | Warehouse-workflow chain,440 varied conservation cases,2500 existing lookup +2500 mixed cases, actual create/edit submit/detail/wording, EN/RU/UZ, recovery/idempotency PASS |
| Frontend red challenge | Exact76820 main submit omits item_breakdown; meaningful assertion fails; current passes |
| Static checks | Nonincremental TypeScript, changed-path ESLint, Ruff backend/app +migration, AST/nonzero, diff checks PASS |
| Full frontend production build | `outputs/batch-size-qa-20261114/frontend-production-build-with-backend.log`, npm run build exit0, Next16.4.3/Turbopack,2 workers, full routes emitted |
| Independent source review | No actionable findings;25 backend/551 frontend hashes match. `independent-review.json` SHA256 d424cf8b30265c57876624284f9a045a34014d83f0c95fb8587ec1754e7a1e3c |

Migration used real Alembic on an isolated unique PG schema: old NULL survived
0156→0157→0156→0157; exact evidence blocked downgrade without losing rows/version.
`guarded-migration-roundtrip.json` SHA256
12399adb42c4fb592ca02a842100e69b1648343123b67da13321b280590ba174.
The public disposable QA fixture was backed up before additive upgrade:614,932bytes,
1,401 restore objects, SHA2569eba61ef6ed79e5403c07728142f5ca3c5dc138899b8732042ef963cd37a8d0a.
All111 protected business tables/231 original rows remained identical (new NULL
column excluded from comparison). No public QA downgrade or backfill.

Preserved failures: initial broader backend selection135pass/5guard-order failures
was fixed and followed by50 then213passing cases. Initial full frontend snapshot
build failed because an existing test reads sibling backend source; exact backend
context was added to the isolated snapshot and the entire build rerun passed.
Initial read-only JSON DISTINCT query and migration-helper URL interpolation failed;
helpers were corrected, not application source. Original logs remain. No replacement
production benchmark, full backend-suite or physical hardware claim is made.

## Actual connected-browser and persisted evidence

Owned localhost UI18943/API18942/PG55441, task-labelled disposable containers and
synthetic accounts only. Six existing fixture cases were preserved. Added order7
QA-BATCH-SIZE-EXACT-20261114/PackagingWO14 with Nastil12 M35 and Nastil13 L40.
Actual Packaging-role UI showed no Save Packaging Record/accept step. Wrong-source
size cells first failed backend409 without writes; after final UI size-cap change
they disable submission. Correct entry produced package7/PRN7 with exactly A-M30,
B-L30, not the old FIFO35/25. Remaining M5/L10, output60, partial workflow started.
Independent SQL and role-scoped GETs verified two30-piece records, one package/run,
exact allocations/snapshot/audits and provisional stock60, with old six cases unchanged.

Browser inspected main creation, saved detail/QR, old mixed NULL detail, queue
wording and correction editor. Changing recipe30/30→29/31 cleared stale cells and
disabled Save; cancelled without a persisted correction. Warehouse role then scanned
barcode316015169194: exactly runPRN7 received once; package placed at A-02/S1. Saved
screenshots were visually inspected, including `exact-mixed-saved-detail.png`,
`legacy-mixed-unknown-detail.png`, `queue-quantity-wording.png`,
`correction-stale-attribution-blocked.png`, `exact-mixed-warehouse-received.png`.
Independent post-receipt SQL/HTTP confirmed the same allocation/items/output/run
snapshot, M5/L10 remaining, the same two stock IDs/quantities and no duplicate stock.
Exactly one received_storage and one placed_storage event joined the original packed
scan; only receive_print_run/place_storage_map audits were added. Initial run receipt
had no location; the later map placement correctly set package A-02/S1. All six prior
cases remained unchanged. Evidence under `outputs/batch-size-qa-20261114/`:
`after-warehouse-browser-receipt.json` SHA256
37170b9a8bee53d55acda8fe712d7eb2a7e5c9f742b5dd3b01d69f5d71c491ce;
`received-browser-http-and-oracle.json` SHA256
61e0da9eaa0e4ac29d0251feed79d39f68d76b2c42c551e871b34ec555252412.
Independent receipt review `independent-receipt-review.json` SHA256
2c031ea14c8a4ee8e04860979e5eedbdbcf2b9177c4d5cd8d886157a297433f1
found no actionable issues and rechecked all source hashes after shutdown. Owned
Next/API/PG are stopped; task data, logs, backup and builds remain intact. Generated
Next AGENTS/next-env/tsconfig changes are absent. Browser extension attribute hydration
warnings are preserved; no application source compile error was observed.

## Limits, acceptance and closing status

Operator entry proves declared physical batch/color/size attribution; Sewing only
proves size totals, not color×size distribution. Missing actual Sewing size evidence
stays manual with actual_size_verified=false. Damage has no size split, so per-size
remaining is a maximum additionally capped by scalar available quantity, not an
additive stock figure. Ambiguous historical mixed consumption reserves worst-case
known-size capacity and may require reconciliation. Existing BOM shortage, legacy
unclassified WIP and material-linked cancellation/reversal gaps remain out of scope.

Required print-popup visual gate remains BLOCKED: browser policy rejects blob URLs.
No workaround was attempted. Normal HTTP package QR/detail and label HTML/snapshot
tests passed; popup layout, physical printing/scanner hardware, tablet visual checks
and human/operator acceptance are unverified. The applicable
[feature skill](../.agents/skills/milana-feature/SKILL.md) explicitly says “Missing
browser access or a required test environment is BLOCKED, never PASS.” Therefore
this is a locally tested checkpoint, not whole-task AI_VERIFIED or release-ready.
Ismail/QA master must review this exact build, actual labels, correction/returns and
warehouse workflow; Shavkat must accept operator wording and declared attribution.
Future deployment requires live-source reconciliation,0157backup/recovery planning,
remaining gates and fresh authorization. No push, merge or deployment here.

At the owner's disk-cleanup request, reviewed eight inactive October `.next/cache`
folders. Automatic approval review rejected recursive deletion; no files deleted.
NTFS compression instead preserved every file and recovered2,369,536,000bytes
(~2.37GB). The full build then passed; C: remained about2.45GB free. No production,
source, database, personal files, dependencies or retained evidence was deleted.
