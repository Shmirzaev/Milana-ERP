# HR schema-compatible recovery preparation — 11 November 2026

This is a recovery artifact candidate, not a feature landing or production change.
Do not merge it into the shared feature branch as a replacement application.

The isolated `codex/hr-schema-recovery-20261111` worktree starts at `c02f83ac0`,
which records active release `20261110_135430`, runtime
`cfe03885e03e4310e9b7c86ec9649ff350565d65` and source manifest
`1abc90b9e4b87f3e16ef0e255fe1829d15e9b510d6f61f1b2c030baf33fa89a3`.
Both host source manifests/slot states were read and matched before preparation.
The production baseline file is unchanged. Neither this branch nor the HR feature
has been deployed by this task. People/platform owner: Dilmurod; technical review:
Mirshoir; operator/QA-master acceptance remains separate.

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
name are retained. The mandatory no-skip PostgreSQL gate now requires 680 cases,
including those 28 recovery cases and nine import cases. Full exact-commit CI and
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
rollback-field compare-and-set. Current disk readings exceed the 70% alert and
must be rechecked before staging. Do not stamp/downgrade production to make an
old image start or replace a serving image in place. Publishing this artifact
does not approve production activation, device writes or old-ERP handover.
