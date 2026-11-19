# ECT and warehouse workflow release — 9 November 2026

Both production hosts now serve blue `20261109_035740`, application
`4f33eba776284b2e950e201a29c9da06cf7bd237`, source manifest
`e5d56b822d8a48d327429a5e6a59cd87111b81bb193a2fd8cf120d007a7fafb1`.
Backend activated at 05:36:04 UTC and frontend at 05:36:23 UTC. Compatible running
rollback is green `20261107_043754` / `3c6ccc82a8521d74ce274151024ccd5bc1942fde`.
Schema remains `0155_eco_gate_merge`; no migration or permission was added.

Immutable images:

- Backend: `ghcr.io/shmirzaev/milana-erp-backend@sha256:94be073321170f113494ad961d87478743713b012eabeefd34bb7c2f69075947`.
- Frontend: `ghcr.io/shmirzaev/milana-erp-frontend@sha256:970e1cf258e362852b47d916bc27a5f406a3fdc988ca86b097a3eb734dfe96a9`.

## Scope and source

The dedicated worktree is `C:/ERP/.codex-work/ect-warehouse-workflows-20261107`,
branch `codex/ect-warehouse-workflows-20261107`. The owner approved starting from
verified `origin/clone_main` / `b21b51e6c`, rather than stale `origin/main`.
Reviewed application source was pushed and normally fast-forwarded to `clone_main`
at exact `4f33eba77` before deployment; later context metadata does not
change the deployed application. The dirty legacy checkout was preserved.

The release adds ECT accessory/fabric receipt tables with shared supplier/date,
older compatible-fabric lookup, passport Open order, optional manual Sewing line
selection, Top/Bottom Excel columns, selected multi-Nastil packaging, searchable
dated shipment reports/Excel and the shared warehouse stock/map workspace.
The final report polish preserves frozen dispatch quantities and package rules.
Operation details and the human checklist remain in
[the task packet](../ECT_WAREHOUSE_WORKFLOWS_20261107.md).

## Verification and limits

Exact-source [CI 42559162662](https://github.com/Shmirzaev/Milana-ERP/actions/runs/42559162662)
passed all five jobs: **6,649 backend tests, 1,567 skips**, 36 passing subtests;
frontend, security-scope, security scan and immutable release publication passed.
Earlier feature PostgreSQL handoff tests passed **25** and report polish tests
passed **15**, including all locales, empty/shared-package totals and formula
protection. Strict TypeScript, lint (zero errors / 14 existing warnings), optimized
frontend and independent AI reviews passed. Earlier Windows-suite failures remain
historical evidence; skips are not passes.

Actual signed-in Edge QA used the exact staged images through a loopback gateway
that blocked business writes. Accessory/fabric rows, keyboard/add-row behavior,
passport Open, manual line options, daily Excel and packaging eligibility were
inspected without production business saves. Daily Excel contained 19 saved
entries / 4,622 sewn, with two Top-only and two Bottom-only entries.
The live packaging selection had no two available Nastils: a live combined save
was **not exercised**. Isolated full/partial/allocation/concurrency tests cover it.

After cutover, public Edge verified Nov6/V-6484 as KJ13053 / 24 pieces / one package /
one shipment. The combined warehouse map and exact BM8010-V-6470/A-05 selection
showed one model / two packages / 180 pieces and a matching placement link.
Screenshots were inspected and console errors were empty. The original fixed-ID
workflow readback passed before/after each measurement phase and again after
public browser QA: 15 signed GETs, unchanged protected hash
`dd0a865350ef6cdc38961a949a719d94097e9e6c20f34d1daf8a62f973008e6e`.
No production business test rows, receipts, packages, shipments or backfill were
created. Normal login/factory selection can update authentication metadata.

## Performance and explicit owner decisions

The original fingerprint setup exceeded its 64 MiB full-source serialization
budget before HTTP. Reviewed v2 retains all 27 tables, mapped columns and ordered
rows through typed full-content PostgreSQL hashes. It budgets fingerprint material
instead; total source bytes are reported and uncapped. Row/cell/statement/child
bounds remain. This is a recorded representation change, not a passed old budget.

Two subsequent epochs remained failed when live business activity changed global
tables despite matching API facts. One interval includes another user's audited
CuttingRecord creation and eight changed bundles; another recorded production
batches 999→1000. This evidence is not a complete causality proof.
Independent review found whole-database quiescence exceeded DEPLOYMENT.md's
ordered-result requirement. Reviewed v3 retains all 27 snapshots as concurrency
evidence while requiring exact actor/schema/runtime, every complete ordered API
projection and the original fixed workflow baseline around every phase. It makes
no global absence/no-write claim. Original failed reports remain unchanged.

The first v3 freeze passed, but local paired-program generation exceeded transfer
headroom before SSH/HTTP. Reviewed transport t2 uses lossless LZMA, preserving all
facts, the 90,000-byte limit and old evidence. Windows/Linux roundtrips, eight core
tests, host fault tests, 18 aggregate tests and 17 exception tests passed.
A fresh t2 freeze was recorded; old results were not relabelled under new pins.

Actual paired measurement completed all 480 serial samples / 482 GETs. Its sole
machine failure was **AB inventory_stock median**: 24.162721→26.592088 ms,
**+10.05419%**, against +10%. Reverse-order median improved 3.2606%; every p95,
payload and full business-fact check passed. Relevant inventory route/service
blobs equal the old application, which does not establish the timing cause.
The owner explicitly answered **Approve this specific exception and deploy**.
The failed report, exit 1 and original limits remain recorded; aggregate acceptance
is explicitly owner-approved with `machine_performance_passed=false`.
This exception covers only that exact report/metric, not public or future runs.

Public before/after measurement completed 120 samples / 121 GETs per side and
**passed every original limit without an exception**. Worst median increase was
inventory stock +1.9255%; worst p95 increase was +11.0587%; all payload ratios 1.0
and every ordered projection matched. Fixed workflow data remained unchanged
across cutover and after the signed browser checks.

The owner separately directed **deploy without 30 minute monitoring**. No timed
observer or start anchor ran, and observation is not claimed complete.
When asked for a separate named QA-master review, the owner answered **continue**;
root disclosed and recorded a narrow owner override. No named reviewer or human
QA-master approval is invented. Operator acceptance remains pending.

## Backup, closing and evidence

Validated PostgreSQL dump, mode0600, 114,628,708 bytes / 1,395 restore objects:
`/app/storage/.milana-backup-archive/milana_erp_pre_20261109_035740_20261109_044335.dump`.
SHA256 `f0a00c88520dd437865274325c542aac46e6281fdeb8bade8cb4a4598885e5af`;
restore-list SHA256 `a0dab2c221e7892dfc95485cd32c7abd203bd0ff5aca8fe1ac15f51ce6b3fba0`.
Restore-list validation does not assert an executed full restore.

Fresh final closing passed all four supported internal/public health/login checks,
internal readiness, exact source/image/default command/two-worker identities,
routers, schema/index/connection headroom and compatible green rollback checks.
Both owned deployment leases were released. The exact owned gateway/tunnel PIDs
were stopped after start-time/command/executable/parent checks; ports 3211/18109/
13109 are closed. The private preview tab was closed; the verified public warehouse
workspace was left open. Earlier SQLite fixtures, source, logs and screenshots
remain retained; disposable PostgreSQL containers and their ephemeral data were
removed. The separately retained Sewing container on port15568 is stopped with its
owned volume retained. No substitute observer was started.

Protected retention archived and byte-verified only six previously reviewed source
directories per host, retaining active/recovery/latest sources. No Docker images,
containers, backups or business data were pruned. Image security policy passed;
backend retains **51 HIGH / 0 CRITICAL** unfixed findings, frontend one MEDIUM;
green recovery retains its prior findings. Disk maintenance remains a follow-up.
Unlinked direct ECO receipts remain outside central cutting sources, and the
pre-existing cancelled-Printing input-cap inconsistency remains separate. This
release does not complete system-wide refactoring, enum adoption or security audit.

Evidence is retained under `outputs/deploy-20261109/`, notably the immutable
config/journal, activation/postflight gates, `qa-v3-t2/`, browser/Excel readbacks,
owner records and cleanup. Key SHA256 values:

| Evidence | SHA256 |
| --- | --- |
| Paired machine failure | `0d3f78e8f44b24e258e3fe72d2bb62d9455f3c14717c0908adf43cc3d636e229` |
| Owner paired exception | `f585f42990d37d9da9030ffe69327c6b188f46d8161b7002f2f8ee773cbb17e8` |
| Owner-accepted paired aggregate | `bd7903c99c135db717821ab09876b4337b194e7178cfe30daf3c86544853e9cf` |
| Public machine pass | `2a4582b32dc1e93b0eea36b96318eca0702952979061fd5fafd7d23987eb294b` |
| Public aggregate | `1d94fa5695c1b35d65ea6af2367f17a8befdb4fde6c68326b6034d13e65cc83e` |
| Post-browser integrity | `b3999699205dbbf69afc283c57561dbdb819bbf362b02b232fda9680930cf23b` |
| Postflight gate | `39289cf9518d6921f54c2593adc156fa1b33d7f9f0236bdec9336975915c8711` |

Gmail confirmed SENT to the authenticated owner's own account, message/thread
`1a1bed7d865cbaf4`, with **all 16 screenshots**: original 12 isolated workflow
screens, two final polished report/Excel screens and two actual public screens.
The email labels test-data provenance and the live packaging-save limitation.
