# Passport reporting and ECT fabric repair

Last updated: 2026-11-06. Local candidate; no deployment or production writes.

User scope: correct Cutting Passport dashboard pieces, including old orders;
embed model and variant pictures in passport Excel exports; fix ECT fabric
visibility and availability while completing passports.

The user authorized reconciliation against the live release after the required
drift stop. Both application hosts are on `20261105_065721`, manifest
`e6c603d4c1954c64a75962cf189427eb5e316c039ea23de4699b9bd4f3112095`.
All 1,905 manifest entries match Git `488f3d654b0669a9878b8efd3d34298994e9dc45`.
Database revision: `0154_eco_receipt_details`. Retained rollback source:
`20261105_043000`. No merge/deployment authorization is inferred.

Worktree: `C:\ERP\.codex-work\passport-totals-ect-20261106`.
Branch: `codex/passport-totals-ect-20261106`. Root Codex owns the shared files;
the `passport_review` agent performs independent review. `ect_fabric` traces the
isolated Eco stock integration, initially without shared-file writes. Domain
engineering ownership remains Mirshoir (Production) / Ismail (Inventory), with
their reciprocal technical review and Shavkat/operator business acceptance.

## Evidence and intended operations

- Read-only production SQL shows the four screenshot rows belong to passports
  800/801 for PO-0749/PO-0750. Each has two material rows of 600 pieces, while
  each parent stores only its first row's 600. The dashboard explicitly counts
  parents once. Expected displayed-row total is 2,400. Correct reporting from
  saved rows, including historical records, without rewriting business history,
  stock, Nastil quantities or confirmed production output.
- Excel currently streams literal cells without images. Preserve existing
  quantity columns and append distinct model/variant picture columns. Reuse
  family model and exact-variant image selection, safe uploaded bytes, and
  existing workbook image embedding; never fetch arbitrary image URLs.
- The user clarified that the unavailable fabric was batch `5A`, transferred
  from Milana. Live readback found two linked Eco receipts of 5 + 146.8 kg, both
  referencing central source batch 1883. The old passport path checked the
  depleted/archived Milana source instead of the 151.8 kg physically held in Eco.
  The correction follows only these authoritative source links, aggregates split
  receipts, enforces QC/reserved/available balances and never reuses Eco primary
  keys as central IDs. No direct, unlinked Eco receipt integration is claimed.

Reporting operations are read-only. No schema migration is introduced.
Model/variant/order/batch names remain configurable data. Existing kilogram/metre
units, booleans, permissions and factory rules are retained. Eco movement writes
use the existing canonical EcoMaterialMovementKind and schema-owned persistence
in the caller's transaction. The reversal reference identifies the original
consume movement; receive/reversal events preserve that original evidence.
Historical schema-owned write/refactor debt outside this operation is unchanged.

## Changed call paths and effects

- Dashboard: existing factory/date/search-scoped report query -> saved material
  row sums -> existing JSON metrics. Missing historical row quantities fall back
  to the parent once; explicit zero remains zero. This never credits downstream
  garments or rewrites old passports. Live read-only comparison: CUT 663 parents,
  65 affected, 307,880 -> 342,110 pieces; ECT 25 parents remain 8,126. The four
  screenshot rows are exactly 2,400. Values describe the readback snapshot.
- Excel: existing scoped report -> batched family/exact-variant image selection
  and selected binary projection -> streaming workbook. Model pictures are in
  M/N on Passports and AG/AH on Materials. Existing quantity and literal-text
  cells remain in place. WebP uploads normalize to PNG. External URLs remain
  literal text; no arbitrary network image request is made. A linked passport's
  own image remains the fallback when its model has no garment photo.
- Fabric lookup: `GET /cutting-passports/material-batches` requires cutting.records
  and the selected order's existing factory authorization. Its dedicated output
  DTO exposes fabric identity/metadata/balance, not inventory costs or permissions.
  ECT linked transfers overlay their central source identity; exhausted linked
  receipts cannot fall back to Milana stock. Legacy unlinked ECT stock is retained.
- Passport save: mapped Eco balances validate actual usage and additions; the
  existing production material identity stays central, without a second central
  reservation/debit. Saving alone still creates no CuttingRecord or stock debit.
- Cutting/deferred usage: existing outer transaction -> locked linked Eco receipts
  -> schema-owned Eco balance and consume movement writes. Central cut paths keep
  their original query budget. Safe batch deletion verifies exact consumption,
  adds receive/reversal evidence and restores only the original physical ledger.
  The ECT fabric-consumption report includes unreversed Eco movement evidence.
- No business state, enum storage, production migration, user permission or
  factory assignment changed. The separate pre-cut batch replacement and Planning
  workflows and direct Eco receipts are outside this passport transfer fix.

## Verification and evidence

All evidence below uses isolated fixtures except the explicitly read-only live
release/history comparisons. Ignored detailed logs/scripts are in `outputs/qa/`.

- Regression challenge: exact old report function returns 1,200 for two parents
  with four 600-piece rows; candidate returns 2,400 (`dashboard-red-green.json`).
  Tests cover legacy null/zero, Tepa, kg/metres, >500 records, date/factory scopes,
  no business writes, distinct embedded image pixels/anchors, WebP, model fallback,
  literal formulas and refusal to fetch arbitrary URLs.
- The final combined backend run passed **201 tests**, with no skipped cases,
  including actual cut/deferred usage, reservation,
  deletion, return, retry, QC/shortage and unauthorized-factory behavior. Independent
  reviewer ran 77 distinct cases successfully and found no remaining blocker;
  both reported findings (image fallback and Eco fabric-report evidence) are fixed.
  Ruff, Python compilation, TypeScript, scoped ESLint and diff checks pass. The
  exact command and result are in `final-backend-tests.log`. Final strict TypeScript
  and scoped ESLint also pass against the production-build snapshot.
- Bounded central query regression passes at 1/50/401 material rows, retaining
  exactly 30 SELECTs. Historical report/list/default query bounds also pass.
- Exact locked Next 16.3.8 dependencies were installed in an isolated directory;
  root dependencies were untouched. Full npm build prerequisites and optimized
  build pass; the final three-language help-text correction passed a fresh build
  and TypeScript. Snapshot source equality is recorded in
  `frontend-parity-build-result.json` and `frontend-build-source-manifest.json`.
- Connected Edge visual QA inspected the actual candidate dashboard displaying
  2,400 (`dashboard-2400.png`). The real Export button downloaded a workbook;
  readback found two summary rows/four embedded pictures and four material rows/
  eight embedded pictures. The browser download-event API timed out after the
  download, but the actual downloaded XLSX was found and inspected successfully.
- The actual ECT cutting-only account saved and reopened `QA-BROWSER-5A` in the
  candidate website (`ect-5a-saved-reopened.png`). PostgreSQL confirms 600 pieces,
  10 kg entered usage, central source remains zero/archived, Eco receipts remain
  5 + 146.8 kg, and no CuttingRecord/bundle was created by passport saving.
  See `ect-browser-persisted-readback.json`.
- Real PostgreSQL concurrent HTTP challenge: two different ECT orders each try
  to consume 100 kg from the same 151.8 kg transfer. Exactly one returns 201 and
  one 409; Eco ends at 51.8, central remains zero, and the refused order has no
  record/bundle/waste/ledger side effects. Retry returns 409 without new writes;
  safe deletion restores 151.8 Eco only. `postgres-http-race.json` records all
  persisted effects and readback. Separate race fixtures preserve browser examples.
- The connected browser injects `bis_skin_checked`/other extension attributes,
  producing inherited hydration warnings. No product error is inferred from
  those injected attributes; zero browser-console errors is not claimed. Initial
  test setup required the configured `.venv` Python (global Python lacks tzdata)
  and existing generated model columns on disposable PG. Early dependency-junction
  build topology errors were corrected with physical, exact-version dependencies;
  they are not reported as product passes or production migrations.

## Human review and handoff

Independent AI source/regression review passes. Operator/human approval, shared
source integration, CI release artifacts and deployment are separate; this task
does not authorize or claim production promotion. Inspect the local candidate:

1. CUT Passports -> Dashboard: the four 600-piece example rows total 2,400;
   date/search filters use the same scope as the list and export.
2. Export Excel: open both sheets, check the separate garment and variant
   pictures, original quantities and no overlapping thumbnails.
3. ECT passport: open transferred batch 5A, save/reopen a quantity within its
   physical balance; confirm shortages are refused. Before confirming Cutting,
   verify the intended fabric amount. Confirmation must debit Eco only.

No production data, release, container, schema, permission, stock quantity or
workflow state was changed. QA used only disposable local synthetic data. Scoped
QA process/container ownership and cleanup are recorded in `outputs/qa/QA_RUNTIME.md`.
