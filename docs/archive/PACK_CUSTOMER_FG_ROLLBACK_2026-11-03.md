# Customer-pack release: restart-compatible rollback

The owner authorized push, merge and deployment of only customer shipment-pack
restriction/admin release and FG numbering, without the 30-minute observer.
This compatibility image descends from exact active runtime
42078704df340558c8a21bf1ef14bf74cc87b222. No application, frontend, configuration,
Dockerfile, dependency, permission or business behavior is changed.

The customer feature preparation already applied migration 0150 after verified
backup `/opt/milana-erp/shared/backups/milana_erp_pre_20261103_094602_20261103_101940.dump`
(SHA256 04ef92dca03dfc2f456c1ab3678957987d88ec05eedda99341108cd36cc48fef).
The new ledger is empty. The old image only knows head 0149, so its strict startup
would reject schema 0150 on child-worker respawn or container restart. Preserve
schema 0150; never bypass production security or stamp/downgrade the database.

Copying the exact reviewed 0150 migration into the old source makes its real CMD
and strict schema verifier compatible. CI must exercise the exact published image
by digest against job-owned PostgreSQL and Redis: no host ports or source mounts,
production security settings, seed disabled, two workers, strict-head verification,
health/readiness, child-worker replacement, container restart, and zero test users,
models or release ledger entries. Cleanup requires run-specific ownership labels.

Activation is blocked until this image gate passes and a reviewed recovery path
can restore both roles. Staging/registering the compatible old runtime after
feature cutover must use its own immutable release identity, leave active routing
and source unchanged, verify both roles, and atomically update only rollback state.
Historical old-green OOM evidence is retained; no new OOM/worker replacement is
permitted before cutover. Candidate and compatibility containers require zero OOM.

Local gate: compilation, Ruff, digest/default-CMD/foreign-cleanup controls and
workflow structure. Actual image recovery runs in immutable-release CI because
local Docker is unavailable. This preparation does not itself activate a release.


Initial CI41620483143 passed 4,886 backend cases, frontend gates and the earlier
PostgreSQL gates, then stopped with175passes/1failure in the schema-contract job.
The old application intentionally does not map the new ledger, so migration0150
adds exactly one reviewed extra table. No image was built or production source,
locks, routing or containers changed during that failed run. The failure is retained.

The correction changes only test_fresh_migration_bootstrap.py: the shared94-entry
baseline remains exact, with one explicit compatibility-only supplement gated by
old-feature absence, source hashes and head0150. It separately reflects every ledger
column/type/null/default/timezone, primary key, both foreign keys includingCASCADE,
quantity check and absence of extra unique constraints/indexes. Negative tests reject
unreviewed schema or normalized drift. Committed LF source hashes also work with
Windows CRLF checkouts. Independent review and actual isolated PostgreSQL36cases
passed before rerunning the complete immutable-release workflow. Application,
frontend, migration, dependencies and image command remain unchanged.
