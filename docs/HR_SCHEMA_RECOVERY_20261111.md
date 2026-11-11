# HR schema-compatible recovery preparation — 11 November 2026

This is a recovery artifact candidate, not a feature landing or production change.
Do not merge it into the shared feature branch as a replacement application.

The isolated `codex/hr-schema-recovery-20261111` worktree now merges verified
`origin/clone_main` `3053788f2`, recording active green `20261111_052632`, runtime
`519c9fa36f3d90905f935caf08fe781417cf7e24` and manifest
`55d0edc9b7893df95987102cc6d9ccbe5b59a89f3c369eb5ea1f46a9868d4520`.
Both complete 2,485-file host manifests and slot states match the updated baseline
record; production remains on `0156_variant_price_workflow`. Recorded rollback is
blue `20261110_135430`. The old feature20c/recovery5b2 artifacts passed their own
CI but are superseded because production advanced during that run. Do not activate
them against the new baseline. Freeze fresh artifacts for initial GREEN ->
compatibility BLUE -> HR GREEN. Neither candidate was deployed by this task.
People/platform owner: Dilmurod; technical review: Mirshoir; operator/QA-master
acceptance remains separate.

All latest deployed pricing eligibility, shared fabric price, public order number
and reviewed retirement semantics are preserved. The recovery's 520 runtime
Python files are pinned to SHA-256
`03f9fc7145eb6ec52a6cbe332d870ed2683edcf678e10e4ba67fdbddb5f0ac13`.

The deployed application and existing pricing behavior are preserved, with one
explicit reviewed runtime compatibility adjustment: catalogue import accepts
exactly one of `0156_variant_price_workflow` or `0157_pricing_gate_live_merge`.
Old/gate-only/unknown/empty/multiple heads refuse with 409. All Finance permissions,
baseline matching, price rules, outer transaction, locks and audit logic remain
unchanged. Seven real PostgreSQL guard cases supplement the original two import
atomicity/race cases. No catalogue import is run against production by preparation.

Identical frozen migration `0156_gate_live_integration` and metadata-only merge
`0157_pricing_gate_live_merge` let the real image CMD migrate/verify the target
head. No live routes, worker, frontend controls or application HR mappings are
added to recovery. Management must stay disabled. Existing 0156 images are not
restart-safe substitutes on the new head.

The test-only HR storage contract activates only when all three live tables and
binding.mode remain unmapped; partial mapping refuses and the full feature gets
no supplement. Runtime and both migration hashes are pinned. Expected PostgreSQL
objects come from frozen migration definitions in one generated temporary schema,
not from the database under test. Only expected objects are created; references
use the already-owned test schema. A savepoint removes expected objects on pass
or refusal. Columns/defaults/timezones/generated/identity, constraints and their
timing/validation, all indexes/options, table flags/triggers/policies and all three
widened mode checks are exact. The original shared 94-entry drift baseline stays
unchanged. Frozen index names are preserved on temporary clones rather than
loosening actual-name comparison.

Local storage/bootstrap/import verification passed 66 cases; 17 tests for other
historical recovery shapes are explicitly inapplicable/skipped. All 28 new HR
contract cases, including 22 storage faults and namespace/source/mapping guards,
ran without skips. Initial failures from the temporary clone's regenerated index
name are retained. The mandatory no-skip PostgreSQL gate now requires 684 cases,
including those 28 recovery cases, nine import and four latest pricing-scope cases. Full exact-commit CI and
immutable image results remain recorded in `outputs/hr-deployment/` and workflow
receipts, not inferred from these local numbers.

The release workflow runs `scripts/test_rollback_image_schema_0157.py` against the
exact published backend digest and source SHA before reporting artifacts ready.
Its real default CMD, strict production settings, disabled startup seeding/schema
bootstrap, two fresh workers, one killed/replaced child, complete container restart,
shared counters, health/readiness and complete database fingerprints must pass.
Synthetic saved pricing approval, staff and retained disabled live configuration/
queued observation must survive. Sales, Models and Pricing GETs stay available;
live management routes must be absent. No host port, mounted source or factory
endpoint is used.

Before promotion, require fresh baseline/source/image review, exact-source full CI,
mandatory PG, security scans and this immutable-image rehearsal. Follow only
`DEPLOYMENT.md`, including protected disk retention, backup/migration, both-host
leases, staging/read-only QA/performance gates, four health checks, observation and
rollback-field compare-and-set. Both current disks are 78%, exceeding the 70% alert and
must be rechecked before staging. Do not stamp/downgrade production to make an
old image start or replace a serving image in place. Publishing this artifact
does not approve production activation, device writes or old-ERP handover.
