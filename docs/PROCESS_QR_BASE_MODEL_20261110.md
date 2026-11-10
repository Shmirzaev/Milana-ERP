# Process QR base-model operations

Owner request: permanently load the model's paid operations instead of the
selected variant's list, then deploy promptly. Owner accepted verified live
20261109_163130 as the source baseline. Catalog owner Ismail/reviewer Mirshoir
remain the human assignments; implementation is by root Codex with independent
Codex review. No human engineering/production acceptance is inferred.

## Scope and contract

Process QR opts in to existing model GET with
`paid_operations_from_model=true` in both standard and Usluga catalogs. The
service projects only paid operations from the exact same catalog/factory
family's base row. Canonical catalog identity and existing latest-base
representative semantics apply. Empty or missing base operations become an
explicit empty list; no-base families and legacy imports retain their own list.
General model GET, model editing, variant identity/pictures/sizes/BOM, operation
rates/order/factory filters, issued QR and payroll snapshots retain their paths.

This read adds no database write, new permission, enum, table, migration or
business row. The query control is boolean; model/factory names remain existing
configurable data and operation JSON retains its established contract. The
indexed PostgreSQL family path avoids approval/write locks. Existing family-save
writes remain unchanged, including their historical catalog-wide family semantics;
this narrow read fix does not claim to resolve broader write-scope risks.

The final implementation reuses the transaction-scoped family identity metadata
already resolved for the garment picture, then reads only the selected base's
details. It retains Catalog's own base classifier, including older orphaned
variant fields; photo selection itself is unchanged. Both metadata caches clear
on flush and transaction change. Opt-in serialization skips the discarded variant
details and copies the final projection once. Earlier full-family JSON hydration
was rejected after read-only diagnostics showed avoidable latency. Diagnostics
of the optimized path found approximately 0.7 ms/2.0 ms direct-service median
overhead on the reported/larger selected families. The final staged HTTP epoch
passed every original budget. No serving source was edited for those diagnostics.

Frontend family cache invalidation covers the opt-in URL. Model/catalog context
guards hide old operations during loading and reject stale/late saves. The loaded
message names the business model; the selected variant remains label/order identity.
CleanUI and Uncodixfy guidance preserve the current layout.

## Deployed identity and source

Both hosts serve blue `20261110_070607`, application
`843adaf3bda1b1f2d234e68b6763bbc649d3b72a`, source manifest
`7bf0a59c139cf8a46fc6af7a3a0c5457795ba7b1de7fe57e70c76b31481fac32`.
Rollback is the healthy retained green `20261109_163130` / application
`271c5005e12d1efc65d6358756862d8c243685a5`. Schema remains
`0155_eco_gate_merge`. No migration or deployment business-data write ran.

Immutable published image digests:

- Backend: `sha256:23ba242423dcbbc5f7ab88e9d8c8aef9553126a5a12fb5eaff6a335c75a5b7f6`.
- Frontend: `sha256:fde260ff20f6aedfef3f2bff6f91927e6b1504621d30274279cc6776229fbd92`.

Source worktree is `C:/ERP/.codex-work/process-qr-base-model-20261110`, branch
`codex/process-qr-base-model-20261110`. Metadata commits do not change these
deployed application/image identities. The legacy checkout was preserved.

## Actual verification

[Exact-source CI 42773355314](https://github.com/Shmirzaev/Milana-ERP/actions/runs/42773355314)
passed all jobs, including frontend lint, strict types, contracts/build, security
scan, exact scanned-image publication, 6,666 backend tests / 1,569 skips /
36 subtests, and mandatory PostgreSQL 207 passed. Full-suite time was 20:27;
mandatory PostgreSQL time was 2:24. The new real-PG test proves 25 exact-family
reads, constant query count, read-only transaction and full model-table fingerprint
conservation. Local focused checks passed 29 with one local-PG skip; local full
suite environment/collection failures remain historical, not the final Linux CI.
Ruff/compilation, Process QR ordering/batch/size/manual/factory/label-identity and
family-save/stale-catalog contracts passed. Independent Codex runtime review passed.

Actual Edge staging and public QA used normal user sign-in. PO-0720 retained
BJ5039-V-6795 identity, pictures, two Nastils and six first-batch sizes of 50;
paid operations auto-loaded from BJ5039, with 20 rows after expansion and explicit
Load model reload. Both Nastils retained 120 issued labels each. No save, issue or
print action ran. Captured console warnings/errors were empty. Four selected model
rows and all 240 selected issued-label rows had identical full SQL fingerprints
before and after API and public browser checks. A divergent real family verified
all 117 operations came from its base while default GET and variant details stayed
unchanged. No production test records were created.

Backend activated before frontend. All four supported health endpoints, readiness,
strict schema/workers/seed settings, full 2,455-file source manifests, exact active
and rollback images, routers, database/index/headroom and formal closing passed.
The full high-risk observer ran 1,800.16 seconds after cutover, 07:59:57.925 to
08:29:58 UTC, with 61 ticks / 244 HTTP 200 results, no failures or gaps and identical
runtime identities before/after. Fresh post-observer checks also passed.

Fresh verified backup before startup:
`/app/storage/.milana-backup-archive/milana_erp_pre_20261110_070607_20261110_074351.dump`,
118,102,830 bytes, mode 0600, 1,395 restore objects, SHA-256
`754966285bba0c59d24ffc070906d5b8a57fd4eb346e51028b16ecdcd1f89e32`.
Image cleanup removed eight exact reviewed unused images and did not delete
source directories, containers, volumes, business records or backups. Temporary
preview processes were stopped by exact owned PID/creation/command checks and all
three local ports were verified free. The live Process QR page was left open.

## Performance evidence and exact owner exceptions

The original SSH transport failure and cold staged p95 failure are retained.
Review found the staged harness warmed only the old slot. One explicitly reviewed
correction retained 96 symmetric warm-up calls, then all original 20 measured
samples per slot/path. Its six paths passed unchanged median +10%, p95 +15% and
payload +15% caps; all full response facts matched the authorized projection.

The single public postflight epoch failed two p95 caps. Access-log correlation
ruled out the later owned browser navigation as their cause; no cause or harmless
noise is claimed and no public rerun occurred. All public medians, payloads,
complete facts and the other four paths passed.

| Public lookup | Baseline p95 | Candidate p95 | Change | Outcome |
| --- | ---: | ---: | ---: | --- |
| BJ5039 generic detail | 30.77 ms | 68.34 ms | +122.13% | Owner accepted exact exception |
| Larger model base-operation lookup | 42.54 ms | 49.90 ms | +17.30% | Owner accepted exact exception |

After full observation and all other checks passed, the user explicitly answered:
"Keep release; accept only these two p95 exceptions (Recommended)". This authorizes
only those two results for this release. Original failed measurements and +15%
limits remain unchanged; no other or future gate was waived. Independent review
approved the transparent acceptance wrapper and postflight gate before formal
closing. Human engineering/production acceptance is not inferred.

## Evidence and remaining ownership

Local evidence is under
`C:/ERP/.codex-work/process-qr-deploy-20261110/.qa-process-qr-deploy/release-20261110_070607`.
It includes the immutable artifacts, exact-source CI, backup, browser DOM/screenshots,
frozen full facts, failed and passing epochs, owner decision, observation and the
append-only phase/owned-lease journal. Important evidence hashes:

- Original failed public report: `23f8d02c3aefd8a6e853872543df8d563ff00be5efa96f7dc9249033c1b0d980`.
- Owner's two-exception record: `0b503bdd618cb14bad9f141a4d328db3b1ef2716fc0210eaee7a7661fa697354`.
- Bound observation: `42397011101c9813b9ffe096b70a5babff9e1303f4863bf9f99f32176e12febc`.
- Approved postflight gate: `5f6e0fd7cde36ba79bc79f779c3ddcb55cc2d05bd669abdae2b130a1e1d4bb85`.

Disk remains above the 70% alert (about 79.23% backend / 79.51% frontend), below
the 80% staging stop; routine protected retention remains operational follow-up.
Existing broader family-save write-scope/security risks were not changed.

Status: **AI_VERIFIED_AWAITING_HUMAN**. AI verification is recorded separately
from human acceptance. Human checklist:

- [ ] Ismail/Mirshoir engineering acceptance.
- [ ] Operator acceptance of the base-model template workflow on normal work.

Earlier candidate `88d15d053` / CI `42770915197` and release identifier
`20261110_064423` were superseded before deployment and are not reused. The separate
BJ5039 configuration repair remains historical evidence; this release adds no backfill.
