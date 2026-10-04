# Team bug tracker — clone_main



**Updated: 2026-10-04. Target: `clone_main`.** **111 implementation rows** = 73 open + 1 blocked on a decision (D4b) + 32 completed owner-approved changes + 5 partial, plus **7 operations follow-ups** and **6 pending decisions** in the Shavkat queue below. **Ismail has 0 open implementation rows.** **All 127 develop audit findings are accounted for below**; tasks and original findings are different counts. Assessments are source-based; current regressions, performance measurements and live operations remain to be verified. **`clone_main` is shared**: other engineers merge into it concurrently, so re-sync and rebase before landing and re-run affected tests afterwards. Counts are derived from the per-row Tracking cells; if a header total stops matching `open + blocked + done + partial`, the header is stale and the rows win.



## How the team updates this file



- **Claim:** change Tracking to `In progress · @owner · issue/PR link` before starting; one responsible owner per task. Use `Open`, `In progress`, `Review`, `Blocked`, `Needs review` or `Done`.

- **Add:** use a stable unique ID (`BUG-001`, then the next free number), P1/P2 priority, affected branch/commit, reproducible steps, actual vs expected behavior, and source/test evidence. Check for duplicates; put long logs/reproduction in a linked issue. Keep this file as the shared index.

- **Fix:** name task IDs in the PR targeting `clone_main`; record dependencies/blockers and relevant test results. Change Tracking to `Review · @owner · PR link` while awaiting review. Reproduce source-only candidates before claiming a confirmed runtime failure.

- **Done:** after the reviewed fix lands on `clone_main` and regressions pass, move the same row to Completed with `Done · @owner · merged PR/commit · test evidence`. Retain its ID/history. Reopen the same row if it regresses. Done means fixed on this branch; record deployment separately.

- Update only affected rows and the date/counts through a PR; reconcile concurrent edits before merging. `—` means unassigned; owner/PR names must not be invented. GitHub closing keywords only auto-close linked issues on the default branch, so verify issue closure after a `clone_main` merge.



**Numbering:** `N` counts rows within each list; P1/P2 share numbers 1–111. Stable task IDs remain unchanged. Audit coverage retains the original finding numbers 1–127, including repeated IDs.



**Source paths:** `B:` = `backend/app/`, `F:` = `frontend/src/`. Earlier locations refer to `942801b0`; newly reviewed locations refer to `38a56bbc`. Follow the current function when lines move. Develop hashes/tests are recovery references, not clone_main test results. **Present** in audit coverage means core source survived; it does not mean fully verified Done.



## Team ownership



Assignments set on 2026-10-03. Each implementation task has one engineering owner responsible for its backend, frontend and regression checks. Names below are team names, not inferred GitHub handles. Open counts below are live per-status tallies of the Tracking cells, not the original allocation; all 110 implementation tasks started Open, and 25 are now Done and 4 Partial.



| Owner | Responsibility | Open implementation tasks | Operations follow-ups |

| --- | --- | --- | --- |

| **Dilmurod** | People and platform: payroll, attendance, HR, authentication, admin security, tasks/notifications and shared API/retry infrastructure. | **38** | `OPS04`, `OPS10`, `OPS11` |

| **Ismail** | Stock and commercial: inventory, purchasing, sales, finance, catalog, schema/migration tooling and uploads. | **0** | `OPS02`, `OPS03` |

| **Mirshoir** | Production and fulfillment: production, cutting, sewing, bundles, packages, finished goods, forecasting, traceability and shipment package locking. | **35** | `OPS01`, `OPS07` |

| **Shavkat** | Business logic decisions and expected business behavior only. Clarifies policy and acceptance criteria with the responsible engineer; no engineering, migration, testing or operations tasks assigned. | **0** (5 decisions queued below) | None |



The Tracking cells below are the authoritative per-task assignments; refer to stable task IDs in PRs. Counts are an initial allocation, not equal effort estimates. Completed rows retain their historical ownership.



### Work order and shared changes



- Address P1 correctness and authorization before optimizing the same paths; use focused PRs targeting `clone_main` and review by another engineer.

- **Ismail:** finish `ST01` before `UI03-PURCHASE` and `FN07-PURCHASE-QUANTITY`; finish `DB03-MODEL` before `DB03-IMPORT-CORRECT`, `DB03-IMPORT-OLD` and `DB03-IMPORT-REVIEWED`.

- **Dilmurod:** coordinate `AT06` with `PERF31`; keep payroll period/label/record lock ordering consistent across `PY02` and `PY05`. Own the shared `FN06` retry contract and coordinate its callers with Ismail and Mirshoir.

- **Mirshoir:** coordinate `PERF04` and `PERF13` receipt contexts; keep package evidence, damage/claims, receipt retries and bulk package operations consistent.

- **Ismail and Mirshoir:** agree on shared inventory/package helper changes, stock lock order and edits to sales/shipment paths before implementation. Ismail owns `PERF24`/`PERF26`/`PERF34`; Mirshoir owns `PERF27`. Tracked as **D5**; recommend adopting the existing `key_share=True` → `FOR NO KEY UPDATE` order at all four call sites.

- Cross-area tasks keep one owner: Ismail coordinates `PERF40` HR upload changes with Dilmurod; Mirshoir coordinates `PERF32` Data Console changes with Dilmurod.

- Shavkat records business decisions for the pending policy groups below. Engineers propose and validate technical contracts, locks, migrations, backups and rollback; existing approval requirements remain. A named decision owner does not resolve a pending policy or authorize a production change.



## P1 — authorization and stock/payroll/money correctness



| N | ID | Current bug | Required fix | Source; develop reference | Tracking |

| --- | --- | --- | --- | --- | --- |

| 1 | **API02** | Task references/states bypass validation and scope. | Validate task states/dates/references; enforce target permission/factory scope and lock referenced rows. | `B:schemas/tasks.py:8`; `22593e7`, `31350dc`, `73d7ca4` | Open · Dilmurod |

| 111 | **RES-PLAN-ARCHIVE** *(raised by PERF03)* | Reservation planning offers **archived** stock batches as fulfillment candidates, and applies no `qc_status` filter. | Decide the eligibility rule, then exclude ineligible batches from the candidate set. **Split into two decisions — D4a is clear, D4b needs a business answer.** | `B:services/inventory.py:499-505` (candidate query filters only `item_id.in_(chunk), quantity > 0`); contrast `B:services/cutting_material_assignment.py:49` and `B:api/routes/inventory.py:591`, which both exclude archived; `B:api/routes/eco_transfers.py:135` is what sets `archived_at`; `B:models/inventory.py:44` qc_status CHECK + `:68` default | **Blocked · Shavkat (D4b only) · Ismail (engineering)** · found while fixing PERF03 ([`95de2c02`](https://github.com/Shmirzaev/Milana-ERP/commit/95de2c02)); behaviour **deliberately preserved and pinned with a test** rather than silently tightened, because eligibility is a business rule. **D4a — archive filter, no business decision needed, recommend fixing:** two production callers already exclude archived batches and the planner does not, so this reads as a gap rather than intent, and an Eco custody dispatch is precisely what sets `archived_at`. Recommending `StockBatch.archived_at.is_(None)` to match both siblings. **D4b — `qc_status` filter, genuinely a business question:** `qc_status` is `('pending','passed','failed','rejected','hold')`, `NOT NULL`, **defaulting to `'pending'`** (`models/inventory.py:44,68`). A survey of `backend/app` found **no production read path filters on `qc_status` at all** — every `qc_status="passed"` occurrence is test or seed data, so the attribute is currently unread by business logic. That cuts both ways and Shavkat should decide explicitly: **(a)** exclude only `failed`/`rejected`/`hold`, letting `pending` stay eligible; or **(b)** require `passed`, which would make **every newly received batch ineligible until someone manually marks it passed** — a large silent behaviour change we should not assume. **Recommend (a).** Engineer: Ismail; change is a predicate in one query plus regression coverage either way. |

| 2 | **API05** | Forecast/report routes read and mutate across factories. | Apply effective per-factory view/manage grants and model attribution to forecasts/reports. | `B:api/routes/forecasting.py:47`; `064be49`, `fc450a5`, `0e9bb6ba`, `feb7415f`, `49d3c200`, `4a5c0b2b` | Open · Mirshoir |

| 3 | **API06** | Editable name/email grants purchasing-price access. | Remove name/email privilege fallbacks from backend and frontend; require explicit permission. | `B:services/price_calculation.py:29`; `B:core/deps.py:164`; `F:lib/priceCalculationRequests.ts:60`; `d89059eb` | Done · @Ismail · [`e808891a`](https://github.com/Shmirzaev/Milana-ERP/commit/e808891a) · reproduced 17 failed/7 passed → 24 passed; +13 user-access, +3 price-workflow; frontend check fails on base, passes on fix; independent review APPROVE. **Deploy prerequisite:** staff relying on the name fallback need an explicit `price_calculation.purchasing` grant. |

| 4 | **AT01** | Failed/unknown device events can establish attendance. | Apply shared accepted-result filtering to overview/usage/export and HR; preserve raw events and legacy NULL-result compatibility. | `B:api/routes/attendance.py:422`; `B:api/routes/hr_workspace.py:452`; `6afe7eb`; [regression](https://github.com/Shmirzaev/Milana-ERP/blob/2f549f9b202ef1a66ed6ffe17be07b5497ccdeab/backend/app/tests/test_attendance_event_results.py) | Open · Dilmurod |

| 5 | **AT05** | HR attendance uses UTC days and unsafe legacy hour conversion. | Align Tashkent dates/default day, use one factory-settings read and bounded safe hour overrides/defaults; preserve factory isolation. | `B:api/routes/hr_workspace.py:449`; `B:api/routes/attendance.py:407`; `76388c2`; [regression](https://github.com/Shmirzaev/Milana-ERP/blob/2f549f9b202ef1a66ed6ffe17be07b5497ccdeab/backend/app/tests/test_hr_attendance_validation.py) | Open · Dilmurod |

| 6 | **AT06** | Concurrent/stale attendance imports race identities and overwrite newer state. | Port API/connector shared locks, refreshed rows and durable source snapshot/checkpoint gates together; preserve factory/device-token scope, events, rollback and legacy transition. | `B:api/routes/attendance.py:165`; `connectors/hikvision_attendance/read_only_connector.py:474`; `853d2e4`, `b13bfdc`, `135d669`; [regression](https://github.com/Shmirzaev/Milana-ERP/blob/2f549f9b202ef1a66ed6ffe17be07b5497ccdeab/backend/app/tests/test_attendance_import_races.py) | Open · Dilmurod |

| 7 | **DB01-ADJUSTMENT** | Forced stock corrections leave reservations underbacked. | Enforce reservation floors on both item and batch correction, including force=true. | `B:api/routes/inventory.py:685`; `69ceef4e` | Done · @Ismail · [`56dded34`](https://github.com/Shmirzaev/Milana-ERP/commit/56dded34) · both item and batch floors fixed (donor covered item only); 5 failed/8 passed → 13 passed; +83 adjacent, +233 domain; force still permits multi-batch, linked-record and delete overrides; independent review APPROVE. |

| 8 | **DB01-CONSUMPTION** | Stock consumption accepts incompatible catalog/request/batch units. | Validate catalog/request/all-batch units before consuming any stock. | `B:services/workflow.py:400`; `B:services/workflow.py:442`; `5b4ac7c0` | Open · Mirshoir |

| 9 | **DB02-WO-STATUS** | Generic work-order PATCH bypasses explicit status transitions. | Reject changed status in generic PATCH; retain metadata no-ops and explicit transition commands. | `B:api/routes/production.py:1607`; `9bdf79c4` | Open · Mirshoir |

| 10 | **FN04** | Concurrent invoice routes can bill one order twice. | Lock/refetch the SalesOrder before invoice existence checks in both finance and sales routes. | `B:api/routes/finance.py:65`; `B:api/routes/sales.py:1985`; `3881177e`, `6843712f` | Done · @Ismail · [`8e42807e`](https://github.com/Shmirzaev/Milana-ERP/commit/8e42807e) · reproduced 2 invoices per order on unfixed base → 9 passed incl. 4 real two-connection PostgreSQL race tests; +110 finance, +143 sales; independent review APPROVE. **Residual:** `partners.py:195` and `services/workflow.py:624` still create invoices without this lock; `invoices` has no unique `sales_order_id`. |

| 11 | **FN06** | Generic retry keys replay across callers and race writes. | Scope replay to caller/key/payload and serialize same-key writes across every generic replay site. | `B:services/idempotency.py:31`; `c21e50bb` | Open · Dilmurod |

| 12 | **FN07-ADJUSTMENT** | Payroll adjustment amount/type/reason validation is incomplete. | Validate finite cent-accurate amounts, supported adjustment types and stored reason length. | `B:schemas/payroll.py:456`; `B:api/routes/payroll.py`; `60f82357`, `4ae84350` | Open · Dilmurod |

| 13 | **FN07-INVOICE** | Invoice/payment money inputs can exceed precision/storage bounds. | Use storage-bounded Decimal amounts; reject nonfinite, overflowing and sub-cent inputs before writes. | `B:schemas/sales.py:162`; `B:api/routes/finance.py:74`; `5a68d122`, `6304934b` | Done · @Ismail · [`3b07db93`](https://github.com/Shmirzaev/Milana-ERP/commit/3b07db93) · real column types verified (NUMERIC(14,2) + CHECK constraints), not assumed; reproduced 21 failed with inf/NaN/overflow/sub-cent accepted and a live PG overflow → 37 passed; the FN04 order lock is preserved; merged-branch finance/invoice/payment/sales slice 265 passed. **Note:** rejecting `inf`/`NaN` directly made FastAPI's own 422 body unserializable, so the error `loc` is remapped. |

| 14 | **FN07-PURCHASE-QUANTITY** | Purchase/receipt quantity fields lack finite/storage bounds. | Restore finite/storage quantity bounds after ST01; retain approved unit-cost rounding. | `B:schemas/purchasing.py:77`; `3e75ca62` | Done · @Ismail · [`f539b4e2`](https://github.com/Shmirzaev/Milana-ERP/commit/f539b4e2) · all three quantity inputs bounded to 9999999999.9999 with non-finite rejection, plus a Decimal running-total re-check so accumulation cannot overflow; reproduced 21 failed/1 passed → 22 passed; adjacent purchasing/receipt/material-roll/unit-cost slice 264 passed with PostgreSQL on, including the ST01 receipt tests. |

| 15 | **FN07-RECORD** | Freeform payroll records lack finite/storage money bounds. | Validate representable payroll record amounts before and after trusted enrichment. | `B:api/routes/payroll.py:121`; `50cbbe84`, `764af788` | Open · Dilmurod |

| 16 | **PY01** | Fast badge/work scans credit the previous employee. | Queue badge/work/manual selection in arrival order; do not credit work before badge resolution. | `F:app/(app)/payroll/scan/page.tsx:948`; `3881177e` | Open · Dilmurod |

| 17 | **PY02** | Payroll writes race period finalization. | Use shared refreshed period locks for all record writers and finalizers. | `B:api/routes/payroll.py:517`; `b285877b` | Open · Dilmurod |

| 18 | **PY03** | Scanner permission can issue caller-priced payable labels. | Require manage permission for payable label issuance/values; scanners use trusted issued labels. | `B:api/routes/payroll.py:2091`; `900641e7` | Open · Dilmurod |

| 19 | **PY04** | Unmatched work dates attach to the latest open period. | Use only the matching date period or no period; remove latest-open fallback in single/bulk paths. | `B:api/routes/payroll.py:540`; `adc79f77` | Open · Dilmurod |

| 20 | **PY05** | QR returns use a conflicting payroll lock order. | Use period -> label -> record lock order with fresh assignment checks for return/scan/finalization. | `B:api/routes/payroll.py:2907`; `a2082235` | Open · Dilmurod |

| 21 | **SEC04** | Disabled or revoked sessions still download model files. | Validate active user and token cutoff for model files; release the auth connection before streaming. | `B:main.py:378`; `3881177e` | Open · Dilmurod |

| 22 | **SEC05** | Sibling reset links survive a password change. | Lock the account and invalidate sibling reset links on every supported password rotation. | `B:api/routes/auth.py:286`; `3881177e`, `f35a62e6` | Open · Dilmurod |

| 23 | **SEC06** | Concurrent admin removals can remove the final admin. | Serialize PATCH/DELETE membership changes with audit-compatible NO KEY UPDATE locks. | `B:api/routes/admin.py:600`; `74a2973` | Open · Dilmurod |

| 24 | **SEC07-ASSIGNMENT** | Assignment deletion bypasses factory and used-output guards. | Check flow/work-order factory and used/output history under locks before deletion. | `B:api/routes/production_extra.py:392`; `3881177e`, `df14ad66` | Open · Mirshoir |

| 25 | **SEC07-FLOW** | Flow utilization exposes another factory. | Apply sewing-flow access checks to the direct utilization endpoint. | `B:api/routes/production_extra.py:483`; `40c681e` | Open · Mirshoir |

| 26 | **SEC08** | Raw admin console bypasses business and audit safeguards. | Block generic raw UPDATE/DELETE; allow only named audited repairs and soft-deactivation. | `B:api/routes/super_data.py`; `e7782ec`, `297d808`, `df1d08f` | Open · Dilmurod |

| 27 | **SEC09-PROXY** | Forwarded client/scheme headers lack explicit proxy trust. | Validate trusted CIDRs and ordered forwarded headers; ignore untrusted client/scheme claims. | `B:api/routes/auth.py`; `B:main.py`; `b926fba`, `f35a62e6`, `0ad74a69`, `4fee48be` | Open · Dilmurod |

| 28 | **SEC10** | Limited admin can delete a non-wildcard Super Admin. | Protect admin.super targets even when their permission list lacks wildcard. | `B:api/routes/admin.py:600`; `3881177e` | Open · Dilmurod |

| 29 | **ST01** | Purchase receipt retries add stock twice. | Add caller/order/payload-scoped receipt identity, replay and locking so retries create one receipt. | `B:api/routes/purchasing.py:168`; `3881177e`, `641c0580` | Done · @Ismail · [`6fb88ee3`](https://github.com/Shmirzaev/Milana-ERP/commit/6fb88ee3) + [`4bea7a6c`](https://github.com/Shmirzaev/Milana-ERP/commit/4bea7a6c) · reproduced 10 failed/3 passed → 13 passed; +323 adjacent; real PostgreSQL two-connection receipt-concurrency tests pass; independent review APPROVE, its `updated_at` finding fixed in `4bea7a6c`. **Depends on `UI03-PURCHASE`:** the frontend still sends no `Idempotency-Key`, so the receiving UI will keep double-adding until a key is sent. |

| 30 | **ST02** | Stock movement does not update or validate its batch. | Mutate batch and ledger atomically; validate item/unit/warehouse, claims and Eco custody. | `B:api/routes/inventory.py:1293`; `3881177e` | Done · @Ismail · [`c40c9dfb`](https://github.com/Shmirzaev/Milana-ERP/commit/c40c9dfb) · all six defect classes reproduced on the base (21 failed, every invalid request returned 201 and committed a bogus ledger row) → 24 passed; the batch was only ever used to satisfy the FK, never locked, compared or decremented; 148 adjacent passing and the DB01 guard still 13 passed with all three surviving `and not force` overrides intact; two real two-connection PostgreSQL tests including a reserve-committed-mid-wait rejection. **Behaviour change to confirm with the UI owner:** `adjustment` now increments the batch, and only a whole unreserved batch can be transferred, since a batch has one location. |

| 31 | **ST03** | Batchless movements leak into other warehouse balances. | Scope batchless movement aggregation by warehouse and transfer direction without double counting. | `B:services/inventory.py:80`; `3881177e` | Done · @Ismail · [`19c42c74`](https://github.com/Shmirzaev/Milana-ERP/commit/19c42c74) · batches were filtered by warehouse but batchless movements were aggregated across every warehouse, so a return into B raised A's balance and an issue out of B debited A; `transfer` appeared in neither direction set and was dropped entirely; reproduced 4 failed / 11 passed on the base, where the 11 are controls proving the simple paths already worked → 15 passed; adjacent stock/reservation/inventory/accessory/movement/cutting/warehouse slice with PostgreSQL on: 741 passed, 0 failed, 0 skipped. |

| 32 | **ST06** | Concurrent accessory returns share an unlocked allowance. | Lock the shared issue allowance before validating accessory returns and storing replay. | `B:api/routes/inventory.py:865`; `712ccf1` | Done · @Ismail · [`ef9d2e48`](https://github.com/Shmirzaev/Milana-ERP/commit/ef9d2e48) · the allowance turned out to be an **aggregate**, not a row — issued movements plus manual issues minus every recorded return — so the production order is the narrowest row that scopes all of it; locked with `FOR NO KEY UPDATE` before validation and before the replay store, which is what the row asks for; reproduced on real PostgreSQL as **14 returned against 10 issued** → 3 passed, with one backend genuinely parked on the other's lock; 37 DB01/ST02 regression guards green, 146 adjacent passing. **Residual (pre-existing, out of lease):** a generic `StockMovement` writer that sets `reference_type='ProductionOrderAccessoryReturn'` directly still bypasses this lock. |

| 33 | **ST09** | Damaged packages remain reservable and damage races claims. | Recheck damage status under shared package/stock locks; block damage of reserved/linked packages. | `B:api/routes/finished_goods.py:184`; `B:services/packages.py:1203`; `9e336ce`, `f40f4e4` | Open · Mirshoir |

| 34 | **ST11** | Item-only and mixed reservations can overclaim stock. | Lock common item capacity for item-only and mixed batched reservations; preserve lock order. | `B:services/inventory.py:475`; `3881177e` | **Partial · @Ismail** · [`321240df`](https://github.com/Shmirzaev/Milana-ERP/commit/321240df) · the locking half is done and proven: one shared pre-pass locks batches then items in a global order with FOR NO KEY UPDATE, and the two paths can no longer bypass each other; 4 failed on base (20 reserved against 10 on hand) → 4 passed, with two-connection PostgreSQL 17.11 proof, 300 adjacent passing. **Still open — needs Shavkat's decision:** serializing the paths does not cap a batch-scoped reservation against item-scoped claims, because `available_stock_for_batch` counts only reservations carrying that `stock_batch_id`. An item-only claim of 10 plus a batched claim of 10 can still total 20 against 10 on hand, and no lock can close it. Whether a batched reservation must be capped by item-scoped claims is a business rule; the availability formulas were deliberately left untouched. |

| 35 | **UI03-PACKAGE** | Corrected package receipts remain blocked by pending retry state. | Restore durable cross-tab retry state and server reconciliation/tombstones, including changed-body/429 cases. | `F:lib/packageWorkflow.ts:58`; `B:api/routes/package_workflows.py:77`; `3ef1c83e`, `00567734`, `e2a6d8cb`, `3532e8e4` | Open · Mirshoir |

| 36 | **WF01** | Generic production PATCH changes internal fields/status. | Replace raw setattr PATCH with typed field/reference allowlist and legal workflow-status guards. | `B:api/routes/production.py:1003`; `859b7ca`, `d11fb7aa` | Open · Mirshoir |

| 37 | **WF02** | Generic work-order commands miss stage/factory boundaries. | Enforce stage authorization and factory scope on update/start/complete/block/unblock commands. | `B:api/routes/production.py:1601`; `84c322a`, `62a3544`, `d8cd060` | Open · Mirshoir |

| 38 | **WF03** | Ordinary packages can be created without production evidence. | Require packaging evidence for ordinary standard packages; preserve valid first-grade/batch receipts. | `B:services/packages.py:220`; `37258c7` | Open · Mirshoir |

| 39 | **WF08** | Waste sales overdraw capacity, close partial stock and lack safe retries. | Bound Decimal quantities/money, lock remaining capacity and restore scoped retry/reconciliation plus UI balance recovery. Preserve history; do not reactivate excluded business work. | `B:api/routes/waste.py:89`; `B:schemas/waste.py:46`; `6cb2d3a`, `2948674`, `c13d638`, `01e0ee1`, `5638b8a`, `24003a0e`, `8aebf877`; [regression](https://github.com/Shmirzaev/Milana-ERP/blob/2f549f9b202ef1a66ed6ffe17be07b5497ccdeab/backend/app/tests/test_waste_sale_integrity.py) | Done · @Ismail · [`96169417`](https://github.com/Shmirzaev/Milana-ERP/commit/96169417) · three defects in one path, all reproduced: `sell_waste` read the record with `db.get` and **no lock**, never compared the requested quantity to what was left, and set `status='sold'` after *any* sale. A partial sale (4 of 10 kg) stranded the remaining 6 kg permanently; 11 kg could be sold from a 10 kg record; two concurrent callers could both pass the status check and both sell, and a response lost after commit returned a misleading 400 on an already-sold record. Sales now serialize on the waste parent with `FOR UPDATE`, replay the caller-and-record-scoped `Idempotency-Key` before **and** after the lock, validate each partial sale against the remaining quantity, and close the record only at a zero remainder. The replay record is stored **in the same commit as the sale**, so a lost response retries into a replay rather than a second physical sale; a request with no key keeps its previous behaviour. Money/quantity bounded against the real column widths (NUMERIC(14,4)/(12,2)/(14,2)), not assumed. 14 failed / 2 passed → 16 passed; adjacent waste, disposal, audit and idempotency slice with PostgreSQL enabled: 201 passed, 0 failed, 0 skipped. |



## P2 — validation, reliability and performance



| N | ID | Current bug | Required fix | Source; develop reference | Tracking |

| --- | --- | --- | --- | --- | --- |

| 40 | **DB02-HR-STATUS** | Employee status writes accept unsupported vocabulary. | Validate newly supplied employee statuses while preserving historical read compatibility. | `B:api/routes/hr.py:21`; `bf364411` | Open · Dilmurod |

| 41 | **DB03-HR-PROFILE** | Employee profile JSON lacks bounded shape/depth validation. | Validate profile shape/hours and 16 KiB/16-level limits; preserve unchanged legacy values. | `B:api/routes/hr.py:26`; `ada93f89`, `708475d2` | Open · Dilmurod |

| 42 | **DB03-IMPORT-CORRECT** | Old-ERP correction script bypasses model JSON bounds. | After DB03-MODEL, restore b097037e validator guard before correction-script JSON writes. | `backend/scripts/correct_old_erp_models_local.py:2111`; `b097037e` | Done · @Ismail · [`53bedb59`](https://github.com/Shmirzaev/Milana-ERP/commit/53bedb59) · one ORM write, guarded at the single choke point in `plan_model_correction`, so the dry-run plan and the apply that persists it are both covered and a future caller cannot bypass it. Grandfathering passed deliberately: the write is gated on `details_changed`, so a changed document is always fully checked and the exemption can never grow a row. 8 failed / 4 passed → 12 passed; 117 green across six modules. Corrected an assumption in the brief: `NaN` does **not** silently become `null` on SQLite or PostgreSQL jsonb — it persists as a bare token that is not valid JSON per RFC 8259, which is the real defect. |

| 43 | **DB03-IMPORT-OLD** | Old-ERP import script bypasses model JSON bounds. | After DB03-MODEL, restore 6a902d7a guard before old-ERP import JSON writes. | `backend/scripts/import_old_erp_models_local.py:2412`; `6a902d7a` | Done · @Ismail · [`8fcde82e`](https://github.com/Shmirzaev/Milana-ERP/commit/8fcde82e) · reuses the shared validator with no second copy, translating `HTTPException` into the script's own `MigrationError` so `main` and `apply_plan` keep their existing rollback path. **Deliberately not grandfathered**, unlike the correction script: an import is not re-submitting a document it read, it is building the authoritative one from a legacy payload, so "the document happens to be unchanged" is exactly the case in which an unbounded payload would stay blessed across re-runs. |

| 44 | **DB03-IMPORT-REVIEWED** | Reviewed model import bypasses shared JSON bounds. | After DB03-MODEL, restore 3544b1f4 guard on merged/final reviewed-import details. | `backend/scripts/migrate_reviewed_old_erp_models_production.py:1773`; `3544b1f4` | Done · @Ismail · [`1ff9b61a`](https://github.com/Shmirzaev/Milana-ERP/commit/1ff9b61a) · this is the row's real hole and it is specifically a **merge** hole: two independently legal documents (40 042 B and 40 072 B) merge to 80 114 B, over the 64 KiB ceiling, and size/depth/finite-value are properties of the *assembled* document. An input-only check, or one placed before the merge, misses it entirely. Guarded **both** pre-flight and per-record: pre-flight makes the migration refuse to compile so an illegal plan never becomes reviewable or approvable, per-record catches compile/apply drift; a per-record guard alone would have let `apply_plan` materialise media and mutate earlier rows before reaching the offending record. Preflight runs after the plan hash and does not mutate the plan, so the reviewed-plan chain still verifies. 11 failed / 3 passed → 14 passed; 361 adjacent. **Improved on the donor:** its default would have grandfathered a brand-new `create_model` row whenever a receipt happened to be a no-op — rejected in favour of plain `None`. |

| 45 | **DB03-MODEL** | Model details JSON lacks size/depth/established-shape validation. | Restore common size/depth/shape validator across catalog writers, clones/variants and family saves. | `B:schemas/catalog.py:221`; `B:api/routes/catalog.py`; `fa3ba201` | Done · @Ismail · [`71383580`](https://github.com/Shmirzaev/Milana-ERP/commit/71383580) · six writers covered, not one: catalog create/update, clone, variant create/update, family paid-operations save, and the identity rewrite that fires whenever `general.model_no` changes. 64 KiB measured in **UTF-8 bytes of the serialized form** (40k Cyrillic chars = 80 KB rejected, so it is genuinely bytes), depth ceiling 16 against real documents at ~5. Depth walk is **iterative** and survives depth 1,000,000 with a clean 422, 62,500x the ceiling. Reproduced 12 failed / 3 passed → 15 passed; 179 assertions green across 179 adjacent. Sharpest base defect: a deep document was **committed to the database and only then died serializing the response**. **Corrects the donor's reading:** the "established shape" comparison is *grandfathering*, not key-preservation — it returns early for an unchanged legacy document so a pre-existing oversized row stays editable, and never raises on a key difference. |

| 46 | **DB03-PAYROLL-SNAPSHOT** | Payroll employee/work snapshots are unbounded JSON. | Validate 16 KiB/16-level employee/work snapshots before and after trusted enrichment. | `B:api/routes/payroll.py`; `4f4efcb8` | Open · Dilmurod |

| 47 | **DB05** | Migration impact preview/preflight tooling is missing. | Restore read-only predecessor-gated previews adapted to clone migration lineage. Never rerun old destructive/grant migrations; require exact impact, backup and owner approval for changes. | `backend/app/migrations/preflight.py (missing)`; `scripts/migration_preflight.py (missing)`; `backend/alembic/versions/0055_delete_mistaken_po15.py:52`; `d23738c7`, `0df2c172`, `2901212a`, `6118771b`; [regression](https://github.com/Shmirzaev/Milana-ERP/blob/2f549f9b202ef1a66ed6ffe17be07b5497ccdeab/backend/app/tests/test_migration_preflight.py) | Partial · @Ismail · [`6681c61e`](https://github.com/Shmirzaev/Milana-ERP/commit/6681c61e) — tooling done, still D2-gated. A read-only, predecessor-gated preflight now exists (`backend/app/migrations/preflight.py` + `scripts/migration_preflight.py`): it resolves THIS branch's lineage at call time rather than assuming one, refuses unless the database sits at the target's real `down_revision`, rewrites the destructive `DO $$` block into read-only `SELECT count(*)` (resolving `SELECT id INTO` to a scalar subquery and stripping `FOR UPDATE`, which a READ ONLY transaction rejects), and **refuses rather than guessing** on unbounded deletes or unresolved variables. Read-only is proven at the database level, not by inspection: an `UPDATE` inside the preview transaction raises, and row counts plus `alembic_version` are unchanged afterwards. On real PostgreSQL 17.11 the worker actually RAN 0055 and got `Refusing to delete PO-2026-000015 because production activity now exists`, independently confirming the self-guard previously inferred by reading source. **Still open, still D2:** nobody should run a destructive migration on the strength of the tooling without owner approval. **Unverified:** the PL/pgSQL parser is proven against 0055's shape only; other destructive migrations will raise `PreflightUnsupported` rather than preview until exercised. |

| 48 | **DB06** | Fresh schema can create equivalent duplicate FKs and unique indexes. | Use signature-based bootstrap guards and avoid redundant new-schema indexes; verify real PostgreSQL catalog/plans before any approved deployed cleanup or candidate index migration. | `backend/alembic/versions/0002_sales_order_planning_estimate_fields.py:35`; `backend/alembic/versions/0025_material_reservations.py:57`; `a590222f`; [regression](https://github.com/Shmirzaev/Milana-ERP/blob/2f549f9b202ef1a66ed6ffe17be07b5497ccdeab/backend/app/tests/test_fresh_migration_bootstrap.py) | Partial · @Ismail · [`6681c61e`](https://github.com/Shmirzaev/Milana-ERP/commit/6681c61e) — forward guard done, existing schemas still D2-gated. `index_signature` hashes table + ordered columns + uniqueness + partial predicate, so a unique constraint and a unique index over one column genuinely collide; the guard then skips the redundant one, and `find_equivalent_duplicates` is a read-only catalog audit for D2. **This row is deliberately NOT closed.** The guard prevents the duplicate being created going forward; it does **not** remove the duplicate already present in existing schemas, because that cleanup is precisely the approved deployed change D2 gates. `test_postgres_0025_fresh_bootstrap_still_emits_the_duplicate` pins that as current reality rather than asserting a clean chain. No already-applied migration was edited — `0025` is history and production has run it. |

| 49 | **DB07** | Order/bundle numbering exhausts its four-digit namespace. | Expand monotonic numbering beyond 9999 without recycling issued identities; preserve locks/aliases. | `B:services/numbering.py:79`; `b350c4f`, `11aabc1` | Open · Mirshoir |

| 50 | **DB08** | ORM metadata disagrees with the existing migrated schema. | Align legacy model-less sales/Beyka ORM with existing clone migrations; test real migrated PostgreSQL. | `B:models/sales.py:51`; `1141d40` | **Partial · @Ismail** · [`187933b9`](https://github.com/Shmirzaev/Milana-ERP/commit/187933b9) + [`0b0b6a78`](https://github.com/Shmirzaev/Milana-ERP/commit/0b0b6a78) + [`25192d17`](https://github.com/Shmirzaev/Milana-ERP/commit/25192d17) · **The sales and Beyka halves are now Done.** *Sales:* shipped migration `0071_model_less_legacy_sales` had altered `sales_order_items` (model_id nullable, `finished_goods_stock_id` with named FK+index, `source_model_code`, `source_model_name`, plus a CHECK that Alembic autogenerate does not compare) and the ORM never absorbed it — reviewed drift entries 90-95. No migration written or altered; the database already had that shape, so the ORM was the wrong side. Verified against a **real migrated PostgreSQL 17.11** running the full chain 0001-0135, not a `create_all` database; the CHECK is proved enforced. Reviewed drift baseline edited deliberately 126 → 120 (six removed verbatim into a `resolved_by_db08` block, zero added). *Beyka:* migration `0076_cutting_beika_usage` created `cutting_beika_material_usages` and **no ORM class or relationship was ever added**, which was not inert — `services/traceability.py` reads `row.beika_materials` through a defensive `getattr(row, "beika_materials", None)`, so the attribute was always missing, the list always empty, and Beyka traceability silently fell back to the record's `beika_kg` total, dropping every per-batch usage the database was already storing **without anything raising**. `CuttingBeikaMaterialUsage` now mirrors the migrated table (both positive checks, both uniqueness rules, the CASCADE FK, the `unit` server default) with the same ordering, cascade and `lazy="selectin"` as the sibling `materials` relationship. The test reads migration 0076's own definition and compares against a real PostgreSQL table, because SQLite `create_all` builds the database *from* the ORM and a missing class cannot appear as drift. **Still open (23 entries):** HR indexes, `packages`/`package_items` nullability and `sewing_replacement_requests`. **`id`/`created_at`/`updated_at` were deliberately left alone** — they come from the shared `PkMixin`/`TimestampMixin` whose `DateTime` is timezone-naive while the migrations write TIMESTAMPTZ, a divergence that applies to every table and is not this row's to change. |

| 51 | **FN07-HR-SALARY** | Employee salary values lack storage validation. | Reject nonfinite, negative and column-overflow employee salaries before create/update. | `B:api/routes/hr.py:21`; `15833133`, `dd03309c` | Open · Dilmurod |

| 52 | **OPS05** | Readiness ignores a failed required shared store. | Probe PostgreSQL and required shared store under one bounded, single-flight readiness deadline. | `B:main.py:499`; `c275be7` | Open · Dilmurod |

| 53 | **OPS06** | Recovery tooling cannot verify paired database/upload backups. | Add paired DB/upload manifest verification for dump identity and missing/changed/extra files. | `scripts/storage_recovery_manifest.py (missing)`; `13f5994` | Open · Dilmurod |

| 54 | **OPS08** | Runtime/dependency hardening from develop is absent. | Review PyJWT/runtime migration; verify legacy tokens and run fresh dependency/built-image scans. | `B:core/security.py`; `frontend/Dockerfile`; `.github/workflows/ci.yml`; `06705b9`, `1896408`, `f288ada`, `f0a1536` | Open · Dilmurod |

| 55 | **OPS09-WEB** | Production scripts lack nonce CSP and reliable HTTPS headers. | Restore nonce CSP/layout and trusted HTTPS/HSTS handling; keep 1C retired. | `frontend/next.config.js:32`; `aa8fac1`, `f35a62e6`, `0ad74a69`, `4fee48be` | Open · Dilmurod |

| 56 | **PERF01** | Package list still queries model/assets/BOM per row. | Preload model/asset/BOM contexts once and pass them into package serialization; preserve returns and QR repair. | `B:api/routes/packages.py:110`; `B:api/routes/packages.py:530`; `3881177`; [regression](https://github.com/Shmirzaev/Milana-ERP/blob/2f549f9b202ef1a66ed6ffe17be07b5497ccdeab/backend/app/tests/test_package_query_growth.py) | Open · Mirshoir |

| 57 | **PERF02** | Accessory queue computes every candidate before paging. | Restore set-based PostgreSQL eligibility/status/count before LIMIT and bounded projections; preserve exact totals, units, returns/manual aliases and scope. | `B:api/routes/inventory.py:1030`; `B:services/inventory.py:1438`; `2c30d5d`, `704abef`, `3a74e5a`, `74211ab`, `90b7f21`; [regression](https://github.com/Shmirzaev/Milana-ERP/blob/2f549f9b202ef1a66ed6ffe17be07b5497ccdeab/backend/app/tests/test_accessory_request_postgres.py) | Done · @Ismail · [`dbadfad7`](https://github.com/Shmirzaev/Milana-ERP/commit/dbadfad7) · the queue built a full accessory issue plan per candidate production order (BOM requirement, issued/returned aggregation, per-line available stock) and only then sliced the page in Python. Statement counts via `before_cursor_execute` on PostgreSQL 17.11 at `page_size=5`: 4 candidate orders **243 → 2**, 40 candidates **1143 → 2**, with exact totals unchanged at 46 and 225. One set-based statement now computes eligibility, the EPSILON status ladder, ordering, the count and the bounded projection before `LIMIT/OFFSET`; the per-order path is kept verbatim as the non-PostgreSQL dialect branch, so the SQLite suite is untouched. **Four fidelity points where live code beat the donors, and each would have shipped a wrong number:** donor `90b7f21` **omitted the rounding entirely** — live code does `round(max(0.0, required - issued), 4)`, and Python rounds the exact binary value half-to-**even** while PostgreSQL's `round(numeric, 4)` rounds half-**away from zero**, so half steps are detected in float8 (a non-negative double is a half step iff it is `odd / 32`) and half-to-even is applied, pinned by `0.78125 → 0.7812` and `3.90625 → 3.9062`, which round-away-from-zero gets wrong. A bare `1.0 + waste / 100.0` resolves through PostgreSQL's numeric rules and returns `Decimal` (`0.5*5*1.33` is Python `3.325` but SQL `3.325000…`), so every literal is cast to `double precision`. Donor substituted a normalized/transliterated model-code match, but live search is a plain substring over all seven fields, so `mdl-01` must still hit `MDL-01`. And an item-less manual issue registers under **two alias keys**, reaching a matching requirement twice — reproduced deliberately rather than "fixed", because changing it would alter issued stock. Nine golden payloads **captured from the unfixed code** (default, paged, `include_complete`, three search variants, single order, model filter) all compare identical after, covering pcs/metre, linked and label-only aliases, returns and BOM size/colour matching. The diff removes no line from `_lock_batch_query`, `_lock_item_query`, `_lock_reservation_resources` or any stock/reservation helper; ST02/ST03/ST06/ST11 all pass, and 6 PG tests skip loudly when the URL is unset. **Two pre-existing quirks deliberately preserved and flagged rather than changed:** the alias double-count above, and search ordering pinned with `COLLATE "C"` so it matches the code-point Python sort instead of depending on database locale. |

| 58 | **PERF03** | Reservation planning repeats stock/claim/candidate reads. | Restore chunked balance/reference maps and exact-batch candidate indexes; preserve FIFO, eligibility, units, coverage and archive/Eco rules. | `B:services/inventory.py:387`; `B:services/inventory.py:321`; `8671636`; [regression](https://github.com/Shmirzaev/Milana-ERP/blob/2f549f9b202ef1a66ed6ffe17be07b5497ccdeab/backend/app/tests/test_reservation_plan_query_growth.py) | Done · @Ismail · [`95de2c02`](https://github.com/Shmirzaev/Milana-ERP/commit/95de2c02) · `reservation_plan_for_production_order` walked its requirement rows and re-asked the database the same things: a candidate-batch query per row, **one `reserved_stock_for_batch` aggregate per candidate batch inside that loop**, a fresh current/available/reserved pair per row, and the reservation rows read twice for the two coverage maps. Measured on PostgreSQL with 4 then 16 items (two units each): candidate reads **8→32 → 1**, claim reads **30→114 → 3**, ledger reads **16→64 → 1**, total statements **76→280 → 12**, and candidate rows fetched **48/192 → 24/96 — the unfixed code fetched every candidate batch exactly twice**. Three chunked maps (`_PLAN_CHUNK = 400`, matching PERF25's `_REFERENCE_CHUNK`) now read each table once per chunk, and `_covered_reservation_quantity` became a thin wrapper over `_covered_reservation_columns`, so the entity read and the column read cannot drift apart. **Donor `8671636` contradicted live code in three places and live code won:** it cast through `float()` *and* summed in SQL, where live code hydrates `Numeric(14,4)` as `Decimal` and converts per row, so accumulation stays bit-identical; its `_BULK_STOCK_CHUNK_SIZE` does not exist here; and it relied on dict insertion order for FIFO, so the ordering was made explicit in SQL. **A rows-based growth assertion was itself wrong at first** — "rows must not scale" fails even on fixed code, because candidate rows legitimately scale with item count — so it asserts the exact invariant instead: *each candidate batch is fetched once*, which separates 2× duplication from exactly 1×. FIFO is proven with batches inserted newest-first plus a same-date tie broken by `id`; eligibility is asserted **not tightened**; units are proven with one item planned in two units yielding two independent rows on disjoint batches. No lock was added, removed or reordered, and no leaf helper changed: post-rebase every `_lock_*` and `current_stock_for_item` body is **byte-identical**. 10 new tests pass and skip loudly; **83 targeted and 627 broad post-rebase**. **Unrelated finding, deliberately preserved and pinned with a test rather than silently fixed: the planner has no archive filter, so an archived batch with quantity is still offered as a candidate — and an Eco custody dispatch is exactly what sets `archived_at` (`eco_transfers.py:135`), while `cutting_material_assignment.py:49` and `api/routes/inventory.py:591` both exclude archived.** There is also no `qc_status` filter. That is a business-rule question for an owner, not something to fold into a performance change. |

| 59 | **PERF04** | Bundle receive checks accessories again for each bundle. | Use one transaction/order-bound gate context per request; preserve scanner/factory checks, locks, transitions and rollback. Coordinate with PERF13 receipt context. | `B:api/routes/bundles.py:579`; `B:services/bundles.py:438`; `c72fcb7`; [regression](https://github.com/Shmirzaev/Milana-ERP/blob/2f549f9b202ef1a66ed6ffe17be07b5497ccdeab/backend/app/tests/test_bundle_accessory_gate_batching.py) | Open · Mirshoir |

| 60 | **PERF05** | Payroll label issuance repeats reference/duplicate checks per label. | Batch flow/work-order/factory, existing-label/record and canonical reference reads; preserve issued identity, ambiguity/UID rules and current payroll behavior. | `B:api/routes/payroll.py:2101`; `538ff66`; [regression](https://github.com/Shmirzaev/Milana-ERP/blob/2f549f9b202ef1a66ed6ffe17be07b5497ccdeab/backend/app/tests/test_payroll_label_issuance_queries.py) | Open · Dilmurod |

| 61 | **PERF06** | Bulk payroll is unbounded and misses batched validation. | Cap bulk payroll at 500; batch reference/duplicate validation and audit-head work. | `B:schemas/payroll.py:84`; `f42637c3`, `8240fc9`, `67f0309`, `c625aad` | Open · Dilmurod |

| 62 | **PERF07** | Payroll labels resolve references separately per group. | Preload canonical references and aliases in bounded batches; preserve global counts, factory scope and current payroll identity rules. | `B:api/routes/payroll.py:2607`; `B:api/routes/payroll.py:202`; `6f5ee2e`; [regression](https://github.com/Shmirzaev/Milana-ERP/blob/2f549f9b202ef1a66ed6ffe17be07b5497ccdeab/backend/app/tests/test_payroll_label_query_growth.py) | Open · Dilmurod |

| 63 | **PERF08** | Receiving queue loads all packages and detailed children. | Restore SQL paging/count and minimal queue DTO/removal contract; keep detail-by-ID, latest queue events and returned-package exclusion. | `B:api/routes/packages.py:142`; `B:api/routes/packages.py:1078`; `890177e`, `3da6174`, `cbebcd4`, `2dd8ef8`, `330374c`; [regression](https://github.com/Shmirzaev/Milana-ERP/blob/2f549f9b202ef1a66ed6ffe17be07b5497ccdeab/backend/app/tests/test_receiving_queue_query_growth.py) | Open · Mirshoir |

| 64 | **PERF09** | Bulk package writes repeatedly lock/validate/cost each package. | Restore transaction-bound PackageWriteContext, membership/availability/reference caches, reserved number ranges and final shared synchronization; preserve first-grade/shortfall/return/weight rules. | `B:services/packages.py:492`; `B:services/packages.py:157`; `0066d32`, `a51eb6f`, `a3f8948`, `cd6ec8b`, `0ce77fb`, `a93409d`; [regression](https://github.com/Shmirzaev/Milana-ERP/blob/2f549f9b202ef1a66ed6ffe17be07b5497ccdeab/backend/app/tests/test_package_write_query_growth.py) | Open · Mirshoir |

| 65 | **PERF10** | Bulk package receiving/placement rereads members, stock and orders. | Reuse a shared locked receive gate, batch stock/member/child reads and placement preparation, synchronize each affected order once; preserve current run receipt/return/manifests/evidence. | `B:api/routes/packages.py:1192`; `B:services/package_workflows.py:226`; `B:services/packages.py:1109`; `ba1fe9a`, `749ea5a`, `4bfc9b3`, `b6ab791`; [regression](https://github.com/Shmirzaev/Milana-ERP/blob/2f549f9b202ef1a66ed6ffe17be07b5497ccdeab/backend/app/tests/test_package_batch_receive_concurrency.py) | Open · Mirshoir |

| 66 | **PERF11** | Print-run list queries members separately per run. | Load page members together and pass grouped identities through manifest validation; preserve returned/deleted/replacement run behavior. | `B:api/routes/package_workflows.py:226`; `B:services/package_workflows.py:125`; `7dacb8d`; [regression](https://github.com/Shmirzaev/Milana-ERP/blob/2f549f9b202ef1a66ed6ffe17be07b5497ccdeab/backend/app/tests/test_print_run_query_growth.py) | Open · Mirshoir |

| 67 | **PERF12** | Label sheets lack caps and repeat model/asset/allocation lookups. | Restore pre-read caps (500 by-ID packages, 200 bundles/run packages), shared sheet contexts and selected image projections; preserve per-label rendering and Unicode/thermal/first-grade/return layouts. | `B:api/routes/packages.py:1520`; `B:api/routes/bundles.py:1020`; `B:api/routes/package_workflows.py:274`; `f27e240`, `9fe1c14`, `7f5b30d`, `d990aa6`, `4fba5f1`, `f378278`, `2f92465`, `6277260`; [regression](https://github.com/Shmirzaev/Milana-ERP/blob/2f549f9b202ef1a66ed6ffe17be07b5497ccdeab/backend/app/tests/test_package_label_query_growth.py) | Open · Mirshoir |

| 68 | **PERF13** | Bundle receive repeats shared gates, aggregates and legacy lookups. | Restore SewingReceiptContext/receive_many_at_sewing with shared references and reuse accepted rows for response totals; preserve factory/advisory/batch locks, QR assignments and splits. | `B:api/routes/bundles.py:573`; `B:services/bundles.py:440`; `ef9cb88`, `952b569`, `49fdeea`, `df862ca`, `fb79677`, `f4c8723`, `f5977d0`; [regression](https://github.com/Shmirzaev/Milana-ERP/blob/2f549f9b202ef1a66ed6ffe17be07b5497ccdeab/backend/app/tests/test_bundle_receive_query_growth.py) | Open · Mirshoir |

| 69 | **PERF14** | Passport reads/material additions repeat stock/reference/reservation work. | Batch default/list projections, sorted item/batch locks and reservation reads, reserve one number range and group inserts/audits; preserve units, retries, legacy fabric and Cutting guards. | `B:api/routes/cutting_passports.py:328`; `B:api/routes/cutting_passports.py:505`; `a3f8127`, `2279d2d`, `8bf780a`, `9cac5fb`, `5890272`, `10198ea`; [regression](https://github.com/Shmirzaev/Milana-ERP/blob/2f549f9b202ef1a66ed6ffe17be07b5497ccdeab/backend/app/tests/test_material_reservation_query_growth.py) | Open · Mirshoir |

| 70 | **PERF15** | Planning queries BOM per line and stock/cost/model per item. | Restore bounded BOM/model/cost maps and available_stock_for_items; preserve sizes/colors, stock/claim semantics, composition and response compatibility. | `B:services/planning.py:40`; `B:services/planning.py:63`; `B:services/planning.py:116`; `f72d71b`; [regression](https://github.com/Shmirzaev/Milana-ERP/blob/2f549f9b202ef1a66ed6ffe17be07b5497ccdeab/backend/app/tests/test_planning_query_growth.py) | Done · @Ismail · [`155792a4`](https://github.com/Shmirzaev/Milana-ERP/commit/155792a4) · `material_requirements_for_sales_order` ran one `ModelBOM` query per sales-order line plus `available_stock_for_item` per distinct material, and `planning_estimate_for_sales_order` re-read every `Item` and `Model` row one at a time. Measured on PostgreSQL 17.11 with a 4-line vs 40-line order: requirements **21 → 57** statements and estimate **31 → 103** — exactly +36 for +36 lines, perfectly linear. Each dimension is now read once and keyed in Python (BOM chunked at 400 with `order_by(ModelBOM.id)` to preserve per-model order), giving **6 → 6** and **9 → 9**: flat regardless of line count. **Deviation from donor `f72d71b`, forced by file ownership:** the donor added `available_stock_for_items` to `services/inventory.py`, which this row does not own and which still does not exist upstream, so the batched read is a private `_available_stock_for_items` inside `planning.py` replicating the original global arithmetic exactly — batch balances + batchless ledger movements − active reservation claim, with only the reservation part floored at zero; all quantity columns are `Numeric`, so grouping by item sums the same rows bit-identically, and a BOM row naming a material without an item keeps the original single-item read. Output compatibility is pinned by literals recorded from the **unfixed** service and the growth tests are shown to pass pre-fix too, which is the proof the change is performance-only. Growth assertion is `large <= small * 2 + 8`, not a hardcoded count. **Full backend suite 2534 passed, 0 failed, 0 skipped.** **Two items left open on purpose:** `planning_estimate_for_sales_order` and `material_requirements_for_quantity` have no backend callers (only `material_requirements_for_sales_order` is used) — all three were fixed because the row names them, and removing the dead ones is separate cleanup; and one error-path change, where an explicit `quantity: None` in `material_requirements_for_quantity` previously raised `TypeError` (a 500) and now yields `0`. |

| 71 | **PERF16** | Flow snapshots sum per flow and scan unrelated assignment IDs. | Restore grouped committed-today sums, selected-flow projection and SQL-scoped assignment exclusion; retain existing bulk/single loaders and direct/split date/rounding/factory rules. | `B:api/routes/sewing_flows.py:269`; `B:api/routes/sewing_flows.py:129`; `3e29732`, `5e9418a`; [regression](https://github.com/Shmirzaev/Milana-ERP/blob/2f549f9b202ef1a66ed6ffe17be07b5497ccdeab/backend/app/tests/test_sewing_flow_utilization_query_growth.py) | Open · Mirshoir |

| 72 | **PERF17** | Sewing report reads resolve model/assets/passport per order. | Restore chunked projected model/latest-passport and shared line/report caches; preserve manual overrides, dates, factory filters, split context and write locks. | `B:api/routes/sewing_daily_reports.py:562`; `B:api/routes/sewing_daily_reports.py:82`; `3e2ff6a`; [regression](https://github.com/Shmirzaev/Milana-ERP/blob/2f549f9b202ef1a66ed6ffe17be07b5497ccdeab/backend/app/tests/test_sewing_daily_report_read_query_growth.py) | Open · Mirshoir |

| 73 | **PERF18** | Receive options compute all scopes before search/limit. | Restore SQL target/receipt aggregates, exact/legacy target precedence and scoped search/limit with PostgreSQL CTE plan checks; preserve quantity/accounting/authorization and no-write selectors. | `B:api/routes/production.py:4805`; `B:api/routes/production.py:4817`; `3217856`, `b61e210`, `3aa28b9`, `96d7a61`; [regression](https://github.com/Shmirzaev/Milana-ERP/blob/2f549f9b202ef1a66ed6ffe17be07b5497ccdeab/backend/app/tests/test_packaging_receive_options_query_growth.py) | Open · Mirshoir |

| 74 | **PERF19** | Cutting reconciliation recalculates evidence per work order. | Build grouped actual-scope counters, reuse targets and scoped UNION edit evidence; preserve real-output floor, batchless fallback and failed pieces without replacement work. | `B:api/routes/production.py:4077`; `87c1b76`, `7ebe82b`, `cf7e606`; [regression](https://github.com/Shmirzaev/Milana-ERP/blob/2f549f9b202ef1a66ed6ffe17be07b5497ccdeab/backend/app/tests/test_cutting_reconciliation_query_growth.py) | Open · Mirshoir |

| 75 | **PERF20** | Cutting/packaging writes repeat stock, BOM and bundle supporting reads. | Batch stock/reservation locks/maps, reserve bundle numbers/departments once and group scan logs/BOM reads; preserve saved-passport shortage recording and per-material rollback. | `B:api/routes/production.py:3227`; `B:api/routes/production.py:3302`; `B:services/workflow.py:534`; `57a0b35`, `b4e91e5`, `82824ef`, `4a0ee8e`, `5d8a765`, `05206df`; [regression](https://github.com/Shmirzaev/Milana-ERP/blob/2f549f9b202ef1a66ed6ffe17be07b5497ccdeab/backend/app/tests/test_cutting_packaging_write_postgres.py) | Open · Mirshoir |

| 76 | **PERF21** | Traceability loads broad histories and scalar warehouse/shipment references. | Restore scoped history/context queries and grouped cutting/bundle/warehouse/shipment projections; preserve exact/legacy/batchless evidence, returns and current references. | `B:services/traceability.py:514`; `B:services/traceability.py:304`; `B:services/traceability.py:861`; `2f8f951`, `ae88bb5`, `4447c97`, `a4f005a`, `24bba90`, `6acfa70`, `16d9ec4`, `403af90`, `873979a`; [regression](https://github.com/Shmirzaev/Milana-ERP/blob/2f549f9b202ef1a66ed6ffe17be07b5497ccdeab/backend/app/tests/test_traceability_history_query_growth.py) | Open · Mirshoir |

| 77 | **PERF22-USLUGA** | Usluga directory fetches every order. | Add `limit`/`offset` to the list route and bound the directory with load-more; keep the detail/handover routes untouched. | `F:app/(app)/usluga/page.tsx:83`; `c8ac9f35` | Done · @Ismail · [`ccea9583`](https://github.com/Shmirzaev/Milana-ERP/commit/ccea9583) · The blocking "preserve legacy array compatibility" clause was retired by a consumer sweep: the route had exactly one in-repo consumer, no documented contract, no MCP/integration caller and no print/export path, so enveloping it breaks one file and is an internal shape change. `GET /api/usluga/orders` now takes `limit`/`offset`/`search` and returns `{items, total, limit, offset}` with `total` as the true filtered count; order stays `ProductionOrder.id.desc()`; clamping follows the existing `payroll.py:1616-1617` convention and a hostile `limit` is **clamped, not 422** (deliberately no `ge`/`le` on the bound, since `le=200` would reject instead of clamp). **The real defect was underneath the paging:** `filteredOrders` filtered the *entire* fetched array client-side, applying both the status filter and a free-text search over `order_no`, `customer_name`, `customer_reference`, `model.code` and `model.name`. Capping the fetch at 50 would have silently hidden every match past row 50 — searching for an order you had just created would return empty and look like a correct "no results". Both filters therefore moved server-side, with `search` joining `Model` under the same `catalog_scope`/`factory_code` scope `_order_payload` renders, and the client-side filter kept only as a guard while the debounced request is in flight. `useSWRInfinite` with a 300ms debounce drives load-more. 8 new tests, all 8 failing against the unfixed route; 38 pass across the three suites. **Donor conflict:** `c8ac9f35` was read but not cherry-picked — it used `page`/`page_size` and left `search` client-side, i.e. the exact silent-narrowing bug; live code and the brief won. **Unverified:** no browser/DOM harness and no `node_modules`, so load-more, the debounce and the SWR key reset were argued from code, never executed; type-check went 920 → 921, the one addition being `TS2307: swr/infinite`, the same missing-package class as the file's existing imports. Known deliberate non-fix: `search` uses `.like(f"%{term}%")`, so `%`/`_` are wildcards — matches existing repo convention. |

| 78 | **PERF23** | Pricing lists hydrate all requests/assets and poll every five seconds. | **Assets and polling are Done; the page cap waits on D3.** Bound the list query, preload shared assets once for lists **and** mutations, and replace the five independent 5s timers with one visibility/offline-aware polling hook. | `B:api/routes/price_calculation.py:55`; `B:services/price_calculation.py:24-58`; `F:src/hooks/useSharedPolling.ts`; `F:app/(app)/sales/price-requests/page.tsx:42-46`; `b6b5aab8`, `7823723e`, `c2808846`; [regression](https://github.com/Shmirzaev/Milana-ERP/blob/1e664292/backend/app/tests/test_perf23_price_calculation_list_query_growth.py) | Partial · @Ismail · [`1e664292`](https://github.com/Shmirzaev/Milana-ERP/commit/1e664292) · **Landed:** `PRICE_MODEL_ASSET_RELATIONS` plus `model_asset_load_options()`/`price_request_load_options()` fix the N+1 — `Model.sizes` and `Model.images` are default-lazy and were read once per row (the test caught `model_sizes` read **25 times for one page**). The route list, `_request_or_404` and `create_price_request` all share one preload, which is what the "lists **and** mutations" requirement needed. New `F:src/hooks/useSharedPolling.ts` replaces five independent `refreshInterval: 5_000` settings; it returns `refreshInterval: 0` while the document is hidden or the browser is offline, so SWR schedules no timer at all rather than skipping a fetch, and restores on `revalidateOnFocus` plus `visibilitychange`/`online`/`offline`. React only, no new dependency. Response stays a bare array, so all five consumers keep working with no shape change, and a 39-field assertion pins their field names and status semantics. **Deliberately NOT landed — the cap.** The worker capped the list at 200 with an `X-Total-Count` header, but **no frontend code reads that header and none of the five consumers has load-more**, so anyone past request 200 would watch rows vanish off the end of the screen with no way to reach them. That is the same "silently stops at fifty" shape PERF35-FINANCE just fixed, so shipping it would have been a regression dressed as a performance win. The list stays unbounded by default; `limit` is accepted as an opt-in (max 500) so a client can bound its own read once load-more exists. **Blocking dependency: D3.** **Unverified, and uniquely so in this batch:** the hook and the five pages were never executed — no browser/DOM harness, no `node_modules`, and **no TypeScript compiler anywhere in this environment**, so unlike PERF22 and PERF35 there is no before/after error count at all. The frontend diff is three mechanical lines per page, reviewed by eye, which is not a compiler. |

| 79 | **PERF24** | Sales/shipment lists fetch customer/order references per row. | Select bounded joined reference maps and pass them to serializers; preserve deleted-shipment filters, customer overrides, totals and scope. | `B:api/routes/sales.py:77`; `B:api/routes/shipments.py:66`; `93f8b59a`, `d687557c`; [regression](https://github.com/Shmirzaev/Milana-ERP/blob/2f549f9b202ef1a66ed6ffe17be07b5497ccdeab/backend/app/tests/test_sales_list_query_growth.py) | Done · @Ismail · [`7b95f36a`](https://github.com/Shmirzaev/Milana-ERP/commit/7b95f36a) + [`a843b992`](https://github.com/Shmirzaev/Milana-ERP/commit/a843b992) · Implemented under D5 (`key_share=True` → `FOR NO KEY UPDATE` at the four call sites). Sales and shipment list serializers now take **bounded** reference maps: the route selects only id/name and id/order_no/customer_id columns, so **0 entities are hydrated** rather than merely fewer. Proven by reverting the source: sales list `Customer` entities hydrated went **4 → 20** for a 4 → 20 page unfixed (0 → 0 fixed); shipment list `SalesOrder`+`Customer` **8 → 48** for 4 → 24 shipments (0 → 0 fixed). Deleted-shipment filter, customer override (shipment `customer_id` wins while the `customer_id` field still reports the shipment's own), totals, `include_total`, `q` search and per-factory scope are pinned by tests passing on **both** fixed and unfixed code. Donor conflicts, live code won, nothing cherry-picked: `d687557c` dropped the deleted filter and joined via `func.nullif(customer_id, 0)`; `93f8b59a`/`d687557c` hydrated full entities where the row says bounded. **Unverified:** no concurrent-request lock test — lock mode and ordering are pinned on SQL text only; secondary call sites are covered indirectly. |

| 80 | **PERF25** | Sales history hydrates/sorts every candidate before paging. | Count/order/page a SQL UNION candidate set before selected-ID hydration; preserve tie/null ordering, filters and current summaries. | `B:api/routes/sales.py:1757`; `565d1cdf`, `71a496ff`, `be84006f`; [regression](https://github.com/Shmirzaev/Milana-ERP/blob/2f549f9b202ef1a66ed6ffe17be07b5497ccdeab/backend/app/tests/test_sales_history_candidate_loading.py) | Done · @Ismail · [`a162742a`](https://github.com/Shmirzaev/Milana-ERP/commit/a162742a) · `list_sales_order_history` built the candidate UNION in SQL, then `.all()`-ed **both** branches as full ORM entities — the production branch with four `joinedload` collection options — concatenated, Python-sorted and only then sliced. Measured for a fixed 5-row page: 12 candidates hydrated **12 entity rows → 5**, and 72 candidates **72 → 5**, so hydration is now pinned to the page size. **The defect was rows, not statements:** the unfixed route issued the same two statements and simply received 6× more rows, and ORM instantiation scaled with them, so a statement budget would have passed. Both branches became `enable_eagerloads(False).with_entities(...)` columns unioned into a subquery, `total` is `count(*)` over that union, the page is an ordered `offset/limit` on it, and only selected ids are hydrated — the production branch keeping all four original `joinedload` options. **Ordering is the risk and is proven adversarially:** the fixture carries equal sort keys, a cross-kind tie where the old `list.sort(reverse=True)` resolved by stability, and a NULL sort key forced by dropping the NOT NULL constraint in the isolated schema; two independent oracles (the pre-fix algorithm copied verbatim, and a hand-derived expected order) agree with the route across 9 page sizes × 3 pages. That caught two real errors in the hand-derivation — the id tie-break sorts **descending**, and two filter sets were mis-transcribed — which were corrected rather than loosened. `NULLS LAST` is stated explicitly instead of relying on the PostgreSQL default. `total` stays a whole-union count (`== 12` at page sizes 1/3/5/12/50, and past the end), and 19 filter combinations × 3 page sizes are compared against the oracle. Diff is +57/−8 inside a GET; **FN04's `key_share=True` SalesOrder lock is outside the hunk and its test passes.** 2 failed/7 passed on unfixed → 9 passed; **359 adjacent pre- and post-rebase, 0 skipped**; PG tests skip loudly when the URL is unset. **Noted behaviour change:** the page is now two statements rather than one snapshot, so a candidate deleted in between yields a short page — guarded to degrade rather than 500. |

| 81 | **PERF26** | Branded reservation repeats variant/package/metadata reads. | Batch variant candidates, reuse locked packages and batch metadata repair; preserve package-first locks and recompute mutable completeness. | `B:api/routes/sales.py:1413`; `B:services/finished_goods.py:135`; `5a89e272`, `2cc66e0e`, `fbdda65d`; [regression](https://github.com/Shmirzaev/Milana-ERP/blob/2f549f9b202ef1a66ed6ffe17be07b5497ccdeab/backend/app/tests/test_sales_branded_variant_queries.py) | Done · @Ismail · [`7b95f36a`](https://github.com/Shmirzaev/Milana-ERP/commit/7b95f36a) + [`a843b992`](https://github.com/Shmirzaev/Milana-ERP/commit/a843b992) · Implemented under D5. Stock rows for 1 → 7 variants **9 → 27** unfixed, **9 → 9** fixed; package rows for 9 packages **36 → 63 → 18 → 18**; metadata-repair and model-fallback reads **3 → 12 → 1 → 1**. Lock evidence: unfixed issued **0** `FOR NO KEY UPDATE` locks; fixed issues **2 on packages + 1 on finished_goods_stock**, so the package-first order is now actually taken rather than assumed. **Mutable completeness preserved:** only Package *identity* is cached, and whole-bag eligibility is rebuilt from available/reserved/sold quantities on every call, pinned by a test that consumes a package and re-asks. The metadata repair's write path is byte-identical. Donor conflicts, live code won: `2cc66e0e` *deleted* the package-first lock (forbidden — reimplemented per chunk and pinned on SQL text) and matched colour/size with Python `.strip()`, which would admit `"White "` that SQL `=` rejects; `fbdda65d` dropped the resolver's step-5 re-read after step 4 sets `collection_id`, which is kept. **Unverified:** no two-racing-sessions deadlock test, and the >200-variant multi-chunk path is unexercised. The batched variant query re-applies colour/size/brand in Python over the chunk union — cheaper in round trips, more CPU; the chunk-size constant is the lever if large orders ever prove CPU-bound. |

| 82 | **PERF27** | Shipment loops repeat package locks, stock/claim checks and order sync. | Reuse locked identities, batch stock/reservations and synchronize once per distinct order; preserve reconciliation/reversal/frozen documents and rollback. | `B:api/routes/shipments.py:713`; `B:services/packages.py:1190`; `9d1755e4`, `c0ff7834`, `8de1073e`, `02e8db82`; [regression](https://github.com/Shmirzaev/Milana-ERP/blob/2f549f9b202ef1a66ed6ffe17be07b5497ccdeab/backend/app/tests/test_shipment_package_lock_query_growth.py) | Open · Mirshoir |

| 83 | **PERF28** | Purchasing still reads item/supplier/warehouse references per line. | Batch/project references and remove only proven redundant access reads. PostgreSQL audit-head finalization already survives; preserve rounded costs and repeated-line fallback. | `B:services/purchasing.py:102`; `B:api/routes/purchasing.py:174`; `1efce388`, `41374319`, `d2001615`, `b4b2da02`, `cda1df04`; [regression](https://github.com/Shmirzaev/Milana-ERP/blob/2f549f9b202ef1a66ed6ffe17be07b5497ccdeab/backend/app/tests/test_purchasing_query_growth.py) | Done · @Ismail · [`5078f99a`](https://github.com/Shmirzaev/Milana-ERP/commit/5078f99a) · `create_purchase_order` read one item, warehouse and supplier row per line and `create_purchase_request` one item and supplier row per line, so a 25-line order cost **76 and 50** reference statements; both now collect the payload's ids and read each table once, giving **3 and 2** statements independent of line count. **The row says remove only *proven* redundant reads, and that restraint is the result worth recording:** `receive_purchase_order` (1 statement) and `approve_purchase_request` (0) were deliberately left alone because `PurchaseOrderLine.item/warehouse/supplier` and `PurchaseRequestLine.item/preferred_supplier` are `lazy="joined"`, so the identity map already answers those per-line `db.get` calls — batching there would have *added* statements rather than removed them. The one redundant read removed is the receive route's second per-line `inventory_access.require_item` pass: the loop before the replay check already authorized every line, and `receive_purchase_order` only updates received quantity, cost and warehouse on existing lines, so the repeat could not reach a different verdict, with authorization still preceding any write. The pre-read map is only a cache, so an id it does not hold still falls back to the original single-row read and the original 400/404 still fires in the original order. Costs still round HALF_UP to four decimals through `round_unit_cost`, and a line repeated in one receipt keeps its preceding explicit price. `+974/−9` across the two owned files and the new test. **273 adjacent purchasing, receipt and unit-cost tests pass** on the merged branch with PostgreSQL enabled. |

| 84 | **PERF29** | Customer payment selection sums receipts separately per invoice. | Batch candidate paid sums under existing invoice locks; preserve exact Decimal/payable-cent and approved settlement/revenue behavior. Keep former 1C work retired. | `B:api/routes/partners.py:259`; `91f2f738`; [regression](https://github.com/Shmirzaev/Milana-ERP/blob/2f549f9b202ef1a66ed6ffe17be07b5497ccdeab/backend/app/tests/test_customer_payment_query_growth.py) | Done · @Ismail · [`f9a7f536`](https://github.com/Shmirzaev/Milana-ERP/commit/f9a7f536) · `_find_payable_invoice` locked all candidate invoices in one query and then called `invoice_paid_total` **once per invoice**; the pre-fix run literally emitted 50 copies of `SELECT coalesce(sum(payments.amount), ...) ... WHERE invoice_id = ?`. Measured: 5 invoices **6 → 2** statements, 50 invoices **51 → 2**, 1000 invoices 1001 → 4 (1 lock + 3 chunks of 400), so growth is flat to 400 then `ceil(N/400)+1`. Extracted `_candidate_paid_totals()` following the grouped-aggregate pattern already in `services/finance.py:157`; candidates are collected in id order first, then summed in 400-id batches under the **same** locks, which the test proves by asserting the locking read is byte-identical to base and issues exactly one `FOR UPDATE` and one `GROUP BY`. **Rejected the donor's arithmetic:** `91f2f738` casts through `float()` and tests `balance_due > 0.01`, but live code is `Decimal`-based with `> 0`; copying it would have broken money exactness and the display-only settlement rule, so `Decimal` and `> 0` were kept. Money equality proven against a **live per-invoice oracle** comparing `.as_tuple()` (exact scale/exponent, not just numeric equality) across receipt-less, partial, cent-boundary, exact-settlement, three-receipt and overpaid cases, plus `999999999999.99` overflow, advance rows and reversed invoices. `<= $1.00` settlement display rule untouched (`services/payments.py` diff empty) and 1C stays retired. Caught its own bug: an invoice with no receipts produces no group row, so the dict lookup raised `KeyError` until every requested id was seeded with `Decimal(0)`, matching `coalesce(sum(...), 0)`. 2 failed/7 passed on unfixed → 9 passed; 137 adjacent, 74 post-reconcile, 0 skipped. |

| 85 | **PERF30** | Catalog rename/clone/approval still use broad scans and repeated probes. | Filter rename/collision reads, batch exact clone-code probes with namespace serialization and group BOM counts; preserve indexed family lookup and empty Usluga header exception. | `B:api/routes/catalog.py:1013`; `B:api/routes/catalog.py:1047`; `B:api/routes/catalog.py:2272`; `bb93fbca`, `4a4d0e66`, `0775eaf9`, `acea29dd`, `a5631ea4`, `b4db4b4d`; [regression](https://github.com/Shmirzaev/Milana-ERP/blob/2f549f9b202ef1a66ed6ffe17be07b5497ccdeab/backend/app/tests/test_catalog_family_operations_query_growth.py) | Done · @Ismail · [`e2d8645f`](https://github.com/Shmirzaev/Milana-ERP/commit/e2d8645f) · three read paths, each growing with the wrong quantity. **Rename:** `_rename_model_group` loaded every model in the scope to find one family, then loaded every *other* model again for a collision map; the family read now uses the generated indexed `models.model_group_key` from migration `0084` — the same identity `_model_group_key` already computes in Python and the same lookup `_approval_family` uses — and the collision read probes only the planned codes. **Clone:** one query per rejected `-COPY` suffix meant 59 taken suffixes cost 60 statements; candidates are now probed in batches of 400 and the namespace is serialized with the advisory-lock pattern the approval family already uses, so two concurrent clones cannot both read the same free code. **Approval:** the main-fabric BOM count ran once per pending family member and is now one grouped read, with a model having no main fabric simply absent from the map so its count stays 0 and is still rejected. **The collision guard is where this could quietly weaken:** `_normalized_key` casefolds and collapses whitespace, so a stored code differing only in case or spacing is still a real collision — the narrowed read re-keys its candidates with that same Python normalization, and a test seeds codes differing only in case and only in whitespace to prove the 409 still fires. A second test asserts the stored generated key equals the Python `_model_group_key` on every family member, which is what makes the indexed path safe. The empty Usluga header exception is preserved and asserted separately. Measured on PostgreSQL 17.11 with the real generated columns applied from `0084`: a rename read **4 model rows → 612** once the catalogue held 300+, and taken copy suffixes cost **60 statements → 2**. **The statement count alone was a trap:** the unfixed rename issued a constant *two* statements while returning every row, so a statement budget passed against the defect — the first draft of the test measured statements and had to be rewritten to measure rows. 2 failed / 5 passed against the unfixed module, 7 passed after; 51 existing catalogue tests unchanged, **58 passed post-rebase**; the PG tests skip loudly when the URL is unset. SQLite metadata has no generated columns, so both dialects keep the Python fallback. |

| 86 | **PERF31** | Attendance roster import queries each person separately. | Restore bounded 400-ID roster maps alongside AT06 locks/versioning; preserve counts, full/partial absence, duplicate rollback and factory/device boundaries. | `B:api/routes/attendance.py:221`; `a0b9862`; [regression](https://github.com/Shmirzaev/Milana-ERP/blob/2f549f9b202ef1a66ed6ffe17be07b5497ccdeab/backend/app/tests/test_attendance_people_query_growth.py) | Open · Dilmurod |

| 87 | **PERF32** | Inbox/forecast/context paths still load broad assets and per-group references. | Restore narrow chunked context maps/image metadata projections across inbox, forecast, process tracking, package lists and Data Console; preserve retained catalog projection and routing/image precedence. | `B:api/routes/inbox.py:535`; `B:services/forecasting.py:241`; `B:api/routes/process_tracking.py:942`; `B:api/routes/super_data.py:250`; `f79d195`, `6c2c5ac`, `b40cace`, `3cc7e67`, `ed4be77`; [regression](https://github.com/Shmirzaev/Milana-ERP/blob/2f549f9b202ef1a66ed6ffe17be07b5497ccdeab/backend/app/tests/test_inbox_production_context_query_growth.py) | Open · Mirshoir |

| 88 | **PERF33** | Stocktake detail/export fully hydrate rows and lack a consistent snapshot. | Apply SQL detail/search/changed filtering, bounded summaries and streamed export batches in one consistent read-only snapshot. Preserve bounded list behavior. | `B:api/routes/stocktake.py:66`; `B:api/routes/stocktake.py:168`; `B:api/routes/stocktake.py:313`; `7fe32ef9`, `16104763`, `a47de563`, `2f941d2b`, `31b4254b`; [regression](https://github.com/Shmirzaev/Milana-ERP/blob/2f549f9b202ef1a66ed6ffe17be07b5497ccdeab/backend/app/tests/test_stocktake_postgres_snapshot.py) | Done · @Ismail · [`de7a5150`](https://github.com/Shmirzaev/Milana-ERP/commit/de7a5150) · two defects. **Hydration:** `results()` loaded every row of a count and materialized each into a dict, and `detail()` then filtered/searched/sorted/windowed that list, so a count far larger than `limit` transferred, decoded and JSON-parsed every row to answer one 100-row page. **No snapshot:** the row query and the `package_snapshots` lookup filling `current` were separate statements at READ COMMITTED, so a scan committed between them showed in one half of a row and not the other — pre-scan evidence beside post-scan current state. Rows are now walked in bounded batches (`iter_result_batches`, keyset on `id`, or on `(scanned_at, id)` for the newest-first scanned view) so neither endpoint holds a whole count and the page is chosen while streaming; both reads run in one `REPEATABLE READ READ ONLY` snapshot, and the count header is read **inside** it because the session rolls back when it closes. **Regression this change introduced and an existing test caught:** `scan_summary` counts `scanned` across every row but derives the package totals from the first recorded row per package, so handing it the already-deduplicated set reported `scanned_packages` 2 instead of 3; the raw scanned-row count is now restored afterwards. The summary still describes the whole count, so it is accumulated during the walk rather than recomputed from the page. Response shape, ordering, totals and CSV bytes unchanged; `list_counts` untouched. Reproduced 4 failed/1 passed on unfixed (every failure a genuinely missing capability) → 5 passed with PostgreSQL 17.11; 43 adjacent, **60 passed across all three PERF fixes together on the reconciled tree**; the PG tests skip loudly (5 skipped) when the URL is unset, so there is no false green. |

| 89 | **PERF34** | Shipment documents repeatedly search package/content/price lists. | Build package-content, exact/wildcard price, receipt and invoice-line indexes once; preserve order, ambiguity handling and frozen snapshots. | `B:services/shipment_invoice.py:34`; `B:services/shipment_review.py:208`; `a14827f4`; [regression](https://github.com/Shmirzaev/Milana-ERP/blob/2f549f9b202ef1a66ed6ffe17be07b5497ccdeab/backend/app/tests/test_shipment_document_query_growth.py) | Done · @Ismail · [`6a83c0dd`](https://github.com/Shmirzaev/Milana-ERP/commit/6a83c0dd) · Shipment documents no longer re-search their package, content, price and receipt lists. Per-row visits, measured on identical data with the source reverted to prove it: `contents` **31.0/row → 2.0/row**, `order_items` **30.0/row → 1.0/row**, `build_invoice_rows` 2700 → 90. Two genuinely missing indexes added in migration `0137_perf34_shipment_indexes`, and **each test drops its index and asserts the plan reverts to a Seq Scan**, so neither is decorative; on a disposable schema the planner chose an Index Scan reading 240 of 240,000 rows and 50 of 3,000. `post_manual_shipment_invoice` gains a frozen invoice-line set-index with a guard preserving the original `KeyError` timing. **Two things to know:** the worker edited `models/sales.py` and `models/tracking.py` (one `index=True` each) *outside* its declared ownership — necessary because the shipped ORM-parity test fails without them, verified 3/3 on real PostgreSQL. And `alembic_version.version_num` is `varchar(32)`: a 37-char revision id failed at upgrade time on a real server, so the id is shorter and a length test now guards it. **Unverified:** migration `0137` was never executed against a database — only the real Alembic chain running to its head on a disposable schema, plus a static check on `upgrade()`. |

| 90 | **PERF35-FINANCE** | Finance invoice list silently stops at fifty. | Add `offset`/`search` alongside the existing `limit`, page the invoice table, and report the true total so rows past the cap stay reachable. | `F:app/(app)/finance/page.tsx:65`; `88cedd2c` | Done · @Ismail · [`c50d5719`](https://github.com/Shmirzaev/Milana-ERP/commit/c50d5719) · **The defect was silent truncation, not slow hydration.** The route took a `limit` but no `offset`, so every invoice past the first fifty was unreachable — the page looked complete and was not. The 50 was set in **three** places (frontend `?limit=50`, route default `limit: int = 50`, service cap `safe_limit = max(1, min(limit, 200))`), so raising the limit alone would never have fixed it. `GET /api/finance/invoices` now takes `offset` and `search` and returns `{items, total, limit, offset}`, where `total` is the true filtered count and not the page length; search covers invoice no, order no and customer. **`list_recent_invoices` deliberately still returns a plain list** and gained `offset`/`search` params, because `test_finance_received_revenue.py:61,108` imports it directly and iterates it — enveloping the service would have broken two call sites for no gain. `count_invoices` is a separate function and both share `_invoice_search_filter`, because a count that drifts from the page filter is worse than no count at all. The survey that scoped this row reported **one** test file on the endpoint; a direct grep found **five** (`test_customer_payment_history`, `test_finance_money_bounds`, `test_idempotency`, `test_invoice_creation_integrity`, `test_finance_integration_retirement`) — only the last needed moving, and running all five is what surfaced 6 PG-gated `NUMERIC(14,2)` tests **skipping silently**. Regression test seeds 60 invoices, past the old hard stop of 50, and pins reachability, exact totals, no page overlap, cross-page ordering, search agreement between page and total, and clamping of hostile `limit`/`offset`; **9 of its 10 tests fail against the unfixed route**, the tenth being a service return-type guard that passes both before and after by design. Verified 72 pass across the finance/invoice suites, and 37 pass in `test_finance_money_bounds` with `STABILIZATION_POSTGRES_URL` set, which also proves those 6 are no longer skipping. **Unverified:** no browser/DOM harness and no `node_modules`, so the paging controls and search box were never executed and no type-check was run. Uses the existing `common.search` key rather than a new one, so EN/RU/UZ stay complete. |

| 91 | **PERF35-FINISHED-GOODS** | Finished-goods page loads unpaged stock/inbox graphs. | Page stock/branded/inbox data with exact totals and existing reservation/return behavior. | `F:app/(app)/finished-goods/page.tsx:24`; `7b45c231`, `1a030623`, `deef9c6d`, `59fea8bc` | Open · Mirshoir |

| 92 | **PERF35-HR** | HR employee directory loads all employees/positions. | Use scoped 50-row employee search, exact metrics and lazy retained option pickers. | `F:app/(app)/hr/employees/page.tsx:59`; `9c53b633`, `36b8d225` | Open · Dilmurod |

| 93 | **PERF35-INBOX** | Department inbox fetches a broad order graph. | Restore canonical identity pages and page-only hydration, including replacement/batch queues. | `F:app/(app)/departments/[code]/page.tsx:101`; `6c412e44`, `3e6c5d43`, `bfb51a95`, `051a5a22`, `dc24cdfd` | Open · Mirshoir |

| 94 | **PERF35-PAYROLL** | Payroll lists truncate records and load broad summaries/options. | Page records/summary/adjustments and employee options; remove the silent 300-record cutoff. | `F:app/(app)/payroll/page.tsx:218`; `2174ade0`, `b915b530`, `36b8d225` | Open · Dilmurod |

| 95 | **PERF35-PRODUCTION** | Production directory uses an unpaged array. | Use bounded server search/pages with load more and retained selected/deep-linked orders. | `F:app/(app)/production-orders/page.tsx:31`; `45f24e8b`, `07b5b8fb` | Open · Mirshoir |

| 96 | **PERF35-PURCHASING** | Receiving queue fetches broad order/supplier directories. | Page receiving orders by supplier and use bounded supplier options without losing receipt state. | `F:app/(app)/purchasing/receiving/page.tsx:117`; `59a86c5d`, `b3239284`, `b2e39065` | ** Done · @Ismail · [`a1ff9ad8`](https://github.com/Shmirzaev/Milana-ERP/commit/a1ff9ad8) · `GET /api/purchasing/orders` took no status/limit/offset, so the receiving screen could not page. It now returns `{items, total, limit, offset}`, with `total` derived from the **same base query** as the page — a count that drifts from the page filter is worse than no count. The receiving screen **accumulates** pages with `useSWRInfinite` rather than replacing them, because `openPendingReceipt` resolves a saved receipt out of this list: a single page would silently fail to resume a receipt for an order further down the directory, so a bounded effect grows the window until every pending order is loaded. `test_inventory_access_restore` iterates the orders body directly and moves with the shape change, with its scope assertion preserved verbatim. 9 of 13 new tests fail against the unfixed source; the 4 that pass are the already-shipped PERF40 primitive plus the backward-compatibility guard. 161 pass across the purchasing/order suites, 432 across the whole set. **Unverified:** no browser/DOM harness and no node_modules, so the paging and the pending-receipt auto-load were not executed. |

| 97 | **PERF36** | Fan-out hydrates broad users and flushes/counts once per row/table. | Use cap+1 projected recipients, batch task/notification flushes and count-free directories with on-demand counts; preserve authorization, targets, audit/rollback and counted API compatibility. | `B:api/routes/notifications.py:48`; `B:api/routes/tasks.py:98`; `B:api/routes/super_data.py:221`; `c5b2483`, `b6a8beb`, `1785a88`, `ebe8399`, `bd36441`; [regression](https://github.com/Shmirzaev/Milana-ERP/blob/2f549f9b202ef1a66ed6ffe17be07b5497ccdeab/backend/app/tests/test_notification_fanout_batching.py) | Open · Dilmurod |

| 98 | **PERF37** | Rate-store I/O blocks the async request loop. | Move synchronous rate-store work to bounded worker capacity; test event-loop responsiveness. | `B:main.py:230`; `25fd549` | Open · Dilmurod |

| 99 | **PERF38** | Office users share one global per-IP budget. | Use authenticated identity buckets; retain IP-only login/reset limits and safe credential fallback. | `B:main.py:154`; `a8b1707` | Open · Dilmurod |

| 100 | **PERF39-MODEL** | Hidden model tabs still fetch BOM/seasons/all employees. | Fetch BOM/seasons only for visible tab/editor and use bounded employee options. | `F:app/(app)/models/[id]/page.tsx:209`; `be696e12`, `4c751606`, `2e60854f` | Done · @Ismail · [`bd810b8b`](https://github.com/Shmirzaev/Milana-ERP/commit/bd810b8b) · the model detail page fired five requests on every load, so nine of twelve tabs paid for data they never rendered: `/bom-items` returns the entire item catalogue and `/api/collections/seasons` was fetched although the season picker only appears in the general tab. SWR skips a null key, so both are now requested only when the reading tab is selected, and the `tab` state moved above the fetch calls to gate on it. **The BOM condition is `tab === 3 || tab === 6`, not the materials tab alone, and that is the substance of the change:** `materialRows` and `accessoryRows` split the BOM into fabrics and accessories by item category, and a second panel on tab 6 renders both lists — gating on tab 3 alone would have left that panel showing every row as a fabric and no accessories, with nothing failing visibly. **`/api/employees` deliberately left unconditional:** `saveModel` resolves the already-selected constructor and designer from that list, so deferring it could clear a value the operator never edited. Bounding it needs a searchable endpoint, which is PERF35-HR and owned with HR — `GET /api/employees` still returns every employee for the selected factory with no limit parameter. Verified as far as this environment allows: the file parses with no TypeScript parse diagnostics, the project type-check reports **920 pre-existing errors before and after** (all missing `react`/`next`/`swr` modules, none in the edited region), and there is no browser or DOM test, so the tab behaviour is argued from the render guards rather than executed. |

| 101 | **PERF39-PACKAGES** | Collapsed package change requests fetch eagerly. | Fetch pending changes only when the section is expanded; refresh after actions. | `F:app/(app)/packages/page.tsx:49`; `1da4f66a` | Open · Mirshoir |

| 102 | **PERF39-PRODUCTION** | Production details have waterfalls and closed-editor fetches. | Restore paired page-context API/UI; gate utilization/users and page sales options only when needed. | `F:app/(app)/production-orders/[id]/page.tsx:212`; `7445ad49`, `534c8bf2`, `b669bd44` | Open · Mirshoir |

| 103 | **PERF40** | Uploads still block the event loop and miss lifecycle/admission safeguards. | Offload image/disk/SQL work with worker-owned sessions and scope rechecks; restore admission, cancellation/rollback cleanup and old-logo cleanup. Cross-process/proxy limits still need deployment verification. | `B:services/image_storage.py:224`; `B:api/routes/catalog.py:2320`; `B:api/routes/hr_workspace.py:401`; `170200f`, `503d068`, `b607eda`, `359df00`, `1f13f27f`; [regression](https://github.com/Shmirzaev/Milana-ERP/blob/2f549f9b202ef1a66ed6ffe17be07b5497ccdeab/backend/app/tests/test_image_upload_scheduling.py) | **Partial · @Ismail** · [`a66e11b8`](https://github.com/Shmirzaev/Milana-ERP/commit/a66e11b8) · `store_uploaded_image` was `async def` but only awaited the body read — Pillow decode, WebP re-encode, atomic disk writes, thumbnails and the route SQL all ran on the loop thread. Heartbeat measurement (3 concurrent uploads, 0.15 s slowed decode): ticks **6 → 61**, blocking calls on the loop thread **15 → 0**. **Admission and cleanup, the safety half:** a `CapacityLimiter` (`UPLOAD_MAX_CONCURRENCY_PER_PROCESS`, default 1) plus a bounded wait queue (`UPLOAD_MAX_QUEUED_PER_PROCESS`, default 8) returning 429 beyond both; `asyncio.shield` with `abandon_on_cancel=False` so a cancelled request still learns the outcome and re-raises, proven by asserting a file **was** written post-cancel and **zero survive**, and that a cancelled model upload leaves 0 `ModelImage` rows, no audit delta and no file, while a committed row keeps its file. **The scope recheck survives the offload and is proven by TOCTOU tests that flip the row *after* the file is stored** — moving a model to `usluga` mid-upload and an employee to `ECO` both yield 404 with no row, no audit and a discarded file; the catalog test **fails on unfixed code** with "DID NOT RAISE HTTPException". Donor `b607eda` was rejected: it depends on helpers in `app/core/uploads.py` that **do not exist on this branch**, so those primitives live in `image_storage.py` and live code won. **Not closed:** the old-logo cleanup call site is `settings.py::upload_company_logo` (live lines 108-137), a **fourth file this row does not own** — the tested `discard_replaced_managed_image()` primitive is committed and ready, and the wiring is ~6 lines there. **Cross-process/proxy limits remain unverified:** the limiter is deliberately process-local, and a shared budget across workers needs deployment verification, which is out of scope. 15 new tests pass, 268 across the related set with 0 skipped, and PERF30/DB03-MODEL catalog tests pass untouched. The worker **found and fixed a real deadlock it had introduced** — a threading lock held across the `yield` in `upload_processing_slot` — before committing. Done · @Ismail · [`a1ff9ad8`](https://github.com/Shmirzaev/Milana-ERP/commit/a1ff9ad8) + [`a66e11b8`](https://github.com/Shmirzaev/Milana-ERP/commit/a66e11b8) · `store_uploaded_image` was `async def` but only awaited the body read — Pillow decode, WebP re-encode, atomic disk writes, thumbnails and the route SQL all ran on the loop thread. Heartbeat: ticks **6 → 61**, blocking calls **15 → 0**. Admission and cleanup: a `CapacityLimiter` plus a bounded wait queue returning 429 beyond both, and `asyncio.shield` with `abandon_on_cancel=False` so a cancelled request still learns the outcome. The scope recheck survives the offload and is proven by TOCTOU tests that flip the row *after* the file is stored. Donor `b607eda` rejected — it depends on helpers in `app/core/uploads.py` that do not exist on this branch. **Old-logo cleanup now closed:** `discard_replaced_managed_image()` **had no call site anywhere in the repo** — a fully tested, green function that was never invoked, so every logo upload leaked the previous file and all its prebuilt thumbnails indefinitely. `upload_company_logo` now captures the previous `logo_url` and discards it only AFTER the commit and only when the URL actually changed. Known wart left alone: `prebuild_webp_thumbnails` names thumbnails with a doubled `.webp` extension; writer and deleter agree, so it is correct, and renaming it is separate work. **Still unverified:** cross-process and proxy limits — the limiter is deliberately process-local, and a shared budget across workers needs deployment verification, which is out of scope. 15 new tests pass, 268 across the related set with 0 skipped. The worker **found and fixed a real deadlock it had introduced** — a threading lock held across the `yield` in `upload_processing_slot` — before committing. |

| 104 | **PERF41** | Eco history queries rolls separately per dispatch. | Load page rolls once, group by dispatch and defer unused remaining-inventory data; retain date/order/global totals. | `B:api/routes/eco_transfers.py:193`; `B:api/routes/eco_transfers.py:81`; `732b65d`; [regression](https://github.com/Shmirzaev/Milana-ERP/blob/2f549f9b202ef1a66ed6ffe17be07b5497ccdeab/backend/app/tests/test_eco_history_query_growth.py) | Done · @Ismail · [`47f3714d`](https://github.com/Shmirzaev/Milana-ERP/commit/47f3714d) · `report()` called `dispatch_data()` once per dispatch and each call issued its own `SELECT ... FROM eco_fabric_rolls WHERE dispatch_id = ?`, so cost was 3+N. Measured on PostgreSQL 17.11 with 13 dispatches × 2 rolls: page of 2 went **5 → 4** statements, page of 12 went **15 → 4** — linear to flat. `dispatch_data()` gained a keyword-only `rows=None` that runs the **original** query when unset, so `send()` and `/{id}/pdf` are byte-for-byte untouched; the page's rolls load in one `IN (...)` query ordered by `EcoFabricRoll.id`, matching the old per-dispatch order so `sum(Decimal(...))` addition order is identical. **Corrected the donor:** `732b65d` used a bare `defer()`, but SQLAlchemy 2.0 defaults `raiseload=False`, which lazily re-fetches and would have silently reinstated an N+1; used `defer(..., raiseload=True)` so a future read raises, and the test asserts the column is absent from emitted SQL *and* that access raises. Deferral proven safe by repo-wide grep: `remaining_inventory` is written only in `send()` and read only by tests through their own un-deferred sessions. Totals pinned by a **golden capture** taken from the unfixed route (both pages plus a date-filtered envelope, `str(Decimal)` for every total, so precision is compared as text not floats). 1 failed/6 passed on unfixed → 8 passed; 112 adjacent post-rebase, 0 skipped. **Not changed on purpose:** a dispatch with no rolls makes `sum()` return int `0`, so `sent_kg` serializes as `0` not `"0.0000"`; the golden pins that pre-existing quirk, and normalizing it would alter the payload. |

| 105 | **PERF42** | Sewing line context repeats capacity sums per assignment/work order. | Build line response capacity/batch maps once and pass them into work-order context; keep scalar write validation, top/bottom minimum limits, zero-clamping and planned fallback. | `B:api/routes/sewing_daily_reports.py:287`; `B:api/routes/sewing_daily_reports.py:189`; `2166dba`; [regression](https://github.com/Shmirzaev/Milana-ERP/blob/2f549f9b202ef1a66ed6ffe17be07b5497ccdeab/backend/app/tests/test_sewing_line_context_query_growth.py) | Open · Mirshoir |

| 106 | **SEC09-RESET-PROXY** | Frontend reset proxies accept unbounded bodies and stalled responses. | Bound incoming JSON and upstream full-response deadlines in forgot/reset proxies. | `F:app/api/auth/forgot-password/route.ts`; `F:app/api/auth/reset-password/route.ts`; `b926fba`, `f35a62e6` | Open · Dilmurod |

| 107 | **UI01** | Temporary API/network failures log users out. | Preserve sessions on network/503 failures; logout only for definitive invalid/revoked authentication. | `F:lib/auth.ts:37`; `F:components/AuthGate.tsx:174`; `3881177e` | Open · Dilmurod |

| 108 | **UI02** | Request deadlines end before response bodies finish. | Keep deadline/cancellation active through response-body consumption for JSON/form/label reads. | `F:lib/api.ts:20`; `3881177e` | Open · Dilmurod |

| 109 | **UI03-PURCHASE** | Purchase receipts have no durable retry/recovery UI. | After ST01, restore durable receipt key/payload recovery across reloads and ambiguous/rejected responses. | `F:app/(app)/purchasing/receiving/page.tsx:230`; `3881177e`, `641c0580`, `3532e8e4` | Done · @Ismail · [`6deb80a9`](https://github.com/Shmirzaev/Milana-ERP/commit/6deb80a9) + [`1a1f423d`](https://github.com/Shmirzaev/Milana-ERP/commit/1a1f423d) · the page now sends `Idempotency-Key` via the additive `api.postWithHeaders` from `15c77721`, with a key lifecycle mirroring `lib/packageWorkflow.ts`: stable across retries, **minted anew on any edit** (a reused key with a changed body would 409 and look like a server error), scoped per order+line, persisted in `sessionStorage` so a reload can retry, cleared on success and on a definite 4xx. Replay is reported as success; 409 gets a recoverable tone. Coordinator re-ran the check on the merged branch: retry now yields `received 5 across 1 receipts (replayed: true)`. **Unverified: no browser/DOM run** — reload survival and the operator-facing flow need a human pass. |

| 110 | **UI05** | Home Production KPI double-counts stage activity. | Label summed stage quantities as stage activity, with explanation in EN/RU/UZ. | `F:app/(app)/page.tsx:291`; `a0818c41` | Open · Mirshoir |



## Completed on clone_main



These four previously implemented changes have recorded workflow checks in [project context](docs/PROJECT_CONTEXT.md). They are sub-tasks, not four fully closed develop audit findings; unrelated FN07/FN08/OPS09 work remains open above.



| N | ID | Completed behavior | Tracking / evidence |

| --- | --- | --- | --- |

| 1 | **FN07-SETTLEMENT** | Outstanding USD <= $1.00 displays settled without changing actual debt or receipts. | Done · owner unrecorded · [`6c5bf63c`](https://github.com/Shmirzaev/Milana-ERP/commit/6c5bf63c) · recorded 52 backend checks + TypeScript |

| 2 | **FN07-UNIT-COST** | Finite, bounded purchase/stock unit costs round HALF_UP to four decimals before storage. | Done · owner unrecorded · [`40baf767`](https://github.com/Shmirzaev/Milana-ERP/commit/40baf767) · recorded 213 checks, 2 optional PostgreSQL skips |

| 3 | **FN08-REVENUE** | Active-invoice revenue uses applied received payments; unpaid shipped sales retain debt. | Done · owner unrecorded · [`ece87130`](https://github.com/Shmirzaev/Milana-ERP/commit/ece87130) · recorded 61 checks + isolated PostgreSQL |

| 4 | **OPS09-1C-RETIREMENT** | Unused active 1C connector removed; history/manual payments retained. | Done · owner unrecorded · [`561a0393`](https://github.com/Shmirzaev/Milana-ERP/commit/561a0393) · recorded 27 workflow checks |



## Fix constraints and completion



- Preserve approved settlement display (`6c5bf63c`): outstanding USD <= $1.00 is settled, but actual debt/receipts remain unchanged and remaining cents are payable. Preserve four-decimal HALF_UP purchase/stock unit costs (`40baf767`); historical cost rewriting is not approved.

- Preserve received-payment revenue (`ece87130`): apply receipts to active invoices, cap by invoice value before period filtering, use UTC dates and exclude advances/excess/reversed sales. Shipped unpaid sales remain debt. Retain factory isolation, work dates/split allocation, first-grade and package-return/shipment workflows.

- Port donor helpers and narrow hunks with their dependencies. Clone migration head is `0135_usluga_paid_processes`; adapt additive migrations to it. Failed pieces must not create replacement work.

- Reuse/adapt donor regressions. Verify rejection/success, permission/factory boundaries, retry/rollback and side effects; use isolated migrated PostgreSQL for races/schema checks. For paging/performance, verify exact totals and bounded query/hydration/memory growth. Record fix commit and actual pass/fail/skip results in the PR.

- Keep 1C retired (`561a0393`), preserving historical origin data, manual payments and generic idempotency. Remove obsolete environment entries only during an authorized configuration update. Historical waste repair/backfill is outside scope; preserve history and authorized dashboard presentation mode. Historical audit-chain break #744 requires separate evidence-backed investigation. Already-present fixes and history-only candidates are excluded from the task list.



## Pending policy decisions — Shavkat decision queue



Five open decisions. Each states the question, the options, an engineering recommendation and exactly what is blocked, so they can be answered in one pass without reading code. **D1, D2 and D4a are unblocked from a business standpoint** — only D2's approval step and D4b genuinely need a business answer. Recommendations are ours, not decisions; nothing below is implemented.



| ID | Question | Options | Recommendation | Blocks |

| --- | --- | --- | --- | --- |

| **D1** · FN08 | Which cost and currency source feeds profit and combined totals for historical invoices? | (a) current cost, (b) historical cost as booked, (c) per-invoice recorded currency, (d) converted at booking rate | Needs your call on history; cash revenue/debt are already implemented and stay as-is. | FN08 sub-task |

| **D2** · DB01/DB05/DB06 | Approve the data, permission and index changes, with exact affected rows, backup and rollback — before any of it runs? | (a) approve with the listed rows, (b) approve indexes only, (c) hold | **(a), indexes first.** Two concrete findings reduce the risk: `0055_delete_mistaken_po15` **already self-guards** — it `RAISE NOTICEs` when `PO-2026-000015` is absent and `RAISE EXCEPTION`s when production activity now exists (`0055:30-50`), so it cannot silently re-delete. And `0025_material_reservations` creates **both** a `UniqueConstraint("reservation_no")` (`:57`) **and** a redundant unique index on the same column (`:61`) — the duplicate-constraint case is real, self-contained, and removable. | DB01/DB05/DB06 |

| **D3** · PERF23 | Paging UX for the five pricing-list consumers: page size, load-more vs numbered pages, and whether a 5-second refresh is wanted at all. | (a) load-more, 50/page, poll only when visible and online, (b) numbered pages, no polling, (c) keep 5s polling | **(a).** **Assets and polling already landed** in [`1e664292`](https://github.com/Shmirzaev/Milana-ERP/commit/1e664292) — the N+1 preload and the shared visibility/offline hook are done and are not part of this decision. **What is blocked is the cap**, which was deliberately left off for the reason below. All five consumers are in-repo and all call `.map` on a bare array, so they can change together; the response shape itself need not change. | **PERF23 cap only** — the list is currently unbounded and the shared hook is live |

| **D4b** · RES-PLAN-ARCHIVE | May reservation planning offer a batch whose `qc_status` is not `passed`? | (a) exclude only `failed`/`rejected`/`hold`, keep `pending` eligible, (b) require `passed` | **(a), and it matters.** `qc_status` is `NOT NULL` and **defaults to `'pending'`** (`models/inventory.py:44,68`), and **no production read path filters on `qc_status` at all** today. Option (b) would therefore make **every newly received batch ineligible** until someone manually marks it passed — a large silent behaviour change. Separately, **D4a needs no decision**: excluding `archived_at` matches what `cutting_material_assignment.py:49` and `api/routes/inventory.py:591` already do, and an Eco custody dispatch is exactly what sets `archived_at`, so that half is an inconsistency we will fix under D4a's own merits. | RES-PLAN-ARCHIVE |

| **D5** · ~~PERF24/26/34~~ | ~~Agreed lock order~~ **RESOLVED and implemented** — see the Closed row below. | — | Option (a) adopted. | none — closed |
| **D6** · ST11 | When an item-only reservation and a batch-scoped reservation both draw on the same stock, **does the item-scoped claim count against the batch-scoped one?** This is the entire remaining half of `ST11`. | (a) yes — an item-scoped claim reduces batch-scoped availability, (b) no — the two are deliberately independent, (c) reject the overlap rather than resolve it | **I will not guess; this is stock, and a wrong default is how fabric gets double-committed.** The *locking* half is already done and proven in [`321240df`](https://github.com/Shmirzaev/Milana-ERP/commit/321240df): one shared pre-pass locks batches then items in a global order with `FOR NO KEY UPDATE`, so the two paths can no longer bypass each other (4 failed on base — 20 reserved against 10 on hand — → 4 passed, with a two-connection PostgreSQL 17.11 proof). What is **not** solved is that serialising the paths does not cap a batch-scoped reservation against item-scoped claims, because `available_stock_for_batch` counts only reservations carrying that `stock_batch_id`. So an item-only claim of 10 plus a batched claim of 10 can still total 20 against 10 on hand. The engineering change is small once the rule is chosen; only the rule needs you. | **ST11** |



**Cleared on 2026-10-04 (no longer decisions):** `PERF22-USLUGA` and `PERF35-FINANCE` were previously held here as legacy-array compatibility questions. A consumer sweep showed each list endpoint has exactly one in-repo consumer, no documented contract, no MCP/integration caller and no print/export path, so both are internal shape changes rather than business decisions. **Both have since landed** ([`ccea9583`](https://github.com/Shmirzaev/Milana-ERP/commit/ccea9583), [`c50d5719`](https://github.com/Shmirzaev/Milana-ERP/commit/c50d5719)). Worth recording why the sweep was worth running: PERF22's paging fix would have silently narrowed results, because a client-side filter was hiding matches past row 50, and PERF35's scoping survey under-counted its own test dependencies five-to-one. **PERF23** is split — the asset preload and the shared polling hook landed, and only the cap is still open, blocked on D3 and deliberately left off rather than shipped as silent row loss.



| N | ID | Required decision | Tracking |

| --- | --- | --- | --- |

| 1 | **FN08** | See **D1** above. | Blocked · Shavkat (business decision); Ismail (engineering assessment) |

| 2 | **PERF23** | See **D3** above; paging UX only. | Blocked · Shavkat (business UX); Ismail (engineering) |

| 3 | **DB01 / DB05 / DB06** | See **D2** above. | Blocked · Shavkat (business-data approval); Ismail (technical plan and approval coordination) |

| 4 | **RES-PLAN-ARCHIVE** | See **D4b** above; D4a needs no decision. | Blocked · Shavkat (business eligibility); Ismail (engineering) |

| 5 | **PERF24 / PERF26 / PERF34** | **RESOLVED and implemented** under D5 — see the Closed rows above. | Closed · @Ismail. Remaining gaps: no concurrent-request lock test on PERF26, and migration `0137` was never executed against a live database. |
| 6 | **ST11** | **D6** — item-scoped vs batch-scoped reservation. The locking half is already proven; only the eligibility rule is open. | Blocked · Shavkat (business rule); Ismail (engineering once decided) |



## Operations follow-ups



Owner approvals are requirements, not proof of live completion. Keep the company-server choice, RTO 24h/RPO zero/seven-day retention and approved credential rotation. No live changes/checks were performed in this audit.



| N | ID | Required action / evidence | Develop reference | Tracking |

| --- | --- | --- | --- | --- |

| 1 | **OPS01** | Capture an authorized synchronized browser/API/SQL/network incident window and identify the bottleneck. Develop tracer is local-only; do not enable it publicly. Source: `B:main.py:278`. | `428f8c9c`, `4151427a` | Open · Mirshoir |

| 2 | **OPS02** | Retain the two-worker/pool-eight/overflow-four slot budget; inventory every database client and measure peak concurrency/queueing against the global budget. Source limits alone do not prove capacity. Source: `deploy/slotctl.py:33`. | `cc7ffdf` | Open · Ismail |

| 3 | **OPS03** | On the approved company server, inventory shared workloads/clients, assign owners, verify effective limits/backup schedules and measure contention. Source: `deploy/slotctl.py:33`; `docs/DISASTER_RECOVERY.md:15`. | `b2490d19` | Open · Ismail |

| 4 | **OPS04** | Verify physical host/storage/power/network failure domains and an approved host-loss recovery path; same-host blue/green is not independent failover. Source: `DEPLOYMENT.md:8`; `docs/DISASTER_RECOVERY.md:12`. | `6cb5a1fb` | Open · Dilmurod |

| 5 | **OPS07** | Collect authorized time-matched DNS/TLS/loss/jitter, proxy/backend and firewall/shaping evidence from actual factory/branch paths. Source: `DEPLOYMENT.md:20`. | `5c4d7e60` | Open · Mirshoir |

| 6 | **OPS10** | Assign owners/capacity, protect database plus uploads and seven-day restore chains, then witness an isolated drill proving RTO <=24h and zero acknowledged transaction/file loss. Source: `docs/DISASTER_RECOVERY.md:9`; `docs/DISASTER_RECOVERY.md:77`. | `a5fc23fb` | Open · Dilmurod |

| 7 | **OPS11** | Privately inventory accounts/consumers, assign vault ownership, replace/revoke exposed credentials and verify old-value rejection with value-free evidence. Source: `docs/SECURITY_RUNBOOK.md:25`. | `1e06696d` | Open · Dilmurod |



<details>

<summary>Develop audit coverage — all 127 findings</summary>



The [develop ledger](https://github.com/Shmirzaev/Milana-ERP/blob/2f549f9b202ef1a66ed6ffe17be07b5497ccdeab/docs/audit_backlog.json) contains **127 findings / 124 unique IDs** (ST02 twice, SEC07 three times): **106 fixed, 15 partial, 6 open on develop**.



**Clone_main source assessment: 91 open/partial findings, 26 core fixes present, 7 operational findings still open and 3 retired/intentional.** Broad findings split into multiple implementation tasks. The four Completed sub-tasks are not four fully closed original findings; source presence is not a current runtime or production certification.



Comparison snapshots: `clone_main` `38a56bbc`, `develop` `2f549f9b`; source and donor regressions inspected. Historical data, runtime performance and operational outcomes were not exercised. Sampled/broad rows retain the limits of source review; close only after the full task's required regression evidence lands.



| Original N | ID | Original finding | clone_main disposition / work |

| --- | --- | --- | --- |

| 1 | **ST01** | Same receipt adds stock twice: five becomes ten. | **Open** — Open/partial: `ST01`. |

| 2 | **ST02** | Issuing four from ten leaves ten in stock. | **Open** — Open/partial: `ST02`. |

| 3 | **ST02** | Movement accepts an item with another item's batch. | **Open** — Open/partial: `ST02`. |

| 4 | **ST03** | W1 movement changes W2's reported balance. | **Open** — Open/partial: `ST03`. |

| 5 | **ST11** | Concurrent reservations accept twenty against ten available. | **Partial** — Open/partial: `ST11`. |

| 6 | **FN02** | Payments total 120 against 100; invoice stays partially paid. | **Present** — Core source present; current regressions/measurement pending. `B:services/payments.py:67` |

| 7 | **FN04** | Concurrent requests create two invoices for one order. | **Fixed on `clone_main`** — [`8e42807e`](https://github.com/Shmirzaev/Milana-ERP/commit/8e42807e), reviewed APPROVE. `partners.py:195` and `services/workflow.py:624` remain unlocked. |

| 8 | **SEC03** | Concurrent audit entries break chain verification. | **Present** — Core source present; current regressions/measurement pending. `B:services/audit.py` |

| 9 | **SEC02** | Deleting a user changes hashed historical records. | **Present** — Core source present; current regressions/measurement pending. `B:api/routes/admin.py:437` |

| 10 | **DB04** | Fresh database setup fails at migration 0039. | **Present** — Core source present; rerun/measurement pending. `backend/alembic/versions/0001_initial.py:18` |

| 11 | **SEC01** | Legacy factory wildcard bypasses newer grant restrictions. | **Present** — Core source present; current regressions/measurement pending. `B:services/user_access.py:15` |

| 12 | **SEC10** | Limited user-manager can delete a Super Admin without wildcard. | **Open** — Open/partial: `SEC10`. |

| 13 | **API06** | Changing own name grants pricing-list access. | **Fixed on `clone_main`** — [`e808891a`](https://github.com/Shmirzaev/Milana-ERP/commit/e808891a). Deploy prerequisite: those staff need an explicit grant first. |

| 14 | **SEC04** | Disabled user's cookie still downloads model files. | **Open** — Open/partial: `SEC04`. |

| 15 | **SEC05** | Older unused reset link works after another reset succeeds. | **Open** — Open/partial: `SEC05`. |

| 16 | **SEC07** | Wrong-factory flow utilization returns data. | **Open** — Open/partial: `SEC07-FLOW`. |

| 17 | **SEC07** | Wrong-factory passport GET exposes its notes. | **Present** — Core source present; current regressions/measurement pending. `B:api/routes/cutting_passports.py:450` |

| 18 | **SEC07** | Wrong-factory assignment DELETE succeeds. | **Open** — Open/partial: `SEC07-ASSIGNMENT`. |

| 19 | **PY01** | Fast employee switch credits work to previous employee. | **Partial** — Open/partial: `PY01`. |

| 20 | **UI01** | Temporary 503/network failure logs user out. | **Open** — Open/partial: `UI01`. |

| 21 | **UI02** | Timeout stops at headers; response body can hang. | **Open** — Open/partial: `UI02`. |

| 22 | **UI03** | Rejected pending receipt blocks corrected submission. | **Partial** — Open/partial: `UI03-PACKAGE`, `UI03-PURCHASE`. |

| 23 | **PERF01** | Package list uses 152 SELECTs for fifty rows. | **Partial** — Open/partial source gap: `PERF01` above. |

| 24 | **PERF07** | One-label payroll page uses 155 SELECTs with fifty reference groups; old code used seven. | **Partial** — Open/partial source gap: `PERF07` above. |

| 25 | **PERF41** | Eco history uses 54 SELECTs for fifty dispatches. | **Open** — Open/partial source gap: `PERF41` above. |

| 26 | **UI04** | Management dashboard forces labeled demo data. | **Retired / intentional** — Approved dashboard presentation mode retained. |

| 27 | **ST05** | Accessory returns are deducted from two issue groups. | **Present** — Core source present; current regressions/measurement pending. `B:services/inventory.py:1277` |

| 28 | **ST06** | Concurrent accessory returns share an unlocked allowance. | **Open** — Open/partial: `ST06`. |

| 29 | **ST07** | Legacy finished-goods reservations lack shared locking. | **Present** — Core source present; current regressions/measurement pending. `B:api/routes/finished_goods.py:190` |

| 30 | **ST08** | Legacy release can restore already-shipped stock. | **Present** — Core source present; current regressions/measurement pending. `B:api/routes/finished_goods.py:190` |

| 31 | **ST09** | Damaged packages remain reservable. | **Partial** — Open/partial: `ST09`. |

| 32 | **ST10** | Purchase-request conversion can race. | **Present** — Core source present; current regressions/measurement pending. `B:services/purchasing.py:196` |

| 33 | **WF01** | Generic production PATCH accepts internal fields. | **Open** — Open/partial: `WF01`. |

| 34 | **WF02** | Generic work-order commands skip some stage/factory checks. | **Partial** — Open/partial: `WF02`. |

| 35 | **WF03** | Legacy package creation can bypass missing production evidence. | **Partial** — Open/partial: `WF03`. |

| 36 | **WF04** | Output/input conservation is not consistently checked. | **Present** — Core source present; current regressions/measurement pending. `B:schemas/production.py:347` |

| 37 | **WF05** | Legacy package model can differ from its order. | **Present** — Core source present; current regressions/measurement pending. `B:services/packages.py:335` |

| 38 | **WF06** | Packaging retains target counters loaded before its lock wait. | **Present** — Core source present; current regressions/measurement pending. `B:api/routes/production.py:4997` |

| 39 | **WF12** | Daily reports and sewing writes lock parent/child in different orders. | **Present** — Core source present; current regressions/measurement pending. `B:api/routes/sewing_daily_reports.py:163` |

| 40 | **WF07** | Generic sales PATCH can skip legal status transitions. | **Present** — Core source present; rerun/measurement pending. `B:api/routes/sales.py:1902` |

| 41 | **WF08** | Waste sales lack consistent quantity and remaining-stock checks. | **Open** — Open/partial source gap: `WF08` above. Historical duplicate/value repair and backfill remain excluded. |

| 42 | **WF09** | Waste decisions can repeat or reopen completed disposal. | **Present** — Core source present; rerun/measurement pending. `B:api/routes/waste.py:119` |

| 43 | **WF10** | Viewing waste commits recalculated historical values. | **Present** — Core source present; rerun/measurement pending. `B:api/routes/waste.py:35` |

| 44 | **WF11** | Usluga handover and material edits use different lock rules. | **Present** — Core source present; rerun/measurement pending. `B:api/routes/usluga.py:161; B:api/routes/usluga.py:856` |

| 45 | **AT01** | Failed/unknown device events can count as attendance. | **Open** — Open/partial source gap: `AT01` above. |

| 46 | **AT02** | Incomplete device download advances the checkpoint. | **Present** — Core source present; rerun/measurement pending. `connectors/hikvision_attendance/read_only_connector.py:403` |

| 47 | **AT03** | Roster-refresh failure stops event collection. | **Present** — Core source present; rerun/measurement pending. `connectors/hikvision_attendance/read_only_connector.py:677` |

| 48 | **AT04** | Removing device profiles hides earlier attendance in reports. | **Present** — Core source present; rerun/measurement pending. `B:api/routes/attendance.py:437` |

| 49 | **AT05** | HR and attendance use different day boundaries; weak hours validation. | **Open** — Open/partial source gap: `AT05` above. |

| 50 | **AT06** | Concurrent or out-of-order attendance imports conflict. | **Open** — Open/partial source gap: `AT06` above. |

| 51 | **PY02** | Payroll writers can race with period finalization. | **Open** — Open/partial: `PY02`. |

| 52 | **PY03** | Scanner paths can accept caller-supplied payable values. | **Open** — Open/partial: `PY03`. |

| 53 | **PY04** | Missing date match falls back to latest open period. | **Open** — Open/partial: `PY04`. |

| 54 | **PY05** | QR return uses different locks from scan/finalization. | **Partial** — Open/partial: `PY05`. |

| 55 | **FN01** | 1C import continues after a failed database flush. | **Retired / intentional** — 1C integration retired by owner; preserve imported history/manual payments. |

| 56 | **FN03** | Moving a payment refreshes only the new invoice. | **Retired / intentional** — 1C integration retired by owner; preserve imported history/manual payments. |

| 57 | **FN05** | One-cent advance can leave payment undefined. | **Present** — Core source present; current regressions/measurement pending. `B:api/routes/partners.py:47` |

| 58 | **FN06** | Legacy retry keys lack caller isolation and atomic conflict handling. | **Open** — Open/partial: `FN06`. |

| 59 | **FN07** | Financial types, states and input lists lack consistent bounds. | **Partial** — Open/partial: `FN07-*` (5 tasks). |

| 60 | **FN08** | Reports mix cancelled invoices, current costs and unclear currency rules. | **Partial** — Cash-revenue sub-task Done; historical/current cost and currency policy remain pending: `FN08`. |

| 61 | **SEC06** | Administrator PATCH locks membership; DELETE does not. | **Open** — Open/partial: `SEC06`. |

| 62 | **SEC08** | Super Admin raw edits bypass domain services. | **Open** — Open/partial: `SEC08`. |

| 63 | **SEC09** | Same-second token rotation, incomplete profile response and weak reset-proxy handling remain. | **Partial** — Open/partial: `SEC09-PROXY`, `SEC09-RESET-PROXY`. |

| 64 | **API01** | Task creator can reassign through PATCH despite stricter creation rules. | **Present** — Core source present; current regressions/measurement pending. `B:api/routes/tasks.py:203` |

| 65 | **API02** | Task fields lack consistent state/date/reference validation. | **Open** — Open/partial: `API02`. |

| 66 | **API03** | Settings PATCH can reset omitted fields or return 500. | **Present** — Core source present; current regressions/measurement pending. `B:api/routes/settings.py` |

| 67 | **API04** | HR scope, salary/date ranges and required values are inconsistent. | **Present** — Core source present; current regressions/measurement pending. `B:api/routes/hr_workspace.py` |

| 68 | **API05** | Global reports and forecast relationships need explicit business rules. | **Partial** — Open/partial: `API05`. |

| 69 | **PERF02** | Accessory queue computes every candidate before paging. | **Open** — Open/partial source gap: `PERF02` above. |

| 70 | **PERF03** | Reservation planning repeats item and batch reads. | **Open** — Open/partial source gap: `PERF03` above. |

| 71 | **PERF04** | Bundle checks repeat accessory checks: B × A query component. | **Open** — Open/partial source gap: `PERF04` above. |

| 72 | **PERF05** | Label issuance performs roughly two lookups per label, up to 5,000 labels. | **Open** — Open/partial source gap: `PERF05` above. |

| 73 | **PERF06** | Unbounded bulk payroll repeats validation and refreshes. | **Partial** — Open/partial: `PERF06`. |

| 74 | **PERF08** | Receiving queue loads all packages and detailed children. | **Open** — Open/partial source gap: `PERF08` above. |

| 75 | **PERF09** | Package writes repeat allocation, costing and workflow queries. | **Partial** — Open/partial source gap: `PERF09` above. |

| 76 | **PERF10** | Receiving/placement repeats package, stock and member reads. | **Partial** — Open/partial source gap: `PERF10` above. |

| 77 | **PERF11** | Print-run listing reads members separately per run. | **Open** — Open/partial source gap: `PERF11` above. |

| 78 | **PERF12** | Label printing repeats model/asset/allocation lookups. | **Open** — Open/partial source gap: `PERF12` above. |

| 79 | **PERF13** | Bundle receiving repeats legacy lookups and gates. | **Partial** — Open/partial source gap: `PERF13` above. |

| 80 | **PERF14** | Passport operations repeat order/material lookups. | **Partial** — Open/partial source gap: `PERF14` above. |

| 81 | **PERF15** | Planning loads BOM per sales line and stock per item. | **Open** — Open/partial source gap: `PERF15` above. |

| 82 | **PERF16** | Flow utilization repeats assignment/work-order queries. | **Partial** — Open/partial source gap: `PERF16` above. |

| 83 | **PERF17** | Daily sewing reports repeat passport/model lookups. | **Partial** — Open/partial source gap: `PERF17` above. |

| 84 | **PERF18** | Receive options process all scopes before limiting output. | **Partial** — Open/partial source gap: `PERF18` above. |

| 85 | **PERF19** | Cutting reconciliation repeats aggregates per work order. | **Open** — Open/partial source gap: `PERF19` above. |

| 86 | **PERF20** | Cutting/packaging paths repeat bundle, log, stock and BOM reads. | **Partial** — Open/partial source gap: `PERF20` above. |

| 87 | **PERF21** | Traceability expands related histories with repeated queries. | **Partial** — Open/partial source gap: `PERF21` above. |

| 88 | **PERF22** | Usluga list is unpaged with repeated child reads. | **Partial** — Open/partial: `PERF22-USLUGA`. |

| 89 | **PERF23** | Pricing lists lazily load model assets/BOM; screens poll frequently. | **Open** — Open/partial source gap: `PERF23` above. |

| 90 | **PERF24** | Sales/shipment serializers conditionally fetch missing related records. | **Open** — Open/partial source gap: `PERF24` above. |

| 91 | **PERF25** | Sales history loads/sorts all candidates before summary output. | **Open** — Open/partial source gap: `PERF25` above. |

| 92 | **PERF26** | Legacy branded reservation repeats variant checks/repair. | **Open** — Open/partial source gap: `PERF26` above. |

| 93 | **PERF27** | Shipment operations repeat package checks and order synchronization. | **Open** — Open/partial source gap: `PERF27` above. |

| 94 | **PERF28** | Purchasing repeats per-line reference and audit-head reads. | **Partial** — Open/partial source gap: `PERF28` above. |

| 95 | **PERF29** | Customer/1C processing recalculates payments per invoice/row. | **Partial** — Open/partial source gap: `PERF29` above. |

| 96 | **PERF30** | Catalog clone/rename/approval repeats probes and broad scans. | **Partial** — Open/partial source gap: `PERF30` above. |

| 97 | **PERF31** | Attendance person import reads each person separately. | **Open** — Open/partial source gap: `PERF31` above. |

| 98 | **PERF32** | Inbox/forecast helpers conditionally load assets and references. | **Partial** — Open/partial source gap: `PERF32` above. |

| 99 | **PERF33** | Stocktake loads all results before paging; exports build whole output. | **Partial** — Open/partial source gap: `PERF33` above. |

| 100 | **PERF34** | Shipment document repeatedly searches lists. | **Open** — Open/partial source gap: `PERF34` above. |

| 101 | **PERF35** | Growing business lists/reports/exports may load everything. | **Partial** — Open/partial: `PERF35-*` (7 tasks). |

| 102 | **PERF36** | Notification/task fan-out and admin table counts grow with recipients/schema. | **Partial** — Open/partial source gap: `PERF36` above. |

| 103 | **PERF37** | Async middleware calls blocking SQLite rate-store writes. | **Open** — Open/partial: `PERF37`. |

| 104 | **PERF38** | Historical per-IP budget is shared by office users. | **Open** — Open/partial: `PERF38`. |

| 105 | **PERF39** | Frontend has dependent requests, duplicate keys and hidden-section fetches. | **Partial** — Open/partial: `PERF39-MODEL`, `PERF39-PACKAGES`, `PERF39-PRODUCTION`. |

| 106 | **PERF40** | Async uploads do synchronous image/SQL/disk work; file lifecycle gaps remain. | **Partial** — Open/partial source gap: `PERF40` above. Retained attendance offloading/cleanup does not close other upload paths. |

| 107 | **PERF42** | Sewing line context repeats capacity sums per row. | **Open** — Open/partial source gap: `PERF42` above. |

| 108 | **DB01** | Alternate writers enforce different quantity/reference/state rules. | **Partial** — Open/partial: `DB01-ADJUSTMENT`, `DB01-CONSUMPTION`. |

| 109 | **DB02** | Some commands use loose strings/raw dictionaries. | **Partial** — Open/partial: `DB02-WO-STATUS`, `DB02-HR-STATUS`. |

| 110 | **DB03** | Editable JSON structures need shape/version validation. | **Partial** — Open/partial: `DB03-*` (6 tasks). |

| 111 | **DB05** | Some migrations change permissions or repair/delete data. | **Open** — Open/partial source gap: `DB05` above. Deployed/data outcomes remain unverified. |

| 112 | **DB06** | Saved catalog has duplicate constraints/indexes and missing-index candidates. | **Partial** — Open/partial source gap: `DB06` above. Historical FK-prefix candidates are unproved, not confirmed missing indexes. |

| 113 | **DB07** | Four-digit order/bundle namespaces have finite capacity. | **Open** — Open/partial: `DB07`. |

| 114 | **OPS01** | No correlated peak-time browser/API/SQL/network trace. | **Operations open** — Open operational evidence/action: `OPS01` below. |

| 115 | **OPS02** | Worker/pool connection budget is not proven. | **Operations open** — Pool/slot source present; global capacity/queueing verification remains open: `OPS02` below. |

| 116 | **OPS03** | ERP shares infrastructure with other workloads/backups. | **Operations open** — Open operational evidence/action: `OPS03` below. No live workload/configuration evidence checked. |

| 117 | **OPS04** | ERP VMs share a physical host. | **Operations open** — Open operational evidence/action: `OPS04` below. Keep approved company-server choice; no unapproved hosting migration. |

| 118 | **OPS05** | Basic health endpoint does not prove dependency readiness. | **Partial** — Open/partial: `OPS05`. |

| 119 | **OPS06** | Uploads depend on server-local storage. | **Open** — Open/partial: `OPS06`. |

| 120 | **OPS07** | Firewall, shaping, DNS and actual branch paths are incompletely checked. | **Operations open** — Open operational evidence/action: `OPS07` below. Source configuration alone cannot prove actual network behavior. |

| 121 | **OPS08** | Old dependency/lifecycle findings need a fresh scan. | **Open** — Open/partial: `OPS08`. |

| 122 | **OPS09** | Historical headers/proxy trust/integration identity need review. | **Partial** — Open/partial: `OPS09-WEB`. 1C portion is retired; applicable web security remains open. |

| 123 | **OPS10** | Restore targets, retention and witnessed recovery are unproven. | **Operations open** — Open operational evidence/action: `OPS10` below. Periodic dumps alone do not prove zero RPO. |

| 124 | **OPS11** | Credentials were shared through handover documents. | **Operations open** — Open operational evidence/action: `OPS11` below. Rotation is approved, but live completion unverified; keep 1C retired. |

| 125 | **DB08** | ORM-only test schemas differ from the migration-created database. | **Open** — Open/partial: `DB08`. |

| 126 | **SEC11** | Quality-check creation accepts a work order without checking its factory. | **Present** — Core source present; current regressions/measurement pending. `B:api/routes/production.py:5166` |

| 127 | **UI05** | Legacy home Production KPI adds cutting, printing, sewing and packaging quantities. | **Open** — Open/partial: `UI05`. |



</details>



Tracker conventions: [GitHub assignees](https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/assigning-issues-and-pull-requests-to-other-github-users), [PR/issue links](https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/linking-a-pull-request-to-an-issue), [bug-report fields](https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests/syntax-for-issue-forms).



Reference: [develop implementation/tests](https://github.com/Shmirzaev/Milana-ERP/tree/2f549f9b202ef1a66ed6ffe17be07b5497ccdeab). No application fix, historical backfill, configuration change or production deployment was performed by this tracker audit.

