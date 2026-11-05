# Planning, floor pictures and BST checkpoint — 5 November 2026

Status: feature visual QA approved by the owner; release pending; not deployed. This checkpoint
continues the approved scope in PLANNING_FLOORS_BST_20261104.md. The owner confirmed
that existing Yo'ldasheva Dilfuzaxon is Oydinoy's intended replacement.
Use the existing stored full name for her current team/flow label. Axunova Xayotxon
is the other confirmed existing replacement. No new identity, account or permission is created.

## Verified production and scope

Both application hosts still point to20261104_080711, source984aeffb22aedd3262d7cd61e2d88a905b589e8d,
manifest0221829adfc216391679b744ae512b6c4d96913bb0316c31dfe12fb9a1641be7.
Database remains0154_eco_receipt_details. Compatible green rollback20261104_093330
is preserved. This task has changed no production business data, schema, runtime
slot, image, container, environment, proxy or symlink.

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
  and the owner's visual acceptance subsequently passed as recorded below.
- Immutable workflow41961242842 was dispatched with release20261105_043000 and
  the verified production release/manifest. Dispatch does not establish artifact
  readiness, signed QA, performance approval or production activation.

## BST review and remaining gates

Fresh repeatable-read READ ONLY production capture on5 November confirmed the
private before-state for the approved aggregate42/40-worker handoff. Production
identifiers, membership and manager relationships remain in the ignored reviewed
plan. Preserve old
identities, payroll, attendance, production, QR and report snapshots. Existing
payroll reports will regroup past-period views using current manager links, as
already disclosed; no historical report logic change is included.

The exact reviewed private plan/digest, minimal before-state, proposed after-state
and protected-history hashes are in ignored runtime outputs/bst-20261105. They
are not source-controlled. Recheck frozen state immediately before any eventual
apply; a changed plan requires a new digest and review. No apply or backup has run.

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
Image publication, inactive-slot QA, performance, backup and cutover remain pending.

Deployment authorization remains valid; no new permission request is invented.
The owner waived30-minute monitoring only. Backup/restore-list validation,
immutable artifact identity, source reconciliation, signed read-only QA,
performance thresholds, compatible rollback and all four health checks remain
required before cutover. Read-only resource inspection found application disks
near79 percent; recheck staging headroom and the documented retention policy
before pulling/extracting. Historical ECO p95 exceptions do not apply here.

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
Postcheck usage was 78.8655% backend and 78.3138% frontend. Image pull/unpack and
backup capacity must still be proven for the exact candidate artifacts.

Apply evidence SHA256: 1e0d5966e37e097c7435d4047c8e44364d1614135ecced79666ea3eaa071ef24.
Four-health evidence: 0021562e70041b946c14e2a3e552c7d47fbff6d8c3b701defaf0dfd973c618fc.
Post-CAS evidence: 3e9061d4aef2402d0ccc9fe5e54a8f6e600d5823b6ad9165b3f185173ccd4313.

The publication branch in C:\ERP\.codex-work\planning-floors-integration-20261105,
codex/planning-floors-integration-20261105, commit 501ded302, preserves the exact
reviewed 65eb4cd source tree on parent c5a0d2e4. Private operational history and
ignored plans are excluded from its ancestry. No migration files differ from
clone_main; this remains application reconciliation with the graph package held.
