# Milana ERP: current working context

## Guidance publication and runtime scope

The 26 October guidance publication on `clone_main` at `b92ee8f` was
documentation-only; it did not integrate the runtime candidate in
[draft PR #308](https://github.com/Shmirzaev/Milana-ERP/pull/308). Later integration
candidates contain application changes that require their own exact-source evidence.
Historical results below belong to their named snapshots, not automatically to
this checkout, a new combined candidate or deployed production. Inspect current
code and the operation ledger before advancing a gate. Schema-owned writers,
system-wide enum/type adoption and human acceptance remain incomplete.

Last updated 2026-11-21. Keep this file short: current decisions, release pointers and
unresolved risks. Detailed history belongs in [the archive](archive/README.md),
not appended here. This summary does not replace live release verification.

## Catalogue prices imported from 20-11.xlsx (21 November)

The production catalogue import filled 114 missing standard-variant prices at
09:03:30 Asia/Tashkent. All 114 matched the workbook model and variant. The import
used the USD base price in column F plus $0.30, verified against column G, and
skipped blank base prices. Existing variant prices and provenance were preserved.
The import closed 19 matching active requests and retained their cost history.
Persisted readback verified all prices and the exact remaining queue of 114
requests (111 Milana and 3 Eco Cotton).

The database change ran on release `20261121_035130` with rollback release
`20261120_092044`. Schema revision remains `0159_ceo_balance_snapshots`.
The pre-import backup `auto_pre_prices20_11_20261121_040259.dump` has 135,468,067
bytes and 1,403 restore-list objects. The import manifest hash is
`62d2151826e5327c87828f24d57b573fb099c783833345b0ef40c37703b16075`.

## Reversible Cutting Inventory exclusion (21 November, deployed)

- The owner approved the exact standard-order labels from the revised Cutting reconciliation, keeping labels and history and excluding Usluga from the correction. Audit event `299999` records the activation. A read-only production snapshot verified all **995 labels across 145 standard orders** still exist and all 995 are absent from the inventory projection. The remaining visible label set exactly matched the original set less the approved labels.
- The dashboard, storage summary and inventory list use the reversible `cutting_inventory_exclusions` setting. No bundle status, scan, workflow receipt, production plan, Usluga record or schema was edited. The verified manifest is in the protected backend deployment evidence directory for this release. The versioned `scripts/configure_cutting_inventory_exclusions.py restore <manifest>` command deactivates the exclusion and appends an audit event. Approved manifest SHA-256 is `68ca69313699b84eb4f21a46224a58f000c489a0ad6aceab3a7fac21e6d581fa`.
- Both application hosts serve `20261121_035130` in blue. The previous release `20261120_092044` remains in green for rollback. The runtime source is `2382b7e3b56b2ea51b08501a73e50694c8991690` on `clone_main`. Source manifest SHA-256 is `d5c99f3a34b0d7dec0a29e4534d2f023616c7e7e831b5f4b999fa1ad2e485564`. [Build-only publication](https://github.com/Shmirzaev/Milana-ERP/actions/runs/44863234542) produced the immutable backend and frontend images. Database revision is `0159_ceo_balance_snapshots`.
- Verified pre-change backup `/opt/milana-erp/shared/backups/auto_pre_20261121_035130.dump` has 135,454,716 bytes and 1,403 restore-list objects. Dump SHA-256 is `489a9257bd699fe11c2bad82684a65f04d4391b8894308cd2d8b893fa18120ed`. All four public and internal health/login checks returned HTTP 200. Postflight verified both source manifests, routing configuration, two backend workers, zero container restarts, and zero invalid PostgreSQL indexes.
- The owner explicitly requested a fast deployment without tests. Automated tests, signed browser QA, security scans, performance profiling and timed observation were skipped. The backup, deployment health checks and read-only inventory verification were completed.

## Cutting to Sewing and BSO pattern validation (20 November, deployed)

- Bundle Inventory shows Besttex and Milana storage by displayed order. Cutting can dispatch approved, Sewing-ready Nastils to their assigned factory. Dispatch removes the labels from Cutting stock and keeps the Nastil in transit until Sewing accepts it. The Tashkent-date CSV includes dispatched, accepted, and in-transit quantities. New dispatches snapshot their quantities in the audit log and block Cutting deletion of the dispatched Nastil.
- Direct Packaging keeps package-level sizes and per-Nastil totals. Operators can adjust total pieces by Nastil. Verified Sewing sizes can determine the split automatically. A mixed package with ambiguous size origin keeps that origin unknown and available Sewing sizes still constrain creation. Existing exact attributions and physical correction rules remain available.
- A new BSO and its first production save together. Every model used in branded production requires a Qolip number and pattern attachment. Planning reports the missing information in English, Russian, and Uzbek.
- Both hosts now serve `20261120_092044` in green. Blue `20261120_050400` is running as rollback. Exact runtime source is `6ebfc7a31f1500e0699779b23266948f8638b50f`, merged to clone_main in [PR 576](https://github.com/Shmirzaev/Milana-ERP/pull/576) at `f05b5828a` with the identical tree. [Build-only Actions run](https://github.com/Shmirzaev/Milana-ERP/actions/runs/44709940639) published the immutable images.
- Source manifest SHA-256 `12a6fb2cee87e73a87f6ca19b747f668d6bc500edb018511d22d1a74837191c9`. Backend image `ghcr.io/shmirzaev/milana-erp-backend@sha256:5f04dd52f99c27584046e657e696208b403681f690ae39758105a951cf2af45b`. Frontend image `ghcr.io/shmirzaev/milana-erp-frontend@sha256:fb559bdebf9716605a1a8c7f3e13a4b563a3cd215fed9108dc8e52a8e6a3e01b`.
- The backend switched at 12:33:54 UTC and the frontend at 12:33:56 UTC. All four health endpoints returned HTTP 200. Both routers validated. The backend had two workers and zero candidate restarts. PostgreSQL recorded 32/100 connections and zero invalid indexes. The schema stayed `0159_ceo_balance_snapshots` and the deploy performed no intentional business writes.
- Fresh PostgreSQL backup `/opt/milana-erp/shared/backups/auto_pre_20261120_092044.dump` has 135,292,542 bytes and 1,403 restore-list objects. Dump SHA-256 `b4eb7ee97b7faed68b06e9a633b58ed949a65796ef8018fe4e6e33abc77f3339` and restore-list SHA-256 `7676afc06c1abd774e67d197288fdbfa22c8a189e233acbe91830d0f746ae66d` were verified. A full restore was not performed.
- The owner's no-test instruction applied to this release. The automatic PR validation runs were canceled, earlier CI failures remain recorded, and no new browser QA, performance sampling, or timed observation was performed. Immediate operational verification passed and both deployment reservations were released.
- The ERP backend virtual system disk grew online from 200 to 250 GiB to clear the staging limit. Closing measured disk use was 74.55% on the backend and 78.22% on the frontend. The old UzumPilot rollback copy was retained and its public service on the dedicated VM returned HTTP 200.

## Accessories: four-digit batch numbers and QC UI deployed (20 November)

All759 opening-import batches have unique four-digit labels1000–1818, with
stock, QC, provenance and inventory relationships preserved; completion audit292390.
That data correction ran on040300 with backup/restored-copy QA and Edge readback.
The owner then requested “deploy fast without test” for the QC UI change.
Further tests/CI, browser QA, scans, performance gates, QA-master review and timed
observation were skipped, not passed. Earlier inherited CI failures and blocked
preview evidence remain in the archive. No human acceptance is claimed.

The accessories release was `20261120_045400`, runtime source
`78c8aa5b086d056966d21f1d01fa56eb15ab2f65`, manifest
`c7d955135511446f23665748b33b83ffa167e2c8afcae268dce00a507012c692`.
PR574 merged to clone_main at3a33b7c5e with the identical source tree, preserving
the deployed Cutting changes. Accessory edit/receipt/return forms hide QC and
omit qc_status; fabric QC and stored statuses remain. The four-digit labels persist.
Build-only Actions44677453647 published immutable images outside production.
Fresh133,690,585-byte backup hash/list verified (1,403 objects), not fully restored.
No migration or intentional business write. Schema0159 is unchanged. Backend
activated04:58:06UTC; frontend04:58:33UTC. All four health endpoints returned200.
At that cutover blue044200 provided rollback; blue has since been replaced by the
050400 Cutting display release. Owned leases/reservations were released and automatic
deployment remains inactive. Existing disk exception retained.
See [exact images, evidence and skipped gates](archive/ACCESSORY_BATCH_NUMBERS_QC_20261120.md).

## Cutting remaining-balance fix deployed (20 November)

The owner replaced Needs count with "Show pieces and original label count".
Cutting now shows remaining pieces alongside distinct unaccepted source labels in
batches with a remainder. Original labels are explicitly distinguished from
physical bundles. Fully processed batches stay excluded; partial pieces deduct
recorded downstream work even without acceptance. Quantity reconciliation,
receipt history, permissions and business data stay unchanged. The audit snapshot
has69,563 pieces /1,095 labels (MIL22,908/334; BST46,655/761); live counts follow records.

At that cutover both hosts served blue `20261120_050400`, runtime source `e44d7930c`, manifest
`65d84faa62e71781e2f48d590add0d71662d84f713d8586625a11f2923c419dd`.
PR575 merged to clone_main at `f2a1b39e4` with the identical tree. Backend switched
05:06:29UTC, frontend05:06:43UTC. All four operational health endpoints returned200;
two backend workers, zero restarts/OOM/tracebacks. Green045400 provided that cutover's
rollback, preserving the accessories update. Immutable hosted build succeeded;
only the balance service changed over the exact live backend image. No migration,
production business writes or production-host build/install. Schema0159 unchanged.
Fresh133,738,751-byte backup hash/list verified (1,403 objects), not fully restored.

Independent source-only review passed. Further tests/CI, browser QA, security scans,
performance and timed observation remain skipped under the owner's direct-deploy
instruction; no QA-master acceptance or AI_VERIFIED claim. The earlier129 workflow
tests belong to the preceding Cutting source; its unrelated full-suite collection
error and missing visual evidence remain recorded. Both leases/reservations are
released; automatic deployment stays inactive. Existing disk exception retained.
See [exact images, scope, history and skipped gates](archive/CUTTING_EXACT_BALANCE_20261120.md).

## CEO dashboard access/presentation deployed (20 November)

The owner requested superadmin access, removal of Waiting for handoff, repaired
day/week/month controls and clearer Material stock, then explicitly instructed
deployment "directly without any tests". Further tests/CI validation, browser QA,
scans, performance gates and timed observation are skipped for this release,
not recorded as passed. Earlier access-only checks predate the presentation edits.
The owner's follow-up made the material detail/search/filter/list collapsible,
closed by default, with unit totals visible. Its historical follow-up release is
`20261120_042800`, source `9f64146d4d5b8e523d71fb6c3483c02118d32acb`, manifest
`413aa746515609a15a16ee4ce1d94beb3af58768f30fda051fcca565b8438544`.
Backend switched04:31:43UTC, frontend04:32:12UTC. All four operational health checks
returned200; zero candidate restarts/OOM. Blue `20261120_040300` was retained
as rollback at that point. Schema0159 is unchanged. Fresh133,536,381-byte backup
hash/list verified (1,403 objects), not fully restored. No migration or intentional
business writes/users/role assignments/snapshots. Both reservations/leases released;
automatic deploy stays disabled. Runtime source is pushed/merged to clone_main.
The later044200 Cutting release is current; this section retains the CEO
follow-up release evidence.

Superadmins have a server-derived capability, menu link in all three factories and
Back to ERP; CEO isolation remains. Waiting presentation is removed. Week/month
expand narrow presets, custom dates stay fixed; material totals remain per unit,
with search/filter and bounded visible rows. Source-only independent review
completed; latest presentation is untested by owner request. See
[scope, exact images and release record](archive/CEO_SUPERADMIN_DASHBOARD_20261120.md).

## Latency repair: deployed and observed (19 November)

The 19 November latency release was `20261119_122457_44523647780_1`, source
`65c861c8369d3f966bac69d1b9980aff796744c5`, manifest
`fd7428c089dba546e4b89db784614f9bf8ac44b80bc9a7b1491a7445ce7c8917`.
Backend activated at 12:51:32 UTC; frontend at 12:51:52 UTC. Rollback release
`20261119_030500` / `437523dbd2` was then retained in blue; that inactive container
was replaced by the 20 November dashboard candidate after fresh preparation.
Schema `0159_ceo_balance_snapshots` and fingerprint `c1830a0f…` are unchanged.
CEO assignments/snapshots remain zero. Blue lacks the CEO guard: keep CEO
unassigned or revoke future CEO accounts before rollback.

Measured repairs address SQLite counter connection churn/FD growth, large
responses encoded on the ASGI loop, a repeated filtered model-family count scan,
and normalization of unrelated numeric model codes. The numeric necessary-condition
guard retains the original ILIKE predicate, name search, scope, ordering and
fallback SQL. Worker startup prepares metadata, collects and freezes all then-tracked
objects; new allocations keep enabled default GC (700/10/10). Frozen startup
cycles can remain retained until source thaw on exit. Earlier supplemental GC
p95 and nonattributing memory FAILs remain recorded; no universal latency or
all-memory-pass claim is made. Latest Ismail merge #561 is included, without
attributing these defects to its author.

67 focused Linux/owned-PostgreSQL tests and independent source/image review passed.
Exact-source CI 44523647780 passed after a preserved external Ubuntu APT 503
browser-install failure and fresh-runner retry. Integration CI 44525776222 and
refactor-PG 44525776323 passed. The 32-file exact-image qualification ZIP is
independently hash-verified and root-protected on both hosts. Its first diagnostic
aborted before timing on fixture file ownership; separate V2 corrected only the
fixture. Read-only enforcement, off-loop encoding, child replacement, restart,
natural-cycle criterion (>=99%) and complete post-thaw shutdown cleanup passed.

Seven ordered workflow projections matched on one read-only snapshot; 101 core
pairs and 31 search pairs passed the unchanged budgets. Internal model-options
p95 improved 44.323 -> 33.513 ms; model groups 78.597 -> 53.929 ms. Immediate public
and closing comparisons both passed. Closing public inventory-batch p95 was
181.658 ms versus 214.265 ms before deployment; some other closing p95 values
rose within budget. Observation ran 1800.17 seconds / 61 rounds / 244 successful
health checks, from 12:53:48 to 13:23:48 UTC. Closing runtime, counter persistence,
four health checks, readiness, logs, source identity and PG checks passed:
36/100 connections, no invalid indexes, restarts, OOMs or application error matches.
Both journals are complete; deployment reservations are released.

A fresh 132,789,711-byte backup (1,403 restore-list objects) was hash/list verified,
not fully restored. No migration or QA business records/users/CEO assignments/
snapshots were created in production; only technical counters. Owned isolated
tests used fixtures. Diagnostic containers and private counters were archived
and removed; the legacy checkout is untouched. Context is mirrored to Obsidian.

All earlier failed candidates retain their failed dispositions and protected
evidence. Automatic deployment remains disabled pending pinned-policy reconciliation.
Unrelated host contention, legacy Sewing label ambiguity and broader security/audit
debt remain outside this repair. The recorded owner disk override and the user's
“Ignore and deploy” instruction for QA approval are retained. No QA-master or
signed-in browser acceptance is claimed; the Chrome adapter remains inaccessible.
Public login rendered with zero console errors. See
[exact evidence and remaining risks](archive/RATE_LIMIT_LATENCY_20261119.md).


## Frontend performance fixes (17 November; local candidate)

Scanner fallback, Cutting request/draft handling, Packaging pagination and QR
print preparation have focused automated, restored-copy API, browser and
independent review evidence. Native print-dialog cancellation and full local
image parity remain unverified; production performance/release gates remain.
The owner requested a local `clone_main` commit. No push/deployment is included.
See [scope, evidence and remaining gates](archive/FRONTEND_PERFORMANCE_FIXES_20261117.md).

## Deployment automation baseline (17 November; source reconciliation)

The automatic deployment source is implemented and independently reviewed in the
dedicated worktree. Its 55 Linux deployment fault tests, CI/security policy tests
and observer tests pass. The owner selected a lightweight fixed worker on backend;
its fixed files, dedicated Linux accounts/SSH key, backend configuration and
systemd service, site gates, restricted host configurations/sudo rules and separately
pinned `RELEASE_ID` adapter are installed from reviewed commit
`76c49093d5fc1466399fc2654a03660480d0ff5f`; installed routing controllers are unchanged.
At the 17 November installation the service was enabled/active on backend,
with `AUTO_RELEASE_BUILDS=true` and an idle checkpoint. This is historical:
the 19 November release recovered it to idle and stopped/disabled the service.
The GitHub credential is provisioned
under the owner's explicit authorization, readable only by the worker account;
server-side Actions/branch/collaborator/policy reads, Contents/status writes and
both restricted SSH helpers pass in the real hardened service sandbox. Credential
rotation remains a follow-up. A pinned PostgreSQL 16 backup client replaces the
incompatible native version 18 dump path; the private PostgreSQL 16 restore passes.
The owned two-host preparation/approval/partial-cutover recovery rehearsal passed;
both exact baselines were restored and temporary services/containers removed.
Production activation timing remains unmeasured; bounded laboratory timings are
in the task record. PR #558 is source-merged; broader backend CI is still running,
while 55 focused Linux deployment tests, frontend/security checks and actual
server verification pass. Future application candidates still require all CI jobs.
Application changes require real, exact-plan QA evidence; missing evidence stops
activation before either traffic switch. An initial live package-GET probe may have repaired QR cache/metadata;
the effect was not fingerprinted. Later probes enforce read-only DB/storage.
See [daily use/install](AUTO_DEPLOYMENT.md) and
[verification/limitations](archive/AUTO_DEPLOYMENT_IMPLEMENTATION_20261117.md).

At that historical checkpoint both source pointers named `20261116_130518`, manifest
`bc2e0d4bdbb38f6c06b9f3d5c75f3fdaa1fb5087240ca8f7b49d01318908ce40`.
All 2,559 declared files match raw Git blobs at
`4d7cf17e55b165b1edc05407065f92597cebdbe5`; both manifest checks pass.
Backend health/readiness report that release. Migration source head remains
`0157_package_allocation_items`; protected installed-helper snapshots now pass on
both VMs, including actual routing/container identities and the real backend
database-head check. Both active slots were green; retained rollback was
`20261116_092917` in blue. The 19 November section above supersedes these release
pointers; previous failure/waiver evidence remains historical and unchanged.
The owner authorized reconciling this verified live lineage with `clone_main`,
then preparing and installing automatic deployment. Installation used the existing
SSH account's Docker administrator access; application releases, routing and schema
were unchanged. No intentional business writes occurred; the early QR-repair
uncertainty is recorded above.

## Model-file pool fix candidate (16 November; not deployed)

An isolated candidate on exact source `db8d8d64953eb4f9dadc22bb8218942cd0999ac7`
keeps image authentication and Session release in one synchronous worker call.
The old source fails an 80-request / 40-worker / 8+4-pool regression; the fixed
focused suite passes 35 tests including real PostgreSQL, and related suites pass
51 with eight existing PostgreSQL-upload skips. Browser image rendering,
revocation and recovery passed independent review through the real Next.js gallery
on desktop and phone. Frontend lint, strict type checking and production
build/contracts pass. The initial gallery harness result was invalid and is
retained separately. The broad cached-runtime suite reported 6,850 passed,
1,600 skipped and eight failures also reproduced on unchanged production source.
Corrected runs pass 208 invoice, 255 auth/image/JWT/transport and 1,754 QR tests;
required PostgreSQL groups pass. Only stale invoice test expectations were aligned
with the approved 24pt layout; the generator remains unchanged. Original failures
and unexercised optional skips remain recorded. Exact-commit CI and release gates
are pending. No frontend change,
timeout/pool increase, migration, push, merge or deployment is included. Human
acceptance remains pending. See the
[scoped evidence and limitations](archive/SEC04_POOL_STARVATION_20261116.md).
Earlier SEC04 evidence did include PostgreSQL/browser and 8-concurrent stress;
the gap was testing above the pool/thread scheduling threshold.

## Adaptive invoice description width (16 November; current production)

Backend/frontend serve `20261116_092917`, blue, runtime commit
`db8d8d64953eb4f9dadc22bb8218942cd0999ac7`, manifest
`54acee32ab64f7696a2cef52ad47c23f4f0aa7e8ebd45dafb3f5a3c3e71f96c3`.
Running rollback is `20261116_090442`, green. Schema remains
`0157_package_allocation_items`; no migration or business-data writes.
Excel description width follows the longest description/header in each invoice,
independently of the size column. Original10pt font, uniform24pt rows, no shrink
and compact trailing columns remain. Excel's255-unit width limit still applies.
Owner explicitly requested "deploy without any test". No additional tests/CI
suites, scans, performance/browser QA, separate human approval or timed monitor
ran for deployment; previous81tests/native Excel review are development evidence.
Four operational endpoints returned200; both source/slot identities agree,
zero container restarts/OOM. Immutable build-only run43839778882 reused live
bases, changed only the Git-byte invoice generator; frontend filesystem unchanged.
First092633attempt stopped before activation on source/image line-ending mismatch;
its FAILED receipts remain. Final archive uses raw Git blobs, avoiding Windows
archive EOL conversion. New blue cutover completed09:29UTC; both owned leases
released, previous green retained. No main merge. Prior public-latency risks remain
unresolved and this release was not benchmarked.
Details: [deployment record](INVOICE_AUTO_WIDTH_RELEASE_20261116.md).

## Earlier Pricing and Packaging release (16 November; owner exceptions)

The earlier production release was `20261116_061924`, blue, exact reviewed runtime commit
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
Detailed hashes, preserved failures and limitations: [task record](PRICE_WAREHOUSE_FIXES_20261116.md).

## Mixed-package attribution and wording (14 November; local only)

New mixed packages require exact source Nastil/model/color/size attribution; legacy
NULL remains honestly unknown. Manual cells determine source totals, conserve package
contents and enforce known actual Sewing size/total budgets across all requested packs.
Metadata edits preserve evidence; physical corrections require replacement matrices.
Snapshots/audits/labels/detail retain it through warehouse receipt. Unsupported exact
mixed shipment quantity changes direct operators to attribution-aware Packaging
correction. Migration0157 adds nullable JSON without backfill; downgrade refuses once
exact evidence exists. Operator attribution is not independently proven Sewing color
evidence. Per-size maxima remain capped by total availability after unsized damage.

Packaging-only header now says input recorded; queue distinguishes passed Sewing,
recorded Packaging output and availability including saved unlabelled goods, in
EN/RU/UZ. No quantity formulas changed. 213 affected backend tests, independent
21API/3real-PG checks, frontend conservation/recovery/render checks, TypeScript/ESLint,
full exact-source production build and independent hash review passed. Actual
Packaging-to-Warehouse UI plus independent SQL/HTTP verified exact30M/30L, remaining
5/10, one receipt/location and unchanged prior cases, without duplicate stock.

Print-popup visual gate remains BLOCKED by blob-URL browser policy; physical labels,
hardware and human acceptance pending, no whole AI_VERIFIED/release-ready claim.
This unpushed local checkpoint follows76820 on the investigation branch; it includes
withdrawn ancestry and requires live-source reconciliation before a future release.
No production data/schema change, push, merge or deployment. Public health still
identifies115200; withdrawn094409/e538 stays off traffic. Detailed contract, hashes,
preserved failures, migration recovery, limitations and human checklist are in
[the evidence packet](PACKAGING_BATCH_SIZE_20261114.md). BOM shortage, legacy WIP and
material-linked reversal gaps remain. At the owner's disk request, compression of
eight inactive old build caches recovered~2.37GB without deleting any files.

## Direct Sewing to Packaging correction (14 November; local only)

The owner requested removal of the separate Save Packaging Record step globally.
Local correction on `codex/factory-workflows-20261113` now creates only the selected
packs/labels directly from passed Sewing, reuses saved unlabelled output first,
retains exact batch allocations, supports damage-only entry without labels and
starts partial Packaging automatically. Shared keyed transactions, cross-action
retry exclusion and PO-first Sewing/Packaging locks prevent duplicate quantities
and the reproduced deadlock. Legacy record history/API remains; no migration.

137 focused backend tests, four mandatory PostgreSQL cases and five additional
reserve PostgreSQL cases passed. Frontend regression/property/recovery checks,
TypeScript, changed-path ESLint, fresh exact-source production compilation and
independent hash review passed. Connected Edge admin/Packaging-role UI and read-only
isolated SQL verified full/partial/mixed/grade/damage-only output and warehouse
receiving. Label-popup visual checking is BLOCKED by browser blob-URL policy;
physical labels, hardware and human acceptance are pending. No whole-task
AI_VERIFIED or release-readiness claim. See the
[operation/evidence packet](PACKAGING_DIRECT_SEWING_20261114.md).

At that checkpoint, remaining gaps included mixed size-by-batch detail and confusing
header/queue wording; the newer local-only section above addresses them. BOM shortages
still do not block packing, legacy input greater than packed+damaged needs
reconciliation, and material-linked cancellation lacks an operator reversal path.
No production business data was touched. Active public health still identifies
`20261111_115200`/source46ddd; withdrawn094409/e538 stays off traffic. This branch
contains other withdrawn changes: reconcile the packaging patch with live source
before any future release, complete remaining gates and obtain fresh deployment
authorization. No merge or deployment was performed for this correction.

## Factory workflow deployment rolled back (13 November)

The owner reported bugs after Packaging appeared unchanged overall and instructed
"return the last deployment there are bugs". Both hosts now serve blue
`20261111_115200`, exact source `46ddd5c7864f0a68bd9a3c884d835a2a5dbf9bfb`,
manifest `db9df64cbcf57e4ab93ac83ef677d7d394b07652a1a4cf3fe1815abc92adac28`.
Backend/frontend returned at11:21:38/11:21:43 UTC (16:21 Tashkent); both current
links and served identities agree. Database head remains0156_variant_price_workflow.

The seven-fix release094409/sourcee538 is withdrawn. Its green containers remain
off traffic; although runtime metadata names them as rollback, they are NOT a
known-good fallback. Do not reactivate/redeploy this build using earlier approval.
Any corrected release requires fresh owner authorization and completed verification.
Older052632 source/images remain retained; no extra standby staging occurred.
The task branch preserves the withdrawn code for investigation, not as live source.

Fresh mode0600 backup123,661,339bytes verified1,400 restore objects (SHA5da6b689).
No database downgrade/restore, schema change, business-data deletion or production
fixture occurred; activity since cutover is preserved. All four health/login
endpoints, readiness, source/image/default-command identities, routers, two workers,
zero restart/OOM/log markers, database headroom and zero invalid indexes passed
after rollback and independent review. Both deployment locks were released.
Timed monitoring remained waived; no observer or substitute monitor ran.

The reported defects remain unresolved. Prior automated, isolated and read-only
QA passes are historical evidence and do not override the owner's rollback or
establish human acceptance. Connected Chrome inspection during the follow-up
failed in its control bridge; no fresh Chrome visual pass is claimed. Disk remains
about78.55%/78.08%, above70% alert and below80% stop. See the
[rollback record](archive/FACTORY_WORKFLOWS_ROLLBACK_20261113.md),
[original deployment](archive/FACTORY_WORKFLOWS_RELEASE_20261113.md) and
[task packet](FACTORY_WORKFLOWS_20261113.md). The dedicated branch is pushed, not
merged into clone_main/main; later metadata commits are not deployed runtime code.

## Invoice/report and Sewing update (11 November; previous release)

That release served blue `20261111_115200`, runtime
`46ddd5c7864f0a68bd9a3c884d835a2a5dbf9bfb`, manifest
`db9df64cbcf57e4ab93ac83ef677d7d394b07652a1a4cf3fe1815abc92adac28`.
Its rollback was green `20261111_052632` /
`519c9fa36f3d90905f935caf08fe781417cf7e24`. Schema remained
`0156_variant_price_workflow`; no task-initiated business-data writes or schema changes.
The requested task branch is pushed, not merged into clone_main/main.

Invoices share naturally sorted size text and 10px table/signature type, retaining
23.1pt rows. Existing report has Today/This month Tashkent shortcuts; Sewing pages
20 batches at a time. Exact-source CI passed6,756 backend cases /1,589 reported
skips /36 subtests,649 mandatory PostgreSQL cases plus supplements/contracts,
frontend and security. Staged browser/Excel and550 paired GETs passed.

The first public280-GET check failed only Cutting-passport p95:150.85->186.97ms
(+23.94%, limit15%); original failure and rollback are preserved. After initially
keeping the old release, the owner explicitly instructed immediate deployment
after disclosure of that failure, accepting this named exception. The same scanned
images were promoted again without rebuilding or replacing the timing epoch.
Fresh backup verified1,400 restore objects. Backend/frontend activated17:46:18 /
17:46:24 Tashkent (12:46 UTC). Fresh staged/public complete-fact checks,81 unique
MIL batches, connected Edge invoice/report, four health endpoints, readiness,
source/image/router/worker/log/database checks passed. Timed observation remains
waived; no observer or substitute monitor ran. Human domain acceptance remains
unrecorded. Pre-existing shipment-traceability error at10:37:16 UTC remains unresolved;
deployment-window logs were clean. See the [release record](archive/INVOICE_SEWING_RELEASE_20261111.md).

## Variant pricing November scope (11 November; previous release)

That release served green `20261111_052632`, runtime
`519c9fa36f3d90905f935caf08fe781417cf7e24`, manifest
`55d0edc9b7893df95987102cc6d9ccbe5b59a89f3c369eb5ea1f46a9868d4520`.
Schema remained `0156_variant_price_workflow`; no migration. Its full-app
rollback was blue `20261110_135430` / `cfe03885e03e4310e9b7c86ec9649ff350565d65`.
Source was fast-forwarded into `clone_main`; deployment metadata is a later commit.

Only missing-price standard variants created from 1 November 2026, 00:00
Asia/Tashkent, qualify for active pricing. Usluga and older variants are excluded
from automatic/manual creation, submission and approval, without gating Cutting.
Admin retains Purchasing/Abbosxon and Accessories screens; Finance confirms after
both submissions and has pending, history and full Excel. Existing prices are
reused. Purchasing has one Fabric price USD input feeding the existing formula;
cards show the public Order No. Internal Cutting evidence remains intact.

Latest `11-11.xlsx` F + USD0.30 once filled exactly 14 missing prices. All 6,435
matched prices verify; 6,421 existing prices/provenance remain unchanged. Exact
model/variant wins; variant fallback must be unique across all catalogues.
Exactly 131 older active requests were cancelled with costs/history preserved.
Final snapshot: 39 active eligible requests, 36 MIL and 3 ECO, zero Usluga.
All 36 protected business tables (119,419 rows) stayed identical through both
writes, including order prices, manufacturing, stock and shipments. The original
519-price import/backfill history remains in the [previous release record](archive/VARIANT_PRICING_RELEASE_20261111.md).

Exact-source CI: 6,735 backend passes / 1,589 reported skips / 36 subtests,
649 required PostgreSQL cases plus supplements/contracts, frontend and security.
Staged 550 paired GETs passed. Public 280 GETs preserved complete facts, medians
and payloads but failed model-options p95 162.13 to 202.97 ms (+25.19%) and Cutting
passports 154.33 to 647.94 ms (+319.85%). Owner explicitly accepted these two
new-release exceptions; cause remains unproven and failed evidence is retained.
No replacement timing epoch was run. After writes, 30 full-fact comparisons across
public, active and rollback passed, as did fresh both-host formal closing/all four
health checks. The verified pre-cutover/data backup has 1,400 restore objects.
Actual public Admin forms, imported price/history and the 6,596-row three-sheet
Excel passed; one external ad-blocker error, zero ERP console errors. Owner waived
30-minute observation; no observer/substitute monitor ran. Staff account-to-team
mapping and human/QA-master acceptance remain unrecorded. See the
[scope and deployment record](archive/VARIANT_PRICING_NOVEMBER_SCOPE_20261111.md).

## Process QR base-model operations (10 November; previous release)

The previous release served blue `20261110_070607`, application
`843adaf3bda1b1f2d234e68b6763bbc649d3b72a`, manifest
`7bf0a59c139cf8a46fc6af7a3a0c5457795ba7b1de7fe57e70c76b31481fac32`,
on unchanged schema `0155_eco_gate_merge`. At that deployment, the healthy retained rollback was green
`20261109_163130` / `271c5005e12d1efc65d6358756862d8c243685a5`.
Process QR loads paid operations from the same catalog/factory's base model,
while preserving the selected variant, pictures, sizes and label identity.
No migration, backfill or deployment business-data writes ran.

Exact-source CI passed 6,666 backend tests / 1,569 skips / 36 subtests, mandatory
PostgreSQL 207, frontend, security scan and immutable publication. Actual signed
Edge staging/public checks show all 20 BJ5039 operations. Four selected model rows
and 240 issued labels stayed unchanged. Formal closing, all four health checks,
source/images/workers/routers/database/rollback checks and the full 1,800.16-second
observation passed (61 ticks, 244 HTTP 200 results, no failures or runtime drift).

The owner explicitly accepted only two original public p95 failures: BJ5039
generic detail 30.77 to 68.34 ms (+122.13%), and the larger model's opt-in base
operations 42.54 to 49.90 ms (+17.30%), against the original +15% cap. All medians,
payloads, full facts and four other public paths passed. Failed measurements and
limits remain intact; no repeated public timing epoch or blanket waiver occurred.
The staged benchmark's earlier cold failure was preserved, then one reviewed
symmetric warm-up epoch passed. Human engineering/operator acceptance remains
separate. Disk at that deployment was above the 70% alert (about 79.23% backend / 79.51% frontend);
only eight reviewed unused images were removed, with protected releases retained.
See the [release record](PROCESS_QR_BASE_MODEL_20261110.md).

## BJ5039 Process QR immediate repair (10 November; before deployment)

Owner requested an immediate repair before the permanent base-model loading fix
and accepted verified live `20261109_163130` as the task baseline. The parent
BJ5039 had 20 Milana operations; its four variants had none. The deployed audited
family-save service copied the unchanged parent list to BJ5039-V-6793, V-6794,
V-6795 (PO-0720), and V-6850. Five family-save audits identify System Admin as
actor. Parent details and other variant details were verified unchanged; no
issued QR or payroll rows existed for this family before/after the operation.

Fresh PostgreSQL backup was verified before mutation: 117,227,928 bytes, 1,395
restore objects, SHA-256 `b66142d10a7223810fe21e56f34b574d41062d8e95c2308e246894c08887cfb9`.
Model response serialization returns all 20 selected Milana rows on every family
member. Both live source manifests and all four health checks passed. Browser
automation failed before navigation, so rendered UI verification was pending then;
signed Edge verification passed during the permanent release above.
At repair time, reloading Process QR refreshed the selected variant's cached list. No runtime code,
release, schema, role, order, stock, issued QR, or payroll change was made by that
repair. Active release then was `20261109_163130`, rollback `20261109_035740`.
The permanent direct base-model read is now deployed as recorded above.
See [repair evidence](BJ5039_PROCESS_QR_REPAIR_20261110.md).

## BSO, fabric receipts and model copying (10 November; superseded release)

Both hosts previously served green `20261109_163130`, application
`271c5005e12d1efc65d6358756862d8c243685a5`, manifest
`535aa197ba218b0d0e867480d6a6570a25273307dfdea2185ce28d383f4e56d7`,
on unchanged schema `0155_eco_gate_merge`. Its then-compatible running rollback was blue
`20261109_035740` / `4f33eba776284b2e950e201a29c9da06cf7bd237`.
BSO page/Excel show Milana and Eco Cotton; fabric inventory adds received quantity;
model editing copies all paid operations into an unsaved target draft.

Exact-source CI passed 6,651 backend tests / 1,568 skips / 36 subtests, mandatory
PostgreSQL, frontend, security policy and image publication. Actual signed Edge
public BSO/Excel, received-versus-remaining and copy/full-reload checks passed;
isolated saved-copy/reopen and complete protected read contracts also passed.
No deployment business QA writes, migration, backfill or retention deletion ran.

Original paired fabric-batch medians (+17.248% / +14.496%, limit +10%) and public
p95 search/model-groups/stock (+23.475% / +31.173% / +18.649%, limit +15%) failed.
The owner explicitly approved these two separately disclosed, exact exceptions.
Original reports, exit1 and thresholds remain intact; no blanket performance pass.
All other measured limits and full ordered facts/receipts passed. Seven existing
stock adjustments and six depleted-batch archives explain the overnight dataset
change; fresh complete current A/B parity passed without dropping any fields.

The initial public UI console attempt failed on rapid-search cancellation messages
from unchanged code. A separate settled attempt had zero ERP errors/warnings and
two exact external ad-blocker errors, retained in full raw console with explicit
provenance; global console cleanliness is not claimed. Operator/human acceptance
remains pending under the separate disclosed owner override. No observer ran under
the owner's monitoring waiver. Fresh final closing passed all four health checks,
readiness, source/images/workers/routers, database/index/headroom and rollback
checks. Both leases were released; owned preview processes and tabs were closed.
See the [release record](archive/BSO_FABRIC_PAID_COPY_RELEASE_2026-11-10.md).

## Previous ECT/warehouse release (9 November; superseded)

Historical state before the 10 November cutover above. Both hosts then served blue `20261109_035740`, application
`4f33eba776284b2e950e201a29c9da06cf7bd237`, manifest
`e5d56b822d8a48d327429a5e6a59cd87111b81bb193a2fd8cf120d007a7fafb1`,
on schema `0155_eco_gate_merge`. Backend activated at 05:36:04 UTC and frontend
at 05:36:23 UTC. The then-compatible rollback was green `20261107_043754` /
`3c6ccc82a8521d74ce274151024ccd5bc1942fde`. Reviewed application 4f33 was pushed
and normally fast-forwarded to owner-approved `clone_main`; later metadata commits
do not change the deployed application. No migration or permission was added.

The release includes table ECT accessory/fabric receipts, older fabric-batch lookup,
passport Open order, optional manual Sewing line choice, Top/Bottom Excel,
selected multi-Nastil packaging, polished shipment reporting/Excel and merged
warehouse stock/map. Actual staged signed UI/Excel and isolated write/handoff/
concurrency checks passed. Public signed report/map checks and all affected fixed-ID
read contracts passed after cutover. No production business QA rows or backfill
were created; a live two-eligible-Nastil save was not exercised.

Exact-source CI passed **6,649 backend tests / 1,567 skips**, mandatory PostgreSQL,
frontend, security policy and immutable-image publication. Feature PG 25 and report
polish 15 passed. Earlier Windows-suite failures remain historical evidence in the
[task packet](ECT_WAREHOUSE_WORKFLOWS_20261107.md); they are not the final Linux CI.

Paired inventory-stock AB median **failed** +10.05419% (limit +10%, about 2.43 ms).
The owner explicitly approved that exact exception; the original failed report,
exit 1 and limits remain intact. Reverse-order median improved 3.2606%. Public
before/after measurement passed every original median/p95/payload/fact limit.
The reviewed QA protocol keeps all 27 global snapshots as concurrency evidence and
requires unchanged ordered API projections, actor/runtime and fixed workflow facts;
it does not require unrelated factory activity to stop or claim global quiescence.

The owner separately waived 30-minute monitoring: no observer/start anchor ran.
The separate named QA-master gate was overridden under the owner's disclosed
instruction to continue; no human QA-master approval is claimed. Operator
acceptance remains pending. Fresh final closing passed all four supported health
checks, readiness, exact sources/images/workers/routers, database/index/headroom
and rollback guards. Owned leases were released and exact local preview services
stopped. All 16 screenshots were emailed, including final polish and public screens.

A validated 114,628,708-byte PostgreSQL backup preceded staging. Active backend has
51 HIGH / 0 CRITICAL unfixed scan findings; frontend one MEDIUM. Disk maintenance,
unlinked direct ECO receipts outside central cutting stock and the pre-existing
cancelled-Printing input cap remain follow-ups. System-wide refactoring, enum
adoption and security audit are not complete. Exact identities, backup/evidence
hashes, exceptions and limits are in the
[release record](archive/ECT_WAREHOUSE_RELEASE_2026-11-09.md).

## Dilmurod source classification (7 November)

Behavior-preserving Identity #546, People #545, Support #547 and Work #544 code
landed on `clone_main`; #549 closes the remaining Eco Band writer and Work read
boundaries. The [coverage ledger](REFACTOR_COVERAGE.md#dilmurods-source-classification-slice--7-november-2026)
classifies 23 mapped tables / 324 fields from source and fixtures. Dilmurod
excluded seed and one-off employee reconciliation from the running-app slice on
7 November. Actual stored-value counts, contract decisions and human acceptance
remain open. No deployment is implied by these merges.

## RF-004 shared infrastructure (6 November)

Dilmurod/Mirshoir four-family source extraction covers audit reads, shipment-reopen
receipt hash assignment, bounded readiness probes and reusable verification evidence.
Prerequisites #497/#506 are merged; user authorized one green combined top-PR CI
merge and closure of included lower PRs. Existing shipment/idempotency tests remain
unchanged; affected owner FYIs and dual-database evidence are in
[the operation packet](archive/RF004_SHARED_2026-11-06.md). Ports20400–20402 are the
owned local stack; no screen/Production contract/deployment changes. Global RF-004
ratchet and other domain legacy boundaries remain separately tracked.

## Payroll source extraction (6 November)

Dilmurod / Mirshoir payroll extraction is finishing as three family PRs after the
period/read stack: records and scans, adjustments/reversals, QR lifecycle. The user
authorized a single top PR combined with current `clone_main`, green hosted CI,
then merge and closure of included lower PRs. User owns one final browser check;
the payroll QA servers/data/caches were removed after the user declared payroll done. Automated evidence and the complete
operation/type retention ledger live in [the payroll record](archive/payroll-create-2026-11-06/CONTINUATION.md).
No production deployment, visual acceptance or system-wide enum completion is claimed.

## Historical passport, pictures and ECT release (6 November; superseded)

**Historical 6 November release, superseded by the current runtime above.**
At that release completion, both hosts served
green `20261106_061725`, exact application
`a8579e64efbb2f9545d6df1c35d527c1d4ae2f01`, manifest
`7f52cf7bf61e6fa4159d65e590d9cefaa6a493992e8b80197343490e5ee09fb0`.
Database then used `0154_eco_receipt_details`; no business backfill or production
test rows were created. The historical saved rows now report automatically:
PO-0749 and PO-0750 each show 1,200 pieces, totaling 2,400. Actual public Edge
screenshots and signed immutable API checks agree. Export pictures and the
authoritative ECT 5A picker also passed; fresh available 5A was 151.8 kg at QA.

CI run 42173510387 passed for this exact source: 5,245 backend tests passed, 644
skipped; separate required PostgreSQL gates passed 180/23/176 cases without
skips. Frontend lint, strict types, build and contracts passed. Combined local
Edge flows, independent review, staging/public performance comparisons, all four
health checks, strict startup/router/log checks and database integrity passed.
Fresh 113,383,511-byte PostgreSQL backup validated 1,329 restore objects.
User explicitly waived timed observation; none was run. Owned deployment leases
were released, and owned local QA services were stopped without deleting data.

The historical **read-only** rollback at that checkpoint was blue `20261106_054000` /
`bf9cb9f0e738e82b9a21909b22e4cdecae7bed37`. Plain writable 488 is unsafe after
new grouped/Eco/rejection facts. Recovery uses read-only PostgreSQL and business
storage, with a separate private writable SQLite security counter store; login
locks/rate limits remain enabled across two workers. The retained counter copy
is a rehearsal snapshot: before incident activation, quiesce green and refresh
from its authoritative store using the separately reviewed recovery procedure.
Direct old `activate-readonly-backend` authorization is superseded; no automatic
fallback or completed recovery activation is claimed.

See [combined release record](COMBINED_PASSPORT_FLOOR_RELEASE_20261106.md) for
immutable identities, backup and actual evidence. Branch
`codex/deploy-passport-floor-20261106` is pushed and unmerged; shared-source
integration and human factory acceptance remain pending. The earlier candidate
records below describe their pre-deployment snapshots and are superseded by this
release state; they do not prohibit the owner's later explicit deployment request.
The durable [recovery restriction](archive/passport-floor-release-2026-11-06/READONLY_RECOVERY.md)
records the required fresh operational counter snapshot before emergency use.

At task start both application hosts were verified on `20261105_065721` / `488f3d654`,
manifest `e6c603d4c1954c64a75962cf189427eb5e316c039ea23de4699b9bd4f3112095`.
All 1,905 manifest entries match the candidate base; database remains
`0154_eco_receipt_details`, rollback source `20261105_043000`. The user approved
using this exact source after the required baseline drift stop. Older runtime
pointers below are historical. The initial standalone task did not deploy;
the combined release above subsequently deployed its changes.

The [passport repair packet](PASSPORT_TOTALS_ECT_20261106.md) records a reporting-only
correction: sum saved fabric-row pieces, with a legacy parent fallback and the
existing dashboard-only Tepa multiplier. Screenshot passports 800/801 total 2,400,
not 1,200. Read-only live-history comparison finds 65 affected CUT passports and
342,110 corrected all-time pieces versus 307,880 before; ECT totals are unchanged.
No Nastil, bundle, stock or confirmed production quantity is rewritten. Excel adds
separate embedded family-model/exact-variant pictures while retaining quantity columns.

For transferred batch 5A, ECT passport lookup/validation and Cutting consumption
use authoritative Eco receipt links to the central source batch, including split
receipts and archived/empty Milana sources. Physical consumption and reversal stay
in the Eco ledger; fabric-usage reports include that evidence. Direct unlinked Eco
receipts and the separate central-only batch replacement/Planning workflows are
outside this narrow repair. Candidate tests, independent review, actual browser
checks and isolated PostgreSQL concurrency evidence are recorded in the packet;
human acceptance, shared-source integration and deployment remain separate.

## Production-based Cutting/order UI candidate (5 November)

Both production hosts were verified on `20261105_065721` / `488f3d654`, manifest
`e6c603d4c1954c64a75962cf189427eb5e316c039ea23de4699b9bd4f3112095`;
rollback is `20261105_043000` / `94e4cfc54`. Older runtime pointers below are
historical. The owner explicitly chose this exact production source for an isolated
candidate and deferred integration into clone_main. No deployment is authorized.

The [task packet](SEARCH_CUTTING_ORDER_FIXES_20261105.md) records shared search-icon
padding, blank Planning quantities, package model/variant identities and Cutting
rejection with a required reason. Rejection blocks only the unrecorded Cutting WO,
preserves PO/downstream plans, audits and notifies its creator; execution/history
and stale-writer guards prevent bypass. No migration or production data changed.
Scoped automated/PostgreSQL and connected Edge visual/readback checks passed;
independent AI review found no remaining blocker. Human acceptance, source
integration and release authorization remain separate. The inherited missing
`common.noData` i18n check and extension-injected browser hydration warnings are
disclosed in the packet; neither is claimed fixed by this task.

The follow-up [ECO fabric/Qolip packet](ECO_FABRIC_QOLIP_FIXES_20261105.md) records
Milana-style ECO batch photos/metadata and responsive stock views, plus opaque
20 MiB .gem/.gemx pattern attachments on standard/Usluga models. Final frontend
build, 161 scoped backend cases, isolated HTTP byte-preserving readback and
inventory browser checks pass; independent AI source review found no blocker.
Complete browser file upload remains BLOCKED by extension/native policy checks;
genuine Gemini and human acceptance are not claimed. No migration/deployment or
production data change; both hosts remain065721. Owned QA services/database were
removed; automatic command review blocked temporary QA configuration-file cleanup.

The approved [cutting passport batch split](CUTTING_PASSPORT_BATCH_SPLIT_20261105.md)
adds one shared calculation with exact per-batch allocations (100+200kg), preserving
separate stock movements and one garment output.163 backend cases including7 real
PostgreSQL cases, frontend build/type checks, actual save/reopen/confirmation and
independent AI review pass; human acceptance remains pending. No migration or
production change; both hosts remain065721. Older binaries do not understand new
grouped JSON, so any future rollback needs explicit data compatibility review.
Owned QA services/database were removed; temporary JSON cleanup was blocked by
automatic review. Existing grouped-shortage reconciliation remains unchanged.

## Current ECO runtime and narrow feature candidate (4 November)

Both production hosts were reverified on blue `20261104_080711`, runtime
`984aeffb22aedd3262d7cd61e2d88a905b589e8d`, manifest
`0221829adfc216391679b744ae512b6c4d96913bb0316c31dfe12fb9a1641be7`.
Live database readback is `0154_eco_receipt_details`; compatible retained rollback
is green `20261104_093330` / `bd7d572282b50886e9d03a650bcf886ca9109175`.

The owner approved reconciling the deployed ECO application into clone_main while
preserving existing integration work, and preparing Planning cutting-factory
reassignment, floor print pictures and a BST master handoff. This narrow runtime
candidate starts from exact deployed984 source and ports only those small changes.
No migration file or dependency version changes; it retains0154. Undeployed
turnstile and other clone_main changes remain preserved in the separate source
integration candidate, not included implicitly in this release. A future combined
migration graph needs separate approval. See [candidate evidence](PLANNING_FLOORS_RELEASE_20261104.md).

No production mutation, cutover or timed observation occurred. Connected-browser
verification is BLOCKED after the policy helper could not reliably establish the
current URL. BST execution also awaits confirmation whether stored employee620,
Yo'ldasheva Dilfuzaxon, is the requested Yoldashova Dilfuza. Payroll rows remain
untouched; existing historical reports would regroup under current managers.
Historical performance exceptions apply only to the old release, not this candidate.

## Historical ECO inventory deployment preparation (4 November)

The owner authorized PR375 deployment and explicitly waived the30-minute timed
monitoring window. The [narrow release record](archive/ECO_INVENTORY_RELEASE_2026-11-04.md)
starts from freshly verified live11f80a29/blue20261103_094602 and preserves its
customer-pack/FG fixes. Only reviewed ECO inventory/transfers/approval and package
origin changes are included; unrelated clone_main runtime work remains excluded.
The bounded sewing follow-up resolves the assigned line's factory and actual
batch before the approval gate, including shared-work ECO assignments in order
ownership. Approval and physical issue remain separate; no migration or role
grant is added by that correction.
The follow-up also recognizes a persisted direct sewing line when no active
split assignment exists. Historical factory aliases use the existing shared
mapping in both gate selection and SQL ownership; unknown values refuse safely.
A restart-safe compatibility rollback is required before additive ECO migrations.
No deployment, migration or production business-data changes have occurred yet.

## Current refactor: Finance shipment invoice reversal (4 November)

The [operation packet](REF350_INVOICE_REVERSAL_20261104.md) records
AI_VERIFIED_AWAITING_HUMAN on application/gate candidate 60bcf909: Finance owns
the same-Session schema write that voids eligible shipment invoices. 204 distinct
PostgreSQL cases, actual desktop/EN/RU/UZ phone actions, one-shot receipts,
20-table persisted checks and independent AI review passed. Copied synthetic QA
schema needed a separately recorded existing-0084 repair; original failures stay
preserved and no business action was replayed. Full shipment coordinator audit
still fails on its unchanged legacy scan write. Other writers and broader
Finance/type coverage remain pending. QA master reviews before deployment.
Production/rollback pointers are unchanged; closed PR350 is not reopened.

## Customer-pack and FG release active with approved p95 exception (3 November)

Only customer shipment-pack restriction/admin release and FG numbering were pushed,
merged and deployed. Runtime is blue `20261103_094602` / `11f80a29` on both hosts,
manifest `ee765f999e782193878390897873c7b5865749460d4d776cf321fcd28490f8a9`,
schema `0150_package_customer_release`. Compatible green `20261103_112256` /
`37337ea6` remains the running rollback. Other clone_main runtime changes, including
HR0151, were excluded. PR376/377 feature ancestry and PR383 incident records are
preserved. Exact immutable CI passed 4,935 backend cases plus required PostgreSQL
and frontend gates; isolated shipment denial/admin release/warehouse-role/FG-save
workflows passed. Human production acceptance remains separate.

The final public Model Options p95 failed: 162.26 -> 193.23 ms (+19.09%, above15%);
median153.52 ->153.81 ms (+0.19%). Other six endpoints, rows and payload passed.
Automatic recovery first restored both roles to37337ea6. The owner then explicitly
answered **"Re-deploy with this specific p95 exception"**. The failed result remains
FAIL with only that accepted exception; it was not resampled or relabeled PASS.
Cause remains unproven. After a fresh verified full backup, the same11f80a29 images
were reactivated at12:38:09UTC (17:38:09Tashkent). Fresh source/image/slot/proxy,
default-command/no-seed/schema/readiness/pools/logs/workers/resources and four-health
checks passed, followed by connected public Chrome and GET-only API readback.
The separate 30-minute monitoring waiver was honored; no timed monitor ran.

Inherited startup seeding had reset one configured admin password hash during
initial staging. Only RUN_SEED_ON_STARTUP was disabled under backed-up byte-CAS
controls; both actual backend containers now have seedfalse. A separately reviewed,
backed-up row-lock/CAS transaction restored the exact original credential; actual
PostgreSQL fault tests and independent readback verified it with access/profile
fields unchanged. Earlier partial recovery/helper failures remain in the archive.
No production manufacturing/order/package/shipment/model form was submitted;
the release ledger remains empty. Both backend slots have two workers, zero OOM
and restarts; historical old-container OOM evidence is retained. Final DB24/100,
invalidindexes0; disk78.72%backend/78.54%frontend remains above70%alert/below80%stop.
Owned locks are released and task QA services stopped. See [release/incident evidence](archive/PACK_CUSTOMER_FG_RELEASE_2026-11-03.md)
and [machine-readable record](archive/PACK_CUSTOMER_FG_RELEASE_2026-11-03.json).

## Turnstile development (4 November)

The [Add access](TURNSTILE_ACCESS_BACKEND_20261103.md) and
[Edit details](TURNSTILE_EDIT_DETAILS_20261103.md) packets preserve earlier simulator
evidence. The [Replace photo packet](TURNSTILE_PHOTO_REPLACEMENT_20261104.md) records
the next isolated slice: explicit selected-device replacement, preserving distinct
device names/IDs and retaining prior photos until acceptance. Combined102 tests,
guarded PostgreSQL, full frontend build and actual desktop/EN/RU/UZ phone checks
passed; independent AI review found no remaining source blocker. Human acceptance remains unrecorded. Existing0152 constraints and
guarded downgrade apply; no new migration. Production release/rollback pointers
above are unchanged. REVOKE, adoption, live hardware and remaining system-wide
refactor/type coverage stay pending.
## Shared-counter outage policy (3 November)

The approved [mixed policy and isolated evidence](archive/SHARED_STORE_MIXED_OUTAGE_2026-11-03.md)
keep ordinary authenticated requests available with permissions enforced and a
warning when global limiting is skipped. Login and both password-reset steps
return JSON 503 until the store recovers. Dilmurod implements; Ismail reviews.
Connected-browser evidence is PARTIAL (signed-in checks missing); human acceptance
remains pending. No production changes were
made; active/rollback records below are unchanged. #311 readiness/router integration
must preserve this availability policy and is not included here. Full backend
suite with a disclosed local PERF06 drain adapter: 5,947 passed, one known S06
failure, zero errors/skips; the default fixture race remains a separate follow-up.

## Identity policy-helper prerequisite (3 November)

The [approved policy-only split](archive/ACCESS_POLICY_HELPER_SPLIT_2026-11-03.md)
moves the three unchanged policy evaluators to a catalog-only leaf, preserving
user-access exports while removing the factory-scope/user-access import cycle.
Dilmurod implements; Ismail reviews this PR. RF-009 user creation, IDN-01 and
human verification remain separate. This candidate changes no production release,
permission or database contract; active/rollback records below are unchanged.

## RF-009 create-user extraction candidate (3 November)

Dilmurod approved the six recommended extraction decisions under Mirshoir's
delegation. The [operation record](archive/RF009_CREATE_USER_EXTRACTION_2026-11-03.md)
tracks a separate stacked PR for one create-user service, schema-owned account and
setup-token writes, unchanged shared grant checks, and post-commit setup delivery.
Ismail reviews. The #345 baseline passes unchanged before and after on SQLite and
isolated PostgreSQL (196 cases, zero skips). This is a candidate, not a deployed
release or human acceptance; active/rollback records below are unchanged.

CI security-gate candidate [#507](https://github.com/Shmirzaev/Milana-ERP/pull/507)
adds dated accepted findings and exact scanned-image handoff before manual release.
It stacks on runtime npm removal [#509](https://github.com/Shmirzaev/Milana-ERP/pull/509); technical evidence remains in the PR. The nightly schedule starts once it reaches main. Both candidates are unmerged. JWT guard/migration
[#357](https://github.com/Shmirzaev/Milana-ERP/pull/357)/[#364](https://github.com/Shmirzaev/Milana-ERP/pull/364) remain Shavkat-dependent. No release changed.

## Active green release: older physical-pack history (2 November)

PR369 merged into `clone_main` at `1ed3c5c7`; the owner authorized deployment.
Active green `20261102_063110`, exact runtime `42078704df340558c8a21bf1ef14bf74cc87b222`, was finally
activated at 2026-11-02 12:15:43 Tashkent. Both clean manifests are
`becda671a332afe6fe86857ab948be2d686c984e81d02e6e68053ba83cb7a079`. Blue `20261031_092951` / runtime `337ff3c0`
remains the running compatible rollback with original container identities.
Schema remains `0149_besttex_cutting_access`; no business rows or labels changed.
Only reviewed full-history model/pack/PRN search, Tashkent date/receipt filters
and Previous/Next pages were added to exact previous runtime; other pending
`clone_main` application changes were excluded.

Exact-source CI (4,886 backend cases plus required PostgreSQL gates), independent
review, actual candidate/public API/browser, paired and final public 120-sample
performance and fresh four-health/source/slot/router/worker/database checks passed.
Public lookup found October pack `PKG-2026-000159` / `PRN-2026-000012` among 377 groups.
Console warnings/errors: zero. The first closing measurement aborted and triggered
verified blue rollback; that failure remains recorded with unknown cause. One
independently reviewed instrumentation retry retained the original baseline and
all thresholds, used maximum live payload with constant row counts, and passed.
No latency exception applies. The controller now matches exact release source
`13a9e19d`; previous controller is backed up. Disk remains above 70% alert,
below 80% hard staging limit. Timed 30-minute monitoring was explicitly waived and
not run. Human operator acceptance remains pending.
See [implementation/human checklist](archive/OLDER_PACK_FILTERS_2026-11-02.md) and
[release evidence](archive/OLDER_PACK_FILTERS_RELEASE_2026-11-02.md).

## Retained blue rollback: Process QR order sizes (31 October)

The [reviewed fix and release evidence](archive/PROCESS_QR_ORDER_SIZES_2026-10-31.md)
was deployed on blue `20261031_092951`, exact runtime `337ff3c01bb4778232dad9973d7c996396717e14`,
and is the running rollback after the final 2 November promotion; the first benchmark abort and temporary restoration remain in that release record.
Both verified source manifests are `f270b044a9b67069e44e3954f671bd59f9456146afd13221584f12053c2a3a94`.
Green `20261029_111113` was the compatible rollback at that release; its containers
were replaced by the 2 November candidate. Public PO-0495 / Nastil 1 showed 46/48/50/52/54 at
50 each and no 56. No business data or QR labels changed; ten table hashes match.
The exact release contains only the reviewed frontend/test/localization patch on
active runtime `1344b572`; other pending `clone_main` work was excluded.

Initial public Inventory Stock p95 failed at 178.73 ms versus 148.53 ms (+20.33%),
and both roles were restored to green. The owner then explicitly answered
**“Re-deploy with this latency exception.”** The same source/images were rechecked,
a fresh verified backup was taken, and blue was reactivated at 2026-10-31 15:24:00 Tashkent.
The failed measurement remains FAIL with that specific accepted exception; it
was not resampled or relabeled PASS. Median was unchanged and the other five
public endpoints passed; cause remains unproven. CI, required PostgreSQL suites,
candidate/public QR browser, paired performance and fresh four-health/source/
slot/router/worker/log/database/readiness checks passed. Schema stays
`0149_besttex_cutting_access`; human operator acceptance remains pending.

The separate 30-minute monitoring waiver was honored; no timed monitor ran.
Installed controller `d422ff74` (`/health` probes) was preserved, with explicit
both-slot `/ready` and 48/100 overlap-pool checks. Three owner-approved unused
August release folders were fully archived/compared/hashed and relocated to
`C:\ERP\.codex-work\release-archives\legacy-approved-20261031_092951` before server
copies were removed. Recovery receipts remain on the server. Cleanup disk use
was 78.11%; staging was below 80%, while the 70% alert remains applicable.

## Active whole-ERP refactor

6 November 2026: Payroll period CREATE is draft PR #511, with local characterization and extraction evidence; browser access is blocked and remaining payroll operations are pending. See [task record](archive/payroll-create-2026-11-06/README.md). No production change.

PR343 merged three verified persistence operations into `clone_main` at
`d235cf9e9a44b1de81428beb261f8fab837cbe87`; this did not deploy them. The owner
resumed all remaining domains with cheap isolated subagents on 30 October.
Collection UPDATE, Purchasing costing/notification persistence and typed Finance
payment results are the current candidate batch, with verification still pending.
See [the current operation backlog](REFACTOR_COVERAGE.md#current-integration-and-active-work--30-october-2026).
No whole-domain, system-wide type or human production acceptance is claimed.

## Historical green release (29 October)

The [multiple open shipment package split](archive/OPEN_SHIPMENT_PACKAGE_SPLIT_2026-10-29.md)
was retained on green as rollback `20261029_111113`, exact runtime `1344b572f8bff6f458892d3c2c8022560f306dbb`,
merged into `clone_main` through PR346. Both source manifests are
`93d632752aa355efad66fc67bf294fa6eb6321e90769106fc5de71c4cb6b7720`. Saving a partial per-size selection releases the
unallocated remainder immediately for another open shipment using the same QR;
either shipment may dispatch first. Existing valid package claims are supported.
CI passed 4,874 backend cases (544 opt-in skips), both required PostgreSQL gates
passed 165 cases with zero skips, and private browser/readback, paired/public
120-sample performance, verified backup, no-op schema and four health/runtime
checks passed. Temporary candidates were removed before the single closing
public benchmark. No latency exception was needed. No production business edit
was submitted; package PKG-2026-001240 still had all 60 claimed by open SH-2026-000180
at the conserved readback. The operator must save the desired partial quantity
there first. External earlier cancellations were not agent actions.
The old blue `20261028_123531` containers were replaced during the 31 October
QR release. After the documented rollback and explicit owner latency acceptance,
blue `20261031_092951` was active and this green release was its compatible rollback.
On 2 November these green containers were replaced; its release files/images remain historical recovery material.
The owner's explicit 30-minute observation waiver was honored; no timed monitoring
was performed. Human operator acceptance remains pending.

The prior release remains documented below for its original five changes and
PO-0377 correction; current runtime includes those changes.

[Order artwork, Nastil factory selection, warehouse remainder and invoice
sizing](archive/PRINT_NASTIL_WAREHOUSE_2026-10-29.md) was deployed on green
`20261029_083228`, exact runtime `24f4f2310a2194afe9a589796347525e2a7759fa`,
merged into `clone_main` through PR344. Both source manifests are
`95d3be61132307dc41ec13fff4e51965ad460ab7faa4e5725448db488a13cd59`.
Blue `20261028_123531` remains unchanged, including containers/images/start times.
After verified backup, PO-0377 Nastils 2/3 (255/256) were assigned to Besttex;
Nastil 1 stays Milana. Audit 151254 records the correction. Existing Sewing,
packages, stock, order/batch quantities and unrelated Nastils were conserved.
No historical Sewing output was invented. Exact-source CI (4,860 backend cases),
165 required PostgreSQL cases, candidate/public browser, paired performance,
no-op schema and immediate runtime/health checks passed. Two public p95 checks
failed (model groups +22.17%, then inventory stock +28.03% after temporary
container cleanup); both failures remain recorded. The owner explicitly accepted
this measured latency exception and authorized finishing PO-0377. Cause remains
unproven; no further retry or blanket performance pass is claimed. The separate
30-minute monitoring waiver was honored. Cutting-sheet physical/visual operator
acceptance remains pending. **Blue's old code cannot write mixed shared/dedicated
Nastil scopes safely: use the documented maintenance recovery guard after this
release; ordinary ungated blue activation is unsafe.**

## Earlier production reconciliation (29 October)

The [inactive-material batch-edit fix](archive/INACTIVE_BATCH_EDIT_2026-10-29.md)
was deployed on green `20261029_053553`, runtime `186110a549d48f42801058241ffcabbb22acdaf9` (PR342, clone_main), before the current release.
Only the unchanged-material validation was added to the prior green application;
no separate Mirshoir/Dilmurod changes were introduced. Blue `20261028_123531`
remains the unchanged running rollback. CI, 165 mandatory PG cases, verified backup,
no-op schema, candidate/public browser and 120-sample performance/health/runtime
gates passed. Real batch 7148's material/stock/ledger fingerprint was conserved;
no production business edit was submitted. Monitoring was explicitly waived,
not performed. Operator save/reopen acceptance remains pending.

The owner authorized reconciling latest `clone_main` with all current production
fixes and deploying through blue/green, with current production ready for rollback.
At that earlier cutover, green was `20261029_042945`, exact runtime
`921d646425054bb7b132042b1a173e2998249adc`, verified on both VMs. Retained blue
`20261028_123531` (runtime `a0cb9d8b`) stays running and healthy for rollback.
Both manifests at that earlier cutover were `eda617eedff05dfca42aef15003135c5c5870276bb5da087d6543c1add889580`.
The tested source merges `clone_main` `45b12da1` and production record `a6a89f50`
in a dedicated worktree and was fast-forwarded into shared `clone_main`.
Only Supplier UPDATE and Customer DELETE persistence/type changes differ in
application source; deployed Packaging, payroll, QR, Finance, frontend and
migrations are preserved. Corrected full backend tests passed 4,834 cases with
538 opt-in skips; the separate mandatory PostgreSQL CI gate passed all 165 cases
with no skips. Frontend, exact-source immutable CI, isolated Supplier save/Customer delete
browser and persisted readback, independent review, verified backup, candidate/public
read-only QA, paired/public performance and all four health checks passed.
Database remains `0149_besttex_cutting_access` after a no-op migration check.
Production QA made no business writes; normal authentication GETs touch heartbeat
metadata. The owner explicitly waived the 30-minute monitoring; it was not performed.
The first combined CI failure remains recorded; its SQLite-only timestamp fixture
was corrected and independently challenged without changing application clocks.
Closing root-disk use was backend 79.44%, frontend 77.16%; the 80% staging gate
remains mandatory for the next release. Existing linked-Customer FK error handling
and prior physical-label/operator acceptance limitations remain open.
See the [reconciliation record](archive/CLONE_PRODUCTION_RECONCILIATION_2026-10-29.md).

The earlier QA artifact omitted Next runtime inputs and returned 404 on `/login` and
`/`. A repaired genuine f27 artifact subsequently passed local login and scoped
visual/readback checks for PRs 335–337. This does not establish production status
or human production acceptance. See the [dated integration evidence](archive/VERIFIED_INTEGRATION_2026-10-28.md)
for exact source identities, observations and limitations; the earlier failures and
candidate history remain recorded there.

The current integration checkpoint includes CI tooling PR338 at
`e6f597891489e38207e01b6bfcca3d8df1b7adea` and Customer UPDATE PR339 at
`61b1a7020c5e1465aa076acc238d94ea1ad7dd03`. Its scoped Customer evidence and
V23 resource failure are recorded in the [dated integration evidence](archive/VERIFIED_INTEGRATION_2026-10-28.md).
Supplier UPDATE is a later source candidate with its own verification gates; it is
not included in that dated checkpoint. Dependency PR331 has separate environment
and runtime gates. No deployment or human production acceptance is implied.

## Historical Manual Packaging and combined release (28 October)

At the 28 October release, active blue was `20261028_123531`, exact runtime
`a0cb9d8b9fdab64dd751e7f3da7a1fa832779780`, verified on both VMs. Its then-retained
green rollback was `20261027_115452`. Database stayed `0149_besttex_cutting_access`.
The release combines reviewed clone_main through `61b1a702`, reconciled live
fixes, manual Packaging pack creation/reprinting/cancellation, and a narrow
Finance unlinked-BOM crash correction. Shared refactoring work was untouched;
this does not complete its operation/type ledger or human acceptance.
Fresh backup, exact CI/PostgreSQL, actual connected-browser/read-only QA,
fixed-origin paired/public performance, all four health checks and immediate
runtime/source/rollback postflight passed. Owner waived timed monitoring only.
No QA business data was created. Physical print visual acceptance is pending
after browser blob inspection was refused. See the detailed
[release record](archive/MANUAL_PACKAGING_RELEASE_2026-10-28.md) for immutable
images, backup hashes, failed earlier attempts and honest verification limits.

Owner-authorized employee-master correction applied on 28 October: the two MIL
employees formerly reporting to Akbarova Dilafruz #503 now report to #321.
Both Dilafruz records remain distinct; no payroll or attendance history moved.
The exact reviewed script `fe4bc0f8` passed a real PostgreSQL commit test and a
live rollback rehearsal before apply. Own-transaction attribution verified only
two employee manager/timestamp updates plus audit entries 144572/144573, with
95 other business tables untouched by the transaction. Fresh persisted readback
and all four health checks passed. Backup and full evidence are in
[the task record](archive/MANUAL_PACKAGING_2026-10-28.md). This data correction preceded the runtime promotion above.

## Source and production

- Shared integration/production branch: clone_main. origin/main is stale for this work.
- Pending platform change: staged backend containers will receive `RELEASE_ID` from
  `slotctl.py` and report it in `/health` and `/ready`. The backend VM's shared
  slot manager must be updated from the reviewed release before staging. Existing
  deployed slots have no process release ID until restaged; the observer still
  checks status only.
- Continue a suitable isolated worktree; preserve the legacy C:\ERP checkout.
  Use separate engineer work directories and one landing queue coordinated by Mirshoir.
- [DEPLOYMENT.md](../DEPLOYMENT.md) is the only supported release procedure.
  Before release reconcile Git, production-base.json, both manifests and runtime slots.
- The imported [26 October invoice release record](archive/INVOICE_READABILITY_2026-10-26.md)
  reports green `20261026_085306`, retained blue rollback `20261026_055538`,
  application `439555a77ef583b1b212398e16ecd52ced786e45`, manifest
  `9511b57bf62fd3142c865f3bb07aaf3e2f1053629f90c8521a652cd6da9139e2`
  and database `0149_besttex_cutting_access`. Its invoice-only release uses 11 pt
  customer/transport text, 9 pt product text, separated SVG branding and matching
  Excel. The record reports exact CI/four health checks and a corrected fixed-origin
  performance comparison passing after an initial failed gate and rollback;
  public-path tail variation remains unresolved. No 30-minute observation or
  refactoring job was added. These are attributed upstream observations, not new
  production checks by this integration review; operator acceptance stays separate.
- [PR #310](https://github.com/Shmirzaev/Milana-ERP/pull/310) merged as
  `cdcbdfe5e7cfeb08a65e6a86da27fc7b6175733d`, tree
  `aabd33becc5662469eb2ba408f832fb0059f1229`. Its six-file invoice port is being
  reconciled with frozen refactor candidate `d0920f6367b702f63c88d5940cf1b44155b34aec`.
  This successor candidate is **not deployed, not AI-verified and not human-approved**.
  The prior invoice-only production release does not accept or deploy the refactor.
- `deploy/production-base.json` records the verified 31 October runtime above. The following describes older integration evidence.
  Local successor merge `02c25ecf2c8acad55418d86cf5b067fc89307162` has actual
  parents `034cb788` and recorded production `439555`; all 36 released paths were
  reconciled, retaining reviewed namespace ports and both historical release records.
  It includes released QR pictures, Besttex views, grade weights and the exact
  migration `0149_besttex_cutting_access`. The migration has not been applied to QA
  or production by this review. Customer permissions, Finance payment forms and
  truthful Sales list totals have independent technical reviews; combined checks
  and actual successor browser replay remain required. Live manifests, slots and
  database revision have not been reverified. See the
  [integration addendum](archive/INVOICE_READABILITY_2026-10-26.md#source-reconciliation--27-october-2026).
- The earlier `20261024_032622` deployment recorded an initial performance failure and rollback, followed
  by reactivation of the same images; public-path tail variation remains unresolved.
  The owner waived the timed observation period. The archive preserves all attempts.

## Later-Nastil Sewing fix deployed

- Permanent later-Nastil receipt/completion and assignment fix is implemented and tested for MIL/BST/ECO. Runtime candidate `1fce86b5`; immutable CI `40082616718` passed.
- Ismail merged PR #304 as `ec02b5f`; the owner explicitly accepted his merge as approval and authorized deployment without the 30-minute monitoring window. The tested immutable runtime has identical application/frontend/migration/CI files to that merged fix. Later service relocation `1dfd1c5d` remains outside this release; repository architecture below describes that newer branch state.
- Activated at 16:13 Tashkent. Fresh backup, no-op schema verification, renewed 18-check factory QA, real live browser checks, all four health checks, runtime/log/database/source/rollback checks and fixed-query paired/public performance budgets passed. No business records/history were repaired or replayed; all eight PO-0307 table fingerprints match across cutover. Timed monitoring was explicitly waived, not reported as performed. Operator business acceptance remains pending.
- [Detailed verification and release record](archive/SEWING_LATER_NASTIL_2026-10-24.md) preserves root cause, tests and deployment preparation.
- Owner-authorized historical reconciliation at 16:29 Tashkent: reviewed 44 pending
  Nastils and reopened 38 incorrectly completed Sewing work orders (MIL 33, BST 4,
  ECO 1) through the deployed service. All 38 now appear in their factory's active
  Sewing floor, restoring 19 missing Milana orders. Only status/end_time/update
  timestamps changed; 38 append-only audits record the prior completion times.
  Fresh backup, 41-table conservation/persisted checks, all 131,366 backup audit
  rows, factory API/browser checks and four health endpoints passed. Pending cuts
  and receipts were not approved or fabricated; ECO USL-0008 still has 335 pieces
  awaiting Cutting approval. PO-0307 remains correctly completed at 256 pieces.
  Runtime/rollback/schema are unchanged; see the archive's historical reconciliation.

## Architecture and migration state

- Execution update, 26 October: Ismail explicitly requested "do the rest iwth codex
  subagents !" Codex subagents now implement the remaining system-wide refactor in
  isolated owned checkouts; one integrator and a separate independent reviewer
  retain the operation gates. This supersedes MiniMax-only execution for this task,
  not human domain ownership, acceptance or release/spending authority. Preserve
  prior worker source/evidence. See [execution rules](../AGENTS.md#implementation-execution)
  and the [remaining-domain ledger](REFACTOR_COVERAGE.md#remaining-work-by-domain).
  This is an execution change, not a new verification or completion claim.

- Historical scope correction, 26 October: the earlier six-area extraction
  checkpoint covered service/DTO placement and only the initial InvoiceStatus
  centralization. It did not complete Ismail's assignment. Subsequent enum and
  writer candidates must be assessed from their own operation records in the
  [coverage ledger](REFACTOR_COVERAGE.md); the old completion claim was too broad.
  Production/business acceptance remains separate.
- The owner's required unit is one business operation: study old behavior and
  callers, classify all relevant table/field/type candidates, implement, then
  automated checks -> actual visual E2E -> persisted readback/bounded stress ->
  independent AI review -> `AI_VERIFIED_AWAITING_HUMAN`. Follow the
  [task packet and operation ledger](VERIFICATION.md#0-study-the-old-behavior-and-give-the-agent-a-verifiable-task)
  and [table audit](../backend/app/libs/enums/README.md#table-by-table-audit).
  Human visual/technical approval, merge and production acceptance are separate.
  Synthetic QA values do not establish the complete production vocabulary.
- The owner's system-wide mentor-discipline goal requires actual enum-typed
  DTOs/internal contracts and consistent schema/service consumers. Default-only
  string fields do not satisfy it. Intentional OpenAPI/validation changes needed
  for enum typing must be explicit and tested; keep business rules and operation
  subsets. The six Ismail pilots are incremental work, not whole-ERP completion;
  Identity/People/Production/Packaging/Fulfillment/platform coverage remains owned
  and pending in the system-wide ledger.
- Keep the FastAPI/SQLAlchemy/PostgreSQL monolith. Router -> feature service ->
  schema-owned persistence operations + supplied Session -> database. Services
  retain business rules, permissions and one outer transaction. Ismail explicitly
  requires writes/updates behind schema models; this boundary remains unfinished
  despite the completed namespace move. Include audit/notification/idempotency and
  mapped mutations, preserve locks/hooks, and verify one complete operation first.
  No microservice/ORM replacement.
- Target: api/routes/ for HTTP, models/ for business services, schemas/ for
  database schema models, libs/dto/<feature>/ for input/update/output contracts,
  libs/enums/ for fixed vocabulary, libs/types/ for distinct internal contracts.
- Business services live in `backend/app/models/<group>/*_service.py`;
  existing shared helpers remain in `backend/app/models/*_service.py`.
  The old `backend/app/services/` directory was removed. Archived plans and
  commit-specific bug evidence may still name it; those paths describe history,
  not where an agent should create or move current code. Follow
  [the service guide](../backend/app/models/README.md) and
  [the current source map](REFACTOR_MAP.md).
  The owner then authorized completing namespace separation urgently: the 22 DTO
  files are now in libs/dto/ and 26 SQLAlchemy definition files in schemas/, with
  all callers and ORM registration updated. Table definitions and business rules
  are unchanged. See the plan's verification record for actual checks/limitations.
- The owner authorized all six Ismail areas (catalog, purchasing, sales, inventory,
  planning, finance) as parallel candidate work. The historical `3cdd6808` checkpoint
  for draft PR #308 combined their grouped services and entity-named DTOs. Its modules
  are listed in [the source map](https://github.com/Shmirzaev/Milana-ERP/blob/3cdd6808ff7ced0717f337d17d4e530719d4a86f/docs/REFACTOR_MAP.md#service-destinations). Existing
  shared helpers remain at models/ root. Finance/Purchasing/Sales passed 397
  tests with zero skips; Planning/Finance paging passed 206, including real PG.
  Final affected coverage passed 694 cases plus 18 recovered from Windows temp
  permission setup errors, with zero skips, and two separate PG stock races passed.
  Actual six-area UI flows, persisted readback and bounded stress passed; see
  [the candidate record and human checklist](https://github.com/Shmirzaev/Milana-ERP/blob/3cdd6808ff7ced0717f337d17d4e530719d4a86f/docs/archive/ISMAIL_SIX_AREA_REFACTOR_2026-10-25.md).
  At that checkpoint, API/table DDL parity covered 577 routes, 475 paths and 97 tables.
  These historical checks do not verify later enum/OpenAPI or schema-writer changes.
  Mirshoir's review and Shavkat's business acceptance remain separately recorded gates;
  no current candidate visual pass or production deployment is claimed here.
- Humans decide business policy, interfaces and cutover; AI implements approved
  scope. Multitenancy is deferred. No deletion quota or table-per-service requirement.

## Work and ownership

- [Refactor plan](REFACTOR_PLAN.md): tasks/dependencies; [source map](REFACTOR_MAP.md):
  current files and proposed homes; [team ownership](TEAM_OWNERSHIP.md): exact assignments.
- Mirshoir: architecture, database integrity, production, packaging, fulfillment,
  release approval. Ismail reviews Mirshoir's changes.
- Ismail: catalog, purchasing, sales, inventory, planning, finance; DTO/enum/type
  conventions. Dilmurod: identity, people/payroll, tasks, shared platform and CI.
- Shavkat: business clarification, priorities and operator acceptance, not technical
  review or migrations. Each code change has an engineer and a separate reviewer.
- Use [active bugs](../bugs/bugs.md) for defects and [finished bugs](../bugs/finished_bugs.md)
  only after named human production verification. Refactoring tasks stay in the plan.
- Shared [skills](AGENT_SKILLS.md): milana-refactor for extraction, milana-feature
  for new behavior; both Codex and Claude use repository-controlled instructions.

## SEC04 model-file session authentication (branch review only)

- The 27 October browser follow-up found that one-day file and one-week thumbnail
  private caches let revoked users reopen prior images. The SEC04 branch now
  requires revalidation after auth and returns byte-free 304s for active filesystem
  images; legacy DB fallback is `no-store`. Isolated Chromium Gate 3 and bounded
  HTTP Gate 4 passed on candidate `9f6895a9`; Mirshoir's review and human
  acceptance remain pending. Previously cached old-policy images can outlive the
  deploy until their old TTL expires; rollout handling is unresolved.
  [Current evidence](../backend/app/tests/SEC04-model-file-auth-evidence.md#browser-cache-follow-up--2026-10-27).
- Updated `codex/sec04-model-file-auth` with `clone_main` at `ba70e0cb`.
  Model files/thumbnails use current-account authentication and immediately release
  its DB session before file reads/streaming. Company-wide access is intentional;
  no factory/per-model scope was added. Owner Dilmurod; reviewer Mirshoir (pending).
- The evidence file retains the earlier 25 October BLOCKED record as history;
  the 27 October local gates supersede it. No merge to `clone_main`, deployment,
  production verification or business-data change. Release/rollback pointers
  above are historical and were not reverified.

## Turnstile REVOKE candidate — 4 November 2026

- Guarded simulator REVOKE at functional freeze `75083615` has 113 focused tests,
  finalized PostgreSQL concurrency and migration proofs, and inspected desktop/phone
  evidence. Independent AI source/evidence review found no new blocker; human acceptance remains unrecorded. See the [operation packet](TURNSTILE_REVOKE_20261104.md).
- HR archive and explicit gate revoke are separate. The owner's latest instruction
  places QA master human review before deployment, without pausing source integration
  or further refactoring. No real-device support or deployment is inferred.

## Required checks and open risks

- OPS05 isolated candidate adds the shared-store readiness probe and a shared
  bounded flight; `/health` stays dependency-free. Automated evidence and blocked
  visual/stress gates are in [the task record](archive/OPS05_READINESS_2026-10-26.md).
  This candidate is not merged, deployed or human-accepted.
- API02 candidate (re-aimed 29 October, Dilmurod; Mirshoir review): task write DTOs now
  validate state, priority, date and reference input; task creation/reassignment
  checks target visibility and holds a PostgreSQL key-share lock through commit.
  Existing state reopening remains allowed pending a business transition policy.
  Polymorphic task references still have no database FK, so later target deletion
  can orphan a task. This is branch work, not a production fix; see the
  [API02 verification record](archive/API02_TASK_VALIDATION_2026-10-26.md).
- Follow [verification gates](VERIFICATION.md) after each runtime migration/fix/feature:
  test validity, relevant automated tests, actual visual E2E with screenshot inspection,
  bounded isolated stress, persisted integrity/recovery, then human acceptance.
  Required missing/skipped checks are BLOCKED, not PASS. No production stress/data fabrication.
- The [local PostgreSQL runner adaptation](archive/LOCAL_POSTGRES_RUNNER_2026-10-29.md)
  supplies legacy and approved-instance fixtures together. Its full local run had
  5,375 passes, one stale S06 enum-call failure, and zero skips; required operation
  and supplement groups passed. Mirshoir review remains pending; CI is unchanged.
- Default backend pytest fixtures use SQLite. Real PostgreSQL checks need their
  documented setup/collection; do not infer locking correctness from SQLite success.
- One write path per request and one outer transaction owner. Preserve locks, audit,
  idempotency and side-effect timing. [Retry identity rules](idempotency.md) are active.
- Preserve stable business rules in [AGENTS.md](../AGENTS.md). Particular regression
  cases include sewing 600 received -> 495 then 105, independent Nastils, optional
  stages, and validated packaging receipts before finished-goods stock.
- Historical authorization/audit-chain findings are not declared resolved here;
  consult AGENTS.md and the relevant bug/evidence. OPS01/OPS07 still require the
  correlated factory-path evidence described in [performance evidence](performance-evidence.txt).
- CI branch triggering and automatic recovery improvements in the plan remain
  implementation tasks; skills/docs do not install enforcement or rollback.
- RF-013's [disposable single-host rollback rehearsal](archive/RF013_SINGLE_HOST_REHEARSAL_2026-10-27.md)
  switched both roles through real HAProxy, proved a candidate settings write remains
  readable/writable by the old backend, and recovered from a partial activation.
  The failed frontend remained routed for 41.41 seconds from injected stop to old
  service; `slotctl.activate()` does not compensate. This is local evidence only:
  Mirshoir review, visual acceptance, future RF-005 data compatibility, and an
  accountable production rollback operator remain pending. No production state changed.
- Recovery targets in [DISASTER_RECOVERY.md](DISASTER_RECOVERY.md) remain requirements,
  not proof of measured capacity. Preserve backups, active/rollback releases and evidence.
- OPS06 candidate (26 October, Dilmurod; Mirshoir review) adds a local read-only
  dump/storage pairing verifier with per-file hashes and checks of known database
  upload references. No production pairing schedule or shared snapshot ID was
  found; a manifest cannot prove capture-time atomicity or zero RPO. See the
  [OPS06 record](archive/OPS06_BACKUP_PAIRING_2026-10-26.md).

## Latest documentation work

- Shared skill/ownership baseline: f8719d19; verification gates: c1277680.
- Removed superseded developer/review instructions, consolidated backend/docs into
  docs/, archived dated reports and the full old context, and relocated training
  generation tools under scripts/training/. Runtime code, data, tests, deployment
  settings and test-consumed audit baselines remain unchanged.
- Documentation cleanup is not a deployment. See the final task handoff for its
  publication commit; do not infer current production from a documentation commit.
- Obsidian mirror location from AGENTS.md was unavailable during prior planning;
  no mirror synchronization is claimed. Search archived evidence only as needed.
