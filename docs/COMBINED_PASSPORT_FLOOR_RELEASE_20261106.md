# Combined Cutting/passport/fabric release — 6 November 2026

User explicitly authorized deploying today's three passport fixes together with
yesterday's seven fixes: search icon padding, reason-required Cutting rejection,
blank Planning piece defaults, model/variant shipment package identities,
Milana-style Eco fabric inventory, GEM/GEMX Qolip attachments, and one shared
100 + 200 = 300 kg passport calculation. Use connected Edge visual QA. The user
explicitly waived the 30-minute timed observation; do not start a substitute
timed monitor. All immediate health, backup, source/image, migration, QA and
performance gates remain required.

Clean dedicated worktree: `C:/ERP/.codex-work/deploy-passport-floor-20261106`.
Branch: `codex/deploy-passport-floor-20261106`. Both sources descend from exact
live `488f3d654` / release `20261105_065721`, manifest
`e6c603d4c1954c64a75962cf189427eb5e316c039ea23de4699b9bd4f3112095`.
Backend and frontend pointers were freshly reverified; baseline matches.
Today's parent is `4ed5063c4`; yesterday's parent is `ca022ca0f` (including
`ac3d6e041` and `88f1d06c6`). No unrelated clone_main runtime work is included.

Root Codex integrates and deploys; independent `passport_review` reviews the
combined operations. `ect_fabric` owns the narrowly assigned grouped-transfer
integration and tests, and `qa_environment` owns isolated QA infrastructure and
fixtures. Human engineering owners remain Mirshoir/Ismail by domain. This request
supersedes the earlier no-deployment instruction for these exact changes.

## Integration and acceptance

- Count pieces per logical saved material row, never per batch allocation.
  Two old parents/four 600-piece rows total 2,400. One 600-piece calculation
  allocated 100/200 kg remains 600 pieces, one set of rolls and 300 kg.
- Keep both Excel model/variant pictures and precise source allocation labels.
- Mapped ECT transfers use authoritative Eco physical balances for each grouped
  source, including depleted/archived Milana source identities. No guessed ID
  mapping, second Milana debit, QC bypass or cross-factory access.
- Preserve used grouped calculations and permit notes-only changes without
  treating exhausted archived stock as newly available for another cut.
- Rejection must require/save reason and refuse existing execution or stale
  mutation attempts. Plans, reservations and downstream facts remain preserved.
- CAD files remain opaque authenticated attachments, not image previews. All
  layout/identity/default changes preserve established business operations.

## Gates and release state

**Live on both application hosts:** green `20261106_061725`, exact runtime
`a8579e64efbb2f9545d6df1c35d527c1d4ae2f01`. Backend and frontend were activated
separately, in that order, on 6 November at approximately 07:20 UTC. Four closing
health checks, strict startup/log/router checks and public performance passed.
Database remains `0154_eco_receipt_details`, with zero invalid indexes and
20/100 connections at closing readback. Both owned deployment leases were
released. No timed observation or substitute monitor was run.

All ten requested changes are included. Historical passport reporting is corrected
without rewriting parent pieces, Nastil, Cutting records, bundles or stock.
The actual immutable candidate and public Edge both show PO-0749=1,200 and
PO-0750=1,200: **2,400 pieces total**. Actual candidate Excel exports each contain
two summary pictures and four detail pictures, with no external relationships.
ECT's existing order 482 picker sees central source 1883/5A through its authoritative
Eco receipts, with 151.8 kg available at the signed readback. No production business
rows were created or edited for QA; existing passport JSON and source/receipt
facts remained identical across the bounded signed probes.

## Immutable source and reconciliation

- Worktree: `C:/ERP/.codex-work/deploy-passport-floor-20261106`.
- Branch: `codex/deploy-passport-floor-20261106`; pushed, unmerged. Shared-source
  integration is deferred under the owner's approved exact-production-baseline
  workflow. The dirty legacy `C:/ERP` checkout was preserved.
- [Exact CI run 42173510387](https://github.com/Shmirzaev/Milana-ERP/actions/runs/42173510387)
  completed successfully for the exact runtime commit; backend/frontend/release
  jobs all succeeded. Separate refactor gate 42173499663 also succeeded.
- All 1,934 source manifest entries match Git. Manifest:
  `7f52cf7bf61e6fa4159d65e590d9cefaa6a493992e8b80197343490e5ee09fb0`.
- Source archive 4,790,757 bytes, SHA256
  `5000f63db3979695477ccea65e17b38611764279636c92cf13e409a5f375e2ce`.
- Backend: `ghcr.io/shmirzaev/milana-erp-backend@sha256:062705da07f171976b5a15511bb1e42e09296cf3a21181c73bf2a706b4cc6d4e`.
- Frontend: `ghcr.io/shmirzaev/milana-erp-frontend@sha256:dfbb09a90d4dcca861f8b5dedf1fde792ce0ebba8967eef306c58595e70e5859`.

Immediately before activation, fresh `origin/main` was
`1a067b01fe741025f0d9c8bf644bd417fbca144c` and `origin/clone_main` was
`58d5aff8d392c05126c63a6a8b342665a97268f8`. The newer People/Payroll changes
had no overlap with this reviewed release and remain excluded. No shared branch
was merged, reset or overwritten. Both activation phases fetched and checked
the exact reviewed refs again.

## Tests and actual browser scope

The full backend CI suite passed 5,245 cases with 644 skips. These skips are not
represented as passes: separate required real-PostgreSQL P2/combined/Ismail gates
passed 180/23/176 cases respectively, without skips. Frontend lint, strict type
checking, build, contracts and browser regressions passed. Independent exact P2
review passed 180 cases; focused local callers passed 225. The real per-row ECT
lookup exposed by the earlier failed P2 run was repaired through bounded balance
queries; the original MIL 17-SELECT contract was retained. Earlier failed CI and
fixture/type corrections remain recorded in the ignored release evidence.

Connected **Microsoft Edge** verified all ten flows against isolated combined QA,
including rejection reason/stale guards, blank Planning pieces, shipment model/
variant identities, Eco layout, GEM/GEMX browser uploads and the 300 kg grouped
save/reopen. After the final lookup repair, actual ECT 5A and 100 + 200 kg notes
saves/reopens were repeated, and PostgreSQL readback proved unchanged stocks,
600-piece single grouped output and zero Cutting records for those QA orders.
The final frontend tree is byte-identical to the earlier combined visual source.

After cutover, root reloaded the public site in Edge with the user's existing
session and separately searched both affected orders. Each visibly shows 1,200;
console error collection was empty. Public date inputs remained blank after the
automation's attempted fill, so no public date-input interaction pass is claimed;
the separate immutable signed API checks used and verified exact November 5
filters. Production business forms were not submitted.

Limits retained: local extension-injected hydration warnings were observed;
the browser GEM-download helper timed out and the combined Excel browser-download
file event was not observed. Authenticated API byte/workbook checks passed;
those browser downloads are not claimed as passes. Internal Edge Downloads
inspection was policy-blocked, with no workaround. Synthetic CAD fixtures verify
transport, not opening in genuine Gemini software. Human factory/operator
acceptance remains pending, and the bug stays in the active tracker.

## Backup, performance and operational rollback

Fresh PostgreSQL custom backup:
`/app/storage/.milana-backup-archive/milana_erp_pre_20261106_061725_20261106_065602.dump`.
It is 113,383,511 bytes, mode 0600, SHA256
`e2f9d3ffa7f619ac4e66302b5313a0e2020cc501fce9e25e281d2859582a8a49`;
its restore list validates 1,329 objects. No new migration was added; the approved
upgrade to 0154 was a no-op. To satisfy disk gates, 168 older nonempty backups were
relocated by verified SHA/fsync copy to the storage disk and original paths became
symlinks; the newest ten and November backups were protected. No garment data
changed during that operation; evidence is retained separately.

Fixed-identity paired samples preserved identical rows and payloads across all
five search/inventory endpoints. Stage median changes were between -5.95% and
-1.46%, with maximum p95 increase 7.71%. Closing public comparison also passed:
maximum median increase 0.08%, maximum p95 increase 10.49%, zero payload growth.
All sampled responses were 200. No 10% median/15% p95/15% payload threshold was relaxed.

Compatible read-only rollback is retained on **blue 20261106_054000**, source
`bf9cb9f0e738e82b9a21909b22e4cdecae7bed37`, with successful immutable
CI run 42169647700. Backend digest is
`ghcr.io/shmirzaev/milana-erp-backend@sha256:70bf3c6e842b22304ec2ef53d0f0f7a58d90244c69358cec6207e47fb1313304`;
frontend digest is
`ghcr.io/shmirzaev/milana-erp-frontend@sha256:4b600686df75ad94ba8cbe26611c5a25ff414cf6cf15ae2e3141d66d3fabe0c6`.
The old writable 488 backend is not a safe fallback after grouped/Eco/rejection
facts. Historical source/images remain preserved; active releases were never
edited in place and no VM dependency installation or build occurred.

The production-mode rehearsal found that business storage read-only also blocked
SQLite security counters. A separately reviewed operational supplement keeps
business storage and PostgreSQL read-only, seed/sync disabled and two workers,
while mounting only a private counter directory writable. SQLite online backup
from a canonical `mode=ro` source preserves WAL rows, locks, expiry and namespace.
The exact-image production-mode rehearsal proves seeded/new login locks, rate
limits shared by both workers, normal reads, blocked writes and 13 unchanged
business tables/files. A path guard initially aborted on POSIX double-leading
slashes before any remote mutation; an actual Linux regression verifies the
canonical correction. Both failed attempts and original frozen helpers/configs
are preserved, with explicit supplemental evidence lineage. The successful
production isolated probe passed signed `/auth/me`/passport reads, SQL read-only
settings and 503 write guards, then was removed by exact owned identity.

The retained blue counter store is a rehearsal snapshot, **not an activation-time
authentication snapshot**. Before emergency recovery, quiesce green and refresh
the authoritative security state through a separately reviewed recovery helper;
do not invoke the old direct `activate-readonly-backend` action or reuse a stale
counter clone. The reviewed retention wrapper has no activation capability.
The durable [recovery restriction](archive/passport-floor-release-2026-11-06/READONLY_RECOVERY.md)
preserves the reviewed recipe and the stopped-green/expected503 limitations;
the original reviewed runbook remains in ignored release evidence.
No incident recovery activation or automatic fallback is claimed.

## Evidence pointers and handoff

All paths below are under the dedicated worktree, retained locally in ignored
`outputs/` with hashes and preserved failed attempts. No owner token/env value is
included in this document.

- `outputs/release/feature-20261106_061725-evidence.json`: stage, backup,
  migration, signed compatibility, performance, activations, retained rollback
  and passed closing checks.
- `candidate-signed-qa.json`: SHA256
  `eda0c1a6aaeedfd3fc113f0f1ef4714ad6035280d93dfe287a155839d8aaeab4`;
  `compat-signed-qa.json`:
  `8b28429bfe21b918c9cc4ae1beab8e037edc12bcebbcf8b99703402503fb2776`.
- `candidate-browser-gate.json`: local Edge plus distinct actual immutable API
  evidence, SHA256 `a7963f7b377138914a9a6527f41670b38b481615d4c697fbdfe4212d98a04223`.
  Its pre-activation journal snapshot is preserved byte-for-byte separately.
- `normal-public-edge-gate.json`: actual public Edge observations, SHA256
  `16713ed77d01675adaf0c719ef00919cc04fc5b84d718cc0ea32bb262285b398`.
- Preserved activation config 0638d543 and postflight config 8cf25a89 differ only
  by the actual public-browser gate; stage config 4d88c17c remains unchanged.
- Independent source, operations, exact CI, counter v3/retention, concrete
  activation and postflight-input reviews remain separate evidence files.
- `outputs/qa/production-after-po0749.png`, `production-after-po0750.png` and
  corresponding DOM/console records prove the actual live views.
- Owned local API 8197/frontend 3097 and QA PostgreSQL container 15449 were stopped
  after release verification; QA artifacts/data were preserved.

This documentation commit follows the deployed application commit; it does not
change or retag the immutable runtime. Human production acceptance and shared
integration remain open. Detailed source evidence also remains in the three
yesterday packets and `PASSPORT_TOTALS_ECT_20261106.md`.
