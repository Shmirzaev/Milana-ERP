# WF06/WF07 — Planning and Eco Cotton fabric, 13 November 2026

Implementation agent: `/root/eco_fabric`. Planning/Inventory engineer: Ismail;
reviewer: Mirshoir (ownership assignments, no human approval claimed).
Base: `ba2ac53b74d26e4f535b67819cd4d1e3cc444640`, reconciled live release
`20261111_115200`; this source is not deployed. Worktree
`C:/ERP/.codex-work/factory-eco-20261113`, branch `codex/factory-eco-20261113`.
Uses the repository milana-feature discipline and CleanUI/Uncodixify for existing
UI changes. No redesign, migration, production writes or backfill.

## Studied behavior and root causes

Planning's client/branded order creation passes `ProductionOrderIn` to
`production_planning_service`, then `create_production_order` and
`create_work_orders`. Every planned/cutting/passport/reservation FK is a central
`StockBatch` ID. Planning's selector previously queried only central batches;
creation refused sources whose central availability was zero, even when a real
transferred ECO balance existed. The ECT passport picker and consumption resolver
joined only `EcoMaterialBatch.source_stock_batch_id`, excluding direct receipts.
The Cutting page independently filtered central quantity/availability, hiding
zero/archived central identities with real physical ECO stock.

All runtime `source_stock_batch_id` consumers were inspected: passport lookup,
QC-aware balances, usage metadata/report, actual consumption and delete reversal,
and transfer-receipt creation. Milana transfer dispatch/receipt/export instead use
actual `FactoryFabricTransfer`/`FactoryFabricTransferLine` records. Assigning a
direct receipt identity supplies no proof of Milana-origin transfer.

## Operation contracts and data effects

`GET /planning/eco-fabrics` is a narrow source lookup for current MIL/ECO users
with effective `planning.production`. An explicit ECO Planning policy denial is
honored. It grants no general ECO inventory access or factory session switch.
The existing authorized ECT passport picker also returns direct receipts. Real
gross quantity and QC-passed, unreserved available quantity come exclusively
from ECO. Mixed linked receipts aggregate gross quantity while available counts
only passed receipts; offered sources have a positive usable balance. Source
lookup excludes costs. New Planning output QC/category fields use canonical enums.

Creation input accepts optional primary `eco_fabric_batch_id`; material/passport
input accepts exactly one `stock_batch_id` or `eco_material_batch_id`. Canonical
read/stored passport material IDs remain central positive IDs. The creation
Cutting field now uses canonical `CuttingDepartmentCode`, deliberately rejecting
unknown factory values at DTO validation instead of later work-order creation.
Central legacy identities retain their existing route. ECO sources require ECT.
The trusted internal `eco_fabric_available` creation argument is never taken from
API input. Amount/unit/QC/reservation checks use actual authoritative receipts.

An explicit order/passport save locks existing central identities before ECO
receipts. A source mapped concurrently after the initial read refuses with409
instead of duplicating identity or reversing lock order. An unlinked direct ECO
receipt gets one zero-quantity central identity, marked `ECO-DIRECT-<receipt ID>`
in `internal_batch_no`, and the existing FK links the original ECO receipt.
Only schema-owned insertion/assignment writes occur. The identity uses an existing
validated ECO warehouse. No central physical quantity, reservation, receipt or
movement is created. The surrounding transaction owns commit; failed creation or
passport save rolls back the identity/link/audit together. GETs never write.

Planning amounts remain estimates, matching existing policy: creation does not
reserve physical fabric. Multiple estimates may reference the same source; actual
Cutting is serialized and cannot spend reserved/held/insufficient ECO balances.
Existing consumption/reversal helpers debit/credit only ECO; no second Milana
debit occurs. Cutting lookup uses the authoritative ECT picker projection, including
legacy central-only sources and physical ECO balances, and cannot fall back to
Milana after linked ECO stock is held/depleted.

Frontend adapters use disjoint temporary local numeric selection keys for unsaved
direct receipts. Every write transforms those keys to explicit positive ECO input
fields; none becomes a central FK or persisted source identity. Reload uses the
resolved canonical identity. Existing English/Russian/Uzbek labels are reused.

## Evidence and original failure retained

- New16 SQLite API regressions passed: MIL Planning selection and inventory denial;
  lookup no-writes; create/passport/reopen/actual6.5kg consumption/retry/delete;
  failed create and failed passport rollback; held/reserved/insufficient/unit/route
  refusals; linked real availability; explicit destination denial; trusted balance
  injection and ambiguous identity rejection. Independent review added first-
  material authority (no incidental bridge for unused primary receipt) and
  grouped-source search regressions: complete linked balance is aggregated before
  filtering, preserving displayed canonical source lot/color and receipt search.
- Wider focused run passed56 and skipped32 PostgreSQL-only cases in the Windows
  environment: direct/transferred/grouped passports, submission/deferred usage and
  material reservation concurrency module. The subsequently added policy-denial
  test passed separately with the complete14-case direct regression file.
- Real PostgreSQL17.10 ran in root's approved isolated Docker instance, using
  `pg_approved_instance` and a unique owned database under `review_factory_eco_`.
  Four competing registrations produced exactly one central identity with all
  central physical/reserved/movement totals zero. Two orders each claiming60kg
  from100kg with10kg reserved produced one201 and one409; remaining physical40kg,
  reserved10kg, exactly one ECO debit, no central movement; retries refused.
  A subsequent real-PostgreSQL run of the new cases plus the inherited material-
  reservation concurrency module passed45 with no skips, including its32 cases
  skipped by the unconfigured Windows-only run. The registration race was further
  strengthened to share one BSO (avoiding pre-registration numbering serialization)
  and synchronize all initial receipt mapping reads before any receipt lock.
- Original first PostgreSQL run: registration PASS, competing actual cuts FAIL
  with `psycopg2.errors.DeadlockDetected`, transactions873/874, processes144/145,
  while upgrading `stock_batches` FK KEY SHARE to `FOR UPDATE`; one request500,
  one201. This is a real retained failure, not a pass. The existing material-lock
  preparation call moved before CuttingRecord/Usage FK insertion. Lock strength
  stayed unchanged. Re-run:2 passed, no500, balances and retry integrity correct.
- Ruff passed changed backend paths. Strict TypeScript passed. Runtime frontend
  source-adapter and actual Cutting calculation tests, existing passport batch
  split handlers and multi-material Planning/Cutting contracts passed. Scoped
  ESLint has zero errors and one unchanged Planning navigation warning.

Status: **IMPLEMENTED; COMBINED VISUAL/INDEPENDENT REVIEW PENDING**, not AI-verified.
Root owns full integrated Linux suite/build and actual connected-browser review.
32 unconfigured Windows PG skips are not passes; new mandatory owned PG cases did
run. Human/operator and QA-master acceptance remain separate and unrecorded.

## Reusable isolated browser fixture and acceptance

`backend/app/tests/eco_fabric_fixture.py:make_eco_fabric_case(sessions)` creates
isolated fixture catalog/actors/warehouse plus a genuine ECO100kg receipt with
10kg reserved and90kg available, returning model/brand/item/receipt/batch identity,
MIL planner and ECO operator IDs/headers. `planning_payload(case)` is the equivalent
10-piece ECT request with an8kg estimate. Never run against production.

Visually sign in as MIL Planning, open Add branded production, choose model/brand,
ECT and returned direct batch; save and reopen. Verify ECT work order, central
identity0, physical ECO100/reserved10. As ECO Cutting, save a passport using that
source (2kg layer ×3 plus0.5kg scrap,10pieces), reopen, confirm its Nastil, and
verify the Cutting display and saved ledger show6.5kg spend exclusively from ECO:
93.5kg remaining, reserved10, central0, one consume. Retry must not debit again.
Delete eligible unused Nastil only in isolated QA to verify100kg restoration.
Check linked transferred fabric, held/depleted source and wrong factory refusals.

The root task packet owns final integrated source hashes, independent review,
browser screenshots, human acceptance, publication and deployment state.

## Follow-up from actual connected-browser QA

Root's isolated real ERP browser exercise found two additional caller defects:
new client order6 / Cutting WO9 defaulted to unrelated Milana FAB-COT-001500kg
before its explicitly planned ECO90kg source arrived, and the ECT passport order
dropdown was empty because `/production-orders` never projected the field used
by the frontend's factory filter. These observations are retained as failures;
the initial passing API/selector calculations did not cover these actual callers.

The actual Cutting selection effect now prioritizes the saved primary identity
from all authoritative eligible choices, even when that selected fabric differs
from model BOM. A known unavailable/loading/held primary never selects an unrelated
fallback. An earlier automatic fallback is corrected if the saved source arrives
later; explicit manual choices and legacy no-primary defaults remain supported.

`order_routing_read_service.production_order_list_output` adds canonical nullable
Cutting routing through the list-specific `ProductionOrderListOut`, for plain and
paginated results. It queries actual non-cancelled Cutting work orders once for
the already-authorized returned rows. Missing/mixed/unsupported routes yield null,
never a guessed CUT or ECT. Detail/create DTOs retain their existing shape.
Both passport department filters now require an exact match, excluding null/mixed
routing instead of mistakenly including it in Milana. No data or routing writes.

Four backend HTTP/query-budget regressions pass: plain/page ECT routing, ambiguous
and cancelled sibling semantics, and one query across multiple returned orders.
The combined16 direct ECO + initial3 routing cases passed19 before the additional
query-budget case; final routing module passed4. Ruff and strict TypeScript pass;
scoped ESLint has no errors/warnings. Actual source-adapter/Cutting calculations
and exact passport order filter tests pass and run in the existing build contract.

`test-cutting-planned-source.browser.mjs` mounts the exact actual-page selection
hook with real React effects in Chromium. It passes generic-before-ECO delivery,
outside-BOM planned source90kg, no held-source fallback, deliberate manual choice,
legacy no-primary and late saved-source correction, with zero page errors. The
rendered harness screenshot was actually inspected. This focused harness is not
a substitute for root's complete ERP connected-browser rerun and saved readback,
which remain pending on the combined follow-up revision.

## Further real-browser readback corrections

Root's next actual ERP exercise confirmed the planned ECO source now selects
correctly, but exposed two further facts not covered by the first branded-order
handoff: the batch statistics showed Reserved0 against the real10kg reservation,
and a client-order modal saving only the selected primary fabric (no explicit
material rows) could not save the prefilled passport.

Reserved is the batch-total label; the page has a separate optional "For this
order" label. The source DTO/projection now retains actual `reserved_quantity`:
central sources keep their existing material reservation total; linked/direct
ECO sources sum authoritative ECO receipt reservations independently of QC holds.
No accounting changes. Regression gross170/reserved13/available107 includes50kg
held for QC, proving holds are not mislabeled as reservations. Actual rendered
page statistics assert available90/on-hand100/reserved10.

The client-only mismatch was reproduced RED with the exact HTTP400 "Passport
materials must match the fabrics selected in planning". Passport identity checks
now use the order's saved primary `fabric_batch_id` when explicit planned-material
rows are absent, matching the existing defaults/stock/consumption helpers. The
client regression creates a confirmed sales order with an unrelated model BOM,
uses MIL Planning's primary-only ECO modal contract, saves/reopens the ECT
passport, and confirms6.5kg exclusively in ECO:93.5kg physical,10kg reserved,
central0 and no central debit.

The broader Linux suite also exposed our unconditional enum cast for legacy
configurable Cutting departments in an existing optional-operator PostgreSQL
fixture. Recognized CUT/ECT values now map to canonical enums; unknown departments
remain null for source-resolution purposes. Existing central-only behavior is
preserved, while direct ECO resolution refuses400 outside actual ECT. No invented
enum values or guessed factory routing. Both existing real-PostgreSQL optional-
operator cases pass. Actual ERP rerun/readback and independent source review on
the combined correction remain root-owned gates.

## Last caller and post-confirmation visibility review

Independent review reproduced a further shared-DTO caller omission: generic
`POST /api/production-orders` accepted `eco_fabric_batch_id` but silently ignored
it, returning201 with no selected fabric. Explicit material ECO inputs failed
later on the absent central ID. This caller is now explicitly refused400 through
a typed public source-service guard before attachments, numbering or creator
writes; callers must use the validated Planning operation. Both primary-only and
material-list forms are regression-tested with complete relevant table counts,
receipt identity, physical quantity and reservation unchanged. This is deliberate
refusal, not support or implicit factory rerouting. Existing generic central
inputs remain unchanged. The full creation caller ledger is Planning client,
Planning branded, legacy generic (new ECO inputs refused), and separate Usluga
(its own non-inventory DTO). Repository MCP code contains info/notifications but
no independent production writer; external callers of the generic HTTP contract
receive the same explicit refusal.

Root's actual ERP save/confirmation then passed6.5kg/10pieces/one ECO bundle,
with persisted physical100->93.5, reserved10, central0, no central movement and
exactly one ECO consume6.5. The immediately displayed source balance was stale
until reload because submit refreshed production state but not the stock reads.
The actual successful submit now revalidates the three existing source queries
(filtered central, all central, authorized ECT projection), preserving selected
identity/manual choice. Successful deferred physical usage and eligible Nastil
delete/reversal use the same bounded refresh; refused writes, metadata-only edits
and Usluga do not request these stock refreshes. No GET writes or accounting change.

The new test executes the actual submit/deferred/delete/helper functions extracted
from CuttingPage, delays write acknowledgment, and proves no refresh before
success, exactly three existing source revalidations afterward, visible fixture
83.5available/93.5physical/10reserved, preserved selected/manual state, and no
refresh on refusal/metadata/Usluga. It runs with the existing frontend build
contract. Root owns actual ERP post-write screen rerun on the final combined
candidate; this handler regression is not a claim of that pending full UI check.

## Typed list boundary correction from the full backend run

Root's broad backend run exposed four existing direct list-route readers that
require attribute access (`row.id`, `row.order_no`, `row.sales_order_no`). The
initial routing helper returned dictionaries and broke that internal boundary
despite correct HTTP JSON. It now explicitly returns
`list[ProductionOrderListOut]`, validating each ORM row and copying only the
canonical routing projection into the typed result. HTTP list/page shape and
facts remain identical; no writes or new query are introduced by this correction.

Pagination tests retain typed attribute readers. The query budget explicitly
accounts for the previously added single routing projection: four selects for a
counted page and three for a plain list, with exactly one WorkOrder query for
1/50/401-order fixtures. The helper regression additionally requires every result
to be a real `ProductionOrderListOut`, preserving order IDs. Pagination plus
routing regression modules pass9 cases; Ruff is clean. Root owns the exact
combined broader rerun and independent final review.
