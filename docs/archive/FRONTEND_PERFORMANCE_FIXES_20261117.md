# Frontend performance fixes — 17 November 2026

Owner requested incremental fixes, local-copy tests, independent review, then a
commit on `clone_main`. Six Terra low-reasoning workers handled four isolated
operations, runtime setup and independent review; root integrated the result.
Human domain ownership/review labels remain Mirshoir/Ismail, with Dilmurod
coordinating shared frontend infrastructure. No human acceptance is invented.

## Changes

- Scanner: legacy candidate fallback only for actual API 404; stop other errors,
  preserve decisive error and remove duplicate final barcode lookup. Writes and
  uncertain-write/idempotency behavior are unchanged.
- Cutting: load editor directories on demand, debounce search 300 ms and share
  the applied list/dashboard/export filter. Preserve deep-link initialization,
  edited fields and stale-result guards; lazy images. Keep the existing list cap.
  Browser testing reproduced a material-row transition changing entered pieces
  from 731 to 600. Single-material defaults now preserve edits. Multiple material
  rows require confirmation before replacement; Cancel retains the draft and
  blocks save until bindings are reviewed. No quantity-distribution rule changed.
- Packaging: add typed GET `/api/packaging/reports/page` with bounded pagination,
  SQL aggregation, selected-page details, stable row keys and full-range totals.
  Fetch active tab and append pages. Preserve legacy report, complete three-sheet
  XLSX, dates, grouping, natural order, null meanings, authorization and caps.
  Exclude unset response-model defaults while retaining explicit null values.
- Employee QR: unmount collapsed badge preview; prepare captured print rows,
  deduplicate encoding and await all images. Shared lock protects work/employee
  print overlap. Issued-label identity/history is unchanged.

Existing Next.js, React and SWR dependencies/lockfiles remain. No Redux migration,
schema migration, production setting or business formula change is included.

## Actual verification

Tests ran on the owner's Windows computer using a new owned PostgreSQL 17
database restored from the preserved October 22 archive, migrated from 0148 to
0157. The master archive is unchanged; this is not a current production snapshot.
Outbound integrations/network were blocked. Browser business writes were blocked.
Synthetic employee and pagination fixtures were added only to the owned copy.

- Full frontend build and generated Next-types TypeScript check pass.
- Five-command Cutting suite, full registered QR pipeline, scanner regression,
  locale check and independent source/test reviews pass.
- Thirteen focused Packaging route/auth/export/serialization tests pass. Separate
  PostgreSQL parity covers more than 100 groups, caps and first-packed ordering.
- Real HTTP report facts/order/full summaries match the legacy report. Mounted
  UI appends 100 to 111 rows without changing full totals; dates reset the list.
  Browser-downloaded workbook has all 51/6/10 October rows, matching ordered
  values, formulas and blank totals across the three sheets.
- Mounted scanner error/fallback/recovery, Cutting request counts and delayed
  defaults pass. Real multi-material confirmation/cancel/save guard passes in
  EN/RU/UZ. Desktop and phone screenshots were inspected.
- Four actual 60 x 40 mm QR labels rendered by Chromium decode correctly,
  preserving leading zeros, fallback numbers, copies and order. Mounted image
  failure/retry, both print-overlap orders and client-navigation cancellation
  pass with controlled readiness/print boundaries.

Local diagnostics used five excluded warmups and 40 samples per route/cohort,
one serial loopback client and alternating order. In the restored October cohort,
legacy full-report P95 was 385.74 ms; new daily/entries/completed P95 was
20.17/138.93/44.56 ms. New daily payload was 944 bytes versus legacy 26,641.
For 111 synthetic groups, entries P95 was 35.69 ms versus legacy 44.93 ms.
Different response contracts and shared-laptop activity limit this comparison.
These results do not waive the production P95 15% regression gate or establish
an overall 80% speedup or resolution of production pool exhaustion.

## Integration and remaining gates

The reviewed application started at `4d7cf17e55b165b1edc05407065f92597cebdbe5`.
Before committing, current `clone_main` was fetched at
`c0e32e9`; its twelve newer commits change deployment tooling/docs/CI, with
application bytes unchanged. The fixes were applied in a separate `clone_main`
worktree. The CI merge preserves new automatic-release jobs and adds the focused
PostgreSQL test to the existing PostgreSQL-enabled step. Two test files received
only trailing-blank-line cleanup during staging.

Native print-dialog cancellation remains **BLOCKED**: a real Edge preview opened,
but Cancel automation could not reliably complete. Only the exact owned stalled
browser/driver tree was closed; no Print/Save action was sent. PDF/rendered and
mounted-handler checks do not certify the OS dialog or a physical printer.
Some source images are missing in the local runtime, so full thumbnail/workbook
image parity is unverified. Full `AI_VERIFIED_AWAITING_HUMAN` is not claimed.

The owner subsequently authorized normal remote `clone_main` pushes. A direct
`clone_main` push runs CI; `scripts/release_ci_identity.py` selects automatic
release builds only for `codex/**` pushes when the repository flag is enabled.
An already prepared exact tree can be promoted after integration only after both
host approvals pass. Source publication does not approve deployment. No direct
production access, activation or approval-file creation is included here.

Hosted CI on the initial `81f3654` commit caught two Cutting ref assignments during
render that the earlier local build/type checks did not cover. The follow-up
synchronizes those refs in layout effects after committed state changes, as
required by [React's ref rules](https://react.dev/reference/react/useRef).
Full frontend lint then passed with zero errors
and fourteen existing warnings; existing lint rules were not disabled. Full build,
generated types and the actual delayed-default/confirmation browser scenarios
pass again on the corrected source, including the two-material EN/RU/UZ cases.

A later hosted browser step exposed a partial-section fixture missing the new
`printAttemptActive` state. The fixture now supplies that dependency and reports
initial render errors promptly instead of hiding them behind a selector timeout.
All existing batch/size/print/delete assertions and EN/RU/UZ cases remain. The
exact repaired test and all seventeen existing CI browser commands pass locally;
no quarantine, test skip or timeout increase was introduced.

Detailed local evidence is retained in the workspace under
`outputs/milana-fe-fixes-20261117/REPORT-FINAL.md`, its JSON manifests/results,
screenshots and private runtime logs. Credentials and copied business rows are
excluded from this commit. QA master must complete release checks before deploy.
