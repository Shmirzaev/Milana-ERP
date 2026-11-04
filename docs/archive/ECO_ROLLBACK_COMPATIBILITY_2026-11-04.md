# ECO migration-compatible rollback candidate — 4 November 2026

Owner's deployment request explicitly waives the 30-minute observation only.
Backup, migration, build, independent review, candidate QA, performance, cold
restart and release checks remain separate gates. This worker does not deploy.

The coordinator verified active blue `20261103_094602`, runtime
`11f80a2995daeeb90b5c01318aec9e9c6a40f1c9`, manifest
`ee765f999e782193878390897873c7b5865749460d4d776cf321fcd28490f8a9`, and database
`0150_package_customer_release`. Retained green `20261103_112256` / `37337ea6`
was reported as the previous rollback. The worker made no independent SSH check
or production change. `deploy/production-base.json` records the supplied verified
baseline instead of its stale 2 November record.

## Bounded operation and ownership

Implementation agent: Codex `/root/review_packages`; independent AI reviewer and
release integrator: root coordinator. Migration metadata remains Mirshoir's domain,
reviewed by Ismail; human approval is separate and is not invented here.
Worktree `C:\ERP\.codex-work\eco-inventory-rollback-20261104`, branch
`codex/eco-inventory-rollback-20261104`, starts at exact active `11f80a29`.

Only three ECO migrations come from reviewed feature `f49c2675`. Their original
revision identities are preserved. `0154_eco_receipt_details` merges the ECO branch
with **actual production** `0150_package_customer_release`; it excludes unreleased
HR gate enrollment and every unrelated integration change. Seven additive tables
and two JSON metadata columns create no business stock, roles or production rows.

Startup still enforces an exact canonical head. Before upgrade, it additionally
accepts only exact `0150_package_customer_release` with all seven ECO tables absent.
Unknown/unmerged heads, partial predecessor tables and missing successor columns
refuse startup. Startup only inspects; it never stamps or migrates the database.

## Operational rollback restrictions

After ECO tables exist, the old runtime cannot safely enforce ECO approvals.
Every sewing send/receipt/start/record gate therefore refuses ECO work with HTTP
409 until the feature runtime is restored. Persisted factory/work-order scope keeps
Milana and Besttex handoffs separate on mixed orders. With no ECO tables, all old
business behavior remains in place. This is a rollback freeze, not a new ECO API.
The sewing-record gate runs after assignment ownership/status validation and
uses its persisted line's factory, including line-name-resolved assignments.
Shared `SEW`/`MIL` work orders cannot mask an ECO assignment. A positive-output
reproducer failed for both ECO assignment selection paths before this correction;
the corrected gate refuses both, while positive MIL/BST controls still persist.

Shared item update/delete locks the item and reads new ECO references without
registering new ORM mappings. ECO-linked unit/category edits and hard deletion
are refused. Existing authorized force removal archives the item and preserves
all stock/approval evidence. No new user permission is introduced.

Never downgrade or stamp the migrated database back to the predecessor merely
to run an older image. Build and retain this exact reviewed compatibility image,
verify its cold startup against the upgraded candidate database, and only then
consider production migration. This source publication alone is not release
authorization or evidence of a working deployed rollback.

## Verification

`test_eco_rollback_compatibility.py` exercises real Alembic graph upgrades from
the active predecessor, actual FastAPI lifespan cold starts before
and after upgrade, refusal states, ECO-only operational freeze and preserved item
evidence. SQLite uses active ORM metadata plus a predecessor stamp as an offline
check; PostgreSQL executes the actual full legacy migration chain through
`0150_package_customer_release` before the ECO upgrade. The explicit CI step runs before
the full suite, uses the job-owned loopback database and creates/drops only a
random schema it owns. Local PostgreSQL is unavailable; no local PostgreSQL pass
is claimed. The PostgreSQL URL must target loopback, end in `_ci` or `_qa`, and
contain no query parameters; unsafe targets are rejected before any connection.
Targeted compatibility/startup/readiness/bundle-gate checks passed
31 cases with the one real PostgreSQL case skipped locally. Broader affected
bundle receipt, inventory master-data and migration tests passed 73 cases with
six PostgreSQL skips. The fresh-migration drift test validates the seven complete
additive table shapes explicitly, then excludes only their unmapped rollback
tables from comparison; every other legacy drift expectation remains unchanged.
Exact commands and
the final commit are handed to the root coordinator for independent review and
immutable-image staging.

The final compatibility-only rerun, including assignment-factory and unsafe-URL
regressions, passed 24 cases with the one real PostgreSQL case skipped locally.

## Omitted assignment and direct-line freeze correction

Codex `/root/eco_inventory_transfers` owns this bounded follow-up; the root
coordinator owns independent review, new exact-source CI and release decisions.
The previous explicit-assignment tests did not cover omitted selection. Before
the correction, two positive calls to the real `post_sewing` handler persisted
one passed piece on the upgraded rollback: direct ECO with no split/plan/bundle,
and an active ECO split on shared SEW work with assignment omitted. The regression
run was RED with two failures; four positive MIL/BST controls passed.

The read-only freeze now uses persisted active planned/in-progress/completed
assignment factories first. It uses the work order's direct line only when no
active split exists, then its department. A validated explicit assignment remains
authoritative, so a MIL/BST split can record on mixed work despite a competing
ECO split or stale direct ECO line. The generic order gate resolves the same
work/line/split evidence plus existing bundle and ECO-plan evidence. One CTE
resolves unspecified scope without per-work queries. Shared historical aliases
are recognized through the existing map; unknown values refuse with HTTP400
instead of silently becoming Milana. No API, ORM mapping or runtime writer was
added. The pre-upgrade path still returns before querying absent ECO tables.

The affected callers were traced: bundle send and single/bulk/band receipt pass
their persisted factory; `start_wo` supplies a work-order scope; `post_sewing`
supplies that scope and its already validated explicit/line-name assignment.
Tests exercise positive record persistence, actual start, generic/work gates,
cancelled/transferred splits, aliases and unknown-value refusal. Alias/corrupt
flow fault cases bypass checks only while constructing private SQLite fixtures,
then restore checks before invoking the operation; production constraints are
unchanged. The real PostgreSQL migration/cold-start gate now also executes this
same persisted-scope CTE and its ECO/MIL mixed-work controls on its owned schema.
Local PostgreSQL remains unavailable; its outcome belongs to the next CI run.
The corrected compatibility/startup/readiness/bundle/sewing regression selection
passed 98 cases with the one required PostgreSQL gate skipped locally. Scoped
Ruff, Python compilation and `git diff --check` passed. These results do not
replace independent review, the next exact-image CI or production release gates.
