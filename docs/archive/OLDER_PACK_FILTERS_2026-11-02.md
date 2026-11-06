# Older physical-pack history filters — 2 November 2026

Status: **AI_VERIFIED_AWAITING_HUMAN**. PR369 merged at `1ed3c5c7`; deployed green
`20261102_063110`, runtime `42078704`. Operator acceptance remains pending.
See [release evidence](OLDER_PACK_FILTERS_RELEASE_2026-11-02.md); candidate evidence below is historical.

## Direct scope and source

The owner asked how to find older physically added packs, then directed:
“do all fast, base is in clone_main” and “merge it to clone main then implement this filters”.
The accepted feature scope is Previous/Next pages; model, pack and PRN search;
date range; and received/awaiting receipt filtering. No business mutation was requested.

Worktree: `C:\ERP\.codex-work\older-pack-filters-20261102`.
Branch: `codex/older-pack-filters-20261102`.
Packaging engineer/reviewer: Mirshoir / Ismail; business acceptance: Shavkat/operators.
Actual implementer `/root`; independent reviewer `/root/review_merge`.

Fetched integration base `f9d96c07`; incoming deployed-fix evidence branch
`codex/process-qr-order-sizes-20261031` at `4e39d4fd`, containing exact runtime
`337ff3c01bb4778232dad9973d7c996396717e14`. The only merge conflict was independent
bug-tracker additions; both were retained. Reviewed merge `6e62ffd5` was pushed
to `clone_main` under the owner's explicit authorization. Both production source
manifests verified clean at `f270b044a9b67069e44e3954f671bd59f9456146afd13221584f12053c2a3a94`.
Active release remains blue `20261031_092951`; green `20261029_111113` is rollback.
The backend blue image revision independently confirmed `337ff3c0`.

## Operation and type ledger

Before: UI called the legacy endpoint without page parameters; backend returned
only the latest 100 non-retired runs. Backend already supported optional pagination.
After: the UI requests 50-row pages; all filters apply in SQL before count/offset/limit.
Filters combine with the existing warehouse/department visibility and production-order scope.
Model search accepts displayed `XJ…-V-6316` and stored `XJ…-6316`, including member
item models; pack/PRN/barcode searches are literal substrings with escaped wildcards.
Deleted members retained for accounting are excluded from search as from displayed contents.
Run retirement and corrupt-manifest checks are preserved. Date bounds and displayed
timestamps use Tashkent; naive legacy timestamps are interpreted as UTC.

Route binds typed inputs and delegates to `models/packaging/print_runs_service.py`.
New `PrintRunReceiptStatus` canonical query enum has only `pending` and `received`;
invalid receipt values produce 422. These are derived query categories, not stored
package statuses. Existing stored lifecycle/departments, JSON manifests, configurable
model/pack identifiers and payload serialization remain intentionally retained.
No schema, migration, permission, write operation or transaction ownership changed.
Legacy callers without `page` keep their list response and 100-row bound.

## Verification

- Meaningful red/green: before implementation the old endpoint ignored search,
  returning 105 instead of the uniquely expected old pack; combined receipt/date
  filtering returned 105 instead of 52. Both assertions pass after implementation.
- `C:/ERP/.venv/Scripts/python.exe -m pytest backend/app/tests/test_print_run_filters.py
  backend/app/tests/test_print_run_query_growth.py -q`: **24 passed**, independently repeated.
  Includes old packs beyond 100, literals, combined status/dates, Tashkent midnight,
  invalid inputs, retained deleted members, scope, 401/403 and legacy parity.
- Package workflow/manual dispatch/returns regressions: **37 passed**.
- Bounded read stress: ten filtered 105-run fixture requests; each returns 50 or fewer
  rows, at most five SELECTs per request and zero INSERT/UPDATE/DELETE statements.
- Actual candidate SQL executed through the backend against real PostgreSQL under
  `SET TRANSACTION READ ONLY`; `SHOW transaction_read_only` returned `on` for each case.
  PRN search total 368 / two requested rows; dated pack search total 53 / 50 rows;
  received model search empty; literal percent empty. No source file, container,
  runtime configuration, stored data or deployment was modified by these reads.
- Updated actual-component browser regression passed desktop/phone EN/RU/UZ,
  filter request values, rejected reversed dates with no fetch, reset, pagination
  and recovery when the last page disappears. Independent reviewer repeated it.
- Connected user Chrome inspected actual candidate React components/CSS with the
  actual API on a disposable local SQLite database through a GET-only loopback QA
  server: page 3 showed 101–105 of 105; old pack search returned one; combined model,
  both dates and received status returned 52; reversed date refused. RU/UZ labels
  and phone-width horizontal table scrolling inspected. Console warnings/errors: zero.
  Local screenshot: `outputs/filter-qa/uzbek-search.jpg` (not committed).
- Scoped ESLint, strict TypeScript, Ruff, Python compilation and diff whitespace
  checks passed. Every frontend build contract passed; the first Next invocation
  correctly refused an unset API URL. The optimized build then passed with explicit
  loopback `API_URL=http://127.0.0.1:8000`. No deployable release image was built.
- QR merge separately passed all six ordering scripts and actual-page browser tests.
  Independent AI review found/fixed pagination shrink and PostgreSQL JSON column
  alias issues, then reported no remaining actionable findings.

## Human checklist and next step

1. In the candidate, open Physical print runs. Use Next/Previous to reach an older
   known PRN; confirm its counts and labels remain correct.
2. Search that PRN, its pack number and its model/variant. Confirm the same matching
   group appears even when it was beyond the first 100 rows.
3. Apply a known Tashkent date range, then Received and Awaiting warehouse; verify
   totals, clear the filters and repeat on the warehouse phone/tablet in RU/UZ.
4. Record operator acceptance of the exact deployed release. The owner separately
   authorized merge and deployment; this does not substitute for factory acceptance.

Read-only history filtering adds no department write handoff. Existing creation,
receipt, labels, deletion and dispatch behavior is covered by the adjacent regressions;
no real package was created, received, deleted, reserved or shipped during this task.
The legacy dirty checkout was preserved. No secrets are included in this record.
