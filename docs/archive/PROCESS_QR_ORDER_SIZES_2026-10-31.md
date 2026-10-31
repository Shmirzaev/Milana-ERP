# Process QR uses production-order sizes (31 October 2026)

## Scope and source

- User: fix PO-0495 showing six Process QR sizes while its order has five.
  The user explicitly authorized `clone_main` as the base after the initial
  `origin/main` baseline mismatch was reported.
- Operation: ERP Process QR label-size suggestion, owned by Payroll engineer
  Dilmurod, human reviewer Mirshoir. Codex implements this isolated correction;
  these ownership names do not assert either person's approval.
- Worktree: `C:\ERP\.codex-work\process-qr-order-sizes-20261031`.
  Branch: `codex/process-qr-order-sizes-20261031`.
  Base: `origin/clone_main` at `5bffd255`; no legacy-checkout changes were copied.
- Verified active backend/frontend release: `20261029_111113`, runtime commit
  `1344b572f8bff6f458892d3c2c8022560f306dbb`, manifest
  `93d632752aa355efad66fc67bf294fa6eb6321e90769106fc5de71c4cb6b7720`.
  Both complete production manifests passed verification. The fetched
  `clone_main` production-base record agrees; stale `origin/main` does not.

## Behavior and operation trace

`GET /api/process-tracking?sewing_completed_only=true` supplies production-order
sizes from order items and recorded sewing-size evidence, plus exact batch
sewing quantities. Process QR also loads the selected model's available sizes.
Its `erpSizeAllocations` callback previously preferred that model list when
proposing quantities for sewing output without a size breakdown.

PO-0495 has order/bundle sizes 46, 48, 50, 52 and 54. Its model also offers 56.
The saved Nastil 1 sewing output is 250 with no per-size breakdown. Loading the
model therefore incorrectly proposed 42/42/42/42/41/41 across six sizes.

The callback now prefers the existing production-order size list, falling back
to model/family sizes only if order sizes are unavailable. Batch-recorded size
quantities remain authoritative. PO-0495 proposes five quantities of 50 and no
size 56. EN/RU/UZ explanatory copy now says order sizes. No layout was changed.

The same allocation feeds size inputs, candidate labels and the unchanged
`POST /api/payroll/qr-labels/issue` payload. Existing invalid-total and previously
issued-label conflict guards remain. Manual-order sizing is unchanged. Sizes
remain configurable strings; no vocabulary, enum, DTO, API, permission,
transaction, schema-owned persistence, migration or payroll-rate change is needed.

## Verification

- The new assertion executes the actual page callback and failed against old
  code with the exact six-size 42/41 result; it passes with the corrected code.
- Focused suite covers delayed model loading, order/model/family fallback,
  authoritative recorded sizes, manual isolation, drafts, conflict guards,
  preview-to-issuance payloads and 1,001 bounded conservation cases.
- The actual React/SWR page browser fixture uses a six-size model and five-size
  order. It exercises invalid totals, edits across batches, exact fixture issuance,
  issued conflicts, EN/RU/UZ mobile layouts, recorded read-only sizes, and three
  reloads of a 250-piece batch. All writes go only to disposable in-memory HTTP
  fixtures; there is no ERP or PostgreSQL connection.
- Connected Chrome visual check of the same page in Uzbek confirmed PO-0495,
  Nastil 1, five inputs of 50, total 250, no size 56; 249 blocks issuance. Restoring
  250 and issuing created exactly five fixture labels, each 50, across sizes
  46–54. Refresh retained all five saved fixture labels and zero unissued labels.
  Connected Chrome captured zero warning/error logs.
- Strict TypeScript and targeted ESLint passed. All build prerequisite contract
  suites passed. An initial Next build refused a missing API environment; the
  optimized build passed with local-only `API_URL=http://127.0.0.1:8000`.
- Independent review `/root/review_qr_size_fix` found no actionable defects in
  both the initial and final expanded diff and independently passed the focused
  test and whitespace check. The final browser, localization and optimized build
  checks were repeated after the locale/test edits and passed.
- Screenshots are under ignored `outputs/size-allocation-qa/`, including
  `connected-uz-five-sizes.png` and EN/RU/UZ browser fixtures.

## Acceptance and handoff

Status: **FIX VERIFIED; DEPLOYMENT ROLLED BACK AT PUBLIC PERFORMANCE GATE**. Owner decision on a measured latency exception is pending.
Backend/PostgreSQL write, locking and migration tests are not applicable: no
backend, API, data model or production data was changed. UI issuance evidence
uses disposable in-memory fixture storage, not a real payroll transaction.

Commands from `frontend/`: `npm ci --legacy-peer-deps --no-audit --no-fund`,
`node scripts/test-process-qr-size-allocation.mjs`,
`node scripts/test-process-qr-size-allocation.browser.mjs`,
`npm run check:i18n`, `npm run typecheck:strict`, targeted ESLint for the changed
page/scripts, all `npm run build` prerequisites, and
`API_URL=http://127.0.0.1:8000 npx next build` (PowerShell environment equivalent).
The optimized build generated all 98 routes. No production API was used for
build or fixture tests. `git diff --check` passed.

Human acceptance is pending. In the isolated candidate, select PO-0495 / Nastil 1;
verify 46/48/50/52/54 each show 50 and no 56 appears after model load/refresh.
Check that total 249 refuses issuance and restored total 250 permits it. Check
manual orders and a batch with explicitly recorded size output still retain
their existing behavior. Never issue production labels just to perform QA.

The owner subsequently instructed: "deploy without 30 minute monitoring".
This authorizes the release and explicitly waives only the timed observation;
source reconciliation, CI, backup, candidate QA/performance and immediate
postflight remain required.

Release worktree: `C:\ERP\.codex-work\process-qr-order-sizes-release-20261031`,
branch `codex/process-qr-order-sizes-release-20261031`, based on exact active
runtime `1344b572f8bff6f458892d3c2c8022560f306dbb`. The seven reviewed frontend,
test and localization paths are byte-identical to implementation commit
`c4ee4164`; the baseline metadata is refreshed from verified `clone_main`.
Candidate release: `20261031_092951`. Production remains `20261029_111113` until
activation passes. Other unreleased `clone_main` work is excluded. No business
data edit, schema migration or 30-minute observation is part of this deployment.


## Production attempt and verified rollback

The [complete machine-readable release record](PROCESS_QR_ORDER_SIZES_RELEASE_2026-10-31.json)
records source/image hashes, CI, backup/revision, performance summaries, controller
reconciliation, business fingerprints, cleanup archives and rollback checks.

Release `20261031_092951`, exact runtime `337ff3c01bb4778232dad9973d7c996396717e14`,
descends directly from active `1344b572`. Both immutable images were pinned to
the digests published by [CI run 41188970667](https://github.com/Shmirzaev/Milana-ERP/actions/runs/41188970667).
Core CI: 4,874 passed, 544 opt-in skips; required PostgreSQL suites passed 165
and 176 cases, with remaining required Purchasing/Sales/Forecast/frontend checks passing.
No backend, API, permission, migration or unrelated pending `clone_main` change was deployed.

Fresh custom dump `/opt/milana-erp/shared/backups/milana_erp_pre_20261031_092951_20261031_100144.dump`
is 104,041,731 bytes, mode 0600, SHA-256
`d6efd68fb6a9dcb4a6c969caa7030262ea9f1f032c3c486c2f9db5203ee1070a`.
Successful restore listing has 1,246 objects, 89,402 bytes and SHA-256
`022410decbeda95efda4d92537f243d79a933f03cc0c439a215983504374d58f`.
Single candidate Alembic head, no-op upgrade/current and live database agree on
`0149_besttex_cutting_access`; no business data/schema migration was performed.

Candidate and initial public blue browser checks showed 46/48/50/52/54 at 50 each,
total 250, no 56, after full reload and model loading. An invalid 249 total was
guarded and restoring 250 cleared the message. No labels or Save-to-model request
were submitted. The temporary authenticated candidate proxy was GET/HEAD only,
kept its JWT server-side and was stopped after QA. Browser warning/error counts
were zero. Ten table hashes for this order match before/after, with zero issued labels.
All four immediate health checks, source/slot/image identities, HAProxy service/config,
two workers, zero restarts/OOM, clean logs, database headroom and both-slot readiness passed.

The paired six-endpoint benchmark passed with 120 samples per slot and fixed
queries/client. The closing public comparison used the same origin/client,
five warmups and 120 measured samples, with stable row counts and successful 200 responses:

| Endpoint | Median change | p95 change | Result |
| --- | ---: | ---: | --- |
| global_search | -1.92% | -7.16% | PASS |
| inventory_batches | -1.17% | -2.18% | PASS |
| inventory_stock | -0.12% | +20.33% | FAIL: p95 |
| model_groups | -2.77% | -0.10% | PASS |
| model_options | -0.30% | -0.77% | PASS |
| process_qr | -0.02% | +1.38% | PASS |

Inventory Stock p95 was **178.73 ms versus 148.53 ms (+20.33%)**. The +15% ceiling
was 170.81 ms. Median was 140.50 versus 140.67 ms, rows remained 50 and response
size grew by 2 bytes. This does not cancel the p95 failure or prove its cause.
Independent review confirmed the nearest-rank calculation/method. Raw individual
latencies were not persisted, so causal/outlier reanalysis is unavailable.
The failed comparison is retained; it was not resampled or marked passed.

Both roles were restored, backend first, to **green 20261029_111113** with the
original runtime/source manifest/container IDs/images. All four health checks
passed after rollback. Database remains 0149 with 40/100 connections and zero
invalid indexes. Blue 20261031_092951 remains running but inactive. The public
QR page was refreshed and confirmed the original six-size behavior after rollback.
The user's deployment request remains open pending the explicit decision to
accept this measured latency exception or leave the previous release active.

The original owner instruction “deploy without 30 minute monitoring” waived only
timed observation. No 10- or 30-minute monitor or automation was run. It does not
waive the separate public performance gate in DEPLOYMENT.md.

### Reviewed controller and verification-helper corrections

Initial preparation stopped at an extra controller equality guard. The installed
controller SHA-256 is `d422ff74b96c92115c3c657a02a1732925df5a3565f81b3f3a00bf0e9a5394a1`;
the immutable release controller is `13a9e19d5b266c87d138cb2866a185fedf45a089b85534d26fb28667eb95c3f3`.
Independent review confirmed differences are readiness `/health` versus `/ready`
and named worker/pool constants plus static connection-budget validation. The
installed version was preserved and hash checked on both hosts before staging,
activation and postflight. Explicit readiness GETs and safe inspection of only
allowed worker/pool values verified both slots use two workers and 8+4 pools,
with a 48/100 overlap ceiling. Extracted source was reused only after full expected
manifest, exact regular-file set and no-symlink/special-file checks; no overwrite occurred.

Independent helper review corrected image-tag use to successful-CI digest pins
and made recovery attempts independent by role. Fault injection proved failed
backend recovery does not prevent frontend restoration and retains the original
cutover error. An evidence assertion comparing object key order was corrected to
compare actual size/quantity fields. Initial postflight worker inspection required
the Docker-compatible PID column (`docker top ... -eo pid,args`); full postflight
then passed. These helper failures were retained and resolved, not waived.

### Approved legacy release cleanup

Only 20260812_115541, 20260812_121048 and 20260812_125958 were removed, after owner
approval and full tar content/metadata comparison preserving numeric ownership,
ACLs and xattrs. The archives barely compressed and were relocated to
`C:\ERP\.codex-work\release-archives\legacy-approved-20261031_092951`, with matching
local/remote SHA-256 verification before backend archive copies were removed.
Each archive's exact size/hash/path is in the JSON evidence. The local directory
is restricted to the current user, SYSTEM and Administrators. Server relocation
receipt: `/opt/milana-erp/shared/release-archives/legacy-relocated-20261031_092951.json`.
Backend cleanup disk use was 78.11%; both staging gates were below 80%. Active,
rollback, business files and database backups were preserved. Alert 70% remains.

Screenshots/operational evidence are under the release worktree's ignored
`outputs/deployment/`: public-before-six-sizes.png, candidate-five-sizes.png,
public-five-sizes.png (the initial blue attempt), public-after-rollback.png,
evidence.json and the original public baseline/closing summaries.

The implementation branch merges the reviewed release ancestry with current
clone_main for publication/review, without changing runtime application bytes
from c4ee4164. Shared clone_main merge is not claimed. The legacy checkout's
481 changes were preserved. Human operator/physical-label acceptance remains pending.
