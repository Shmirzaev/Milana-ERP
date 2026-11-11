# Invoice and shipment report polish — 11 November 2026

Owner scope: preserve the existing shipment invoice and report. Apply 10px
type to the marked product/totals/signature region; retain the current row
height (owner reply). Standardize invoice sizes in print and Excel without
changing size identities, quantities, snapshots or financial posting. Verify
the existing model/customer search and add daily/monthly shortcuts to the
existing report. Include the pre-existing sewing receiving Load more fix.
Owner authorizes implementation and deployment from
`codex/sewing-receive-load-more-20261111`, explicitly waiving the 30-minute
observation only. Required immediate release gates remain.

Worktree: `C:\ERP\.codex-work\sewing-receive-load-more-20261111`.
Starting task commit: `070c242c9929ecb462e33eea6761bc59a0803083`.
Verified shared integration base: `3053788f2e17bd5585bccf8cd4547a62cc297516`.
Both production hosts: `20261111_052632`, source manifest
`55d0edc9b7893df95987102cc6d9ccbe5b59a89f3c369eb5ea1f46a9868d4520`,
runtime source `519c9fa36f3d90905f935caf08fe781417cf7e24`.
The legacy checkout and stale origin/main are preserved; the requested existing
task worktree follows the current owner-confirmed clone_main integration line.

Domain ownership: Fulfillment engineer Mirshoir, reviewer Ismail; Shavkat
supplies business acceptance. Implementation: root Codex agent. Independent
AI review is required and will be recorded separately, without claiming either
human's review.

Read path: existing shipment invoice routes -> shipment_review_service frozen
document projection -> shipment_invoice_service / shipment_invoice_excel_service.
Existing warehouse report routes -> fulfillment/shipment_report_service ->
ShipmentReportQuery/Out -> warehouse-stock/shipments page and XLSX. Tables read
include Shipment, ShipmentPackage, Package and retained document identities;
no persistence, permission, vocabulary, state or schema change is introduced.
The existing free-form size labels remain data, not new enums. Financial invoice
writes, stock movements, production handoffs and all unrelated operations retain
their existing owners and behavior. No business data is authorized for creation.

Acceptance: numeric and letter labels use `size × quantity`, sorted naturally;
aggregate size lists use `(size, size) × total` without inventing a per-size split.
Keep colors distinct, unknown labels explicit, text escaped/literal and source
documents unchanged. Print and Excel share the same formatter; 10px equals
7.5pt in Excel. Preserve the current 23.1pt body-row minimum and existing paper
layout, metadata, price visibility, totals and signatures.

Daily/monthly shortcuts select the current Tashkent day/calendar month,
preserve the entered model/customer search, reset pagination and use the same
applied dates for listing, totals and export. Custom historical ranges remain.
Existing model/customer lookup must pass actual API/browser checks.

Verification to record: baseline defect reproduction; invoice formatting and
read-only endpoint regressions, warehouse report boundary/search/export tests,
sewing pagination/handoff regressions, strict TS/lint/build, real connected-browser
invoice/report and Load more QA, independent AI review, exact-source CI/images,
production preflight/backup/candidate QA/parity and immediate postflight. No new
database constraint or transaction behavior means no new migration-specific
test is needed; required existing PostgreSQL CI gates remain.

## Evidence so far

- Baseline reproduction: 13 failures and one pass in the new formatting suite,
  demonstrating unspaced/unsorted sizes, missing aggregate counts and old type.
  The first attempt used an interpreter without PyJWT; the actual reproduction
  used `C:\ERP\.venv\Scripts\python.exe` with `PYTHONPATH=backend`.
- Combined invoice/report/sewing regression: 176 passed in 58.93 seconds.
  Final invoice regression after the whitespace/width correction: 73 passed.
  Existing dependency and disposable test-key warnings remain.
- Date boundary tests passed for Tashkent midnight, year rollover, February and
  leap years. Scoped ESLint, strict TypeScript, Ruff and diff checks passed.
- All frontend build contracts and the optimized local production
  build passed with webpack. The default local Turbopack build cannot resolve
  this worktree's shared node_modules junction; subsequent hermetic exact-source
  CI passed with the default builder. No dependency/config workaround was committed.
- Independent review `/root/review_invoice_report` found and verified the fix
  for whitespace-only sizes; follow-up review passed 49 tests and reported no
  remaining actionable finding. Width allocation now accounts for 10px/7.5pt
  instead of the former 9pt; other column widths and row minimum are retained.
- The initial indefinite preview command was rejected by automatic approval.
  A bounded owned preview with guaranteed cleanup subsequently passed both real
  browser suites, and connected Edge verified invoice/report and Sewing behavior.
  Credentials from the owner's supplied document enabled normal sudo access;
  they remained in memory and were never committed or printed.
- Exact-source CI passed: 6,756 backend cases, 1,589 reported skips and 36 subtests;
  649 mandatory PostgreSQL cases, 17 supplements and 84 shared contracts;
  frontend lint/strict types/default production build and scanned image publication.
- Exact staged production-image browser checks passed for existing shipment 282:
  10px text, 30.796875px retained row height, no clipping, six EN/RU/UZ price-on/off
  XLSX files with 7.5pt type and 23.1pt rows, unchanged source document and totals.
  Today returned 516 PJ1263 pieces; November returned 996. Connected Edge confirmed
  both shortcuts preserve the search and dates. Listing/export boundaries match.
- Actual MIL Sewing pagination reached 20/40/60/80/81 rows without duplicates.
  Connected Edge confirmed 20 -> 40. A MIL session correctly remains forbidden
  from requesting BST/ECO; disposable full-handoff tests cover all three factories.
- Staged 550 paired GETs passed complete frozen facts and all latency/payload
  limits. Public 280 GETs preserved facts, medians and payloads, but Cutting-passport
  p95 rose 150.85 -> 186.97ms (+23.94%; limit15%). No timing retry was made.
- Candidate 20261111_115200 was rolled back. The owner explicitly chose to keep
  green20261111_052632. Original blue20261110_135430 standby was restored and both
  hosts passed fresh health/runtime checks. No task-initiated business-data writes
  or schema changes occurred.
  Timed observation was explicitly waived; no observer or substitute monitor ran.

Status: implementation, automated/visual checks and independent AI review passed;
**AI_VERIFIED_AWAITING_HUMAN**, with human business acceptance unrecorded.
Deployment was attempted and rolled back for the performance gate. The owner
chose the previous release. Changes are pushed on the requested task branch,
not merged into clone_main/main and not currently live. See the
[complete release record](archive/INVOICE_SEWING_RELEASE_20261111.md).
