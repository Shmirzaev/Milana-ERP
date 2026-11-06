# Degraded incident recovery for the 6 November release

The owner authorized deployment of the combined passport/floor repairs. Independent
review found that the previous488 application must not remain a writable rollback
after grouped passport allocations, persisted Cutting rejections or ECO consumption
exist. This dedicated recovery branch starts from exact live
`488f3d654b0669a9878b8efd3d34298994e9dc45`, release `20261105_065721`, manifest
`e6c603d4c1954c64a75962cf189427eb5e316c039ea23de4699b9bd4f3112095`.
Both production hosts were freshly verified by the deployment coordinator before
this branch was created; updating inherited production-base metadata is authorized.
Worktree `C:/ERP/.codex-work/rollback-readonly-20261106`, branch
`codex/rollback-readonly-20261106`. Codex qa_environment implements; independent
reviewer Codex passport_review. This work does not stage or activate production.

## One operation: inspect safely during incident recovery

`INCIDENT_READ_ONLY=true` is an explicit opt-in, defaultfalse. Middleware refuses
every method except GET/HEAD/OPTIONS with503, apart from exactly enumerated normal
auth/session login, JSON login, logout and auth/token POST endpoints. Factory switch,
credentials/profile changes, uploads, business mutations and unknown verbs refuse.
The old GET packages list is also disabled because it generates QR files and commits.
Login and auth/session me omit their legacy timestamp writes. Existing permissions,
selected-factory authorization, session cookies and external auth rate limits remain.

The application PostgreSQL engine defaults every connection to read-only and sets
each transaction READ ONLY, covering normal sessions and hidden/raw SQL GET writes.
PostgreSQL25006 is mapped to503. Startup fails if schema sync or seed is enabled;
unsupported non-PostgreSQL engines refuse rather than silently losing enforcement.
No new business state, DTO, schema, migration or persistence operation is introduced.
The switch is a typed boolean deployment setting; HTTP verbs and exception SQLSTATE
are infrastructure protocols, not new business enums. Existing domain writers and
table/type adoption remain outside this narrow incident containment operation.

This is a **degraded read-only rollback**, not feature-compatible writable recovery.
Old screens may omit grouped allocations, pictures, rejection controls or ECO facts,
show old report totals, or return503 when a legacy read attempts a write. All database
business mutation is unavailable. Shared-store auth counters and normal file reads
remain; the identified packages QR-writing GET is unavailable. Restore service using
the compatible current application or a reviewed forward fix before enabling writes.

## Required artifact and recovery controls

Build release `20261106_050850` from the exact reviewed commit with ci.yml. Retain its
source archive, metadata, manifest, backend/frontend image digests and verification
evidence before candidate cutover. The previous plain488 image is not a safe writable
rollback after the new release begins accepting business writes.

The image's safe default remainsfalse. The recovery operator must explicitly set
`INCIDENT_READ_ONLY=true`, `STARTUP_SCHEMA_SYNC=false`, `RUN_SEED_ON_STARTUP=false`
**before starting its backend container**, and verify those exact non-secret values.
Current slotctl uses shared/backend.env; it does not support a per-slot switch. Do
not infer the flag from the image tag, stage an unfenced instance, or alter the
active candidate's environment. The deployment coordinator owns an exact reviewed
recovery recipe to enable the flag before staging the retained backend into the
inactive recovery slot, then probe it before any traffic switch. No activation is
performed by this branch or by its CI artifact workflow.

Before cutover, the deployment coordinator must smoke the retained exact backend
digest on a third loopback-only18003 instance, explicitly forcing the read-only
flag and disabling seed/schema sync while retaining its default startup command.
Verify the environment, health/ready,503 probes and application-engine SHOW values,
then stop that instance before candidate performance measurements. This probe does
not activate recovery. After cutover, any recovery must recreate the inactive slot
from the compatible fenced digest before activation; never route to the plain488
container merely because it is retained.

Before any recovery activation, verify the exact OCI revision/digests and environment,
PostgreSQL `SHOW default_transaction_read_only` and `SHOW transaction_read_only` both
on using the application's engine, health/readiness, login/me/logout, a normal
authorized read, a deliberately refused business command503 and packages GET503.
Verify `X-ERP-Read-Only:true`; preserve before/after business snapshots. Existing
DEPLOYMENT.md health/backup/source/rollback gates remain; the owner waived only the
30-minute observation window, not compatibility or health checks.

## Evidence and remaining gate

Targeted mode/auth/config/startup tests45passed. Actual PostgreSQL gate uses a unique
schema in a disposable loopback QA database, distinct-source100+200 grouped JSON,
an independent no-execution rejected order, and an ECO physical debit. It reads the
actual grouped passport, checks persisted allocations, attempts old mutation paths,
repeats raw SQL write refusals after commit, and exercises a hidden GET writer. It
compares13 business/auth/evidence tables before/after and requires no changes.
Ruff, compile and whitespace checks pass. The CI workflow explicitly repeats the
required PostgreSQL gate; full existing backend/frontend gates run for the exact
artifact commit. Final result/commit and CI evidence are recorded by the coordinator.

Initial PG fixture used a duplicate allocation source and put rejected state on an
already-executed order; independent review required representative separate facts.
Those fixture-only defects were corrected before final rehearsal. The first richer
fixture omitted StockMovement.item_id and rolled back setup; adding the required
reference corrected the harness. A subsequent grouped-detail read exposed missing
default material fields in the hand-built test JSON; using the canonical stored
material defaults corrected that fixture. These failures touched no production data.
Actual old-frontend visual rehearsal and final immutable-image probes remain required
deployment-coordinator evidence; do not label them passed from backend tests alone.
