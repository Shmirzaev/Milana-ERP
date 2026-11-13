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
