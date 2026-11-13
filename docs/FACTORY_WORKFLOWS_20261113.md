# Factory workflow corrections — 13 November 2026

## Initial authorization and reconciled implementation baseline

The owner requested: (1) matching public Order No/new batch numbering; (2)
automatic Sewing-to-Packaging availability, selectable batch and pack-label count;
(3) passport Open to Cutting; (4) correct Cutting dashboard calculations; (5)
uniform invoice package-row heights and 10 pt font; (6) Milana Planning using Eco
Cotton fabric for Eco Cutting; (7) repair Eco passport fabric lookup/consumption.
Plan then implement; wait for separate deployment approval. The owner subsequently
authorized reconciling the baseline with the verified live release.

Fetched clone_main: 3053788f2e17bd5585bccf8cd4547a62cc297516. Both hosts then served
20261111_115200, manifest db9df64cbcf57e4ab93ac83ef677d7d394b07652a1a4cf3fe1815abc92adac28;
both complete live manifest checks passed. All 2,495 manifest files match Git
46ddd5c7864f0a68bd9a3c884d835a2a5dbf9bfb byte-for-byte (LF Git archive).
The already-deployed source and later release metadata on fa9177846 were merged
into this isolated task branch as 479c5bf6. No production mutation occurred during
baseline reconciliation. Recorded rollback was 20261111_052632 and schema
0156_variant_price_workflow. Protected slot-state access required sudo and was
pending at this checkpoint; the deployment addendum records its later verification.

## Implementation plan and operation ledger

Lead engineering domain: Production/Packaging (Mirshoir; default reviewer Ismail).
Planning/Inventory/Finance ownership remains Ismail, reviewer Mirshoir. These are
repository ownership assignments, not claims of human participation or approval.
Codex implements isolated disjoint slices and a different agent reviews each
integrated change under AGENTS.md. Human/operator acceptance remains pending.

| Operation | Intended change and acceptance | Source seams | State |
| --- | --- | --- | --- |
| WF01 numbering | New Nastil serial uses public order number, retains unique batch suffix; historical identities/QR remain stable; retry does not duplicate. | production_service, passport_nastil_service, extra-batch route, production/batch_number_service | Implemented; automated, real PG, browser and independent review PASS |
| WF02 packaging | Proven Sewing output immediately appears in Packaging without a manual acceptance action. Operator chooses source batch(es) and a bounded number of packs to label; unselected balances stay available. Preserve physical Packaging/warehouse evidence, factory scope, partial packs, retry/concurrency protection. | workflow/batch progress, packaging receipt/source services and Packaging UI | Implemented; workflow, PG, browser and independent review PASS |
| WF03 passport navigation | Open resolves the actual authorized Cutting work order rather than whole-order detail, including ECT. | passport output/UI and Cutting route | Implemented; CUT/ECT browser and query-budget checks PASS |
| WF04 Cutting dashboard | Trace the main Cutting and passport dashboard calculations, dates/factory/status filters, multi-material/Nastil grain, units and partial output; fix evidenced defects and reconcile independently computed totals. | dashboards and cutting_passport_reports | Implemented; computed facts, real PG, browser/review PASS |
| WF05 invoice Excel | Package table font is 10 pt; all package rows share a common height sufficient for the longest wrapped row. Preserve counts, money, sorting, images and existing print settings. | shipment_invoice_excel_service and export tests | Implemented; numeric/format assertions and rendered export PASS |
| WF06 Planning ECO | Milana Planning can select valid Eco stock and create an order routed to ECT, without an account/factory bypass. Reject unauthorized/unavailable sources. | production_planning, material selection and Planning UI | Implemented; restricted MIL Planning -> actual ECT passport/Cutting browser PASS |
| WF07 ECO fabric | Trace direct and transferred receipts through selection, reservation, passport confirmation and exact physical ledger debit/reversal. Support real eligible ECO fabric; never debit MIL a second time, fabricate stock, or bypass QC/reservations. | ect_passport_fabric and eco inventory/planning services | Implemented; physical ledger, reservations, races and browser/review PASS |

New/changed fixed vocabulary must reuse canonical enums; configurable fabric,
factory and order identities remain data. No broad refactor or historical data
repair is authorized. No production business rows may be created for testing.

## Verification and delivery

Each worker records callers, affected fields/DTOs, exact changed paths and tests.
Run defect reproductions and focused backend/frontend regressions first; then
affected full handoffs, real isolated PostgreSQL integrity/concurrency checks,
lint, strict TypeScript, build and applicable required gates. Prepare isolated
fixtures for actual connected-browser visual checks, reopen/readback and bounded
load/retry challenges. Missing required checks remain BLOCKED, never PASS.
Review exact integrated source independently. Record all results here before
handoff. Commit/push only intended task paths after proportional tests; do not
merge clone_main or deploy without the owner's separate authority.

Implementation worktree: C:/ERP/.codex-work/factory-workflows-20261113.
Branch: codex/factory-workflows-20261113. Preserve C:/ERP unchanged.

## WF01 technical evidence

Six defect regressions failed on reconciled source: initial PO/SO/USL/five-digit
numbers, manual extra batch, and later passport Nastil all used the PK rather
than the public reference. The fix uses one pure shared formatter for those three
writers. It reads ProductionOrder.order_no (SalesOrder first when linked), keeps
the familiar numeric suffix plus two-digit Nastil suffix, and never rewrites
existing rows. Nonstandard historical references retain their old creation fallback.
No API/DTO/storage type, permission, QR payload or sequence stream was changed.
The schema-hotfix historical repair and frontend missing-serial fallback remain
unchanged; neither creates new regular orders or overwrites a stored serial.

Windows focused suite: 38 passed. Same focused tests plus the existing PostgreSQL
numbering concurrency check on Linux: 39 passed. Three additional real PostgreSQL
PO/SO/USL commit/reopen/retry cases passed. Reports: outputs/factory-qa/numbering.xml
and numbering-pg.xml. Scoped Ruff and git diff --check passed. Existing test-only
deprecation/short synthetic JWT warnings remain. Browser/independent review pending.

Independent WF01 reviewer /root/packaging reproduced a downstream ambiguity:
separate POs sharing one Sales Order, or PO/USL numeric streams, can now share the
same order-local Nastil serial. The old unscoped traceability lookup selected the
newest matching row silently. Two added plain/BATCH reference regressions failed
with a wrong-order HTTP 200 before the correction; lookup now refuses ambiguous
serials with HTTP 409. Exact BATCH_ID printed QR resolution is preserved. The
numbering/traceability/query-growth suite then passed 32 tests; scoped Ruff passed.
No other active batch creator was missed in the independent source search.

## Combined candidate and bounded scope

Detailed operation evidence: [Packaging](WF02_PACKAGING_20261113.md),
[reports/invoice/navigation](FACTORY_REPORTS_20261113.md),
[Eco fabric and Planning](FACTORY_ECO_FABRIC_20261113.md), and
[full-suite triage](FACTORY_SUITE_TRIAGE_20261113.md).
The root branch includes all frozen implementation/review corrections; its final
handoff commit is recorded in Git. No main/clone_main integration or production
deployment has been performed. Human domain/operator and QA-master acceptance are
unrecorded. The final verification results and remaining release gates are below.

New fixed vocabulary uses the existing CuttingDepartmentCode/WorkOrderStatus,
stock QC/material movement enums and typed DTOs. Order/Nastil numbers, fabric
SKU/color, factory/catalog records and role/permission configuration remain data.
The new list-only routing output is nullable for missing/ambiguous routes and has
one batched query; detail/create output is retained. Explicit ECO source IDs are
distinct from central StockBatch IDs. Persistence is behind inventory schema
operations using the caller's Session/transaction; no migration, background
stock creation, GET mutation or duplicate physical inventory is introduced.
Unrelated legacy route/service and enum extraction work remains outside this task.

## Actual connected-browser evidence

The actual integrated Next/FastAPI application ran only on127.0.0.1:18933/18932.
`backend/app/tests/factory_workflows_browser.py` creates isolated SQLite fixtures,
with optional resume of its verified test database. Production was never used
for test writes. Local fixture accounts, stock, orders and packages are synthetic.
Screenshots, raw console, JSON readbacks, Excel and JUnit are under the ignored
`outputs/factory-qa/` directory in this worktree.

- CUT dashboard:20current pieces,1bundle/1order/1work order;27created/7transferred;
  waste2.5kg/3m. Today passport dashboard:1passport/400dashboard pieces with Tepa,
 12kg/14.5m/5rolls, independently specified fixture facts. ECT fixture gives30
  current pieces. Mixed CUT/ECT order retains each bundle's true Cutting origin.
  CUT passport Open navigated directly to/work-orders/5/cutting.
- Packaging queue immediately showed95unaccepted Sewing pieces and a later-Nastil
  legacy order with240passed/75packed/165remaining. Saving95Packaging pieces then
  Copies1 created exactly one60-piece package, retaining35. Selecting only the
  first two packed Nastils produced one60-piece package allocated35+25;15remained
  on the second source and the third source stayed untouched. Reload and API
  source-ledger readbacks agreed. No automatic package or finished-goods receipt.
- Restricted Milana planner (planning.production only) selected a genuine direct
  ECO100kg receipt with10reserved/90available, Brand and ECT in the real Sales
  Planning dialog. Created order6/publicSO-2025-000001 with8kg estimate and actual
  ECTCutting work order9. No fabric debit on Planning/passport save. Passport
  dropdown includes that order and excludes ambiguous routes.
- ECT passport selected the exact planned source. First Nastil0001-01/10Mpieces,
 2kg x3layers +0.5scrap saved/reopened and Open led directly to/work-orders/9/cutting.
  Confirmed Cutting created one10-piece ECO bundle and exactly one6.5kg ECO debit:
  physical100->93.5, reservation10unchanged, central identity0/zero movements.
  Second passport/Nastil0001-02/5Mpieces used2.5kg: immediate screen showed81kg
  available/91kg physical/10reserved, without page reload. Two actual bundles/15
  pieces persisted. Historical batch numbers were not modified.
- Actual generated invoice export was downloaded from the candidate endpoint and
  imported read-only for a rendered A9:K12 inspection. Its two package rows have
  the same sufficient height;10pt table/header/signature checks and totals
 7pieces/2.75kg/17.50passed. Long and short descriptions fit the uniform height.
- English, Russian and Uzbek operator copy was inspected. Old accepted-order
  empty-state wording found visually was removed in all three dictionaries/mirrors.
  Existing tablet-width layout remained usable; automated page checks also cover
  narrower viewports and real selection/submit handlers.

Independent reviewer identity: /root/packaging reviewed WF01 and reports;
/root/cutting_reports reviewed Packaging and ECO (including all follow-ups).
The reviewer caught ambiguous serial lookup, a misleading mixed-pack preview,
missing route projection, Enum adaptation and generic API silent source loss;
all were corrected and rechecked. Root separately exercised the actual website
and persisted effects. Developer console hydration warnings identify extension-
injected bis_skin_checked/bis_register attributes; raw logs are preserved, not
reported as a zero-warning run. No ERP exception occurred in successful flows.

## Final verification ledger and human deployment checklist

Passed local gates: 649 required PostgreSQL operation cases; 17 supplemental
Purchasing/Fabric cases on the same owned PG17.10 instance; 84 shared audit,
idempotency, readiness, boundary and runner contracts (both SQLite and PostgreSQL);
113 affected workflow tests with real PostgreSQL and no skips; two separate S06
stock-adjustment races; four real HAProxy gateway cases; and 171 JWT contracts.
The integrated correction run passed 140 cases before the final typed-list
boundary fix; its expanded final rerun includes existing pagination contracts.
New follow-up HTTP/no-write and actual React handler tests passed independently.
Full backend Ruff and compile passed, with one unchanged Alembic head:
0156_variant_price_workflow. The complete normal npm build (contracts, optimized
Turbopack compilation, TypeScript and routes) passed with freshly installed locked
dependencies. Configured project typechecking passed; lint has zero errors and
14 existing warnings.

Correction to earlier worker/packet wording: configured `npm run typecheck:strict`
uses `tsconfig.strict.json` with `strict: true` and a scoped include list; it passed.
The main `tsconfig.json` remains non-strict. The explicit optional whole-app command
`npx tsc --noEmit --strict --incremental false` reports 16 primary diagnostics.
A separate clean ba2ac53b worktree with identical lockfile/config/dependencies
reports exactly the same 16 diagnostics on unchanged source expressions: zero
introduced, zero removed. These inherited strict-mode findings remain unresolved;
this task does not expand into unrelated global typing cleanup.

The first broad diagnostic run retained 8,290 passes, 11 failures, 17 errors,
77 skips and 36 passing subtests. The corrected-environment second snapshot had
6,801 passes, five failures, 1,596 optional skips and 36 passing subtests. These
are failing historical runs, never relabeled PASS. Four second-run failures
identified a real direct-reader boundary defect: the new list helper returned
dicts where existing consumers use row.id/sales_order_no. It now returns actual
typed ProductionOrderListOut objects with identical HTTP JSON. The fifth was the
obsolete legacy acceptance test already loaded before its approved replacement;
the current complete production_flow file passed 81 cases in the 140-case run.
The final expanded rerun on 04bfd2b16 passed all 145 cases without skips, covering
every affected failed test on integrated source (final-boundaries.xml).
Required PostgreSQL/readiness/gateway cases skipped by the default SQLite run
were executed separately as recorded above; optional skips are not claimed as
passes. No clean full-suite result for an untested later commit is invented.

Local environment corrections were confined to owned QA infrastructure: missing
barcode/dev extras, obsolete python-jose/ecdsa inherited from the old test image,
HAProxy and the actual slot manager's API error-file fixture, guarded disposable
database names, and a fresh local node_modules directory instead of an external
junction rejected by Turbopack. Shared dependencies and production were untouched.
The optimized local preview startup was rejected by automatic approval review
with only "blocked by policy" supplied. No retry bypass or deployment was made;
the actual candidate browser flows/screenshots were completed before the build.

The 17 supplement cases ran directly with the approved local 55439 identity; the
CI-only supplement launcher hardcodes55432/review_ci_refactor_ and was not claimed
to have run unchanged. CI/release image security scans and production staging,
backup, slot-state, paired runtime/health and QA-master review remain release
gates, to run only as part of an authorized deployment. No performance waiver is
created by this task. Failed diagnostics remain in the local evidence directory.

Before deployment approval, the owner/QA master should inspect new Order No and
Nastil numbers, automatic Packaging arrival, exact selected-source pack counts,
partial remainder/reprint, both Cutting dashboards and passport navigation,
uniform10pt invoice, and Milana Planning -> ECO passport -> real inventory debit.
Retain factory denial/held-stock/over-quantity refusals and historical QR/receipt
compatibility. Reconcile fresh clone_main/live manifests/protected slot state,
use the exact reviewed clean Git commit and DEPLOYMENT.md immutable-image
blue/green procedure, verify backup/migrations before touching the active release,
and retain the recorded rollback. Approval to implement is not deployment approval.

## Implementation handoff (historical; superseded by release addendum)

WF01-WF07: **AI_VERIFIED_AWAITING_HUMAN**. Independent final typed-boundary review
passed nine pagination/routing cases on 951279cbf (integrated 04bfd2b16), with no
remaining findings. The named domain owners/operator and QA master have
not accepted a production build. The normal build and focused/current regression
gates passed; inherited strict-mode findings and historical broad-run failures
remain disclosed above. Release CI/security/image/staging gates are separate.

The root branch is intended to be committed and pushed as a review candidate,
without merging clone_main/main or deploying. Final commit/push state is reported
at handoff; no promise of production readiness bypasses DEPLOYMENT.md.

## Deployment addendum — 13 November 2026

The owner subsequently instructed deployment without 30-minute monitoring and,
after disclosure of the actual failed paired Sales measurements, replied
**"Deploy with this specific exception"**. This authorizes only that gate's Sales
median +11.0316% (10% limit) and p95 +26.3905% (15% limit); the failed artifact is
retained as FAIL. No public timing cap, data check or other failure was waived.

Exact reviewed source `e5383f2509ceef4eb20f73f34dc0beba64fcea19` is deployed on both
hosts as green `20261113_094409`, with healthy blue `20261111_115200` rollback.
Both source symlinks/manifests and scanned immutable images agree. The database
remains at `0156_variant_price_workflow`; migration was a no-op after a verified
1,400-object backup. No task-initiated production business-data writes occurred.

Exact-source CI43403793296 and PG43403798457 passed. Backend: 6,808 passes,
1,596 reported optional skips and 36 subtests. Required PG: five numbering cases,
649 mandatory cases, 17 supplements and 84 shared contracts, with no required
skips. Frontend lint/build/configured scoped strict check and security passed;
five known quarantined Node failures and 34 NEEDS_APP outcomes remain disclosed,
not relabeled as passes. All 17 applicable browser scripts passed.

Actual staged/public Edge and complete independent database oracles passed all
26 checks, including all three Packaging queues, both Cutting departments,
restricted Planning ECO lookup/negative authorization, and invoice XLSX values,
merges, 10pt fonts and uniform package-row heights. Shipment44 contains 100
packages grouped into 57 invoice rows; all 57 were checked. Live Planning had zero
eligible confirmed orders; complete creation, ECO debit/reopen and central-zero
readback were tested in isolated same-source infrastructure instead of creating
production fixtures. Public browser console errors were zero; one SSL EOF event
in the private MIL viewing transport remains recorded separately.

Staff activity invalidated earlier frozen facts. Complete operator-ledger proofs
and independently reviewed whole current-facts packets replaced only expected
business bodies, preserving the original paired failure and original public
timing baseline. One final strict public epoch passed all 270 GETs with complete
ordered bodies and unchanged median10%/p9515%/bytes15% limits. Fresh four health
checks, readiness, two workers, strict head, zero restarts/OOM/log errors, router
validity, source/image identities, database headroom and rollback checks passed.
No observer or substitute monitor ran. Human domain/QA-master acceptance remains
unrecorded; explicit owner deployment authorization is not invented acceptance.

The task branch is pushed, not merged into clone_main/main. A later metadata-only
commit advances production-base/context; deployed runtime source remains e538.
See the [full release record](archive/FACTORY_WORKFLOWS_RELEASE_20261113.md).
