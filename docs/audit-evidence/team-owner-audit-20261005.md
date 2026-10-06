# Ismail bug and team delivery audit

Audited on 2026-10-05 against GitHub `clone_main` at `f61262dd56b1c81eedbff6c8aa57969bdd5cec0b` and Ismail proposal PR 279. Every original Ismail implementation row was checked for commit ancestry, current source and available regression evidence. The audit reproduced one overlooked ST02 reservation-floor gap and includes its fix in the proposal. A green suite is evidence for covered cases, not proof that every possible bug is absent.

## Ismail result

The 37 original tasks now divide into **31 landed fixes and six proposal fixes**: ST02, ST11, DB05, DB06, DB08 and PERF23. The additional QC/archive finding is also in PR 279. ST02 had previously been marked Done; it is returned to Review because its broader floor correction has not merged. No original implementation row is Open, Partial or Blocked on the corrected proposal tracker. Production deployment is separate.

The audit reproduction on source `34bc462f` reported **two failures and two passing controls**: with either a warehouse-scoped or global item-only reservation for all 10 units, issuing one unit from the batch returned HTTP 201 and left only nine units backing the ten-unit claim. Batch-pinned reservations and unreserved stock behaved correctly. The extension uses common batch-before-item locks and the shared global/warehouse capacity check for batch and batchless outgoing movements. Tests cover issue/consume/transfer, atomic rejection, exact free quantity, fractional arithmetic, warehouse independence and six two-connection PostgreSQL claim/movement combinations. This is recorded under ST02, not hidden as an unrelated new task.

The previous exact-source full CI on `34bc462f` passed 2,756 backend tests (222 optional skips), 121 dedicated PostgreSQL tests, frontend checks and migration/concurrency gates. The new local stock/adjustment/planner run passed 116 tests with PostgreSQL enabled; the final movement suite passed 50 tests with PostgreSQL enabled after adding fractional controls. These runs overlap and are not a unique-test sum. New-source full CI is available through [PR 279](https://github.com/Shmirzaev/Milana-ERP/pull/279). Historical results must not be mistaken for validation of the new extension. Database-dependent movement tests are now part of the mandatory PostgreSQL CI gate.

## Every original Ismail task

Landed means the referenced fix commit is an ancestor of the current GitHub target. Proposal means implemented in PR 279 and awaiting merge. Regression links identify the relevant checked-in coverage; test-function counts are not added together, and optional PostgreSQL skips in the general suite are not called passes.

| Task | Delivery | Regression evidence |
| --- | --- | --- |
| API06 | [Landed e808891a](https://github.com/Shmirzaev/Milana-ERP/commit/e808891a) | [test_name_authorization.py](https://github.com/Shmirzaev/Milana-ERP/blob/codex/ismail-review-fixes/backend/app/tests/test_name_authorization.py); [test_price_calculation_workflow.py](https://github.com/Shmirzaev/Milana-ERP/blob/codex/ismail-review-fixes/backend/app/tests/test_price_calculation_workflow.py) |
| DB01-ADJUSTMENT | [Landed 56dded34](https://github.com/Shmirzaev/Milana-ERP/commit/56dded34) | [test_inventory_stock_adjustment_bounds.py](https://github.com/Shmirzaev/Milana-ERP/blob/codex/ismail-review-fixes/backend/app/tests/test_inventory_stock_adjustment_bounds.py) |
| FN04 | [Landed 8e42807e](https://github.com/Shmirzaev/Milana-ERP/commit/8e42807e) | [test_invoice_creation_integrity.py](https://github.com/Shmirzaev/Milana-ERP/blob/codex/ismail-review-fixes/backend/app/tests/test_invoice_creation_integrity.py) |
| FN07-INVOICE | [Landed 3b07db93](https://github.com/Shmirzaev/Milana-ERP/commit/3b07db93) | [test_finance_money_bounds.py](https://github.com/Shmirzaev/Milana-ERP/blob/codex/ismail-review-fixes/backend/app/tests/test_finance_money_bounds.py) |
| FN07-PURCHASE-QUANTITY | [Landed f539b4e2](https://github.com/Shmirzaev/Milana-ERP/commit/f539b4e2) | [test_purchase_quantity_bounds.py](https://github.com/Shmirzaev/Milana-ERP/blob/codex/ismail-review-fixes/backend/app/tests/test_purchase_quantity_bounds.py) |
| ST01 | [Landed 6fb88ee3](https://github.com/Shmirzaev/Milana-ERP/commit/6fb88ee3) | [test_purchase_receipt_idempotency.py](https://github.com/Shmirzaev/Milana-ERP/blob/codex/ismail-review-fixes/backend/app/tests/test_purchase_receipt_idempotency.py) |
| ST02 | [PR 279](https://github.com/Shmirzaev/Milana-ERP/pull/279) | [test_stock_movement_batch_integrity.py](https://github.com/Shmirzaev/Milana-ERP/blob/codex/ismail-review-fixes/backend/app/tests/test_stock_movement_batch_integrity.py) |
| ST03 | [Landed 19c42c74](https://github.com/Shmirzaev/Milana-ERP/commit/19c42c74) | [test_batchless_movement_warehouse_scope.py](https://github.com/Shmirzaev/Milana-ERP/blob/codex/ismail-review-fixes/backend/app/tests/test_batchless_movement_warehouse_scope.py) |
| ST06 | [Landed ef9d2e48](https://github.com/Shmirzaev/Milana-ERP/commit/ef9d2e48) | [test_accessory_return_allowance_lock.py](https://github.com/Shmirzaev/Milana-ERP/blob/codex/ismail-review-fixes/backend/app/tests/test_accessory_return_allowance_lock.py) |
| ST11 | [PR 279](https://github.com/Shmirzaev/Milana-ERP/pull/279) | [test_reservation_overclaim.py](https://github.com/Shmirzaev/Milana-ERP/blob/codex/ismail-review-fixes/backend/app/tests/test_reservation_overclaim.py) |
| WF08 | [Landed 96169417](https://github.com/Shmirzaev/Milana-ERP/commit/96169417) | [test_waste_sale_integrity.py](https://github.com/Shmirzaev/Milana-ERP/blob/codex/ismail-review-fixes/backend/app/tests/test_waste_sale_integrity.py) |
| DB03-IMPORT-CORRECT | [Landed 53bedb59](https://github.com/Shmirzaev/Milana-ERP/commit/53bedb59) | [test_correct_old_erp_models_details_bounds.py](https://github.com/Shmirzaev/Milana-ERP/blob/codex/ismail-review-fixes/backend/app/tests/test_correct_old_erp_models_details_bounds.py) |
| DB03-IMPORT-OLD | [Landed 8fcde82e](https://github.com/Shmirzaev/Milana-ERP/commit/8fcde82e) | [test_import_old_erp_models_details_bounds.py](https://github.com/Shmirzaev/Milana-ERP/blob/codex/ismail-review-fixes/backend/app/tests/test_import_old_erp_models_details_bounds.py) |
| DB03-IMPORT-REVIEWED | [Landed 1ff9b61a](https://github.com/Shmirzaev/Milana-ERP/commit/1ff9b61a) | [test_migrate_reviewed_models_details_bounds.py](https://github.com/Shmirzaev/Milana-ERP/blob/codex/ismail-review-fixes/backend/app/tests/test_migrate_reviewed_models_details_bounds.py) |
| DB03-MODEL | [Landed 71383580](https://github.com/Shmirzaev/Milana-ERP/commit/71383580) | [test_model_details_paid_operations_validation.py](https://github.com/Shmirzaev/Milana-ERP/blob/codex/ismail-review-fixes/backend/app/tests/test_model_details_paid_operations_validation.py) |
| DB05 | [PR 279](https://github.com/Shmirzaev/Milana-ERP/pull/279) | [test_migration_preflight.py](https://github.com/Shmirzaev/Milana-ERP/blob/codex/ismail-review-fixes/backend/app/tests/test_migration_preflight.py) |
| DB06 | [PR 279](https://github.com/Shmirzaev/Milana-ERP/pull/279) | [test_ismail_schema_completion.py](https://github.com/Shmirzaev/Milana-ERP/blob/codex/ismail-review-fixes/backend/app/tests/test_ismail_schema_completion.py) |
| DB08 | [PR 279](https://github.com/Shmirzaev/Milana-ERP/pull/279) | [test_fresh_migration_bootstrap.py](https://github.com/Shmirzaev/Milana-ERP/blob/codex/ismail-review-fixes/backend/app/tests/test_fresh_migration_bootstrap.py); [test_db08_beyka_orm_parity.py](https://github.com/Shmirzaev/Milana-ERP/blob/codex/ismail-review-fixes/backend/app/tests/test_db08_beyka_orm_parity.py) |
| PERF02 | [Landed dbadfad7](https://github.com/Shmirzaev/Milana-ERP/commit/dbadfad7) | [test_accessory_request_postgres.py](https://github.com/Shmirzaev/Milana-ERP/blob/codex/ismail-review-fixes/backend/app/tests/test_accessory_request_postgres.py) |
| PERF03 | [Landed 95de2c02](https://github.com/Shmirzaev/Milana-ERP/commit/95de2c02) | [test_reservation_plan_query_growth.py](https://github.com/Shmirzaev/Milana-ERP/blob/codex/ismail-review-fixes/backend/app/tests/test_reservation_plan_query_growth.py) |
| PERF15 | [Landed 155792a4](https://github.com/Shmirzaev/Milana-ERP/commit/155792a4) | [test_planning_query_growth.py](https://github.com/Shmirzaev/Milana-ERP/blob/codex/ismail-review-fixes/backend/app/tests/test_planning_query_growth.py) |
| PERF22-USLUGA | [Landed ccea9583](https://github.com/Shmirzaev/Milana-ERP/commit/ccea9583) | [test_perf22_usluga_orders_pagination.py](https://github.com/Shmirzaev/Milana-ERP/blob/codex/ismail-review-fixes/backend/app/tests/test_perf22_usluga_orders_pagination.py) |
| PERF23 | [PR 279](https://github.com/Shmirzaev/Milana-ERP/pull/279) | [test-pricing-browser.mjs](https://github.com/Shmirzaev/Milana-ERP/blob/codex/ismail-review-fixes/frontend/scripts/test-pricing-browser.mjs) |
| PERF24 | [Landed 7b95f36a](https://github.com/Shmirzaev/Milana-ERP/commit/7b95f36a) | [test_sales_branded_variant_queries.py](https://github.com/Shmirzaev/Milana-ERP/blob/codex/ismail-review-fixes/backend/app/tests/test_sales_branded_variant_queries.py); [test_sales_list_query_growth.py](https://github.com/Shmirzaev/Milana-ERP/blob/codex/ismail-review-fixes/backend/app/tests/test_sales_list_query_growth.py) |
| PERF25 | [Landed a162742a](https://github.com/Shmirzaev/Milana-ERP/commit/a162742a) | [test_sales_history_candidate_loading.py](https://github.com/Shmirzaev/Milana-ERP/blob/codex/ismail-review-fixes/backend/app/tests/test_sales_history_candidate_loading.py) |
| PERF26 | [Landed 7b95f36a](https://github.com/Shmirzaev/Milana-ERP/commit/7b95f36a) | [test_sales_branded_variant_queries.py](https://github.com/Shmirzaev/Milana-ERP/blob/codex/ismail-review-fixes/backend/app/tests/test_sales_branded_variant_queries.py); [test_sales_list_query_growth.py](https://github.com/Shmirzaev/Milana-ERP/blob/codex/ismail-review-fixes/backend/app/tests/test_sales_list_query_growth.py) |
| PERF28 | [Landed 5078f99a](https://github.com/Shmirzaev/Milana-ERP/commit/5078f99a) | [test_purchasing_reference_query_growth.py](https://github.com/Shmirzaev/Milana-ERP/blob/codex/ismail-review-fixes/backend/app/tests/test_purchasing_reference_query_growth.py) |
| PERF29 | [Landed f9a7f536](https://github.com/Shmirzaev/Milana-ERP/commit/f9a7f536) | [test_customer_payment_query_growth.py](https://github.com/Shmirzaev/Milana-ERP/blob/codex/ismail-review-fixes/backend/app/tests/test_customer_payment_query_growth.py) |
| PERF30 | [Landed e2d8645f](https://github.com/Shmirzaev/Milana-ERP/commit/e2d8645f) | [test_catalog_family_operations_query_growth.py](https://github.com/Shmirzaev/Milana-ERP/blob/codex/ismail-review-fixes/backend/app/tests/test_catalog_family_operations_query_growth.py) |
| PERF33 | [Landed de7a5150](https://github.com/Shmirzaev/Milana-ERP/commit/de7a5150) | [test_stocktake_postgres_snapshot.py](https://github.com/Shmirzaev/Milana-ERP/blob/codex/ismail-review-fixes/backend/app/tests/test_stocktake_postgres_snapshot.py) |
| PERF34 | [Landed 6a83c0dd](https://github.com/Shmirzaev/Milana-ERP/commit/6a83c0dd) | [test_shipment_document_query_growth.py](https://github.com/Shmirzaev/Milana-ERP/blob/codex/ismail-review-fixes/backend/app/tests/test_shipment_document_query_growth.py) |
| PERF35-FINANCE | [Landed c50d5719](https://github.com/Shmirzaev/Milana-ERP/commit/c50d5719) | [test_finance_integration_retirement.py](https://github.com/Shmirzaev/Milana-ERP/blob/codex/ismail-review-fixes/backend/app/tests/test_finance_integration_retirement.py); [test_perf35_finance_invoice_paging.py](https://github.com/Shmirzaev/Milana-ERP/blob/codex/ismail-review-fixes/backend/app/tests/test_perf35_finance_invoice_paging.py) |
| PERF35-PURCHASING | [Landed e79f0918](https://github.com/Shmirzaev/Milana-ERP/commit/e79f0918) | [test_perf39_40_35_employee_and_order_bounds.py](https://github.com/Shmirzaev/Milana-ERP/blob/codex/ismail-review-fixes/backend/app/tests/test_perf39_40_35_employee_and_order_bounds.py); [test-purchasing-browser.mjs](https://github.com/Shmirzaev/Milana-ERP/blob/codex/ismail-review-fixes/frontend/scripts/test-purchasing-browser.mjs) |
| PERF39-MODEL | [Landed bd810b8b](https://github.com/Shmirzaev/Milana-ERP/commit/bd810b8b) | [test_perf39_40_35_employee_and_order_bounds.py](https://github.com/Shmirzaev/Milana-ERP/blob/codex/ismail-review-fixes/backend/app/tests/test_perf39_40_35_employee_and_order_bounds.py) |
| PERF40 | [Landed a1ff9ad8](https://github.com/Shmirzaev/Milana-ERP/commit/a1ff9ad8) | [test_image_upload_scheduling.py](https://github.com/Shmirzaev/Milana-ERP/blob/codex/ismail-review-fixes/backend/app/tests/test_image_upload_scheduling.py); [test_inventory_access_restore.py](https://github.com/Shmirzaev/Milana-ERP/blob/codex/ismail-review-fixes/backend/app/tests/test_inventory_access_restore.py) |
| PERF41 | [Landed 47f3714d](https://github.com/Shmirzaev/Milana-ERP/commit/47f3714d) | [test_eco_history_query_growth.py](https://github.com/Shmirzaev/Milana-ERP/blob/codex/ismail-review-fixes/backend/app/tests/test_eco_history_query_growth.py) |
| UI03-PURCHASE | [Landed 6deb80a9](https://github.com/Shmirzaev/Milana-ERP/commit/6deb80a9) | [test-purchase-receipt-idempotency-key.mjs](https://github.com/Shmirzaev/Milana-ERP/blob/codex/ismail-review-fixes/frontend/scripts/test-purchase-receipt-idempotency-key.mjs); [test-purchasing-browser.mjs](https://github.com/Shmirzaev/Milana-ERP/blob/codex/ismail-review-fixes/frontend/scripts/test-purchasing-browser.mjs) |

[PERF23 API paging and query-growth regressions](https://github.com/Shmirzaev/Milana-ERP/blob/codex/ismail-review-fixes/backend/app/tests/test_perf23_price_calculation_list_query_growth.py) complement the browser evidence above.

Additional RES-PLAN-ARCHIVE coverage is in `test_reservation_plan_query_growth.py`: archived and failed/rejected/hold candidates are excluded, pending/passed remain eligible, and pinned stock/claim ledgers remain intact. The receiving page recovery loop is also corrected and browser-verified.

## Other owners and actual GitHub delivery

All 38 PRs targeting clone_main were examined, including closed/merged proposals. Their merge commits were checked against the current target. All published remote branch tips were fetched, because the clone initially fetched only clone_main. Recent author identities and task-linked PRs were compared with the ownership assignments starting 2026-10-03.

`Phantom-curly` is attributed to Dilmurod from the Git author identity containing Dilmurod's name and the corresponding assigned tasks; the GitHub profile has no display name. That account clearly contributed. PR count, author activity and owner-task completion are different measures.

| Owner | Original engineering allocation | Delivery evidence | Outstanding evidence |
| --- | --- | --- | --- |
| Ismail | 37 | 31 remain landed; six fixed in PR 279 after ST02 re-audit | Merge/review of the six, plus separate live OPS02/OPS03 evidence |
| Dilmurod | 38 | 32 assigned-task PRs merged; SEC04 source pushed separately | Five tasks without a matching merged PR or task branch; SEC04 still not merged |
| Mirshoir | 35 | PERF32 has a merged task PR, authored by Dilmurod | Other 34 tasks have no matching task delivery PR in this review; no owner-attributable recent bug-fix commit was identified |
| Shavkat | 0 engineering tasks | Business decision owner | D1 historical profit/currency and D2 concrete production data/catalog approval remain |

This establishes published delivery, not whether someone has worked privately. Mirshoir has no attributable recent delivery evidence in this repository; it would be inaccurate to assert that he has done no local work. PERF32 is evidence that a task in his allocation was delivered by another engineer, not that Mirshoir submitted it. Separate application and operations commits from repository account `Shmirzaev` are present through 2026-10-05; this audit does not equate that account with a team name without identity evidence.

Dilmurod's remaining five are **API02, FN06, OPS05, OPS06 and OPS08**. Source checks support the gaps: task schemas still accept unrestricted status/reference fields; generic replay is scoped only by endpoint/key/payload and does not check its stored caller; readiness checks PostgreSQL without the full shared-store contract; `scripts/storage_recovery_manifest.py` is missing; security still imports `jose` and no fresh built-image dependency audit was evidenced. These are delivery/source assessments, not fresh runtime reproductions of every finding.

**SEC04 is pushed but not delivered:** [commit 0596ad39](https://github.com/Shmirzaev/Milana-ERP/commit/0596ad39cd2572357ede264e30631fabeb4036f7) on `codex/sec04-model-file-auth`. Its tip is not an ancestor of clone_main, and a PR lookup for that head returned none. Current clone_main model-file token validation still does not query active-account or token-cutoff state.

## Dilmurod task evidence

| Task | GitHub delivery | Tracker |
| --- | --- | --- |
| API02 | No matching delivery evidence | Open |
| AT01 | [Merged PR 267](https://github.com/Shmirzaev/Milana-ERP/pull/267) | Open |
| AT05 | [Merged PR 268](https://github.com/Shmirzaev/Milana-ERP/pull/268) | Open |
| AT06 | [Merged PR 269](https://github.com/Shmirzaev/Milana-ERP/pull/269) | Open |
| FN06 | No matching delivery evidence | Open |
| FN07-ADJUSTMENT | [Merged PR 260](https://github.com/Shmirzaev/Milana-ERP/pull/260) | Open |
| FN07-RECORD | [Merged PR 261](https://github.com/Shmirzaev/Milana-ERP/pull/261) | Open |
| PY01 | [Merged PR 264](https://github.com/Shmirzaev/Milana-ERP/pull/264) | Open |
| PY02 | [Merged PR 265](https://github.com/Shmirzaev/Milana-ERP/pull/265) | Open |
| PY03 | [Merged PR 262](https://github.com/Shmirzaev/Milana-ERP/pull/262) | Open |
| PY04 | [Merged PR 263](https://github.com/Shmirzaev/Milana-ERP/pull/263) | Open |
| PY05 | [Merged PR 266](https://github.com/Shmirzaev/Milana-ERP/pull/266) | Open |
| SEC04 | Pushed branch, no PR or merge | Open |
| SEC05 | [Merged PR 256](https://github.com/Shmirzaev/Milana-ERP/pull/256) | Open |
| SEC06 | [Merged PR 259](https://github.com/Shmirzaev/Milana-ERP/pull/259) | Open |
| SEC08 | [Merged PR 258](https://github.com/Shmirzaev/Milana-ERP/pull/258) | Open |
| SEC09-PROXY | [Merged PR 257](https://github.com/Shmirzaev/Milana-ERP/pull/257) | Open |
| SEC10 | [Merged PR 255](https://github.com/Shmirzaev/Milana-ERP/pull/255) | Open |
| DB02-HR-STATUS | [Merged PR 270](https://github.com/Shmirzaev/Milana-ERP/pull/270) | Open |
| DB03-HR-PROFILE | [Merged PR 272](https://github.com/Shmirzaev/Milana-ERP/pull/272) | Open |
| DB03-PAYROLL-SNAPSHOT | [Merged PR 273](https://github.com/Shmirzaev/Milana-ERP/pull/273) | Open |
| FN07-HR-SALARY | [Merged PR 271](https://github.com/Shmirzaev/Milana-ERP/pull/271) | Open |
| OPS05 | No matching delivery evidence | Open |
| OPS06 | No matching delivery evidence | Open |
| OPS08 | No matching delivery evidence | Open |
| OPS09-WEB | [Merged PR 277](https://github.com/Shmirzaev/Milana-ERP/pull/277) | Open |
| PERF05 | [Merged PR 281](https://github.com/Shmirzaev/Milana-ERP/pull/281) | Open |
| PERF06 | [Merged PR 284](https://github.com/Shmirzaev/Milana-ERP/pull/284) | Open |
| PERF07 | [Merged PR 285](https://github.com/Shmirzaev/Milana-ERP/pull/285) | Open |
| PERF31 | [Merged PR 289](https://github.com/Shmirzaev/Milana-ERP/pull/289) | Open |
| PERF35-HR | [Merged PR 286](https://github.com/Shmirzaev/Milana-ERP/pull/286) | Open |
| PERF35-PAYROLL | [Merged PR 282](https://github.com/Shmirzaev/Milana-ERP/pull/282) | Open |
| PERF36 | [Merged PR 288](https://github.com/Shmirzaev/Milana-ERP/pull/288) | Open |
| PERF37 | [Merged PR 280](https://github.com/Shmirzaev/Milana-ERP/pull/280) | Open |
| PERF38 | [Merged PR 283](https://github.com/Shmirzaev/Milana-ERP/pull/283) | Open |
| SEC09-RESET-PROXY | [Merged PR 276](https://github.com/Shmirzaev/Milana-ERP/pull/276) | Open |
| UI01 | [Merged PR 274](https://github.com/Shmirzaev/Milana-ERP/pull/274) | Open |
| UI02 | [Merged PR 275](https://github.com/Shmirzaev/Milana-ERP/pull/275) | Open |
## Mirshoir task evidence

| Task | GitHub delivery | Tracker |
| --- | --- | --- |
| API05 | No matching delivery evidence | Open |
| DB01-CONSUMPTION | No matching delivery evidence | Open |
| DB02-WO-STATUS | No matching delivery evidence | Open |
| SEC07-ASSIGNMENT | No matching delivery evidence | Open |
| SEC07-FLOW | No matching delivery evidence | Open |
| ST09 | No matching delivery evidence | Open |
| UI03-PACKAGE | No matching delivery evidence | Open |
| WF01 | No matching delivery evidence | Open |
| WF02 | No matching delivery evidence | Open |
| WF03 | No matching delivery evidence | Open |
| DB07 | No matching delivery evidence | Open |
| PERF01 | No matching delivery evidence | Open |
| PERF04 | No matching delivery evidence | Open |
| PERF08 | No matching delivery evidence | Open |
| PERF09 | No matching delivery evidence | Open |
| PERF10 | No matching delivery evidence | Open |
| PERF11 | No matching delivery evidence | Open |
| PERF12 | No matching delivery evidence | Open |
| PERF13 | No matching delivery evidence | Open |
| PERF14 | No matching delivery evidence | Open |
| PERF16 | No matching delivery evidence | Open |
| PERF17 | No matching delivery evidence | Open |
| PERF18 | No matching delivery evidence | Open |
| PERF19 | No matching delivery evidence | Open |
| PERF20 | No matching delivery evidence | Open |
| PERF21 | No matching delivery evidence | Open |
| PERF27 | No matching delivery evidence | Open |
| PERF32 | [Merged PR 287](https://github.com/Shmirzaev/Milana-ERP/pull/287); authored by Phantom-curly | Open |
| PERF35-FINISHED-GOODS | No matching delivery evidence | Open |
| PERF35-INBOX | No matching delivery evidence | Open |
| PERF35-PRODUCTION | No matching delivery evidence | Open |
| PERF39-PACKAGES | No matching delivery evidence | Open |
| PERF39-PRODUCTION | No matching delivery evidence | Open |
| PERF42 | No matching delivery evidence | Open |
| UI05 | No matching delivery evidence | Open |

## Scope limits and remaining risks

- Existing FN04 acceptance checks cover the finance and sales invoice routes. Customer-payment invoice creation in `backend/app/api/routes/partners.py` and delivered-shipment creation in `backend/app/services/workflow.py` still lack the same common SalesOrder lock. The tracker already records this residual; it is not proof that all invoice-creation paths are race-safe.
- The dedicated accessory-return route has ST06's allowance lock. Generic movement references can still bypass it by writing `ProductionOrderAccessoryReturn` directly. This is a known source candidate outside the narrow ST06 route proof.
- Dilmurod's unresolved FN06 affects generic finance/inventory retry callers; Ismail's purchasing receipts and waste sales use their own caller-scoped replay scopes and parent locks. No blanket claim of generic replay safety is made.
- DB08 removes exactly 23 tracked differences. The other 94 accepted normalized schema differences remain; global ORM parity is not claimed. Live 0138 catalog application still requires actual catalog/lock assessment, verified backup and D2 approval.
- OPS02/OPS03 for Ismail, OPS04/OPS10/OPS11 for Dilmurod, and OPS01/OPS07 for Mirshoir remain unverified production follow-ups. Source changes and merged PRs do not establish live capacity, restore, infrastructure or network evidence.
- The latest shared deployment record reports blue 20261005_070406, application 25a7dd1c and schema 0137. No fresh live verification, production mutation or deployment occurred in this audit. Public GitHub checks ran on disposable databases.
- The other-owner tracker rows are not closed wholesale based only on matching PR titles. The report records their actual merge evidence separately and avoids overstating independent acceptance review or performance measurements.

Worktree: `C:/Users/ismoi/OneDrive/Desktop/remote_work/milana_ERP/.codex-work/ismail-completion`. Local branch `codex/ismail-completion`; proposal branch `codex/ismail-review-fixes`; target `clone_main`. The shared checkout, other engineers' source and preserved server data remain untouched. The ST02 source, tests, mandatory CI gate and corrected tracker are included in PR 279; no merge or deployment was performed.
