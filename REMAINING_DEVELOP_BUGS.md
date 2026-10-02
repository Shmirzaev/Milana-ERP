# Remaining `develop` fixes and owner decisions

**Snapshot (2026-10-01):** `clone_main` `6fc9f729`, `main` `77046b16`, `develop` `2f549f9b`. This is a triage of *fix-labeled commits*, not a claim of 338 independent bugs or that every change applies unchanged to `clone_main`. The [complete branch comparison](https://github.com/Shmirzaev/Milana-ERP/compare/clone_main...develop) also includes non-fix work.

## Fixes still outside `clone_main`

Of 435 fix-labeled `develop` commits reviewed against the earlier `main` base, 101 were cherry-picked and four were subsequently reverted because prerequisite behavior was absent; **97 remain active and 338 are not active**. Of those 338, 334 were never picked (321 had text conflicts in that earlier isolated check; 13 merged textually but were not validated for inclusion). The other four are the reverted import/purchasing fixes. These are historical triage results; conflicts and correctness must be checked again against the current branches.

| Area | Commits | Unmerged bug-fix themes |
| --- | ---: | --- |
| Stock, inventory, receiving | 58 | Reservation/claim loss, concurrent adjustments, batch and item unit mismatches, scoped warehouse stock, consistent stocktake snapshots. Examples: `69ceef4e`, `f6a9548e`, `5b4ac7c0`. |
| Finance, sales, forecasting, shipments | 56 | Cent-accurate payment state, cost/price precision, currency provenance, invoice races, sales bounds and paged commercial views. Examples: `13d37a00`, `00c07757`, `6843712f`. |
| Catalog, purchasing, legacy imports | 47 | BOM/model JSON validation, purchase/receipt quantity and cost bounds, legacy import payloads. **Four attempted fixes were reverted:** `b097037e`, `6a902d7a`, `3544b1f4` need the model-details validation chain; `3e75ca62` needs the receipt idempotency chain. Examples: `fa3ba201`, `fd36ac07`. |
| Production, cutting, sewing, packaging | 52 | Work-order state/permission guards, material and bundle validation, sewing progress, package receipt evidence and reservations, Finished Goods bounds. Examples: `d11fb7aa`, `df14ad66`, `3ef1c83e`. |
| Waste | 13 | Sale balance, retry/idempotency, decimal quantity, item/batch matching, history and list paging. Examples: `8aebf877`, `01e0ee18`. |
| Payroll, HR, attendance | 29 | Amount/JSON bounds, payroll write races, HR field validation, stale device snapshots and failed-event handling. Examples: `4ae84350`, `15833133`, `135d669d`. |
| Security, authorization, administration | 17 | Credential/proxy/JWT hardening, factory and pricing permissions, raw data-console mutations, membership races. Examples: `f35a62e6`, `e7782ec2`. |
| Data, API, frontend and operations | 44 | JSON/schema checks, migration safety, upload cleanup/limits, dependency patches, readiness, pagination and inbox loading. Examples: `6216855c`, `06705b9d`, `9bdb9e77`. |
| Cross-cutting or unscoped | 22 | Mixed stock/finance/waste validation, rounding and paging across multiple features. Examples: `49495bf4`, `ab9c7ff7`. |
| **Total** | **338** | Commit counts overlap conceptually; they are not a severity ranking. |

The first sequential cherry-pick conflict was `13400e81` (stock-adjustment bounds). A prior whole-branch merge also conflicted in 25 files; neither result proves that an individual fix is impossible to port. Port by bug with its dependencies, then test affected workflows and PostgreSQL races/migrations where relevant.

## Original decision requests (2026-10-01)

The [audit ledger at `develop`](https://github.com/Shmirzaev/Milana-ERP/blob/2f549f9b202ef1a66ed6ffe17be07b5497ccdeab/docs/audit_backlog.json) records **106 fixed, 15 partial and 6 open** findings (21 incomplete). Its status is for `develop`, **not** `clone_main`. These questions need a business, data, security or operations owner; coding alone cannot settle them.

| Finding | Decision to record |
| --- | --- |
| **WF08 — waste sales** | Which historical duplicate sales should be repaired, and should old sale value use recorded cost or a recalculated cost? Approve the source records and backfill rule. |
| **FN07 — money precision/state** | Should a manual payment leave an exact $0.01 balance open while 1C calls it partially paid? Should five-decimal purchase/stock costs be rejected or rounded before storage in four-decimal fields? |
| **FN08 — reporting** | Define revenue date/cancellation rules, historical versus current cost for profit, and currency conversion/source for combined totals. |
| **PERF35 / legacy PERF22 contract** | Which large screens may load details lazily or enforce paging? Decide whether the legacy unpaged Usluga array remains a supported API contract. |
| **DB01 / DB05 — legacy data and migrations** | Define treatment of historical unit mismatches (correct data or authorized conversion); approve affected rows, permission changes, recovery and rollback before data-changing migrations. |
| **OPS03 / OPS04 — capacity and availability** | Assign owners/limits/schedules to shared workloads and decide whether recovery on the same physical host meets the required availability target or independent failover is needed. |
| **OPS06 / OPS10 — recovery** | Set RTO, RPO and retention; choose coordinated database-plus-upload backup/restore and witness a restore drill. |
| **OPS09 — 1C integration** | Decide whether external 1C IDs are globally unique or client-scoped; approve caller credential/proxy configuration and rollout. |
| **OPS11 — secrets** | Assign vault ownership and approve rotation/revocation of credentials that appeared in handover documents. |

The other incomplete ledger entries—**PERF40, DB02, DB03, DB06, OPS01, OPS02, OPS05, OPS07, OPS08**—primarily need implementation, measurement or environment verification; DB06 index changes also need migration approval. See the [QA/evidence notes](https://github.com/Shmirzaev/Milana-ERP/blob/2f549f9b202ef1a66ed6ffe17be07b5497ccdeab/docs/stabilization_qa.md) for the exact partial-work boundaries. The original report did not merge further fixes.

## Owner answers and implementation (2026-10-02)

The supplied owner responses supersede the original questions only where explicitly answered. A dash means **pending**. New fixes were implemented against pulled `clone_main` `80becbd1`, reviewed and committed individually; the historical commit counts and `develop` audit ledger above have not been reassessed. No historical data deletion was approved.

| Finding | Approved answer / current result | Still needed |
| --- | --- | --- |
| **FN07 — settlement** | Outstanding USD balance **<= $1.00**, inclusive, is displayed as settled. Implemented `6c5bf63c`: exact Decimal allocation, shared status rule and server-refreshed customer display. Actual debt/receipts remain unchanged; remaining cents can still be paid. | Production rollout. |
| **FN07 — cost precision** | Round purchase/stock unit costs to **four decimals before storage**. Implemented `40baf767`: HALF_UP rounding, finite/nonnegative/range guards, preserved retry fingerprints and purchase fallback behavior. | Production rollout; historical cost rewriting was not approved. |
| **FN08 — cash revenue/debt** | Shipped unpaid sales remain customer debt; revenue comes from received payments. Implemented `ece87130`: receipts applied to active sales, capped by invoice value before period filtering, UTC dates and localized labels. Advances/excess and reversed sales are excluded from sale revenue. | Historical/current cost and currency conversion/source policy; production rollout. |
| **OPS09 — 1C** | Unused integration removed from active scope. Implemented `561a0393`: sync endpoint/config/modules removed, endpoint returns 404. Historical imported records/origin identifiers, manual payments and generic idempotency remain. | Production rollout; remove obsolete environment entries during authorized configuration update. |
| **WF08 — waste history** | Historical duplicate/value repair and backfill are **outside current scope** because the section is inactive and records unreliable. | Preserve history; reassess only if scope changes. |
| **PERF35 / legacy PERF22** | No answer provided. | Lazy loading/paging and legacy unpaged Usluga contract decision. |
| **DB01 / DB05** | No answer provided. | Historical unit treatment, affected rows and migration/recovery approval. |
| **OPS03 / OPS04** | Continue on the company's existing server for now. | Workload owners, limits, schedules and verified availability/failure model. |
| **OPS06 / OPS10** | **RTO 24 hours, RPO zero, retention seven days** recorded in `docs/DISASTER_RECOVERY.md`. | Coordinated database/files protection, capacity/owners and isolated restore drill; periodic dumps alone cannot prove zero RPO. |
| **OPS11 — secrets** | Replacement and old-credential revocation approved; procedure updated in `docs/SECURITY_RUNBOOK.md`. | Vault/rotation owner and private affected-account inventory, then live rotation/revocation and evidence. No credentials changed by this task. |

**Delivery boundary:** these are source changes on `clone_main`; no production deployment, configuration change or historical backfill occurred. Live VM verification was unavailable (SSH timeout); the recorded baseline was retained. Operational approvals are requirements, not verified live capabilities.

**Verification:** combined affected-workflow gate **318 passed, two optional PostgreSQL tests skipped**; separate disposable PostgreSQL 17.11 allocation/date/precision checks passed. Scoped Ruff, compilation, strict TypeScript and changed-file lint passed. Global i18n still reports the same 22 missing-key references as the starting commit; the complete backend suite was not completed.

**Transfer coverage (2026-10-02):** 97/435 reviewed source fix commits have retained selective-transfer history (**22.3%**). Mapping the 127 `develop` ledger rows gives 26 with all cited fix commits traced, 12 with some, 83 with none, and six with no recorded source fix. These are Git-history results, not proof that 83 bugs remain in `clone_main`; independent `main` implementations and the four new owner-approved fixes need separate behavior assessment. See [the exact 127-row comparison](DEVELOP_TO_CLONE_MAIN_COVERAGE.md). The approved FN07 settlement/cost subrules are fixed; this does not close every broader FN07 bounds/precision issue.
