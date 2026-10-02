# Team bug tracker — clone_main

**Updated: 2026-10-02. Target: `clone_main`.** **68 open implementation tasks**, 4 completed changes, 6 pending decision/operations groups and 56 audit findings needing verification. Source gaps still need runtime reproduction/regression evidence. A develop fix or a missing commit does not establish clone_main status.

## How the team updates this file

- **Claim:** change Tracking to `In progress · @owner · issue/PR link` before starting; one responsible owner per task. Use `Open`, `In progress`, `Review`, `Blocked`, `Needs review` or `Done`.
- **Add:** use a stable unique ID (`BUG-001`, then the next free number), P1/P2 priority, affected branch/commit, reproducible steps, actual vs expected behavior, and source/test evidence. Check for duplicates; put long logs/reproduction in a linked issue. Keep this file as the shared index.
- **Fix:** name task IDs in the PR targeting `clone_main`; record dependencies/blockers and relevant test results. Change Tracking to `Review · @owner · PR link` while awaiting review. Reproduce source-only candidates before claiming a confirmed runtime failure.
- **Done:** after the reviewed fix lands on `clone_main` and regressions pass, move the same row to Completed with `Done · @owner · merged PR/commit · test evidence`. Retain its ID/history. Reopen the same row if it regresses. Done means fixed on this branch; record deployment separately.
- Update only affected rows and the date/counts through a PR; reconcile concurrent edits before merging. `—` means unassigned; owner/PR names must not be invented. GitHub closing keywords only auto-close linked issues on the default branch, so verify issue closure after a `clone_main` merge.

**Numbering:** `N` counts rows within each list; P1/P2 share numbers 1–68. Stable task IDs remain unchanged. Review findings are not additional confirmed bugs.

**Source paths:** `B:` = `backend/app/`, `F:` = `frontend/src/`. Existing source locations refer to snapshot `942801b0`; follow the current function when lines move. Develop hashes are implementation/test references.

## P1 — authorization and stock/payroll/money correctness

| N | ID | Current bug | Required fix | Source; develop reference | Tracking |
| --- | --- | --- | --- | --- | --- |
| 1 | **API02** | Task references/states bypass validation and scope. | Validate task states/dates/references; enforce target permission/factory scope and lock referenced rows. | `B:schemas/tasks.py:8`; `22593e7`, `31350dc`, `73d7ca4` | Open · — |
| 2 | **API05** | Forecast/report routes read and mutate across factories. | Apply effective per-factory view/manage grants and model attribution to forecasts/reports. | `B:api/routes/forecasting.py:47`; `064be49`, `fc450a5`, `0e9bb6ba`, `feb7415f`, `49d3c200`, `4a5c0b2b` | Open · — |
| 3 | **API06** | Editable name/email grants purchasing-price access. | Remove name/email privilege fallbacks from backend and frontend; require explicit permission. | `B:services/price_calculation.py:29`; `B:core/deps.py:164`; `F:lib/priceCalculationRequests.ts:60`; `d89059eb` | Open · — |
| 4 | **DB01-ADJUSTMENT** | Forced stock corrections leave reservations underbacked. | Enforce reservation floors on both item and batch correction, including force=true. | `B:api/routes/inventory.py:685`; `69ceef4e` | Open · — |
| 5 | **DB01-CONSUMPTION** | Stock consumption accepts incompatible catalog/request/batch units. | Validate catalog/request/all-batch units before consuming any stock. | `B:services/workflow.py:400`; `B:services/workflow.py:442`; `5b4ac7c0` | Open · — |
| 6 | **DB02-WO-STATUS** | Generic work-order PATCH bypasses explicit status transitions. | Reject changed status in generic PATCH; retain metadata no-ops and explicit transition commands. | `B:api/routes/production.py:1607`; `9bdf79c4` | Open · — |
| 7 | **FN04** | Concurrent invoice routes can bill one order twice. | Lock/refetch the SalesOrder before invoice existence checks in both finance and sales routes. | `B:api/routes/finance.py:65`; `B:api/routes/sales.py:1985`; `3881177e`, `6843712f` | Open · — |
| 8 | **FN06** | Generic retry keys replay across callers and race writes. | Scope replay to caller/key/payload and serialize same-key writes across every generic replay site. | `B:services/idempotency.py:31`; `c21e50bb` | Open · — |
| 9 | **FN07-ADJUSTMENT** | Payroll adjustment amount/type/reason validation is incomplete. | Validate finite cent-accurate amounts, supported adjustment types and stored reason length. | `B:schemas/payroll.py:456`; `B:api/routes/payroll.py`; `60f82357`, `4ae84350` | Open · — |
| 10 | **FN07-INVOICE** | Invoice/payment money inputs can exceed precision/storage bounds. | Use storage-bounded Decimal amounts; reject nonfinite, overflowing and sub-cent inputs before writes. | `B:schemas/sales.py:162`; `B:api/routes/finance.py:74`; `5a68d122`, `6304934b` | Open · — |
| 11 | **FN07-PURCHASE-QUANTITY** | Purchase/receipt quantity fields lack finite/storage bounds. | Restore finite/storage quantity bounds after ST01; retain approved unit-cost rounding. | `B:schemas/purchasing.py:77`; `3e75ca62` | Open · — |
| 12 | **FN07-RECORD** | Freeform payroll records lack finite/storage money bounds. | Validate representable payroll record amounts before and after trusted enrichment. | `B:api/routes/payroll.py:121`; `50cbbe84`, `764af788` | Open · — |
| 13 | **PY01** | Fast badge/work scans credit the previous employee. | Queue badge/work/manual selection in arrival order; do not credit work before badge resolution. | `F:app/(app)/payroll/scan/page.tsx:948`; `3881177e` | Open · — |
| 14 | **PY02** | Payroll writes race period finalization. | Use shared refreshed period locks for all record writers and finalizers. | `B:api/routes/payroll.py:517`; `b285877b` | Open · — |
| 15 | **PY03** | Scanner permission can issue caller-priced payable labels. | Require manage permission for payable label issuance/values; scanners use trusted issued labels. | `B:api/routes/payroll.py:2091`; `900641e7` | Open · — |
| 16 | **PY04** | Unmatched work dates attach to the latest open period. | Use only the matching date period or no period; remove latest-open fallback in single/bulk paths. | `B:api/routes/payroll.py:540`; `adc79f77` | Open · — |
| 17 | **PY05** | QR returns use a conflicting payroll lock order. | Use period -> label -> record lock order with fresh assignment checks for return/scan/finalization. | `B:api/routes/payroll.py:2907`; `a2082235` | Open · — |
| 18 | **SEC04** | Disabled or revoked sessions still download model files. | Validate active user and token cutoff for model files; release the auth connection before streaming. | `B:main.py:378`; `3881177e` | Open · — |
| 19 | **SEC05** | Sibling reset links survive a password change. | Lock the account and invalidate sibling reset links on every supported password rotation. | `B:api/routes/auth.py:286`; `3881177e`, `f35a62e6` | Open · — |
| 20 | **SEC06** | Concurrent admin removals can remove the final admin. | Serialize PATCH/DELETE membership changes with audit-compatible NO KEY UPDATE locks. | `B:api/routes/admin.py:600`; `74a2973` | Open · — |
| 21 | **SEC07-ASSIGNMENT** | Assignment deletion bypasses factory and used-output guards. | Check flow/work-order factory and used/output history under locks before deletion. | `B:api/routes/production_extra.py:392`; `3881177e`, `df14ad66` | Open · — |
| 22 | **SEC07-FLOW** | Flow utilization exposes another factory. | Apply sewing-flow access checks to the direct utilization endpoint. | `B:api/routes/production_extra.py:483`; `40c681e` | Open · — |
| 23 | **SEC08** | Raw admin console bypasses business and audit safeguards. | Block generic raw UPDATE/DELETE; allow only named audited repairs and soft-deactivation. | `B:api/routes/super_data.py`; `e7782ec`, `297d808`, `df1d08f` | Open · — |
| 24 | **SEC09-PROXY** | Forwarded client/scheme headers lack explicit proxy trust. | Validate trusted CIDRs and ordered forwarded headers; ignore untrusted client/scheme claims. | `B:api/routes/auth.py`; `B:main.py`; `b926fba`, `f35a62e6`, `0ad74a69`, `4fee48be` | Open · — |
| 25 | **SEC10** | Limited admin can delete a non-wildcard Super Admin. | Protect admin.super targets even when their permission list lacks wildcard. | `B:api/routes/admin.py:600`; `3881177e` | Open · — |
| 26 | **ST01** | Purchase receipt retries add stock twice. | Add caller/order/payload-scoped receipt identity, replay and locking so retries create one receipt. | `B:api/routes/purchasing.py:168`; `3881177e`, `641c0580` | Open · — |
| 27 | **ST02** | Stock movement does not update or validate its batch. | Mutate batch and ledger atomically; validate item/unit/warehouse, claims and Eco custody. | `B:api/routes/inventory.py:1293`; `3881177e` | Open · — |
| 28 | **ST03** | Batchless movements leak into other warehouse balances. | Scope batchless movement aggregation by warehouse and transfer direction without double counting. | `B:services/inventory.py:80`; `3881177e` | Open · — |
| 29 | **ST06** | Concurrent accessory returns share an unlocked allowance. | Lock the shared issue allowance before validating accessory returns and storing replay. | `B:api/routes/inventory.py:865`; `712ccf1` | Open · — |
| 30 | **ST09** | Damaged packages remain reservable and damage races claims. | Recheck damage status under shared package/stock locks; block damage of reserved/linked packages. | `B:api/routes/finished_goods.py:184`; `B:services/packages.py:1203`; `9e336ce`, `f40f4e4` | Open · — |
| 31 | **ST11** | Item-only and mixed reservations can overclaim stock. | Lock common item capacity for item-only and mixed batched reservations; preserve lock order. | `B:services/inventory.py:475`; `3881177e` | Open · — |
| 32 | **UI03-PACKAGE** | Corrected package receipts remain blocked by pending retry state. | Restore durable cross-tab retry state and server reconciliation/tombstones, including changed-body/429 cases. | `F:lib/packageWorkflow.ts:58`; `B:api/routes/package_workflows.py:77`; `3ef1c83e`, `00567734`, `e2a6d8cb`, `3532e8e4` | Open · — |
| 33 | **WF01** | Generic production PATCH changes internal fields/status. | Replace raw setattr PATCH with typed field/reference allowlist and legal workflow-status guards. | `B:api/routes/production.py:1003`; `859b7ca`, `d11fb7aa` | Open · — |
| 34 | **WF02** | Generic work-order commands miss stage/factory boundaries. | Enforce stage authorization and factory scope on update/start/complete/block/unblock commands. | `B:api/routes/production.py:1601`; `84c322a`, `62a3544`, `d8cd060` | Open · — |
| 35 | **WF03** | Ordinary packages can be created without production evidence. | Require packaging evidence for ordinary standard packages; preserve valid first-grade/batch receipts. | `B:services/packages.py:220`; `37258c7` | Open · — |

## P2 — validation, reliability and performance

| N | ID | Current bug | Required fix | Source; develop reference | Tracking |
| --- | --- | --- | --- | --- | --- |
| 36 | **DB02-HR-STATUS** | Employee status writes accept unsupported vocabulary. | Validate newly supplied employee statuses while preserving historical read compatibility. | `B:api/routes/hr.py:21`; `bf364411` | Open · — |
| 37 | **DB03-HR-PROFILE** | Employee profile JSON lacks bounded shape/depth validation. | Validate profile shape/hours and 16 KiB/16-level limits; preserve unchanged legacy values. | `B:api/routes/hr.py:26`; `ada93f89`, `708475d2` | Open · — |
| 38 | **DB03-IMPORT-CORRECT** | Old-ERP correction script bypasses model JSON bounds. | After DB03-MODEL, restore b097037e validator guard before correction-script JSON writes. | `backend/scripts/correct_old_erp_models_local.py:2111`; `b097037e` | Open · — |
| 39 | **DB03-IMPORT-OLD** | Old-ERP import script bypasses model JSON bounds. | After DB03-MODEL, restore 6a902d7a guard before old-ERP import JSON writes. | `backend/scripts/import_old_erp_models_local.py:2412`; `6a902d7a` | Open · — |
| 40 | **DB03-IMPORT-REVIEWED** | Reviewed model import bypasses shared JSON bounds. | After DB03-MODEL, restore 3544b1f4 guard on merged/final reviewed-import details. | `backend/scripts/migrate_reviewed_old_erp_models_production.py:1773`; `3544b1f4` | Open · — |
| 41 | **DB03-MODEL** | Model details JSON lacks size/depth/established-shape validation. | Restore common size/depth/shape validator across catalog writers, clones/variants and family saves. | `B:schemas/catalog.py:221`; `B:api/routes/catalog.py`; `fa3ba201` | Open · — |
| 42 | **DB03-PAYROLL-SNAPSHOT** | Payroll employee/work snapshots are unbounded JSON. | Validate 16 KiB/16-level employee/work snapshots before and after trusted enrichment. | `B:api/routes/payroll.py`; `4f4efcb8` | Open · — |
| 43 | **DB07** | Order/bundle numbering exhausts its four-digit namespace. | Expand monotonic numbering beyond 9999 without recycling issued identities; preserve locks/aliases. | `B:services/numbering.py:79`; `b350c4f`, `11aabc1` | Open · — |
| 44 | **DB08** | ORM metadata disagrees with the existing migrated schema. | Align legacy model-less sales/Beyka ORM with existing clone migrations; test real migrated PostgreSQL. | `B:models/sales.py:51`; `1141d40` | Open · — |
| 45 | **FN07-HR-SALARY** | Employee salary values lack storage validation. | Reject nonfinite, negative and column-overflow employee salaries before create/update. | `B:api/routes/hr.py:21`; `15833133`, `dd03309c` | Open · — |
| 46 | **OPS05** | Readiness ignores a failed required shared store. | Probe PostgreSQL and required shared store under one bounded, single-flight readiness deadline. | `B:main.py:499`; `c275be7` | Open · — |
| 47 | **OPS06** | Recovery tooling cannot verify paired database/upload backups. | Add paired DB/upload manifest verification for dump identity and missing/changed/extra files. | `scripts/storage_recovery_manifest.py (missing)`; `13f5994` | Open · — |
| 48 | **OPS08** | Runtime/dependency hardening from develop is absent. | Review PyJWT/runtime migration; verify legacy tokens and run fresh dependency/built-image scans. | `B:core/security.py`; `frontend/Dockerfile`; `.github/workflows/ci.yml`; `06705b9`, `1896408`, `f288ada`, `f0a1536` | Open · — |
| 49 | **OPS09-WEB** | Production scripts lack nonce CSP and reliable HTTPS headers. | Restore nonce CSP/layout and trusted HTTPS/HSTS handling; keep 1C retired. | `frontend/next.config.js:32`; `aa8fac1`, `f35a62e6`, `0ad74a69`, `4fee48be` | Open · — |
| 50 | **PERF06** | Bulk payroll is unbounded and misses batched validation. | Cap bulk payroll at 500; batch reference/duplicate validation and audit-head work. | `B:schemas/payroll.py:84`; `f42637c3`, `8240fc9`, `67f0309`, `c625aad` | Open · — |
| 51 | **PERF22-USLUGA** | Usluga directory fetches every order. | Use bounded order pages/load more; preserve legacy array compatibility pending owner policy. | `F:app/(app)/usluga/page.tsx:83`; `c8ac9f35` | Open · — |
| 52 | **PERF35-FINANCE** | Finance invoice list silently stops at fifty. | Page/search invoices with exact totals so rows beyond fifty remain reachable. | `F:app/(app)/finance/page.tsx:65`; `88cedd2c` | Open · — |
| 53 | **PERF35-FINISHED-GOODS** | Finished-goods page loads unpaged stock/inbox graphs. | Page stock/branded/inbox data with exact totals and existing reservation/return behavior. | `F:app/(app)/finished-goods/page.tsx:24`; `7b45c231`, `1a030623`, `deef9c6d`, `59fea8bc` | Open · — |
| 54 | **PERF35-HR** | HR employee directory loads all employees/positions. | Use scoped 50-row employee search, exact metrics and lazy retained option pickers. | `F:app/(app)/hr/employees/page.tsx:59`; `9c53b633`, `36b8d225` | Open · — |
| 55 | **PERF35-INBOX** | Department inbox fetches a broad order graph. | Restore canonical identity pages and page-only hydration, including replacement/batch queues. | `F:app/(app)/departments/[code]/page.tsx:101`; `6c412e44`, `3e6c5d43`, `bfb51a95`, `051a5a22`, `dc24cdfd` | Open · — |
| 56 | **PERF35-PAYROLL** | Payroll lists truncate records and load broad summaries/options. | Page records/summary/adjustments and employee options; remove the silent 300-record cutoff. | `F:app/(app)/payroll/page.tsx:218`; `2174ade0`, `b915b530`, `36b8d225` | Open · — |
| 57 | **PERF35-PRODUCTION** | Production directory uses an unpaged array. | Use bounded server search/pages with load more and retained selected/deep-linked orders. | `F:app/(app)/production-orders/page.tsx:31`; `45f24e8b`, `07b5b8fb` | Open · — |
| 58 | **PERF35-PURCHASING** | Receiving queue fetches broad order/supplier directories. | Page receiving orders by supplier and use bounded supplier options without losing receipt state. | `F:app/(app)/purchasing/receiving/page.tsx:117`; `59a86c5d`, `b3239284`, `b2e39065` | Open · — |
| 59 | **PERF37** | Rate-store I/O blocks the async request loop. | Move synchronous rate-store work to bounded worker capacity; test event-loop responsiveness. | `B:main.py:230`; `25fd549` | Open · — |
| 60 | **PERF38** | Office users share one global per-IP budget. | Use authenticated identity buckets; retain IP-only login/reset limits and safe credential fallback. | `B:main.py:154`; `a8b1707` | Open · — |
| 61 | **PERF39-MODEL** | Hidden model tabs still fetch BOM/seasons/all employees. | Fetch BOM/seasons only for visible tab/editor and use bounded employee options. | `F:app/(app)/models/[id]/page.tsx:209`; `be696e12`, `4c751606`, `2e60854f` | Open · — |
| 62 | **PERF39-PACKAGES** | Collapsed package change requests fetch eagerly. | Fetch pending changes only when the section is expanded; refresh after actions. | `F:app/(app)/packages/page.tsx:49`; `1da4f66a` | Open · — |
| 63 | **PERF39-PRODUCTION** | Production details have waterfalls and closed-editor fetches. | Restore paired page-context API/UI; gate utilization/users and page sales options only when needed. | `F:app/(app)/production-orders/[id]/page.tsx:212`; `7445ad49`, `534c8bf2`, `b669bd44` | Open · — |
| 64 | **SEC09-RESET-PROXY** | Frontend reset proxies accept unbounded bodies and stalled responses. | Bound incoming JSON and upstream full-response deadlines in forgot/reset proxies. | `F:app/api/auth/forgot-password/route.ts`; `F:app/api/auth/reset-password/route.ts`; `b926fba`, `f35a62e6` | Open · — |
| 65 | **UI01** | Temporary API/network failures log users out. | Preserve sessions on network/503 failures; logout only for definitive invalid/revoked authentication. | `F:lib/auth.ts:37`; `F:components/AuthGate.tsx:174`; `3881177e` | Open · — |
| 66 | **UI02** | Request deadlines end before response bodies finish. | Keep deadline/cancellation active through response-body consumption for JSON/form/label reads. | `F:lib/api.ts:20`; `3881177e` | Open · — |
| 67 | **UI03-PURCHASE** | Purchase receipts have no durable retry/recovery UI. | After ST01, restore durable receipt key/payload recovery across reloads and ambiguous/rejected responses. | `F:app/(app)/purchasing/receiving/page.tsx:230`; `3881177e`, `641c0580`, `3532e8e4` | Open · — |
| 68 | **UI05** | Home Production KPI double-counts stage activity. | Label summed stage quantities as stage activity, with explanation in EN/RU/UZ. | `F:app/(app)/page.tsx:291`; `a0818c41` | Open · — |


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

## Pending decisions and operational work

| N | ID | Required action | Tracking |
| --- | --- | --- | --- |
| 1 | **FN08** | Decide historical/current cost and currency source/conversion for profit and combined totals. | Blocked · — |
| 2 | **PERF35 / PERF22** | Confirm lazy loading/paging contracts and support for the legacy unpaged Usluga array. | Blocked · — |
| 3 | **DB01 / DB05 / DB06** | Approve historical unit treatment, affected rows, data/permission/index migrations and recovery/rollback before changing data. | Blocked · — |
| 4 | **OPS03 / OPS04** | Existing company server is approved for now; assign workload owners, limits and schedules, and verify availability/failure behavior. | Blocked · — |
| 5 | **OPS06 / OPS10** | Meet approved RTO 24h, RPO zero and seven-day retention: assign owners/capacity, protect database plus uploads together and prove an isolated restore. Periodic dumps alone do not prove zero RPO. | Blocked · — |
| 6 | **OPS11** | Rotation/revocation is approved; assign vault/rotation owner, privately inventory affected accounts, replace/revoke credentials and record evidence. Live rotation remains unverified. | Blocked · — |

<details>
<summary>Develop audit reconciliation and 56 findings needing verification</summary>

The repository [develop ledger](https://github.com/Shmirzaev/Milana-ERP/blob/2f549f9b202ef1a66ed6ffe17be07b5497ccdeab/docs/audit_backlog.json) contains **127 findings / 124 unique IDs** (ST02 appears twice, SEC07 three times): **106 fixed, 15 partial, 6 open on develop**. The supplied Slack file was inaccessible; its claimed 123 count has not been reconciled.

**Clone_main review: 71 findings inspected = 49 gap/partial + 19 core fixes present + 3 retired/intentional; 56 findings not yet verified.** Broad findings split into multiple tasks, so **68 open tasks does not mean about 60 findings are fixed**. Core source present is not a full runtime/operations pass. These classifications refer to the earlier source review, not a new exhaustive audit.

Core source present: FN02 (#6), SEC03 (#8), SEC02 (#9), SEC01 (#11), SEC07 (#17), ST05 (#27), ST07 (#29), ST08 (#30), ST10 (#32), WF04 (#36), WF05 (#37), WF06 (#38), WF12 (#39), FN05 (#57), API01 (#64), API03 (#66), API04 (#67), OPS02 (#115), SEC11 (#126). OPS02 still needs operational measurement; the historical audit-chain break #744 remains unresolved.

Retired/intentional: UI04 (#26, approved presentation mode), FN01 (#55) and FN03 (#56, retired 1C). Historical WF08 repair/backfill remains excluded; current workflow code has not been verified.

For each row below, compare current clone_main source and regressions with the linked develop ledger before moving it to Open or Completed. These are original findings, not 56 additional confirmed bugs; some overlap pending decisions above. Keep old audit IDs; `#number` disambiguates original findings. Performance findings need measured query/latency evidence; operational findings need environment evidence, not commit ancestry.

| N | Audit ID | Finding to verify on clone_main | Tracking | Develop source reference |
| --- | --- | --- | --- | --- |
| 1 | **DB04 (#10)** | Fresh database setup fails at migration 0039. | Needs review · — | `backend/alembic/versions/0001_initial.py:21` |
| 2 | **PERF01 (#23)** | Package list uses 152 SELECTs for fifty rows. | Needs review · — | `backend/app/api/routes/packages.py:85` |
| 3 | **PERF07 (#24)** | One-label payroll page uses 155 SELECTs with fifty reference groups; old code used seven. | Needs review · — | `backend/app/api/routes/payroll.py:2572` |
| 4 | **PERF41 (#25)** | Eco history uses 54 SELECTs for fifty dispatches. | Needs review · — | `backend/app/api/routes/eco_transfers.py:81` |
| 5 | **WF07 (#40)** | Generic sales PATCH can skip legal status transitions. | Needs review · — | `backend/app/api/routes/sales.py:1875` |
| 6 | **WF08 (#41)** | Waste sales lack consistent quantity and remaining-stock checks. Historical repair/backfill is excluded. | Needs review · — | `backend/app/api/routes/waste.py:85` |
| 7 | **WF09 (#42)** | Waste decisions can repeat or reopen completed disposal. | Needs review · — | `backend/app/api/routes/waste.py:108` |
| 8 | **WF10 (#43)** | Viewing waste commits recalculated historical values. | Needs review · — | `backend/app/api/routes/waste.py:43` |
| 9 | **WF11 (#44)** | Usluga handover and material edits use different lock rules. | Needs review · — | `backend/app/api/routes/usluga.py:787` |
| 10 | **AT01 (#45)** | Failed/unknown device events can count as attendance. | Needs review · — | `connectors/hikvision_attendance/read_only_connector.py:532` |
| 11 | **AT02 (#46)** | Incomplete device download advances the checkpoint. | Needs review · — | `connectors/hikvision_attendance/read_only_connector.py:425` |
| 12 | **AT03 (#47)** | Roster-refresh failure stops event collection. | Needs review · — | `connectors/hikvision_attendance/read_only_connector.py:689` |
| 13 | **AT04 (#48)** | Removing device profiles hides earlier attendance in reports. | Needs review · — | `backend/app/api/routes/attendance.py:416` |
| 14 | **AT05 (#49)** | HR and attendance use different day boundaries; weak hours validation. | Needs review · — | `backend/app/api/routes/hr_workspace.py:350` |
| 15 | **AT06 (#50)** | Concurrent or out-of-order attendance imports conflict. | Needs review · — | `backend/app/api/routes/attendance.py:220` |
| 16 | **PERF02 (#69)** | Accessory queue computes every candidate before paging. | Needs review · — | `backend/app/services/inventory.py:1425` |
| 17 | **PERF03 (#70)** | Reservation planning repeats item and batch reads. | Needs review · — | `backend/app/services/inventory.py:377` |
| 18 | **PERF04 (#71)** | Bundle checks repeat accessory checks: B Ã— A query component. | Needs review · — | `backend/app/services/inventory.py:1344` |
| 19 | **PERF05 (#72)** | Label issuance performs roughly two lookups per label, up to 5,000 labels. | Needs review · — | `backend/app/api/routes/payroll.py:2058` |
| 20 | **PERF08 (#74)** | Receiving queue loads all packages and detailed children. | Needs review · — | `backend/app/api/routes/packages.py:1032` |
| 21 | **PERF09 (#75)** | Package writes repeat allocation, costing and workflow queries. | Needs review · — | `backend/app/services/packages.py:258` |
| 22 | **PERF10 (#76)** | Receiving/placement repeats package, stock and member reads. | Needs review · — | `backend/app/api/routes/packages.py:1131` |
| 23 | **PERF11 (#77)** | Print-run listing reads members separately per run. | Needs review · — | `backend/app/services/package_workflows.py:78` |
| 24 | **PERF12 (#78)** | Label printing repeats model/asset/allocation lookups. | Needs review · — | `backend/app/api/routes/packages.py:1486` |
| 25 | **PERF13 (#79)** | Bundle receiving repeats legacy lookups and gates. | Needs review · — | `backend/app/api/routes/bundles.py:326` |
| 26 | **PERF14 (#80)** | Passport operations repeat order/material lookups. | Needs review · — | `backend/app/api/routes/cutting_passports.py:317` |
| 27 | **PERF15 (#81)** | Planning loads BOM per sales line and stock per item. | Needs review · — | `backend/app/services/planning.py:28` |
| 28 | **PERF16 (#82)** | Flow utilization repeats assignment/work-order queries. | Needs review · — | `backend/app/api/routes/sewing_flows.py:274` |
| 29 | **PERF17 (#83)** | Daily sewing reports repeat passport/model lookups. | Needs review · — | `backend/app/api/routes/sewing_daily_reports.py:200` |
| 30 | **PERF18 (#84)** | Receive options process all scopes before limiting output. | Needs review · — | `backend/app/api/routes/production.py:5031` |
| 31 | **PERF19 (#85)** | Cutting reconciliation repeats aggregates per work order. | Needs review · — | `backend/app/api/routes/production.py:4220` |
| 32 | **PERF20 (#86)** | Cutting/packaging paths repeat bundle, log, stock and BOM reads. | Needs review · — | `backend/app/api/routes/production.py:3012` |
| 33 | **PERF21 (#87)** | Traceability expands related histories with repeated queries. | Needs review · — | `backend/app/services/traceability.py:251` |
| 34 | **PERF23 (#89)** | Pricing lists lazily load model assets/BOM; screens poll frequently. | Needs review · — | `backend/app/api/routes/price_calculation.py:53` |
| 35 | **PERF24 (#90)** | Sales/shipment serializers conditionally fetch missing related records. | Needs review · — | `backend/app/api/routes/sales.py:1638` |
| 36 | **PERF25 (#91)** | Sales history loads/sorts all candidates before summary output. | Needs review · — | `backend/app/api/routes/sales.py:1735` |
| 37 | **PERF26 (#92)** | Legacy branded reservation repeats variant checks/repair. | Needs review · — | `backend/app/api/routes/sales.py:1328` |
| 38 | **PERF27 (#93)** | Shipment operations repeat package checks and order synchronization. | Needs review · — | `backend/app/api/routes/shipments.py:978` |
| 39 | **PERF28 (#94)** | Purchasing repeats per-line reference and audit-head reads. | Needs review · — | `backend/app/services/purchasing.py:93` |
| 40 | **PERF29 (#95)** | Customer/1C processing recalculates payments per invoice/row. Review active customer/payment paths; retired 1C is excluded. | Needs review · — | `backend/app/api/routes/partners.py:243` |
| 41 | **PERF30 (#96)** | Catalog clone/rename/approval repeats probes and broad scans. | Needs review · — | `backend/app/api/routes/catalog.py:1045` |
| 42 | **PERF31 (#97)** | Attendance person import reads each person separately. | Needs review · — | `backend/app/api/routes/attendance.py:220` |
| 43 | **PERF32 (#98)** | Inbox/forecast helpers conditionally load assets and references. | Needs review · — | `backend/app/api/routes/inbox.py:689` |
| 44 | **PERF33 (#99)** | Stocktake loads all results before paging; exports build whole output. | Needs review · — | `backend/app/api/routes/stocktake.py:139` |
| 45 | **PERF34 (#100)** | Shipment document repeatedly searches lists. | Needs review · — | `backend/app/api/routes/shipments.py:154` |
| 46 | **PERF36 (#102)** | Notification/task fan-out and admin table counts grow with recipients/schema. | Needs review · — | `backend/app/api/routes/tasks.py:94` |
| 47 | **PERF40 (#106)** | Async uploads do synchronous image/SQL/disk work; file lifecycle gaps remain. | Needs review · — | `backend/app/services/image_storage.py:180` |
| 48 | **PERF42 (#107)** | Sewing line context repeats capacity sums per row. | Needs review · — | `backend/app/api/routes/sewing_daily_reports.py:170` |
| 49 | **DB05 (#111)** | Some migrations change permissions or repair/delete data. | Needs review · — | [audit ledger](https://github.com/Shmirzaev/Milana-ERP/blob/2f549f9b202ef1a66ed6ffe17be07b5497ccdeab/docs/audit_backlog.json) |
| 50 | **DB06 (#112)** | Saved catalog has duplicate constraints/indexes and missing-index candidates. | Needs review · — | [audit ledger](https://github.com/Shmirzaev/Milana-ERP/blob/2f549f9b202ef1a66ed6ffe17be07b5497ccdeab/docs/audit_backlog.json) |
| 51 | **OPS01 (#114)** | No correlated peak-time browser/API/SQL/network trace. | Needs review · — | [audit ledger](https://github.com/Shmirzaev/Milana-ERP/blob/2f549f9b202ef1a66ed6ffe17be07b5497ccdeab/docs/audit_backlog.json) |
| 52 | **OPS03 (#116)** | ERP shares infrastructure with other workloads/backups. | Needs review · — | [audit ledger](https://github.com/Shmirzaev/Milana-ERP/blob/2f549f9b202ef1a66ed6ffe17be07b5497ccdeab/docs/audit_backlog.json) |
| 53 | **OPS04 (#117)** | ERP VMs share a physical host. | Needs review · — | [audit ledger](https://github.com/Shmirzaev/Milana-ERP/blob/2f549f9b202ef1a66ed6ffe17be07b5497ccdeab/docs/audit_backlog.json) |
| 54 | **OPS07 (#120)** | Firewall, shaping, DNS and actual branch paths are incompletely checked. | Needs review · — | [audit ledger](https://github.com/Shmirzaev/Milana-ERP/blob/2f549f9b202ef1a66ed6ffe17be07b5497ccdeab/docs/audit_backlog.json) |
| 55 | **OPS10 (#123)** | Restore targets, retention and witnessed recovery are unproven. | Needs review · — | [audit ledger](https://github.com/Shmirzaev/Milana-ERP/blob/2f549f9b202ef1a66ed6ffe17be07b5497ccdeab/docs/audit_backlog.json) |
| 56 | **OPS11 (#124)** | Credentials were shared through handover documents. | Needs review · — | [audit ledger](https://github.com/Shmirzaev/Milana-ERP/blob/2f549f9b202ef1a66ed6ffe17be07b5497ccdeab/docs/audit_backlog.json) |

</details>

Tracker conventions: [GitHub assignees](https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/assigning-issues-and-pull-requests-to-other-github-users), [PR/issue links](https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/linking-a-pull-request-to-an-issue), [bug-report fields](https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests/syntax-for-issue-forms).

Reference: [develop implementation/tests](https://github.com/Shmirzaev/Milana-ERP/tree/2f549f9b202ef1a66ed6ffe17be07b5497ccdeab). No application change or production deployment was performed by this tracker update.
