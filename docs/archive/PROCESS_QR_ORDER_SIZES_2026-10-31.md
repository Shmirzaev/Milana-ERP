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

Status: **AI_VERIFIED_AWAITING_HUMAN** for this frontend-only operation.
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

No production data or releases changed. No push, merge or deployment is authorized
by this task. The production fix still requires the reviewed release workflow;
latest `clone_main` contains other unreleased work, so it must not be deployed
wholesale as this one-line runtime correction.
