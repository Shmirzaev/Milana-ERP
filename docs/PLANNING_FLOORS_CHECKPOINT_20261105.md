# Planning, floor pictures and BST checkpoint — 5 November 2026

Status: owner-approved feature visual QA and production BST handoff complete;
exact candidate staged; traffic cutover and closing verification pending.
Last updated 2026-11-05. This checkpoint continues the approved scope in
PLANNING_FLOORS_BST_20261104.md. The owner confirmed existing Yo'ldasheva
Dilfuzaxon as Oydinoy's replacement and Axunova Xayotxon as Shaxnoza's replacement.
Their stored full names label their current teams/flows. No new identity, account
or permission was created.

## Verified production and scope

Both application hosts still point to20261104_080711, source984aeffb22aedd3262d7cd61e2d88a905b589e8d,
manifest0221829adfc216391679b744ae512b6c4d96913bb0316c31dfe12fb9a1641be7.
Database remains0154_eco_receipt_details with zero pending revisions and no DDL.
Exact candidate 20261105_043000 is staged in green on both hosts. Active blue
containers, traffic, current source links, proxies and slot-state files remain
unchanged; production-base remains blue until actual cutover. Blue remains the
working rollback for candidate activation; the older 20261104_093330 release
remains retained as source and immutable images.

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
  and the owner's visual acceptance subsequently passed as recorded below. Normal
  signed-in inactive production-preview QA remains pending.
- Immutable workflow41961242842 completed successfully for release20261105_043000.
  Source archive, manifest, CI provenance and both digest-pinned images were
  verified, prepared and staged on their respective hosts.
- The fresh 112,183,293-byte custom PostgreSQL backup passed its 1,329-object
  restore-list validation, bounded by the reviewed 1 GiB file cap.
- Same-schema proof passed at0154_eco_receipt_details with zero pending revisions.
  No migration files, DDL or migration stamping were applied.
- Official paired active/candidate benchmarks passed unchanged default comparison
  thresholds. The benchmark against the public endpoint established a passing
  baseline. Maintenance authentication does not establish normal browser login.

## BST review and remaining gates

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
Image publication, preparation, backup, same-schema proof, both inactive stages,
paired performance and the public baseline now pass. Normal signed-in inactive
preview QA remains pending, followed by backend-first traffic activation, current
links, normal public read-only QA, public closing benchmark, all four health checks
and runtime/database closing checks. Preview login awaits the owner's existing
requested action; it has not been counted as passing.

Deployment authorization remains valid; no new permission request is invented.
The owner waived only 30-minute monitoring. Required immediate verification and
compatible rollback remain mandatory; pending normal-auth preview QA must pass
before cutover. Historical ECO p95 exceptions do not apply here. This checkpoint
does not mark the feature deployed or approve a pending gate by implication.

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
