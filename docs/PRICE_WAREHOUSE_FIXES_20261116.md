# Printing cost ownership and warehouse model navigation

Owner request: remove print price from Purchasing price requests because Finance
will enter it; make the highlighted Warehouse Stock model card open its details;
deploy `codex/factory-workflows-20261113` without 30-minute monitoring.

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
