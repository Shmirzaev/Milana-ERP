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

## Shared-assignment approval gate correction

Independent rollback review reproduced the analogous feature bypass on exact
`f1e41f03`: an ECO assignment on a shared SEW work order, with either no bundle
or a Milana bundle, committed positive Sewing output without any ECO approval.
Eight new regression cases were red before the correction, including missing
approval, shared-work block ownership and the complete issue handoff.

Implementation agent `/root/review_packages` used isolated worktree
`C:\ERP\.codex-work\eco-sewing-gate-release-fix-20261104` from `f1e41f03`.
The coordinator independently reviews and integrates this patch. Existing
assignment ownership/status and batch validation now run before the gate;
the canonical assigned factory and resolved batch are authoritative. ECO BSO
discovery, material order selection and issue also recognize valid ECO line
assignments. Cancelled/transferred assignments grant no new ECO ownership.
Shared block updates use the valid assigned work IDs and preserve separate
MIL/BST checks, including pending ECO work on the same shared work order.

No stored vocabulary, schema, permissions, approval/issue timing or stock
calculation changes. Approved allocation still permits handoff; issuing still
deducts physical stock exactly once. Existing SEW work-order authorization is
preserved by this bounded correction. The new factory projection returns the
canonical `SewingFactoryCode`; existing persisted assignment-status values and
the route's accepted action subset remain unchanged.

The affected local regression selection passed 122 cases; the final assignment
boundary file passed 11 cases; full-app Ruff and compilation passed.
PostgreSQL/immutable CI, candidate browser and release checks require their own
exact-source evidence. All reproduction rows
were isolated test data. This worker changed no production state or business
rows and did not push or deploy.

## Sewing factory aliases and direct-line follow-up

Independent review reproduced two remaining compatibility cases against
`cf23c065`: a historical `BESTTEX` bundle reached the new enum conversion and
raised `ValueError`, and an unsplit shared SEW work order assigned directly to
an ECO line could record output without approval. Eighteen new assertions failed
before this follow-up. The gate now uses the existing bundle alias map lazily,
returns canonical factory values before selecting the approval path, and refuses
unknown factories with HTTP400. SQL ownership, assigned work selection and
historical sewing evidence recognize the same supported alias spellings.

The persisted primary line is authoritative only without any active split
assignment. Its work-order batch remains the gate scope; a stale former primary
line cannot override active MIL/BST splits. Direct ECO work participates in order
selection, approval blocks and historical grandfathering. Tests include no
assignment, cancelled/transferred splits, real positive MIL/BST output, all
supported legacy factory families, refusal of unknown factories, batch isolation
and approved direct ECO allocation through output and exactly-once issue.

The independent package reviewer probed BESTTEX, unknown values, direct ECO
refusal with zero output, direct MIL positive output, history/batch predicates
and stale-primary suppression and found no remaining actionable blocker.
The affected local selection passed 219 distinct cases (96 ECO/transfer/bundle
cases and 123 sewing/receiving/quantity/query-growth cases); the final boundary
file passed 38 cases after adding real legacy positive-output assertions.
Full-app Ruff, compilation and diff checks passed. Real PostgreSQL, immutable
CI and deployment verification remain coordinator gates.
This follow-up added no schema, permissions or production data changes.
