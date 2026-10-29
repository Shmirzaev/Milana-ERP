# Production and clone_main reconciliation — 29 October 2026

The owner explicitly requested: reconcile production with latest clone_main,
preserve production fixes, test and deploy Ismail's remaining changes. The follow-up
requires blue/green with the current production version ready to switch back.
This authorizes this reconciliation, branch publication, integration and deployment;
it does not authorize creating or repairing production business records.

## Source and ownership

- Worktree: `C:/ERP/.codex-work/reconcile-clone-production-20261029`.
- Branch: `codex/reconcile-clone-production-20261029`.
- Shared input: `45b12da171c836921e0681f883e02001e39a4f46` (`clone_main`, PR341).
- Production record input: `a6a89f50b3e2ad5bcf9609985eefd0d55a777249`.
- Verified active runtime: `a0cb9d8b9fdab64dd751e7f3da7a1fa832779780`.
- Active release/slot: `20261028_123531`, blue on both VMs.
- Both clean source manifests: `3b2fb1c4e67f5c08a127d56d9490ee64c10997eb576ee0aeb9613caee246aaed`.
- Initial retained release: `20261027_115452`, green on both VMs.
- Candidate slot: green. Preserve blue `20261028_123531` running after activation.
- Database baseline: `0149_besttex_cutting_access`; no migration file changes.
- Ismail owns Catalog; Mirshoir reviews integration/release. Codex root integrates;
  independent Codex `/root/reconciliation_review` reviews source/test integrity.
  These assignments do not claim human business acceptance.

The legacy `C:/ERP` working files are preserved. A no-conflict merge imported the
exact production branch into latest clone_main. The stale clone_main production
baseline is corrected by the verified production record. Relative to active
production, only three runtime source files change: the partner service, its
schema persistence operations and Catalog internal types. Every deployed frontend,
Packaging, payroll, QR, Finance, CI and migration path is retained byte-for-byte.

## Operation map and gates

Supplier PATCH: authenticated partners route -> Catalog `update_supplier` ->
typed `SupplierUpdateCommand` -> schema `apply_supplier_update` -> same supplied
Session. Preserve permissions, required name, omitted/null/empty optional fields,
existing inactive-row behavior, service-owned audit, commit and refresh.

Customer DELETE: authenticated partners route -> Catalog `delete_customer` ->
schema `delete_customer_row` -> same supplied Session. Preserve missing-row and
sales-order/shipment guards, foreign-key refusal, audit and one outer commit.
Additional FK refusal still follows legacy error behavior; this release does not
introduce a new deletion policy or present that behavior as fixed.

Required checks: focused characterization/refusal/rollback tests; complete backend
suite and Ruff/compilation; exact-source immutable release CI; mandatory operation
PostgreSQL gate with no skipped required cases, including all Supplier update and
Customer delete/reference-race groups; frontend lint/strict types/production build;
independent source/release-helper review; actual browser Supplier/Customer UI and
persisted readback on isolated QA data, then signed read-only candidate/public QA.
Production QA must not create or mutate customers, suppliers or other business rows.

Before cutover: fresh verified 0600 PostgreSQL backup, no-op schema compatibility,
source/image/slot identities, rollback health, fixed-origin paired/public performance,
runtime/log/database/disk gates and final Git/production drift verification.
Backend switches first, then frontend; all four health checks must pass.

Observation: high/uncertain risk, 30 minutes, because the diff contains persistence
operations. Keep the former production blue slot running. The prior release's
waiver is historical and is not inherited. Continue through observer completion and
closing runtime/identity/database/log/performance checks. Roll back to retained
blue on failed postflight as appropriate; never downgrade the database implicitly.

Status: PREPARING. Test, build, backup, candidate QA, activation and observation
results will be recorded with their actual source identities and evidence.
