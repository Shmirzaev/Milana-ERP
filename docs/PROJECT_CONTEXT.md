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

Last updated 2026-11-06. Keep this file short: current decisions, release pointers and
unresolved risks. Detailed history belongs in [the archive](archive/README.md),
not appended here. This summary does not replace live release verification.

## Payroll source extraction (6 November)

Dilmurod / Mirshoir payroll extraction is finishing as three family PRs after the
period/read stack: records and scans, adjustments/reversals, QR lifecycle. The user
authorized a single top PR combined with current `clone_main`, green hosted CI,
then merge and closure of included lower PRs. User owns one final browser check;
local ports 20000–20002 remain available. Automated evidence and the complete
operation/type retention ledger live in [the payroll record](archive/payroll-create-2026-11-06/CONTINUATION.md).
No production deployment, visual acceptance or system-wide enum completion is claimed.

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
