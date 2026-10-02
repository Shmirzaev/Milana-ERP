# Bugs to fix on clone_main

**Updated: 2026-10-02. Target: `clone_main`. All rows below are open.** These are source-checked gaps on this branch; runtime regression checks remain pending. Develop commits are implementation/test references, not status evidence.

**Source paths:** `B:` = `backend/app/`, `F:` = `frontend/src/`. Locations refer to source snapshot `942801b0`, unchanged in `d857478a`. Pick a task ID, assign it in your issue/PR, and close it here only after the verified fix lands on `clone_main`.

## P1 — authorization and stock/payroll/money correctness

| ID | Current bug | Required fix | Source; develop reference |
| --- | --- | --- | --- |
| **API02** | Task references/states bypass validation and scope. | Validate task states/dates/references; enforce target permission/factory scope and lock referenced rows. | `B:schemas/tasks.py:8`; `22593e7`, `31350dc`, `73d7ca4` |
| **API05** | Forecast/report routes read and mutate across factories. | Apply effective per-factory view/manage grants and model attribution to forecasts/reports. | `B:api/routes/forecasting.py:47`; `064be49`, `fc450a5`, `0e9bb6ba`, `feb7415f`, `49d3c200`, `4a5c0b2b` |
| **API06** | Editable name/email grants purchasing-price access. | Remove name/email privilege fallbacks from backend and frontend; require explicit permission. | `B:services/price_calculation.py:29`; `B:core/deps.py:164`; `F:lib/priceCalculationRequests.ts:60`; `d89059eb` |
| **DB01-ADJUSTMENT** | Forced stock corrections leave reservations underbacked. | Enforce reservation floors on both item and batch correction, including force=true. | `B:api/routes/inventory.py:685`; `69ceef4e` |
| **DB01-CONSUMPTION** | Stock consumption accepts incompatible catalog/request/batch units. | Validate catalog/request/all-batch units before consuming any stock. | `B:services/workflow.py:400`; `B:services/workflow.py:442`; `5b4ac7c0` |
| **DB02-WO-STATUS** | Generic work-order PATCH bypasses explicit status transitions. | Reject changed status in generic PATCH; retain metadata no-ops and explicit transition commands. | `B:api/routes/production.py:1607`; `9bdf79c4` |
| **FN04** | Concurrent invoice routes can bill one order twice. | Lock/refetch the SalesOrder before invoice existence checks in both finance and sales routes. | `B:api/routes/finance.py:65`; `B:api/routes/sales.py:1985`; `3881177e`, `6843712f` |
| **FN06** | Generic retry keys replay across callers and race writes. | Scope replay to caller/key/payload and serialize same-key writes across every generic replay site. | `B:services/idempotency.py:31`; `c21e50bb` |
| **FN07-ADJUSTMENT** | Payroll adjustment amount/type/reason validation is incomplete. | Validate finite cent-accurate amounts, supported adjustment types and stored reason length. | `B:schemas/payroll.py:456`; `B:api/routes/payroll.py`; `60f82357`, `4ae84350` |
| **FN07-INVOICE** | Invoice/payment money inputs can exceed precision/storage bounds. | Use storage-bounded Decimal amounts; reject nonfinite, overflowing and sub-cent inputs before writes. | `B:schemas/sales.py:162`; `B:api/routes/finance.py:74`; `5a68d122`, `6304934b` |
| **FN07-PURCHASE-QUANTITY** | Purchase/receipt quantity fields lack finite/storage bounds. | Restore finite/storage quantity bounds after ST01; retain approved unit-cost rounding. | `B:schemas/purchasing.py:77`; `3e75ca62` |
| **FN07-RECORD** | Freeform payroll records lack finite/storage money bounds. | Validate representable payroll record amounts before and after trusted enrichment. | `B:api/routes/payroll.py:121`; `50cbbe84`, `764af788` |
| **PY01** | Fast badge/work scans credit the previous employee. | Queue badge/work/manual selection in arrival order; do not credit work before badge resolution. | `F:app/(app)/payroll/scan/page.tsx:948`; `3881177e` |
| **PY02** | Payroll writes race period finalization. | Use shared refreshed period locks for all record writers and finalizers. | `B:api/routes/payroll.py:517`; `b285877b` |
| **PY03** | Scanner permission can issue caller-priced payable labels. | Require manage permission for payable label issuance/values; scanners use trusted issued labels. | `B:api/routes/payroll.py:2091`; `900641e7` |
| **PY04** | Unmatched work dates attach to the latest open period. | Use only the matching date period or no period; remove latest-open fallback in single/bulk paths. | `B:api/routes/payroll.py:540`; `adc79f77` |
| **PY05** | QR returns use a conflicting payroll lock order. | Use period -> label -> record lock order with fresh assignment checks for return/scan/finalization. | `B:api/routes/payroll.py:2907`; `a2082235` |
| **SEC04** | Disabled or revoked sessions still download model files. | Validate active user and token cutoff for model files; release the auth connection before streaming. | `B:main.py:378`; `3881177e` |
| **SEC05** | Sibling reset links survive a password change. | Lock the account and invalidate sibling reset links on every supported password rotation. | `B:api/routes/auth.py:286`; `3881177e`, `f35a62e6` |
| **SEC06** | Concurrent admin removals can remove the final admin. | Serialize PATCH/DELETE membership changes with audit-compatible NO KEY UPDATE locks. | `B:api/routes/admin.py:600`; `74a2973` |
| **SEC07-ASSIGNMENT** | Assignment deletion bypasses factory and used-output guards. | Check flow/work-order factory and used/output history under locks before deletion. | `B:api/routes/production_extra.py:392`; `3881177e`, `df14ad66` |
| **SEC07-FLOW** | Flow utilization exposes another factory. | Apply sewing-flow access checks to the direct utilization endpoint. | `B:api/routes/production_extra.py:483`; `40c681e` |
| **SEC08** | Raw admin console bypasses business and audit safeguards. | Block generic raw UPDATE/DELETE; allow only named audited repairs and soft-deactivation. | `B:api/routes/super_data.py`; `e7782ec`, `297d808`, `df1d08f` |
| **SEC09-PROXY** | Forwarded client/scheme headers lack explicit proxy trust. | Validate trusted CIDRs and ordered forwarded headers; ignore untrusted client/scheme claims. | `B:api/routes/auth.py`; `B:main.py`; `b926fba`, `f35a62e6`, `0ad74a69`, `4fee48be` |
| **SEC10** | Limited admin can delete a non-wildcard Super Admin. | Protect admin.super targets even when their permission list lacks wildcard. | `B:api/routes/admin.py:600`; `3881177e` |
| **ST01** | Purchase receipt retries add stock twice. | Add caller/order/payload-scoped receipt identity, replay and locking so retries create one receipt. | `B:api/routes/purchasing.py:168`; `3881177e`, `641c0580` |
| **ST02** | Stock movement does not update or validate its batch. | Mutate batch and ledger atomically; validate item/unit/warehouse, claims and Eco custody. | `B:api/routes/inventory.py:1293`; `3881177e` |
| **ST03** | Batchless movements leak into other warehouse balances. | Scope batchless movement aggregation by warehouse and transfer direction without double counting. | `B:services/inventory.py:80`; `3881177e` |
| **ST06** | Concurrent accessory returns share an unlocked allowance. | Lock the shared issue allowance before validating accessory returns and storing replay. | `B:api/routes/inventory.py:865`; `712ccf1` |
| **ST09** | Damaged packages remain reservable and damage races claims. | Recheck damage status under shared package/stock locks; block damage of reserved/linked packages. | `B:api/routes/finished_goods.py:184`; `B:services/packages.py:1203`; `9e336ce`, `f40f4e4` |
| **ST11** | Item-only and mixed reservations can overclaim stock. | Lock common item capacity for item-only and mixed batched reservations; preserve lock order. | `B:services/inventory.py:475`; `3881177e` |
| **UI03-PACKAGE** | Corrected package receipts remain blocked by pending retry state. | Restore durable cross-tab retry state and server reconciliation/tombstones, including changed-body/429 cases. | `F:lib/packageWorkflow.ts:58`; `B:api/routes/package_workflows.py:77`; `3ef1c83e`, `00567734`, `e2a6d8cb`, `3532e8e4` |
| **WF01** | Generic production PATCH changes internal fields/status. | Replace raw setattr PATCH with typed field/reference allowlist and legal workflow-status guards. | `B:api/routes/production.py:1003`; `859b7ca`, `d11fb7aa` |
| **WF02** | Generic work-order commands miss stage/factory boundaries. | Enforce stage authorization and factory scope on update/start/complete/block/unblock commands. | `B:api/routes/production.py:1601`; `84c322a`, `62a3544`, `d8cd060` |
| **WF03** | Ordinary packages can be created without production evidence. | Require packaging evidence for ordinary standard packages; preserve valid first-grade/batch receipts. | `B:services/packages.py:220`; `37258c7` |

## P2 — validation, reliability and performance

| ID | Current bug | Required fix | Source; develop reference |
| --- | --- | --- | --- |
| **DB02-HR-STATUS** | Employee status writes accept unsupported vocabulary. | Validate newly supplied employee statuses while preserving historical read compatibility. | `B:api/routes/hr.py:21`; `bf364411` |
| **DB03-HR-PROFILE** | Employee profile JSON lacks bounded shape/depth validation. | Validate profile shape/hours and 16 KiB/16-level limits; preserve unchanged legacy values. | `B:api/routes/hr.py:26`; `ada93f89`, `708475d2` |
| **DB03-IMPORT-CORRECT** | Old-ERP correction script bypasses model JSON bounds. | After DB03-MODEL, restore b097037e validator guard before correction-script JSON writes. | `backend/scripts/correct_old_erp_models_local.py:2111`; `b097037e` |
| **DB03-IMPORT-OLD** | Old-ERP import script bypasses model JSON bounds. | After DB03-MODEL, restore 6a902d7a guard before old-ERP import JSON writes. | `backend/scripts/import_old_erp_models_local.py:2412`; `6a902d7a` |
| **DB03-IMPORT-REVIEWED** | Reviewed model import bypasses shared JSON bounds. | After DB03-MODEL, restore 3544b1f4 guard on merged/final reviewed-import details. | `backend/scripts/migrate_reviewed_old_erp_models_production.py:1773`; `3544b1f4` |
| **DB03-MODEL** | Model details JSON lacks size/depth/established-shape validation. | Restore common size/depth/shape validator across catalog writers, clones/variants and family saves. | `B:schemas/catalog.py:221`; `B:api/routes/catalog.py`; `fa3ba201` |
| **DB03-PAYROLL-SNAPSHOT** | Payroll employee/work snapshots are unbounded JSON. | Validate 16 KiB/16-level employee/work snapshots before and after trusted enrichment. | `B:api/routes/payroll.py`; `4f4efcb8` |
| **DB07** | Order/bundle numbering exhausts its four-digit namespace. | Expand monotonic numbering beyond 9999 without recycling issued identities; preserve locks/aliases. | `B:services/numbering.py:79`; `b350c4f`, `11aabc1` |
| **DB08** | ORM metadata disagrees with the existing migrated schema. | Align legacy model-less sales/Beyka ORM with existing clone migrations; test real migrated PostgreSQL. | `B:models/sales.py:51`; `1141d40` |
| **FN07-HR-SALARY** | Employee salary values lack storage validation. | Reject nonfinite, negative and column-overflow employee salaries before create/update. | `B:api/routes/hr.py:21`; `15833133`, `dd03309c` |
| **OPS05** | Readiness ignores a failed required shared store. | Probe PostgreSQL and required shared store under one bounded, single-flight readiness deadline. | `B:main.py:499`; `c275be7` |
| **OPS06** | Recovery tooling cannot verify paired database/upload backups. | Add paired DB/upload manifest verification for dump identity and missing/changed/extra files. | `scripts/storage_recovery_manifest.py (missing)`; `13f5994` |
| **OPS08** | Runtime/dependency hardening from develop is absent. | Review PyJWT/runtime migration; verify legacy tokens and run fresh dependency/built-image scans. | `B:core/security.py`; `frontend/Dockerfile`; `.github/workflows/ci.yml`; `06705b9`, `1896408`, `f288ada`, `f0a1536` |
| **OPS09-WEB** | Production scripts lack nonce CSP and reliable HTTPS headers. | Restore nonce CSP/layout and trusted HTTPS/HSTS handling; keep 1C retired. | `frontend/next.config.js:32`; `aa8fac1`, `f35a62e6`, `0ad74a69`, `4fee48be` |
| **PERF06** | Bulk payroll is unbounded and misses batched validation. | Cap bulk payroll at 500; batch reference/duplicate validation and audit-head work. | `B:schemas/payroll.py:84`; `f42637c3`, `8240fc9`, `67f0309`, `c625aad` |
| **PERF22-USLUGA** | Usluga directory fetches every order. | Use bounded order pages/load more; preserve legacy array compatibility pending owner policy. | `F:app/(app)/usluga/page.tsx:83`; `c8ac9f35` |
| **PERF35-FINANCE** | Finance invoice list silently stops at fifty. | Page/search invoices with exact totals so rows beyond fifty remain reachable. | `F:app/(app)/finance/page.tsx:65`; `88cedd2c` |
| **PERF35-FINISHED-GOODS** | Finished-goods page loads unpaged stock/inbox graphs. | Page stock/branded/inbox data with exact totals and existing reservation/return behavior. | `F:app/(app)/finished-goods/page.tsx:24`; `7b45c231`, `1a030623`, `deef9c6d`, `59fea8bc` |
| **PERF35-HR** | HR employee directory loads all employees/positions. | Use scoped 50-row employee search, exact metrics and lazy retained option pickers. | `F:app/(app)/hr/employees/page.tsx:59`; `9c53b633`, `36b8d225` |
| **PERF35-INBOX** | Department inbox fetches a broad order graph. | Restore canonical identity pages and page-only hydration, including replacement/batch queues. | `F:app/(app)/departments/[code]/page.tsx:101`; `6c412e44`, `3e6c5d43`, `bfb51a95`, `051a5a22`, `dc24cdfd` |
| **PERF35-PAYROLL** | Payroll lists truncate records and load broad summaries/options. | Page records/summary/adjustments and employee options; remove the silent 300-record cutoff. | `F:app/(app)/payroll/page.tsx:218`; `2174ade0`, `b915b530`, `36b8d225` |
| **PERF35-PRODUCTION** | Production directory uses an unpaged array. | Use bounded server search/pages with load more and retained selected/deep-linked orders. | `F:app/(app)/production-orders/page.tsx:31`; `45f24e8b`, `07b5b8fb` |
| **PERF35-PURCHASING** | Receiving queue fetches broad order/supplier directories. | Page receiving orders by supplier and use bounded supplier options without losing receipt state. | `F:app/(app)/purchasing/receiving/page.tsx:117`; `59a86c5d`, `b3239284`, `b2e39065` |
| **PERF37** | Rate-store I/O blocks the async request loop. | Move synchronous rate-store work to bounded worker capacity; test event-loop responsiveness. | `B:main.py:230`; `25fd549` |
| **PERF38** | Office users share one global per-IP budget. | Use authenticated identity buckets; retain IP-only login/reset limits and safe credential fallback. | `B:main.py:154`; `a8b1707` |
| **PERF39-MODEL** | Hidden model tabs still fetch BOM/seasons/all employees. | Fetch BOM/seasons only for visible tab/editor and use bounded employee options. | `F:app/(app)/models/[id]/page.tsx:209`; `be696e12`, `4c751606`, `2e60854f` |
| **PERF39-PACKAGES** | Collapsed package change requests fetch eagerly. | Fetch pending changes only when the section is expanded; refresh after actions. | `F:app/(app)/packages/page.tsx:49`; `1da4f66a` |
| **PERF39-PRODUCTION** | Production details have waterfalls and closed-editor fetches. | Restore paired page-context API/UI; gate utilization/users and page sales options only when needed. | `F:app/(app)/production-orders/[id]/page.tsx:212`; `7445ad49`, `534c8bf2`, `b669bd44` |
| **SEC09-RESET-PROXY** | Frontend reset proxies accept unbounded bodies and stalled responses. | Bound incoming JSON and upstream full-response deadlines in forgot/reset proxies. | `F:app/api/auth/forgot-password/route.ts`; `F:app/api/auth/reset-password/route.ts`; `b926fba`, `f35a62e6` |
| **UI01** | Temporary API/network failures log users out. | Preserve sessions on network/503 failures; logout only for definitive invalid/revoked authentication. | `F:lib/auth.ts:37`; `F:components/AuthGate.tsx:174`; `3881177e` |
| **UI02** | Request deadlines end before response bodies finish. | Keep deadline/cancellation active through response-body consumption for JSON/form/label reads. | `F:lib/api.ts:20`; `3881177e` |
| **UI03-PURCHASE** | Purchase receipts have no durable retry/recovery UI. | After ST01, restore durable receipt key/payload recovery across reloads and ambiguous/rejected responses. | `F:app/(app)/purchasing/receiving/page.tsx:230`; `3881177e`, `641c0580`, `3532e8e4` |
| **UI05** | Home Production KPI double-counts stage activity. | Label summed stage quantities as stage activity, with explanation in EN/RU/UZ. | `F:app/(app)/page.tsx:291`; `a0818c41` |

## Fix constraints and completion

- Preserve approved USD <= $1.00 settlement display, four-decimal HALF_UP unit costs and received-payment revenue; retain factory isolation, work dates/split allocation, first-grade and package-return/shipment workflows.
- Port donor helpers and narrow hunks with their dependencies. Clone migration head is `0134_packaging_returns`; adapt additive migrations to it. Failed pieces must not create replacement work.
- Reuse/adapt donor regressions. Verify rejection/success, permission/factory boundaries, retry/rollback and side effects; use isolated migrated PostgreSQL for races/schema checks. For paging/performance, verify exact totals and bounded query/hydration/memory growth. Record fix commit and actual pass/fail/skip results in the PR.
- Owner decisions still needed: historical unit/data repair, cost/currency policy, legacy unpaged Usluga contract and data/permission migration approvals. Recovery targets are RTO 24h/RPO zero/seven-day retention; restore proof and credential rotation remain operational work.
- Keep 1C retired, historical waste repair outside scope and authorized dashboard presentation mode unchanged. Historical audit-chain break #744 requires separate evidence-backed investigation. Already-present fixes and history-only candidates are excluded from this list.

Reference: [develop implementation/tests](https://github.com/Shmirzaev/Milana-ERP/tree/2f549f9b202ef1a66ed6ffe17be07b5497ccdeab) and [owner decisions](REMAINING_DEVELOP_BUGS.md).
