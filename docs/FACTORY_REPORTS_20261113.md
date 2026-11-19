# Factory reporting, passport navigation and Excel corrections

Last updated: 2026-11-13. Worker `/root/cutting_reports`; isolated worktree
`C:/ERP/.codex-work/factory-reports-20261113`, branch
`codex/factory-reports-20261113`, base `ba2ac53b74d26e4f535b67819cd4d1e3cc444640`.
Owner-authorized WF03/WF04/WF05 implementation, pending deployment approval.
Production remains `20261111_115200`; no production writes or deployment.
Reconciliation/authorization is recorded in `FACTORY_WORKFLOWS_20261113.md`.
Domain engineering: Mirshoir (Production), Ismail (Finance), reciprocal default
review; Shavkat/operator acceptance remains pending. Names describe repository
ownership, not participation or approval.

## Studied operations and exact changes

- WF03: passport list/detail/create/update serialization, `passport_batch_map`,
  CuttingPassportOut, selected-factory access policy, WorkOrder/batch definitions,
  Passport Open and `/work-orders/[id]/cutting`. The new read-only
  `production/cutting_passport_navigation_service.py` projects the actual selected
  factory's Cutting work order in one query for the entire list. Exact matching
  Nastil work wins; unique whole-order work is the historical fallback. Unlinked,
  ambiguous or other-Nastil-only passports have no link. Existing list/detail
  authorization remains, and projection independently filters the selected
  Cutting department. `cutting_work_order_id: int | None` is an additive output
  contract; no input, permission or persistence change. The button links directly
  to the dedicated Cutting route, preserving its existing design and EN/RU/UZ text.
- WF04: `/dashboard/cutting` -> `cutting_board`, the shared bundle-inventory
  origin/current/aggregate helpers, `/bundles/cutting-inventory`, scan transitions,
  waste, Tashkent periods, and passport filtering/streamed report calculation were
  traced. Proven defect: any ECT work order reclassified every bundle on an order
  as ECT even when its actual CuttingRecord belonged to CUT. Source-record
  WorkOrder/department now determines origin; bundles without a usable source
  retain the historical order-level fallback. Both dashboard and inventory use
  the same condition. Current balances remain independent of period dates;
  creation and first physical receipt stay separate period movements. Repeated
  Printing/Sewing receipts still count once. Waste stays grouped by recorded unit.
- WF04 calendar defect: new passport and Add-batch forms used the UTC date while
  Today filters use Tashkent. Between midnight and04:59 local time a new passport
  was saved under yesterday. Both defaults now reuse the established `businessDate`
  function, as does the filter. Historical stored calendar dates and explicit
  example data remain unchanged.
- WF05: shipment invoice JSON/frozen snapshot -> `shipment_invoice_workbook` and
  existing HTML/size formatting. Excel package-table/signature text is now10pt.
  Each package detail row receives the same height: the largest wrapped-text
  requirement among all detail rows, minimum23.1pt. This includes split-package
  model rows. Unwrapped sizes/numeric columns reserve space for10pt text. Existing
  numeric types, merged package counts/weights, prices toggle, size sorting,
  literal-text protection, logo and print settings remain. HTML retains its
  independently requested10px styling. Metadata/headings retain their typography.

## Arithmetic and value/type ledger

Passport totals intentionally count saved material rows, including historical
600+600 rows, not confirmed downstream garment output. Existing Tepa pass doubles
only dashboard piece totals; Excel, stock, Nastils and work-order output remain
unchanged. Grouped physical allocations count the logical material calculation
once. Kilograms and metres never combine. Calendar-date storage is UTC midnight
for the date entered, unlike event timestamps used by department movements.

The historical ungrouped display formula includes layer quantity × layers +
scrap + binding; kilogram stock usage excludes separate binding. Grouped actual
usage follows the canonical `material_quantity`. These established display/ledger
semantics and the separate theoretical/gross per-piece formulas were checked
against the meter/grouped/submission regression suites; this reporting change
does not silently redefine consumption or rewrite stored values.

Tables/fields reviewed: Bundle quantities/status/source/factory; BundleScanLog
receipt type/time; CuttingRecord source work; WorkOrder operation/department/batch;
Department configurable identity; WasteRecord quantity/unit/type; CuttingPassport
date/Tepa/material JSON/pieces; ProductionBatch passport link; shipment document
and package rows. No new fixed vocabulary, enum member, discriminator or state
transition is introduced. Existing CUT/ECT, scan/status and unit filters retain
their stored values. New output identity is nullable integer; order/fabric/model
identities remain data. Broader legacy DTO/enum and schema-write migration debt
is intentionally retained outside these read-only operations.

## Evidence on the worker candidate

- Red/green navigation browser assertion: old link `/production-orders/450`
  failed the expected `/work-orders/701/cutting`; corrected actual ERP page passes.
- Red/green calendar browser assertion under fixed2026-10-16T20:00Z: old form
  default2026-10-16 failed expected Tashkent2026-10-17; corrected form passes.
- Red/green main-board fixture: one order with CUT20 and ECT30 pieces previously
  returned CUT0; corrected board returns CUT20/ECT30, including matching creation
  metrics and inventory endpoint. Legacy source-less bundle fallback is tested.
- Red/green Excel: all six language/price combinations failed10pt font assertions;
  all six mixed-row cases failed uniform heights (23.1 versus178.125pt). Corrected
  workbook preserves amounts/counts/weights/print settings and uniform sufficient
  row heights. No shrink-to-fit is used.
- Focused Windows backend:149 passed across factory reports, passport scope,
  department dashboards, passport reports, invoice size/export, metre calculations
  and grouped allocations; then14 factory regressions passed after adding the
  explicit legacy fallback and500-row one-query budget cases.
- Real PostgreSQL17.10: `test_factory_reports_postgres.py` passed on the owned
  Docker database using the root-provided reports environment. The shared fixture
  uses an isolated `planning_cutting_<uuid>` schema and reproduces historical0084
  generated catalog columns; teardown drops only that schema. Initial missing0084
  fixture-DDL failure was corrected, not counted as a product pass. A commit/reopen
  proves MIL/ECT navigation, date totals, mixed-unit arithmetic, record-origin
  current/created/transferred quantities, deduplicated scans and waste. Forty
  board GETs with four workers completed within the30s per-factory bound. All
  modeled table fingerprints remain identical and no INSERT/UPDATE/DELETE occurs
  during measured reads, including XLSX export. No manufacturing output is minted.
- Frontend `tsc --noEmit`, scoped ESLint and passport autofill/size/metre contracts
  pass. The actual ERP-page fixture Playwright script passes EN/RU/UZ, mobile,
  filtering, empty/error, permission visibility, export and navigation assertions.
  Worker visually inspected the generated passport screenshot; root must inspect
  the exact integrated candidate through the user's connected browser.

Reusable isolated-data helper: `backend/app/tests/factory_reports_fixture.py`.
`build_factory_reports_fixture(db)` performs no commit and returns IDs, date,
expected per-factory dashboard/passport facts and frozen shipment ID. Caller must
provide the explicitly isolated test Session. `uniform_invoice_document()` returns
short/long detail rows with7 pieces,2.75kg and17.50 total. Never invoke the helper
against production. Root integration can use these facts for actual local API/UI
readback. Main dashboard starts with CUT20/ECT30 current pieces; MIL creation27,
transfer7 and waste2.5kg/3m; passport MIL400/ECO200 pieces,12kg/14.5m/5 rolls each.

State: IMPLEMENTED_WITH_FOCUSED_EVIDENCE; integrated build/full required gates,
connected-browser inspection, independent AI review and human acceptance pending.
Do not label AI_VERIFIED_AWAITING_HUMAN until those required AI gates pass. No
merge, push or deployment is performed by this worker.

## Combined-suite query-budget reconciliation

On combined candidate `6570901bc`, the inherited passport-list query-growth test
still expected7/7/12 SELECTs for1/50/401 distinct orders. The actual8/8/13 adds
exactly the intentional single authorized Cutting-navigation projection. This
was reproduced as a failing test before editing. The narrow test-only correction
updates those fixed budgets and explicitly asserts exactly one scalar navigation
query at all three cardinalities, while retaining the original ordering, model
images, sales references, exact-size, chunking and no-blob assertions. The fixture
has no Cutting work orders, so links must remain null rather than be fabricated.
No runtime code or SQL changed. The17 focused query-growth/factory-report tests
pass on Windows and in the root's `milana-factory-qa:20261113` Linux image.

## Actual form initializer in the build harness

Root's frontend build on `8bc7a2781` exposed the batch-split VM harness missing
the `businessDate` binding used by the actual form initializer. The ReferenceError
was reproduced unchanged before this test-only correction. The harness now
compiles the real shared date helper, verifies four UTC instants across Tashkent
midnight, then supplies an explicit20:00UTC instant while evaluating the actual
EMPTY_FORM. It asserts the next Tashkent date, rather than stubbing a date string.
The size-edit and metre-formula VM contexts were inspected; they do not evaluate
this initializer or call the new date helper. Runtime code is unchanged. Passport
batch-split, autofill and multi-material Planning build dependencies pass; scoped
ESLint has zero errors and the existing unused React import warning. Root owns
the final integrated Next build and rendered ERP verification.
The complete pre-Next build chain passed this repaired harness, then failed the
separate stale Planning selector assertion in `check-branded-fabric-type-override.mjs:13`
(old central-only list versus the approved CUT/ECT-selected list). The ECO worker
owns that correction; no complete build pass is claimed here.
