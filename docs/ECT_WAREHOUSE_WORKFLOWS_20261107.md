# ECT receiving, production handoffs and warehouse improvements

State: AI_VERIFIED_AWAITING_HUMAN for the requested workflows. The broad suite is
not fully green: baseline Windows failures and unconfigured readiness cases remain
listed below. Requested 7 November 2026; human acceptance and deployment are not
authorized/completed by these checks.

User approved `origin/clone_main` after the required baseline stop. Both production
hosts were read-only verified on `20261107_043754`, manifest
`43b30accbabc4674a395eaa46eecd2c7f554a2513adc33dc859131355526bddd`.
Candidate starts at `b21b51e6c6112a9c181853b8646944de7416ee8b` in isolated
`C:/ERP/.codex-work/ect-warehouse-workflows-20261107`.

## Direct user scope and acceptance

1. Table receiving for ECT accessories and fabric: supplier/date once; per-row
   type/name, quantity, unit, batch; plus/Enter adds another row. Fabric fields
   follow evidence of actual Milana use, not guessed mandatory fields.
2. Cutting Passport Open action navigates directly to its linked production order.
3. Repair adding a distinct batch of an existing fabric when the inventory picker
   cannot find it; preserve separate lot identity.
4. Daily Sewing Excel retains the selected Top/Bottom garment part.
5. Manual bundle receive can choose a sewing line immediately OR leave unassigned,
   as explicitly confirmed by the user; retain chosen assignment on reopening.
6. Choose two released Nastils for combined packaging, preserving source evidence,
   partial quantities, allocation limits and retries.
7. Warehouse shipment report: search model, variant, order, customer and dispatch
   date; export matching rows to Excel with model/variant/pieces/package details.
8. User screenshot: map on the left, stock on the right, shared search/factory/date
   filters. Exact variant selection restricts stock to that variant. Keep existing
   warehouse placement/movement/label actions reachable.
9. After implementation and visual verification email screenshots to the user's
   authenticated Gmail account, with actual completion/test/deployment state.

## Ownership and sources

Codex root integrates and implements passport navigation, warehouse report/map.
Ismail owns inventory; Mirshoir reviews it. Mirshoir owns production, packaging
and fulfillment; Ismail reviews them. Shavkat/operator human acceptance is pending;
these assignments do not claim those people performed a review.

Independent isolated Codex workers: `ect_receiving` owns receipt/picker operations;
`sewing_receiving_export` owns sewing receipt/export; `pack_two_nastils` owns
packaging selection/allocation validation. Root reviews their code. A separate
worker reviews root's frozen diff. Shared frontend navigation is root-owned.

Root trace: cutting-passports -> linked production_order_id (existing output DTO);
warehouse-stock -> packages/storage-map -> Package/Model/legacy receipt and sewing
origin projection; warehouse-map retains placement/move/label mutations;
shipment report -> Shipment terminal status/shipped_at + frozen dispatch document,
legacy read reconstruction through shipment_document, no financial output/writes.
Report uses existing ShipmentStatus enum; names, models, sizes and partners remain
configurable text. No new database table, permission or migration is planned.

## Implemented behavior

- ECT receiving saves up to 100 rows atomically with one authenticated idempotency
  key. Shared receipt fields are supplier/date/warehouse/source/document/order.
  Fabric rows expose rolls, color/code, gramaj and picture; less-used details stay
  expandable. Read-only production fill evidence: 1,550 fabric batches, supplier
  1,506, roll count 1,510, image 1,129, color 824, color code 758, gramaj 614 and
  width zero. No production stock was edited to obtain these counts.
- Compatible-fabric lookup applies item_id before the latest-500 result limit.
  Central StockBatch and proven transferred ECO sources retain their identities.
  Direct, unlinked ECO receipts do not gain a new cutting-physical-source identity.
- Passport rows open their linked order. Manual Sewing receive can choose an
  active same-factory line or retain the existing/unassigned state. QR and manual
  receipt share the same transaction/assignment guards. Active Printing rejects
  are excluded from usable Sewing assignment quantities without rewriting labels.
- Daily Sewing Excel keeps garment part, Top qty and Bottom qty beside Sewn qty.
- Multi-Nastil packaging explicitly selects sources and preserves full/partial
  package allocations. The read-only source projection spans sibling work orders
  of the same receiving department; ordinary record-entry progress stays scoped
  to its own work order. Every creation API rechecks each source's factory owner.
- Shipment reports use shipped/delivered dispatches, frozen dispatch quantities
  and Tashkent dates. Historical missing snapshots use ShipmentPackage quantities,
  never today's depleted package remainder. Historical rows are labelled and
  unknown historical sizes remain unknown. Search and Excel share the projection.
- Warehouse Stock now has map left, model stock right, shared search/factory/date
  filters and exact model/variant selection. Cell selection intersects the filters.
  Placement/move remains reachable with those filters. Filtered summaries match
  the selection while physical target occupancy retains every package.

No table, migration or permission was added. Read contracts use existing category,
factory, packaging department, receipt source and shipment status enums; names,
codes, variants and package references remain configurable data. Existing legacy
state strings are retained at their established service boundaries, not promoted
to new configurable-name enums. New mapped assignment writes use the schema-owned
receipt operation and the caller's transaction; reports/projections perform no writes.

## Exact feature evidence and review

Integrated worker source: receipt 67e88e0e6/e463f0104, sewing
5df36ac8e/92ede3b44/7c00c955d, packaging b22a93475/3f3b83f75.
Root implementation is 714891c7c; final runtime source is 49af995a1, including the
catalog namespace correction and concurrency-safe Sewing follow-ups. Independent
review record is ROOT_WAREHOUSE_REVIEW_20261107.md.
Root reviewed worker API/service/schema/DTO and UI boundaries. Separate workers
reviewed root report/map, the Printing-loss correction, final receipt integration
and the sibling-source projection. Final map summary blob reviewed independently:
3673cffa49e866d52c898ded291d3a5805b34f46. Unit-column width is a final cosmetic fix.

- Final root focused backend: **40 passed**, 18.04 s (shipment report, receipt table,
  passport allocation regressions). Ruff passes across backend/app and QA script.
- Combined real PostgreSQL: **19 passed**, 26.61 s for receipt retries/rollback,
  packaging allocations and Sewing receipt/assignment. Final packaging follow-up:
  **13 passed**, 11.16 s including real PG and dedicated-sibling source tests.
- Final frontend optimized build and its contract suite pass. Strict TypeScript
  passes. ESLint has zero errors and 14 existing warnings. Normal TypeScript runs
  within the optimized build. No dependency manifest/lockfile changes were needed.
- Bounded stress: 100-row atomic receipt; 2,500 package-plan balance cases;
  200-Nastil source projection in eight SELECTs; 500 frozen shipment report rows
  in one SELECT (12.66 ms); 2,500 warehouse placements remain reachable. See the
  worker packets for concurrency, deliberate-fault and red/green details.
- Bug validity: missing older same-fabric sources reproduced behind 501 unrelated
  newer lots; old dedicated-WO selector fails the new UI regression; Printing
  loss assignment corrected and independently verified on real PostgreSQL.

Actual connected Edge browser, local SQLite/API only:

1. Enter adds a row. Two accessory lots save together: thread 12 rolls and bags
   24 pcs, shared supplier/date, both retained in stock after reload.
2. Two same-fabric lots save 120 kg/6 rolls and 60 kg/3 rolls with independent
   lot/color/gramaj metadata. Browser found Count's fractional min versus step=1
   mismatch; min=1 correction saves successfully. Final kg unit remains readable.
3. Passport Open navigates to the actual order. An older compatible lot appears
   behind 501 newer unrelated lots and saves as a three-source 100+100+100 kg split.
4. Manual Sewing line choice receives four bundles/128 pieces. Persisted assignment
   is line28, quantity128 and work-order line28. No-line/existing-line cases have
   backend coverage; physical tablet/operator acceptance remains pending.
5. Selecting only Nastils35+40 creates packages60+15, allocations35+25+15.
   Unselected Nastil90 remains available. One print-run package scan receives both;
   both move to A-03/S1. Independent DB readback confirms saved allocations/status.
6. Shared stock/map exact variant3372 plus cell A-01 shows one package/60 pieces.
   Placement handoff selects that package and reports one/60 while retaining other
   models for occupancy validation. Unfiltered totals include the received75.
7. Search V-3372 with both dates 7 November returns20 shipped pieces, one package,
   sizes M12/L8/customer/order/time. Actual Excel downloads retain matching20.
   Native date keyboard editing commits correctly; automation-only date fill did
   not trigger React's native change and was not accepted as filter evidence.
8. Actual Sewing Excel download renders Top24 and Bottom16 in explicit columns.
   Both downloaded Excel files were imported/rendered with the spreadsheet skill.

Screenshots: outputs/ect-workflows-screenshots/01 through12 (12 images). All were
visually inspected. They use synthetic test data. Browser extension-injected
attributes produce the local Next developer hydration warning badge. An optimized
local server start was rejected by automatic approval review without a stated
reason; permitted loopback development server browser checks and the successful
optimized build are recorded separately. No production-browser success is claimed.

## Remaining limits and acceptance

The broad pinned backend suite is not green; exact closing results follow below.
Feature PostgreSQL checks use the owned disposable local server, not production.
Broad PG skips are not passes. A pre-existing cancelled-Printing inconsistency remains: completion
excludes cancelled Printing but existing output context can still cap usable input
at100 versus128. It reproduces before this correction and is outside this task's
production.py scope. No cancellation fix or system-wide audit closure is claimed.

Human local checklist: receive real approved sample rows in each ECT table;
confirm fabric details/units and scanner/tablet keyboard usability; open a passport
order and add a compatible lot; check Top/Bottom Excel in Excel; receive with and
without line choice; select two released same-factory Nastils and verify labels,
partial pack, warehouse receipt; filter exact variant/cell and a dated shipment
Excel. Shavkat/operator acceptance must be recorded before deployment readiness.

Production remains 20261107_043754. No production writes, migration, merge or
deployment occurred for this task. Local synthetic fixtures, images and private
credentials are isolated/ignored.

## Closing record (7 November)

Final frozen runtime: **49af995a1d4d7e956924ed82f99517261218af1e**. Its frontend
tree exactly equals the optimized-build/browser candidate 714891c7c. The final
backend follow-ups change retry namespace and fresh Printing reads, with unchanged
UI/response contracts. Root independently reviewed those changes and their tests.

- Final real PostgreSQL integration: **25 passed**, 30.84 s, covering ECT bulk
  receipt, multi-Nastil packages and Sewing receipt, including actual lock waits.
- Frozen complete backend collection: **8,169 cases / 746 files**, split by file
  across six separate Python processes with independent SQLite databases and
  shared-counter files. Exact source stayed fixed throughout. Aggregate:
  **6,622 passed, 1,538 skipped, 4 failed, 5 errors**, plus 36 passing subtests.
  Logs: final-full-backend-frozen.log and final-backend-shard-0.log through -5.log.
  This is an explicitly failing broad gate, not an all-tests-pass claim.
- All four failures reproduce on unchanged b21b51e6c: Windows symlink privilege,
  Unix file-mode expectation, unsupported pass_fds and SQLite file rename while
  Windows retains a handle. The last requires the whole shared-store test module
  to reproduce: baseline **34 passed / 1 failed**, 22.99 s. The other three are
  recorded in baseline-failures-comparison.log. Five readiness errors in both
  candidates require MILANA_TEST_PG_INSTANCE; these are configuration-blocked and
  do not substitute for the separate successful feature PostgreSQL checks.
- An earlier exploratory long run overlapped later source additions. Its label
  source-inspection failure does not reproduce with frozen source. Final package
  label and SQLite single-test rerun: **3 passed**, 8.00 s. That initial sweep is
  retained as diagnostic evidence, not final-source certification.
- That sweep exposed six stale performance-test dependency seams after receipt
  extraction plus one permission-catalog namespace collision. Scope changed from
  eco_inventory.receive_bulk to eco_inventory:receive-bulk without granting a new
  permission; catalog/receipt regressions **31 passed** after a reproduced red.
  The audit double now patches the service owner and asserts every audit call;
  real PostgreSQL checks also validate persisted audit counts and hash chains.
- Root rejected the intermediate joined Printing aggregate after a meaningful
  real-PG legacy publication race assigned 128 instead of 100. Final reads Printing
  with a fresh statement after bundle-lock waits. Modern FK publication control
  and legacy coalesced publication both assign 100 from 128 with 28 rejects.
  Constant SQLite query budgets at 1/50/401 bundles are 20 unassigned manual,
  30 QR and 25 chosen-line manual; the extra correctness read is deliberate.
  Real-audit PostgreSQL counts are23/32/27 at all three sizes. Worker final scope:
  **76 SQLite / 17 PostgreSQL passed**. No audit or quantity guard was removed.
- Final Ruff and whitespace checks pass. Optimized frontend/strict TypeScript
  and ESLint (zero errors / 14 warnings) remain valid: no frontend source changed
  after that build. Fresh origin/clone_main still equals b21b51e6c.

Dedicated branch **codex/ect-warehouse-workflows-20261107** was pushed through
49af995a1. Final documentation is committed separately. No merge or deployment.
Runtime rollback is a source revert before any release; no production data rollback
is needed because this task changed no production business data.

The Gmail connector confirmed SENT to the authenticated user's own account with
**all 12 screenshot attachments**, subject “Milana ERP — screenshots of ECT and
warehouse changes — 7 November”. The message identifies synthetic data, source,
test limits and absence of deployment. No production/credential screenshot is used.

Owned API on port 18107 and frontend on port 3107 stopped. Packaging's disposable
PostgreSQL on port 15567 was automatically removed on stop. The retained Sewing
PostgreSQL container on port 15568 is
stopped; its owned volume remains. Final checks find no listener on those four
owned QA ports. Source, logs, screenshots and local SQLite readback fixtures remain
retained; private credentials and fixtures remain ignored. No unrelated service or
legacy checkout change was discarded. Human checklist and cancelled-Printing risk
above remain open.


## Release closure — 9 November 2026

Final application `4f33eba77` includes the requested report presentation polish.
It was pushed and normally fast-forwarded into `clone_main`, then deployed as
blue `20261109_035740` on both hosts. Green `20261107_043754` remains compatible
rollback. Exact-source Linux CI passed 6,649 backend tests / 1,567 skips plus frontend,
mandatory PostgreSQL, security and immutable publication; feature PG 25/report15
passed. The earlier Windows failure record above remains historical.

The owner approved the exact paired inventory-stock AB median exception
(+10.05419% against +10%, about 2.43 ms); the machine result remains failed.
Public performance passed all original limits, every full ordered projection and
fixed workflow readback matched, and final four-health/runtime/rollback checks
passed. No 30-minute observer ran under the separate owner waiver. A separate named
QA-master approval was not supplied; root disclosed the owner override of that
gate. Operator acceptance and the live two-eligible-Nastil save remain unclaimed.
No production business QA rows were created. Owned leases and local preview
processes are released/stopped. Gmail confirmed SENT with all 16 screenshots,
including polished report/Excel and actual public screens, message 1a1bed7d865cbaf4.
See [the final release record](archive/ECT_WAREHOUSE_RELEASE_2026-11-09.md) for
source/image/backup identities, preserved failed evidence, exact exception scope,
cleanup and unresolved risks. This closure supersedes earlier candidate-only and
no-deployment statements for this operation; it does not erase their history.
