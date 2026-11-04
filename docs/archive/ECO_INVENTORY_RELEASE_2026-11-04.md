# ECO inventory release preparation — 4 November 2026

The owner explicitly instructed: **"deploy without 30 minute monitoring"** after
local review of PR375. This authorizes release of that feature and waives the
timed observation period only. Backup, immutable builds, source reconciliation,
candidate QA, performance and immediate/final health gates remain required.

## Exact scope and baseline

Both production hosts were freshly verified as blue20261103_094602, source
`11f80a2995daeeb90b5c01318aec9e9c6a40f1c9`, manifest
`ee765f999e782193878390897873c7b5865749460d4d776cf321fcd28490f8a9`,
database0150_package_customer_release. Green20261103_112256 is the recorded
compatible rollback. Source manifests pass full verification on both hosts.

The narrow release worktree starts at that exact active commit. Only the
73 reviewed PR375 feature paths are ported from its d6c2edd8→f49c2675 diff;
broad context/bug files and local demo runner are excluded. Existing active
customer-pack safeguards and FG numbering/tests remain. Unrelated HR, finance,
identity, platform and catalog refactors on clone_main are not released.
No production stock/order/material model or role grant is created by this work.

Package origin/display needs no migration. ECO adds its seven ledger/approval
tables;0154 adds typed receipt snapshots and merges the ECO branch with the
already deployed0150 package branch. HR migration0151 is deliberately excluded.
Original ECO revision identities remain intact.

## Review and remaining gates

Independent package review confirmed the exact10 runtime files and preservation
of shipped guards. Independent rollback review identified that old runtime's
exact Alembic-head check would refuse restart after0154. A separate compatibility
rollback, derived from the exact active source, is required before migration.
It must cold-start on both verified predecessor and complete successor schemas
and protect new ECO evidence while the ECO UI is unavailable during rollback.
Do not stamp/downgrade/drop new ledger tables to make an old image start.

The review also found source QC could be promoted to passed through transfer.
This candidate now filters non-passed batches before source pagination and
refuses their direct dispatch. Four regressions cover pending/hold/failed/rejected
stock with source conservation and no transfer creation after refusal.

Proportional local checks:152 focused receipt/approval/sewing/package/query-growth
cases passed; Ruff and compileall passed. Full local backend, frontend gates,
exact immutable CI, PostgreSQL gates, compatible rollback, backups, candidate QA,
performance and cutover remain pending until their actual evidence is recorded.

Preflight disk usage was79.15% backend and78.58% frontend (both below80% staging
stop, above70% alert). Retention dry runs are recorded under ignored
outputs/deployment. No cleanup, migration, staging or traffic switch has occurred.

Status: PREPARING. Timed monitoring: waived, not run. User deployment authority
does not fabricate a separate operator acceptance record.
