# Historical evidence

These reports preserve what was observed at their recorded date. They are not
current implementation instructions or proof of today's production state.
Start with [current context](../PROJECT_CONTEXT.md) for active work.

- [Owner rollback of factory workflows, 13 November 2026](FACTORY_WORKFLOWS_ROLLBACK_20261113.md): after reported bugs, blue115200 restored on both hosts; current data preserved, fresh backup and closing checks passed; green094409 withdrawn and not approved for reactivation.

- [Factory workflows release, 13 November 2026](FACTORY_WORKFLOWS_RELEASE_20261113.md): all seven fixes deployed as green094409; owner accepted only the two paired Sales latency failures, strict public checks passed, healthy blue115200 retained, monitoring waived.

- [Invoice/report and Sewing release, 11 November 2026](INVOICE_SEWING_RELEASE_20261111.md): blue115200 deployed after owner accepted the named p95 exception; initial rollback preserved, green052632 retained, fresh backup/public checks passed, monitoring waived.

- [November pricing scope and latest Excel, 11 November 2026](VARIANT_PRICING_NOVEMBER_SCOPE_20261111.md): green 20261111_052632 deployed; one fabric field, Order No., recent non-Usluga queues, 131 retirements, 14 missing-price fills, conserved orders and accepted public timing exceptions.

- [Variant pricing release, 11 November 2026](VARIANT_PRICING_RELEASE_20261111.md): blue 20261110_135430 / schema 0156 deployed; exact CI and recovery, owner latency exceptions, price/backfill completion record.

- [Variant pricing candidate, 10 November 2026](VARIANT_PRICING_WORKFLOW_20261110.md): explicit team submissions and Finance approval, complete Excel, isolated workflow/lock verification; historical candidate evidence, superseded by the release record.

- [BSO, fabric receipts and operation copying, 10 November 2026](BSO_FABRIC_PAID_COPY_RELEASE_2026-11-10.md): green163130 deployed, retained blue035740, exact owner timing exceptions, signed public verification and completed closing.

- [BSO, fabric receipts and operation-copy candidate, 9 November 2026](BSO_FABRIC_PAID_COPY_CANDIDATE_2026-11-09.md): corrected Milana/Eco Cotton labels, green staged; cutover awaits explicit two-median exception, active blue unchanged.

- [ECT and warehouse workflow release, 9 November 2026](ECT_WAREHOUSE_RELEASE_2026-11-09.md): blue20261109_035740, all eight workflows, polished report, explicit paired-median exception, public pass and waived monitoring.

- [Operational test account, 18 September 2026](OPERATIONAL_TEST_ACCOUNT_2026-09-18.md): sanitized historical record; current account status unverified.

- [BSOrder cleanup historical scripts, 10 September 2026](BS_CLEANUP_2026-09-10/README.md): completed one-off source retained as text; never rerun.

- [FG model-number prefix, 3 November 2026](FG_MODEL_PREFIX_2026-11-03.md): FG202001 start, focused and local-browser verification; PostgreSQL gate pending, not deployed.

- [Older-pack exact release, 2 November 2026](OLDER_PACK_FILTERS_RELEASE_2026-11-02.md): green20261102_063110, immutable provenance, retained aborted attempt, reviewed retry, backup and waived monitoring.

- [Older-pack history filters, 2 November 2026](OLDER_PACK_FILTERS_2026-11-02.md): deployed QR merge, scoped read-only history search/pagination candidate, checks and operator acceptance steps.

- [One package in multiple open shipments, 29 October 2026](OPEN_SHIPMENT_PACKAGE_SPLIT_2026-10-29.md): immediate remaining-size claims before dispatch, exact green release and unchanged blue recovery guard.

- [Order artwork, Nastil factories and warehouse corrections, 29 October 2026](PRINT_NASTIL_WAREHOUSE_2026-10-29.md): green release, audited PO-0377 correction, retained blue, explicit latency exception and monitoring waiver.

- [Production and clone_main reconciliation, 29 October 2026](CLONE_PRODUCTION_RECONCILIATION_2026-10-29.md): verified green release, preserved production fixes, retained blue rollback and explicit monitoring waiver.

- [Verified integration checkpoint, 28 October 2026](VERIFIED_INTEGRATION_2026-10-28.md): scoped Planning, Customer, Brand and Supplier evidence, PR338/339 and superseded QA history.

- [Manual Finance invoice creation, 27 October 2026](FINANCE_MANUAL_INVOICE_CREATE_2026-10-27.md):
  schema-owned insert candidate, unchanged policy, type ledger and pending gates.

- [Ismail six-area refactor candidate, 25 October 2026](ISMAIL_SIX_AREA_REFACTOR_2026-10-25.md):
  implementation, local verification, limits and human checklist; not a production release.
- [Complete project context before cleanup](PROJECT_CONTEXT-2026-10-24.md): deployment
  attempts, active/rollback identities, backups, fixes, known gaps and planning history.
- [SEWING_ECO_REVIEW_2026-09-17.md](SEWING_ECO_REVIEW_2026-09-17.md)
- [MODEL_PAID_OPERATIONS_RECONCILIATION_2026-09-29.md](MODEL_PAID_OPERATIONS_RECONCILIATION_2026-09-29.md)
- [catalog-parity-20260930.md](catalog-parity-20260930.md)
- [WAREHOUSE_STOCK_SPEED_2026-10-16.md](WAREHOUSE_STOCK_SPEED_2026-10-16.md)
- [PAYROLL_DEPARTMENTS_REVIEW_2026-09-09.md](PAYROLL_DEPARTMENTS_REVIEW_2026-09-09.md)
- [RF-013 single-host rollback rehearsal](RF013_SINGLE_HOST_REHEARSAL_2026-10-27.md):
  disposable HAProxy switch, data compatibility and partial-failure evidence.

Older audit reports remain in ../audit-evidence/ because existing records/tests
refer to them. No historical business or release evidence was deleted in this cleanup.
New detailed dated events belong here; current summaries link to the relevant record.

- [Combined manual Packaging release, 28 October 2026](MANUAL_PACKAGING_RELEASE_2026-10-28.md):
  verified blue promotion, retained green rollback, exact CI/backup/QA and print acceptance limits.
- [Manual Packaging and employee master correction, 28 October 2026](MANUAL_PACKAGING_2026-10-28.md).

- [RF-009 create_user baseline](RF009_CREATE_USER_BASELINE_2026-10-29.md):
  196 passing current-behavior cases; extraction agreement remains pending.
- [RF-009 create_user extraction candidate, 3 November 2026](RF009_CREATE_USER_EXTRACTION_2026-11-03.md):
  delegated seam approval, unchanged baseline, schema writes and pending human gate.
- [Local PostgreSQL runner adaptation](LOCAL_POSTGRES_RUNNER_2026-10-29.md):
  combined fixture wiring, zero skips and the remaining S06 test-contract failure.
