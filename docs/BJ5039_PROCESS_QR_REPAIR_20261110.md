# BJ5039 immediate Process QR configuration repair

Date: 2026-11-10 (Asia/Tashkent).

The owner requested that existing operations become visible immediately before
the permanent change from variant-based to model-based loading. The owner
explicitly accepted live release 20261109_163130 as the source baseline after
disclosure that origin/main records an older release. This record does not claim
the permanent runtime change or a deployment.

## Verified baseline

- Both hosts: 20261109_163130, application 271c5005e12d1efc65d6358756862d8c243685a5.
- Both full source manifests pass; manifest SHA-256
  535aa197ba218b0d0e867480d6a6570a25273307dfdea2185ce28d383f4e56d7.
- Dedicated worktree: C:/ERP/.codex-work/process-qr-base-model-20261110.
- Branch: codex/process-qr-base-model-20261110; starts at production record
  2bb66fc44475c50cfe4f9d979b2e184b8a127f56. No legacy checkout edits.
- Retained rollback: 20261109_035740. No release/container/router change.

## Backup and mutation

Fresh PostgreSQL custom dump completed before the repair:
`/opt/milana-erp/shared/backups/milana_erp_pre_20261110_065001.dump`.
Size 117,227,928 bytes; SHA-256
`b66142d10a7223810fe21e56f34b574d41062d8e95c2308e246894c08887cfb9`.
pg_restore --list succeeded with 1,395 objects. Restore-list SHA-256
`6413343699185c8600ae5ea928c905d5fbe1f65c7419b826240cad3a4722b3c2`.
Dump and restore list use mode 0600.

Invoked the deployed `models_service.update_model_paid_operations` with the
existing active System Admin actor (id 1), parent model 8887, sewing_factory
milana, and the parent's existing 20-row operation list. The existing family
advisory lock and ordered row locks were acquired before rechecking exact family
membership, donor size/factory, and empty variant lists. The normal schema-owned
persistence, validation, audit and commit path was used, with no raw SQL writes.

| Model | Internal reference | Before | After |
| --- | --- | --- | --- |
| BJ5039 | 8887 | 20 | 20 |
| BJ5039-V-6793 | 8888 | 0 | 20 |
| BJ5039-V-6794 | 8889 | 0 | 20 |
| BJ5039-V-6795 | 8890 | 0 | 20 |
| BJ5039-V-6850 | 8957 | 0 | 20 |

All lists exactly match the donor, including operation metadata/rates/order.
Parent details are identical to before. Other variant detail keys are identical
to before. Five update_paid_operations / Model audit events record model_family
scope and requested parent id. Standard catalog identity is model:bj5039;
Usluga and other model families were not targeted.

## Verification and limits

- Independent post-commit readback through deployed get_model serialization
  returns 20 selected milana operations on all five family members.
- Family payroll_qr_labels and payroll_records were both empty before and after;
  each unchanged serialized empty-list SHA-256 is
  4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945.
- Internal backend health, internal frontend login, public health and public
  login all return HTTP 200. Both source-manifest checks pass after repair.
- Browser inventory worked, but Chrome automation failed before opening the
  verification tab. No UI save/issue/print action was performed; no rendered UI
  success is claimed. Reload Process QR to fetch updated configuration.
- No code tests were needed for this configuration-only use of the deployed
  service. No new business records, labels, payroll, orders, stock, permissions,
  migrations or deployment were created. Existing model configurations changed
  as listed, plus their normal update metadata and append-only audits.
- Permanent base-model loading remains pending. This repair does not fix future
  parent/variant divergence or other families.
