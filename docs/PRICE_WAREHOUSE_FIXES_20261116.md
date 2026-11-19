# Printing cost ownership and warehouse model navigation

Owner request: remove print price from Purchasing price requests because Finance
will enter it; make the highlighted Warehouse Stock model card open its details;
deploy `codex/factory-workflows-20261113` without 30-minute monitoring.

## Current production outcome — 16 November

Backend/frontend now serve `20261116_061924`, blue, exact reviewed runtime commit
`8fb52df54a34ce94127ead2460e94d81a90721b2`, manifest
`cd22477f24b62858d893ed4990d872ca8ca25dbed838b37314f06f0fbff3270b`.
Backend activated08:35:47UTC, frontend08:36:07UTC; both source links match.
Rollback is the running compatible `20261116_053002`, green, commit1ab6ff577,
manifest304f2d4fea15243fe212b32135cc804c33eb55612e20b36d623ee436d096e2c4.
DB remains `0157_package_allocation_items`: nullable JSON, no backfill/downgrade.
The complete owner-selected branch is live: Purchasing no longer enters printing
cost; Finance owns it. Whole Warehouse model cards open details, including missing
pictures and Enter navigation. Direct/mixed Packaging and all factory changes are
included. Source is pushed on codex/factory-workflows-20261113; no main/clone_main merge.

Owner QA approved6c including physical labels/scans and its narrow8fb Printing
follow-up. Exact CI43815960892 passed all five jobs: backend6862 passed/1628 skipped,
required real-PG238 passed/zero skipped, related Linux127 passed/zero skipped.
Recovery CI43810018892 and strict published0157 cold start/restart/worker/evidence
compatibility passed. Immutable backend digestd9c0ef0ea998554780779876b1aa14230066269d9528ef9a820281935f097732;
frontendff7beffb118fd7613de034bbec314cda8169301d8d8a82783b4fd1b94812ad59.

Fresh staged43-response/26-table integrity checks and44 semantic checks passed.
810 paired timing samples passed unchanged10% median/15% p95/15% bytes budgets
(worst+3.64%,+7.91%,+1.48%). Public270 samples preserved all complete ordered bodies
but FAILED two p95 limits: model groups334.919→1021.852ms; Cutting passports
145.081→365.211ms. Owner explicitly chose “Keep the full release with these
additional public-latency exceptions.” Earlier owner “deploy with an exception”
covers the separate recovery PO762 median154.047→169.777ms (+10.21%). All original
FAILED reports remain unchanged; neither timing reruns nor broader gate waivers
were substituted. The public path latency cause remains unresolved.

Actual staged/public signed read-only UI verified Purchasing/Finance, missing-image
Warehouse model8836 (216 pieces, six sizes×36), direct Packaging PO0551/Nastil2
(162 sewn/120 recorded/42 available) and Cutting. Zero ERP application console
errors;51 staged/62 public M_ID errors originate solely in a browser extension.
Public transport preserved one QR TLS interruption and four aborted unrelated
prefetch requests; the latter causes are unproven. Two bounded TLS-verified public
QR controls matched exact backend PNG732bytes/SHAfab1e4b26cf6b77e61fbf76edec43d7c7e8ccee60e495e26667c921c9dfdd013.

Operator entries invalidated several captures despite pause confirmations. Exact
pre-cutover ECT/Oyatullo additions (2batches/3Cutting records/24bundles/24creation
logs) caused the original public global-fact-equality failure, preserved as FAILED.
Separate independently reviewed transition verification proved all26 existing
ordered fact tables unchanged/no deletions, exactly53 traced pre-cutover additions,
all10 timing bodies unchanged, and all44 semantic/SQL checks using an explicit
in-memory expected projection. No captured file or production fact was rewritten.
A separate verifier omission of batch_no/name was corrected from authoritative
SQL batch facts, retaining original failures and exact capture hashes.

Fresh closing all four health checks passed at08:44:42UTC: both manifests/slots,
strict defaultCMD/seeds, two workers, zero restarts/OOM/app errors, healthy routers,
DB headroom/no invalid indexes, disk below80%. Compatible green remains running;
original115200/052632/135430 sources/images retained. Fresh0600 PostgreSQL backup
pre_final_20261116_061924_20261116_083243.dump:126631173bytes/1400restore objects,
SHAcebdb35706458d2e95363e78637376e9a795cc3763549d87bfdd76092b7468e2.
Both owned leases released; operators told to resume. No release business-data
writes. Owner waived timed observation; no observer or substitute monitor ran.
Detailed hashes and preserved failures are listed below.

Evidence under outputs/price-warehouse-20261116:

- feature-closing-state-journal.json binds final runtime, released leases, checks and exceptions.
- resume-plan-v3-frozen.json SHA668790b0995db0d662b3c833d2012b8b42c52896347bee36bbb27c699c985d05.
- resume-qa-batch-labels/final-promotion-gate.json SHAc0f7554eb4bf2914e06b260353fa46362c077b20e381cd229f0f014bf3f424b8.
- resume-qa-batch-labels/postflight-transition-proof.json SHA1c716457da04cf7365d728025917e5a1f546b3bc2bd2e312b6268e05650ac103.
- resume-qa-batch-labels/final-paired-benchmark.json SHAbbbaa45cb685d0b3c210cdf65b5fb419bde56127f906d6a3831182ae80b1dff8 is PASS.
- resume-qa-batch-labels/final-public-benchmark.json SHA84bb62c2a08f0f6216817c5ccca844a636e56767869c824fa5b788336497f49c stays FAILED; explicit owner waiver is separate.
- Historical recovery public report39c4e2c1b6a0cd79ccd2a70776769b86ef009df6ce6f4f7715f3902ca9901763 stays FAILED.
- Both stage/activation/link/backup attempts and earlier released ownership records are immutable and were never replayed.

Earlier two0600 backups remain retained (070058 recovery and071357 pre-final),
plus082213/083243 fresh pre-final dumps. No generic prune, source/backup removal,
credential/permission change, business fixture or stock cleanup occurred.
Legacy ECT bundle creation still records current CUT department; ECT origin is
traced through the actual Cutting record/work order. This pre-existing behavior
was explicitly checked by the transition oracle and was not changed by release.

The following sections preserve the earlier implementation and pre-release
verification history; their historical pending/no-production-change statements
are superseded by the actual outcome above.

Starting candidate: 7c9729b63607e698659ac4a216f7865a8d9eb159, clean dedicated
worktree C:/ERP/.codex-work/factory-workflows-20261113. Both live hosts verified
20261111_115200, manifest db9df64cbcf57e4ab93ac83ef677d7d394b07652a1a4cf3fe1815abc92adac28,
matching this branch's production-base.json. origin/main is historical; the
owner-selected branch includes withdrawn factory changes and local Packaging fixes.
These require full candidate reconciliation before release, including migration0157
and strict-schema recovery compatibility. No automatic reactivation of094409.

Implementation: Codex root, independent AI reviewer: release_review. Human domain
ownership remains Ismail/Mirshoir for Planning/Finance and Mirshoir/Ismail for
Fulfillment; no human acceptance is invented.

Pricing operation trace: price_calculation route -> costing_service / variant
pricing service -> existing schema-owned persistence, audit and notification.
Existing numeric printing_cost storage is retained; no new vocabulary/schema.
Purchasing cannot write printing_cost, and its submission no longer waits for it.
Finance can save a finite nonnegative printing price. Printed variants cannot be
approved or display a complete cost until that price is supplied; explicit zero
is valid. Existing print values and exact model/factory/revision checks survive.
Warehouse navigation uses the existing model-details route and current stock kind;
picture-less cards and keyboard activation must work. Model-less legacy cards
must retain an honest fallback without linking to an undefined model.

## Current verification

- 40 focused SQLite/API cases passed on Windows. Seven focused Linux cases passed
  with zero skips, including the new actual PostgreSQL print handoff and existing
  creation/submission/approval races and atomic rollback. Clearing/reapplying print
  cost, explicit zero, nonfinite/negative values, unauthorized Purchasing writes,
  stale revisions, partial saves and protected manufacturing facts are covered.
- Frontend rendered regressions pass for Finance/Purchasing and missing-photo,
  stock-kind and model-less legacy cards. The original Purchasing, Finance and
  Warehouse implementations each fail the corresponding assertions when separately
  injected into that test (three preserved red challenges). Disabling only the
  server print approval guard made the missing-print API test fail as intended
  (moneyguard-red.xml); the fault is not present in tracked source. Twenty bounded
  local GETs at concurrency4 preserved both complete pricing/package projections.
- Full frontend lint has zero errors and 14 existing warnings; strict TypeScript,
  scoped ESLint, repository Ruff/compilation, existing production build contracts
  and an optimized Next build passed. The final configured build including the new
  rendered regression passed; the small required-error translation addition also
  passed its EN/RU/UZ regression and a fresh optimized build. The strict-index errors inherited from the local
  Packaging checkpoint were corrected without changing valid budget semantics.
- Actual connected Edge UI: Purchasing saved fabric2/sewing0.5 and submitted with
  no print field; Accessories saved its no-accessories reason and submitted; Finance
  received the request with missing print/disabled confirmation, saved explicit0,
  selling5/exchange12500, reloaded it and approved. Independent read-only local SQL
  confirmed print0, model price5 and the approval snapshot. Pointer and Enter on
  the picture-less model card opened the correct model2 stock page with the saved
  30M/30L package. The inset focus outline is visibly intact.
- Browser screenshots are in ignored outputs/price-warehouse-20261116. Edge's
  installed extension injected bis_skin_checked/bis_register attributes and caused
  hydration warnings; this is preserved, not a zero-console-errors claim. The first
  QA actor fixture used example.invalid emails rejected by EmailStr; only those
  three owned local actors were corrected to example.com before successful QA.
- Independent agent /root/release_review found no remaining actionable scoped
  correctness/security issue and inspected the screenshots and 7-pass PG report.
  Reviewer fingerprint:3b5dc5c6b52ae405403960f00783e67929d1008172789ea64467f4706670da6d.
- The original full combined branch backend/PostgreSQL failure report is preserved
  below; it is not a clean full-suite pass.

The full local run completed:8362 passed,12 failed,17 errors,84 skipped. All failed
and error cases plus adjacent operations subsequently passed a71-case Linux run,
zero skips and clean exit. The substantive defect was catalogue import rejecting
schema0157; both applications now allow exactly0156/0157 and keep unknown heads
refused. PG proves unknown-head no-writes, deferred-commit rollback, Finance/import
race and retirement/import serialization. Existing mixed-package fixtures now
supply explicit matrices; label mocks carry honest NULL evidence. First-grade
creation retains two distinct bounded Sewing reads; source projection performs16
reads for both three and200 Nastils. The gateway fixture writes the actual API503
document to an owned temporary path. ECO fixtures reran against an owned *_qa DB.

The first rerun was interrupted when the workstation disk filled and its owned PG
server stopped. Its XML/errors are preserved as interrupted-disk-full.xml, not
counted as passing. Automatic review blocked deleting generated Next cache; NTFS
compression preserved generated files, and the local Docker service was restored
after it had stopped. The successful71-case rerun used a fresh owned PG instance.
No production resource or business data changed. Recovery's combined migrated PG
run passed five cases with successful process/cleanup. Independent review found
no new actionable issue in these corrections or the strict recovery runner.

## Release blockers and owner decision

The entire requested branch includes the withdrawn seven factory fixes plus two
later Packaging checkpoints (135 paths before today's fixes). User asked what it
contains after being offered either the full branch or only these two changes on
stable production; the features and migration implications were explained. No
narrowed release scope is assumed. The owner subsequently explicitly selected
the entire branch, including Packaging changes, on16 November.

Separate recovery preparation at
C:/ERP/.codex-work/factory-recovery-20261116 starts at exact active46ddd and adds
the exact0157 script, current production-base metadata and narrow compatibility
guards. Recovery preserves exact attribution in print-run snapshots and refuses
edits/deletion/physical shipment corrections for packages containing that evidence.
Legacy NULL packages retain baseline behavior. Independent review caught and
corrected a misplaced warehouse guard before any commit or deployment. Actual
receipt/replay and each protected writer passed52 focused cases and five combined
migrated-PG cases. Source1ab6ff57746b39e569b579dcd7f38d36d3ac1604 is committed and
pushed. Exact published-image startup/restart proof is pending CI artifacts; no
production staging/migration/activation has occurred.

The first exact-source CI run43807385043 passed the frontend job; security failed
because its cached backend apt layer held libpq5 17.11. Debian's security tracker
records17.12-0+deb13u1 as fixed. Both final and recovery Dockerfiles now require
that minimum for libpq-dev/libpq5, invalidating that layer and failing closed if
the fixed package is unavailable. No security allowlist or severity policy changed.
Official evidence: https://security-tracker.debian.org/tracker/CVE-2026-116304

Security-only run43808560606 on855d9fd025f6793dc1ec5fbf720c1ccdeb669e12 passed.
The two superseded full CI runs43807385043/43808766068 were cancelled after their
known failed snapshots were corrected; they are not green release evidence.
Recovery source1ab6ff57746b39e569b579dcd7f38d36d3ac1604 is pushed and its new
full CI run43810018892 has passed backend, frontend and security and is publishing
immutable artifacts. Final sourcea55b692cc includes that recovery
ancestry through an ours merge preserving the final feature tree. Its CI43810107925
was cancelled when combined review found the lock inversions described next;
neither run is presented as completed final-release evidence.

## Combined Sewing/Packaging lock review

Direct Packaging locks the parent order before Sewing/Packaging work orders.
Independent combined review found older receipt/report/output wrappers that could
retain a work order, bundle, batch or implicit foreign-key lock before requesting
that parent. The affected entry points now take the parent first: retained
Packaging receipt, band receive/final output, daily-report create/update/delete,
Sewing correction edit/delete, scanner transitions and manual/batch acceptance.
Every production caller of the shared Sewing receipt helpers was inventoried;
assignment-only writers and NOWAIT Cutting guards retain their existing contracts.
Permissions, factory checks, stale revisions and one outer transaction are retained.

Retained physical Packaging receipts also preserve the sum of recorded Packaging
input once records exist, including explicit zero. Receipt-only legacy orders
retain their incremental physical-input counter. Thus both receipt95 then direct60
and direct60 then receipt95 end with recorded input60, rather than155.

The first targeted run passed25 cases:24 real-PG and one SQLite capacity test.
It forces each legacy writer to wait on a held parent, checks its actual waiting
SQL and probes WO/batch/bundle with NOWAIT, commits real direct labels or damage,
then verifies resumed results and saved facts. Correction writers must return the
defined handed-off409 after output. Completed-WO scanner reopening and fresh
first-line batch assignment succeed. Both receipt/output orders and zero input
are checked. These tests are now included in the required CI PostgreSQL group.

A broader596-case Sewing/Packaging run passed587 and exposed only nine outdated
query-budget assertions. Their original evidence is retained as sewing-adjacent.
The new parent lock costs exactly one narrow query per whole receipt; revised
21/31/26-query budgets stay constant for1/50/401 bundles. All19 query-context cases
passed on Windows. The125-case Linux final run passed with zero skips, combining
the lock/query cases and the complete production-flow file. Replacing only six
runtime files with the priora55 source through read-only container overlays made
all18 legacy-writer races, all three daily-report lock cases and two counter cases
fail as intended (23 failures; receipt-first and SQLite-capacity baselines still
pass). No fault was written into tracked source. Original red/failed reports are
preserved separately from the green reports. Repository Ruff and compilation
passed. Independent runtime review found no remaining blocker; final changed-file
review and exact commit CI remain pending.

Fresh read-only source/routing checks still match115200 on both hosts. The retained
115200/052632/135430 sources pass their exact manifests on both hosts, and all six
immutable image digests have the expected OCI revisions. These historical copies
are retention evidence, not schema0157-compatible runtime recovery. Disk headroom
must still be budgeted against the actual new artifacts before any pull/extraction.

Pending release gates include full exact-source CI/security, safe0157 recovery,
branch-wide label/visual verification, QA-master pre-deployment review, fresh
production backup, staging/paired complete-fact performance and all closing checks.
The user's no30-minute-monitoring instruction waives only timed observation; no
observer or substitute monitor has been started. Production remains115200.
Production data touched:none. All fixture changes were isolated local QA only.

## Final Printing interlock correction

Owner-reported QA approved commit6c714f9cc, including Packaging and physical
label/scan checks. Preserve that exact acceptance; it does not automatically
approve a later source. Final review then found Printing's accessory-state flush
could hold a Sewing work order before updating its parent, conflicting with the
parent-first scanners and direct Packaging. Printing now locks the parent before
refreshing/locking its own work order and before status, authorization and input
checks; existing permissions, quantities and department handoffs are retained.

Two real PostgreSQL cases force a real Printing increment to wait on the parent
while direct labels or damage commits; the holder can lock Printing, Sewing,
batch and bundle rows with NOWAIT. Readback proves exactly two Printing records,
97 input/passed, unchanged95 Sewing output and conserved Packaging output.
Overlaying only the exact6c Printing route makes both cases fail on its actual
late parent UPDATE; the corrected route passes both. The complete related Linux
suite passed127 cases with zero skips; independent runtime/test review, Ruff,
compile and diff checks passed. New exact-source CI and recorded human review
remain required before release. A first rerun used a nonexistent test filename
and collected no tests; its failed report is retained and is not pass evidence.
