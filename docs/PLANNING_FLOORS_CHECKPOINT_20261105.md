# Planning, floor pictures and BST checkpoint — 5 November 2026

Status: exact narrow runtime deployed; production BST handoff, normal browser QA,
performance and immediate closing verification passed.
Last updated 2026-11-05. This checkpoint continues the approved scope in
PLANNING_FLOORS_BST_20261104.md. The owner confirmed existing Yo'ldasheva
Dilfuzaxon as Oydinoy's replacement and Axunova Xayotxon as Shaxnoza's replacement.
Their stored full names label their current teams/flows. No new identity, account
or permission was created.

## Verified production and scope

Both application hosts now serve active green 20261105_043000, exact source
94e4cfc54c6cc4fd5787bcbc7ba8483f4518a507, with both current links updated.
Source manifest is dd662d889407378ce78d22ebb40e5ce3f53a3043377027b84315f8733234b257.
Working rollback is blue 20261104_080711 / 984aeffb22aedd3262d7cd61e2d88a905b589e8d
on both hosts, preserving original container IDs, images, starts and backend
worker PIDs. Database remains 0154_eco_receipt_details with zero pending revisions
and no DDL. Production-base now records the actual narrow deployed source.
The older 20261104_093330 source and immutable images remain retained.

The pushed runtime branch codex/planning-floors-release-20261104 is exact
94e4cfc54c6cc4fd5787bcbc7ba8483f4518a507 in
C:\ERP\.codex-work\planning-floors-release-20261104. It contains the approved
small features over deployed ECO, with zero migration-file, dependency-version
or package-lock diff. The separate source reconciliation branch preserves existing
clone_main work. New origin/clone_mainc5a0d2e4 changes since4e17b4aa5 have70 paths,
no migration/dependency delta; their only shared changed file, inventory_service.py,
combines disjoint typed reservation and ECO authorization sections cleanly. These
undeployed reservation/catalog/finance/purchasing/stocktake/forecast changes remain
excluded from the narrow runtime. The combined source branch still requires the
separately approved migration graph reconciliation before it can deploy.

The combined source passed207 focused cases with31 PostgreSQL cases initially
skipped without a target. A follow-up on a new owned loopback PostgreSQL16
container passed61 reservation readiness/status/query-growth, stocktake snapshot
and purchase-receipt cases, zero skips. Ruff, diff check and the forecasting chart
contract passed. This is focused reconciliation evidence, not a complete combined
CI pass or a migration-graph approval. The source's ECO migration-file tests remain
deferred with the separate graph package; exact narrow runtime ECO PostgreSQL8
already passed in complete CI. Test-owned schema cleanup was verified before
removing the uniquely identified task container.

## CI and immutable build

- ERP CI41835800604 passed on exact94e4cfc54: full backend5116 passed/606 skipped;
  explicit Planning19, BST27, ECO8 PostgreSQL cases passed, plus dedicated existing
  database gates. Skipped optional full-suite checks are not called passing.
- Refactor PostgreSQL gate41835800637 passed on the same exact source.
- Frontend optimized102-page Next16.3.8 build, strict types, build contracts,
  Planning9 and floor artwork14 component cases passed. Actual isolated Edge QA
  and the owner's visual acceptance passed. Normal signed-in production-preview
  and post-cutover public read-only browser QA subsequently passed.
- Immutable workflow41961242842 completed successfully for release20261105_043000.
  Source archive, manifest, CI provenance and both digest-pinned images were
  verified, prepared, staged and activated on their respective hosts. Backend
  image digest 586f24d858073bbe08ec95eaed525cf298bd40ac3924cfcd935eb3ae8a0b4251
  and frontend be0e003ce910756c98caa3e3034499b9b8dbb940b049411e78f362022d3a0c98
  are the exact successful CI images.
- The fresh 112,183,293-byte custom PostgreSQL backup passed its 1,329-object
  restore-list validation, bounded by the reviewed 1 GiB file cap.
- Same-schema proof passed at0154_eco_receipt_details with zero pending revisions.
  No migration files, DDL or migration stamping were applied.
- Official paired active/candidate benchmarks passed unchanged default comparison
  thresholds: maximum median +1.57%, p95 +0.96%. Final public comparison against
  the public baseline passed: maximum median +0.32%, p95 +1.27%, payload +0.02%.
  Public payload changes ranged from -0.34% to +0.02%, within the unchanged 15-percent
  allowance; row counts, queries and benchmark identity matched. Maintenance
  benchmark authentication remains distinct from the actual normal browser QA.

## BST handoff and release closing

The reviewed production handoffs to Yo'ldasheva Dilfuzaxon and Axunova Xayotxon
committed and passed persisted verification with one audit receipt. Their current
worker links and flow names match the approved plan. Old leaders remain distinct
identities; protected historical records and original record sets are unchanged.
Historical report views continue to group using current manager links, as
previously disclosed; historical report logic was not changed.

The initial attempt stopped at the backup restore-list guard before apply. Its
original UNKNOWN result remains preserved. Read-only reconciliation proved no
committed handoff and no durable before-state file. After independent review and
focused tests, a separate frozen wrapper copy changed only the restore-list
container's read-only mount to the exact dump file and explicit root user; the
paired finishing wrapper was rebound to that copy. The corrected guarded attempt
returned COMMITTED_VERIFIED. It was not an unexamined replay.

Production identifiers, membership, the exact private plan, before-state and
protected-history comparisons remain in ignored reviewed outputs. Private row
details are not published.

Connected Chrome tab claim/create still failed. Documented Windows fallback
stopped because the current browser URL could not be established confidently.
No further Chrome input or bypass followed. The owner directed use of Edge;
connected Edge browser access then succeeded. The owner signed in again; real
production read-only BST baseline checks passed. The exact-candidate isolated
preview passed Planning save/reload and PostgreSQL readback, recorded/assigned
refusals, restricted visibility, EN/RU/UZ and phone layout, all changed floor
wrappers and synthetic BST flow/employee-manager readback, with empty application
console-error logs. See PLANNING_FLOORS_VISUAL_QA_20261105.md. After that concrete
review request, the owner replied “Visual QA approved” for exact94e on5 November.
Image publication, preparation, backup, same-schema proof, staging, normal signed-in
preview QA, backend-first activation, both current links, public read-only browser
QA, final public performance, all four health checks and runtime/database closing
passed. Only the authorized BST handoff changed business state; no other
production business form was submitted. Closing confirmed zero invalid indexes
and 36/100 database connections. Both owned deployment leases were released after
closing, with active green and working blue rollback identities verified.

The initial preview 403 and failed proof are retained. A separately reviewed
delivery-helper correction changed only client-abort handling, passing 53 offline
cases. The corrected normal proxy served 282 HTTP 200 responses, preserved identical
before/after runtime identities, and was closed. No deployed application source
was changed by this delivery correction. Final normal public browser QA recorded
zero application console errors; 29 unrelated browser-extension M_ID errors are
explicitly retained. This is not a total-zero-console-error claim.

Deployment authorization remains valid; no new permission request is invented.
The owner waived only 30-minute monitoring; no monitor was created or run. Required
immediate checks passed and working rollback remains available. No historical ECO
p95 exception or relaxed performance/capacity threshold was used. Only the exact
narrow runtime 94e was deployed. Combined source PR496 remains DRAFT and unmerged;
its separate migration-graph approval remains held.

## Verified capacity maintenance

At 04:12 UTC on 5 November the pinned official retention tool archived and removed
exactly 9 old backend and 40 old frontend source directories. Each of the 49 archives
passed complete member/path/size/content-hash checks against its original source
manifest. Five protected releases on each host and every preexisting archive and
checksum were preserved; images, containers, business data and schema were unchanged.
The active 080711 and rollback 093330 identities, worker PIDs and routing matched
the original baseline afterward. Both owned leases were released and all four
internal/public health checks returned 200. Net free-space gains measured during
the two apply phases were 222,224,384 and 730,161,152 bytes; later normal filesystem
activity means these are measurements rather than a permanent capacity guarantee.
Postcheck usage was 78.8655% backend and 78.3138% frontend. Those historical
measurements did not establish candidate pull/unpack or backup capacity.

Subsequent independent review approved removal of one exact unused backend image
with its source archive retained. Only that image was removed; actual free space
was then measured. Preparation passed fresh strict 80-percent prospective disk and
RAM guards using verified cached layer prefixes, missing-layer allocation, source,
capped-backup and safety budgets. No threshold, reserve or performance allowance
was relaxed; protected sources, active runtime and historical records remained
preserved.

Apply evidence SHA256: 1e0d5966e37e097c7435d4047c8e44364d1614135ecced79666ea3eaa071ef24.
Four-health evidence: 0021562e70041b946c14e2a3e552c7d47fbff6d8c3b701defaf0dfd973c618fc.
Post-CAS evidence: 3e9061d4aef2402d0ccc9fe5e54a8f6e600d5823b6ad9165b3f185173ccd4313.

The publication branch in C:\ERP\.codex-work\planning-floors-integration-20261105,
codex/planning-floors-integration-20261105, starts from verified c5a0d2e4 and
preserves the reviewed application tree. Public documentation and test identities
were subsequently minimized; the remapped BST fixture passed all 27 PostgreSQL
cases without changing runtime code. Private operational history and ignored
plans are excluded from publication ancestry. No migration files differ from
clone_main; application reconciliation remains a draft with the graph package held.
