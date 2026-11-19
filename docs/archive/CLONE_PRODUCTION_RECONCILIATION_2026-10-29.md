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
- Initially verified runtime: `a0cb9d8b9fdab64dd751e7f3da7a1fa832779780`.
- Initial active release/slot: `20261028_123531`, blue on both VMs.
- Initial clean source manifests: `3b2fb1c4e67f5c08a127d56d9490ee64c10997eb576ee0aeb9613caee246aaed`.
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

Observation was initially planned as high/uncertain risk, 30 minutes. The owner
subsequently explicitly requested "skip the 30 minute monitoring as well" in this
chat. Timed monitoring is therefore waived for this release; do not report it as
performed. Keep the former production blue slot running and complete every immediate
runtime/identity/database/log/performance check. Roll back to retained blue on failed
postflight as appropriate; never downgrade the database implicitly.

## First exact candidate and disposable-clock correction

Candidate `53fd8137b0ced5814fb382ee5848a22f8167e161` preserved all production
application fixes. Its required PostgreSQL gate passed 148 operation cases plus
17 Purchasing/Fabric cases with no skips. Local PostgreSQL16 passed all 20 new
operation cases. Actual connected Chrome saved/reloaded the synthetic Supplier and
deleted/reloaded the disposable Customer; direct PostgreSQL readback confirmed one
update audit, one delete audit, retained Supplier fields and absent Customer.
The existing production frontend was used read-only because it is byte-identical
to the candidate; all API writes went only to the owned local PostgreSQL database.
An attempted local Next restart was rejected by automatic approval review and was
not retried through another launcher. No production business row was changed.

The Windows full run FAILED: 1 failed, 4,831 passed, 538 opt-in skips, 14 warnings.
The exact Linux release CI [40816106669](https://github.com/Shmirzaev/Milana-ERP/actions/runs/40816106669)
also FAILED with 1 failed, 4,831 passed, 538 skips. Both errors were the unchanged
Cutting deletion guard refusing Waste history whose timestamp differed from its
Cutting record. SQLite CURRENT_TIMESTAMP advances per statement at second precision;
PostgreSQL now() is transaction-stable. Independent review reproduced the exact
409 on both candidate and runtime-identical baseline by delaying the Waste insert
across a second boundary. Targeted baseline/candidate runs passed separately; a
77-case Customer/Cutting prefix also passed. Those passes do not relabel either
failed full run. No immutable release artifact or activation came from that attempt.

The correction is confined to the disposable SQLite test engine: its SQLAlchemy
begin event registers a connection-local UTC CURRENT_TIMESTAMP value for that
transaction, refreshed at the next transaction. New regressions challenge stability
across a second boundary, refresh after commit and separate simultaneous connections.
Application clocks, engines, persistence, deletion guards and existing assertions
remain unchanged. Renew independent review, the full backend/required PG/frontend CI
and immutable artifacts on the corrected exact commit before staging.

That preparation status is historical. The corrected exact release below passed
the renewed gates and was deployed; timed observation was explicitly waived.

## Verified release and handoff

Green `20261029_042945` was activated backend first, then frontend, at about
04:58 UTC / 09:58 Tashkent on 29 October. Immediate postflight completed at
05:01:22 UTC / 10:01:22 Tashkent. Both VMs, actual HAProxy targets, slot state,
current symlinks and immutable image labels agree on runtime
`921d646425054bb7b132042b1a173e2998249adc`. Both 1,807-file source manifests verify
against the exact reviewed Git archive:
`eda617eedff05dfca42aef15003135c5c5870276bb5da087d6543c1add889580`.
Archive SHA-256: `8a5854fa9a46acdadf137f4466556738b619fd5657ac2f18782c34bc2634cf71`.

The source was pushed on `codex/reconcile-clone-production-20261029`, then landed
by an ordinary fast-forward from reviewed `clone_main` `45b12da1` to `921d6464`
after a fresh fetch. Stale `origin/main` stayed `1a067b01`. The following release
record commit changes only documentation and production-base metadata; the live
runtime remains the exact CI-built `921d6464`, not that later record commit.

Immutable backend image:
`ghcr.io/shmirzaev/milana-erp-backend@sha256:1dbdf2803cb614e421dcb5a11a96ed8515b0600f8c1308c483b9ab917bda2d79`.
Immutable frontend image:
`ghcr.io/shmirzaev/milana-erp-frontend@sha256:bb8dd6787979530b5777e19e735b161142453df108bf33115f9b88d0b93d0f0e`.
No serving VM built images or installed dependencies. The exact-image backend
starts normally with two workers, 8+4 pool per worker, persistent storage mounted,
schema sync disabled and startup seeding explicitly disabled.

### Tests and independent review

- Corrected full local backend: **4,834 passed, 538 opt-in skipped, 14 known
  warnings**, 761.19 seconds. Ruff/compilation and single Alembic head passed.
- [Exact-source release CI 40818058945](https://github.com/Shmirzaev/Milana-ERP/actions/runs/40818058945):
  backend, frontend and immutable release jobs all succeeded on `921d6464`.
- [Required PostgreSQL CI 40818058533](https://github.com/Shmirzaev/Milana-ERP/actions/runs/40818058533):
  148 operation cases plus 17 Purchasing/Fabric cases, zero required skips/errors.
  Local exact-source PostgreSQL16 also passed all 20 changed-operation cases.
- Frontend lint: zero errors, 12 existing warnings; strict types and optimized
  production build passed. The exact CI reran its frontend gates. Frontend source
  is byte-identical to the retained production version.
- Independent source/fixture review passed, including 26 clock/Cutting cases,
  two forced second-boundary cases and a mutation that fails without the listener.
  Four isolated deployment-helper simulations confirmed rollback after benchmark
  failure, diagnostic-write failure and final identity drift, and correct success
  ordering. These are simulations, not a claim of an actual production rollback.
- Actual connected Chrome isolated Supplier save and Customer delete plus direct
  PostgreSQL audit/readback passed on application source identical to `921d6464`.
  Candidate and public QA then used a loopback gateway that refuses all writes,
  targeting the actual staged images/public HTTPS respectively. Supplier list and
  existing edit form, 36-Customer list and delete controls rendered correctly;
  screenshots were visually inspected, with zero console errors/warnings. No live
  Save/Delete action was performed. An initial guessed catalog URL returned Next
  404; navigation through the actual menu passed. This does not imply human or
  whole-ERP operation acceptance.

### Backup, data and closing checks

Fresh custom-format PostgreSQL backup verified at 04:33:22 UTC:
`/opt/milana-erp/shared/backups/milana_erp_pre_20261029_042945.dump`.
It is mode 0600, 95,602,104 bytes, with 1,246 restore objects. Dump SHA-256:
`4fe95e434a6a04b8d86dcc23a1f48e0f2199a36f6722a2ee382ca0d601cb1fe7`.
Restore-list SHA-256:
`62ea4e6f5c87fba98f7b11b651adfaeb97dd7bd2e952496d3fa5a0bf15406c93`.
The dump/list hashes, permissions and freshness were rechecked before migration,
staging and activation. Exact-image Alembic upgrade was a no-op; live revision
remains `0149_besttex_cutting_access`.

Candidate and public signed GET-only checks passed 25 workflow projections,
historical payroll/QR integrity, six existing package labels, Cutting production
sheet, finite Finance cost breakdown matching retained corrected blue, manual
Packaging API contract and unauthenticated/nonmanager refusal (401/403).
Historical record fingerprints were preserved. Ordinary business activity can
continue during QA; this is not a claim that the entire production database stood
still. Public root `/openapi.json` remains its verified baseline Next 404; the
actual backend contract was checked directly.

All four required health checks passed: internal backend `/health`, internal
frontend `/login`, public `/health` and public `/login`. Closing checks after the
public benchmark reconfirmed green identities/manifests, actual HAProxy routing,
two workers, zero restarts/OOM, clean error logs, database connection headroom and
zero invalid indexes. Disk use: backend 79.44%, frontend 77.16%, below the 80%
staging gate; this is limited headroom for the next release, not permission to
remove rollback or unrelated projects.

No production business records were created, edited, deleted, repaired or replayed
by this release/QA. Normal signed-in authentication GETs update user heartbeat
metadata (`last_seen_at` and `updated_at`). No accounts or permissions were granted.
Owned synthetic PostgreSQL clusters, QA gateways and browser tabs were stopped.
The legacy dirty `C:/ERP` source was preserved.

### Rollback and limits

Retained **blue `20261028_123531`**, runtime
`a0cb9d8b9fdab64dd751e7f3da7a1fa832779780`, remains running and healthy on both
VMs, with its original clean source, storage and images intact. The runtime state
explicitly names it as rollback. To restore it, follow `DEPLOYMENT.md`: activate
backend blue then frontend blue for that release, repoint both current symlinks,
and repeat all four health checks. No database downgrade is required or authorized.
The guarded helper also reasserts actual router targets even if activation was
interrupted before slot-state persistence.

The owner explicitly waived the 30-minute monitoring. No timed observer or
background monitor was run; only immediate postflight and closing checks are
reported. The scope remains Supplier UPDATE/Customer DELETE integration and
preservation of deployed fixes. Existing linked Payment/BrandedPlanning/
WarehouseReservation Customer DELETE constraints can still surface HTTP 500
instead of 409; protection remains, but error presentation is not corrected here.
Prior physical-label/operator acceptance and the broader operation/type refactor
remain incomplete and are not marked accepted by this deployment.

Local evidence: `outputs/deployment-corrected/` in the dedicated worktree; first
failed attempt and independent-review evidence remain under `outputs/deployment/`.
Closing `evidence.json` SHA-256:
`c8b7dfad945184127cd1311df0cb2b45d863f9ccfa254797bcb9d8aaddb3cf76`.

### Fixed-origin performance results

All five paths used 120 measured samples after five warmups, with the same retained
blue client origin, query values and request primitive. Counts matched and payload
growth was zero throughout. No failed benchmark was resampled.

| Endpoint | Paired median change | Paired p95 change | Public median change | Public p95 change |
| --- | ---: | ---: | ---: | ---: |
| global_search | +0.15% | -0.19% | +0.82% | -13.15% |
| inventory_batches | +0.30% | +0.48% | -0.76% | -10.06% |
| inventory_stock | +0.49% | -1.79% | -1.12% | -0.68% |
| model_groups | -2.14% | -2.04% | +1.87% | -0.39% |
| model_options | +0.79% | +2.59% | -0.30% | -1.28% |
