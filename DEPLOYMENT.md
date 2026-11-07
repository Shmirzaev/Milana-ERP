# Milana ERP Production Deployment Rule

This is the only supported production deployment process. Production changes are promoted from a clean Git commit as immutable source plus backend/frontend images. Production VMs do not install dependencies or build the application.

## Production topology

- Public domain: `https://erp.milanapremium.uz`
- PostgreSQL VM: `172.16.10.3`
- Backend VM: `172.16.10.4`; stable port `8000`
- Frontend VM: `172.16.10.5`; stable port `3000`
- Backend slots: loopback `18001` (blue), `18002` (green)
- Frontend slots: loopback `13001` (blue), `13002` (green)
- Stable-port service on each application VM: `milana-router`
- Releases: `/opt/milana-erp/releases/<release_id>`
- Current source: `/opt/milana-erp/current`
- Runtime slot state: `/opt/milana-erp/runtime/slots.json`
- Backend environment: `/opt/milana-erp/shared/backend.env`
- Persistent storage: host `/app/storage`, mounted at `/app/storage`

Nginx Proxy Manager continues routing the public domain to stable ports. It does not change during a normal blue-green release.

## Absolute rules

1. Never deploy from a dirty worktree, `C:\ERP`, an old release, or unreconciled GitHub `main`.
2. Every change begins from the latest exact production-baseline commit.
3. Never run `npm ci`, `next build`, `pip install`, or `docker build` on a serving production VM.
4. Never edit `current`, a retained release, a running container, or `.next` in place.
5. Never switch traffic before tests, backup/migration, health, warm-up, signed read-only QA, and the performance gate pass.
6. Keep the previous slot live for the observation window.
7. Slot ports remain loopback-only.
8. Never expose or print secrets.
9. A base-manifest mismatch, result-count change, median regression above 10%, p95 regression above 15%, or payload growth above 15% is an automatic stop.
10. Keep active, rollback, and at least three additional releases.

## Source of truth

The deployable branch must descend from the latest clean production baseline recorded in `deploy/production-base.json`.

The owner-confirmed production/integration branch is `clone_main`. Its current head
can contain work not yet deployed; verify the exact reviewed candidate and active
release separately. Use the shared-branch coordination rule in `AGENTS.md`. Never
release unreviewed pending changes merely because they are on this branch.

Before work, verify both application VMs:

```sh
active="$(readlink -f /opt/milana-erp/current)"
cd "$active"
sha256sum -c SOURCE_MANIFEST.sha256
sha256sum SOURCE_MANIFEST.sha256
```

Both VMs must name the same release and manifest. If either differs from `deploy/production-base.json`, stop and create a new clean baseline from the exact active source archive. Preserve the legacy dirty checkout and port reviewed changes individually; never merge it wholesale.

## Make a change

1. Fetch and use a separate clean working directory for the exact reviewed
   `clone_main` lineage, reconciled with the production baseline. Never share one
   writable checkout between engineers/agents. The team currently uses one shared
   integration line with serialized landing; a short-lived task branch/worktree is
   an alternative only when accepted by the team. Continue an existing isolated
   task worktree when appropriate. Reconcile the full candidate diff with active
   production before preparing a release.

2. Read `AGENTS.md` and relevant `docs/PROJECT_CONTEXT.md` sections.
3. Make one scoped change with workflow and authorization regression tests.
4. Run all local gates:

   ```sh
   cd backend
   python -m ruff check app
   python -m compileall -q app scripts
   python -m pytest -q

   cd ../frontend
   npm ci --legacy-peer-deps
   npm run lint
   npm run typecheck:strict
   npm run build
   ```

5. Review `git diff --check`, the complete baseline diff, and all previously deployed performance contracts.
6. Review and test the exact change, then land into `clone_main` through the single
   integration queue when authorized. Re-fetch and rerun affected checks if another
   change landed first. Require passing CI for the exact release candidate before
   promotion; never copy uncommitted files directly to production. Both `main`
   and `clone_main` pushes now trigger validation. Verify the actual run's source
   SHA and result; a successful push is not a successful validation or deployment.

## Reduce elapsed time without removing gates

Use this order for every release:

1. **Preflight early.** Reconcile both live releases/manifests with the recorded
   production baseline before coding or building. Check disk space, registry
   access and rollback compatibility immediately. Resolve the 70% disk alert
   through the protected retention procedure before staging reaches its 80% stop.
   Keep routine retention outside the release's critical path. Never blanket-prune
   Docker on these shared hosts or remove active/rollback images and backups.
2. **Find affected failures first.** Run changed-workflow, authorization and real
   PostgreSQL migration/concurrency/query-budget checks before the long full
   regression suite. Keep every required suite; an early pass does not replace it.
   Preserve failure evidence and fix the cause before starting another full run.
3. **Overlap independent checks.** Backend and frontend validation may run at the
   same time on isolated runners. PostgreSQL jobs need their own databases and
   fixture state. Do not run concurrent writers against a shared test database.
4. **Freeze one candidate.** Record the exact source SHA, build configuration,
   base release/manifest and all gate results. Reuse valid evidence for that same
   candidate; rerun checks invalidated by source, configuration, baseline or
   environment changes. Never substitute a parent commit's green run. The manual
   artifact workflow still runs every gate encoded in its job dependencies.
5. **Build once, promote the scanned images.** Use the exact cached immutable
   images from the required security scan. The release job verifies their source
   SHA and image IDs, then publishes those same images. Do not rebuild between
   scanning and publication or on a serving VM.
6. **Prepare both hosts concurrently.** After artifact verification and exclusive
   deployment ownership, source transfer/verification and image pulls on separate
   hosts may overlap. Keep backup completion before migration, successful migration
   before candidate startup/QA, and every candidate gate before activation.
   Activate backend first, verify it, then activate frontend.
7. **Report each milestone promptly.** Record timestamps for preflight, validation,
   artifacts ready, staging, QA, activation and observation completion. Report
   Live after immediate postflight passes while continuing the required observer.
   Observation is a separate phase, not additional application downtime. A waiver
   applies only when the user explicitly grants it for that deployment.

The 6 November release took 33m17s to artifacts ready: its backend job took
26m53s, and image publication followed for 6m16s. Frontend validation ran alongside
backend and finished in 4m34s. Failed earlier candidates and runtime/recovery/disk
preparation added elapsed time; use these measurements to prioritize improvements,
not as a guaranteed deployment duration.

Collect slow-test timings with `pytest --durations=25` and retain the report.
Splitting the backend suite into balanced jobs is a separately tested CI tooling
follow-up: this document does not install sharding or authorize skipping tests.

## Build immutable artifacts

Run `.github/workflows/ci.yml` with **Run workflow** and provide:

- `release_id`: unique UTC `YYYYMMDD_HHMMSS`;
- `production_base_release`: currently active release;
- `production_base_manifest`: SHA-256 of its `SOURCE_MANIFEST.sha256`.

The workflow validates backend/frontend, verifies the production base, packages deterministic source, builds both images once outside production, pushes release-tagged images to GHCR, and retains the source/evidence artifact.

The security workflow builds and scans both images, including the dependency
lockfiles, before handing exact image identities to the manual release job.
Docker Buildx imports and exports separate backend/frontend layer caches. A cache
miss uses a normal build. Dependency-file changes invalidate their install layers;
source changes invalidate dependent layers. Verify the scanned image's source
revision and effective build arguments; cache reuse must not substitute another
candidate's frontend/API configuration. Both builds still pull base images, and all
local/CI validation and production gates remain required. The first cache export
may add time; later releases can reuse those layers.

The frontend Dockerfile uses the repository root as its build context
(`docker build -f frontend/Dockerfile .`). Its builder includes backend application
source for cross-layer contract checks in `npm run build`; the runtime stage
contains only the frontend standalone output and assets. Do not narrow the build
context to `frontend/` or skip these contract checks.

The workflow summary reports **Artifacts ready**, the exact source commit and
manifest, and both image digests. This means the candidate is built, not live.
Use the recorded digests to identify the reviewed images; never substitute an
older release or rebuild on a production VM to save time.

Production only pulls these images:

```sh
docker pull ghcr.io/shmirzaev/milana-erp-backend:<release_id>
docker pull ghcr.io/shmirzaev/milana-erp-frontend:<release_id>
docker image inspect ghcr.io/shmirzaev/milana-erp-backend:<release_id>
docker image inspect ghcr.io/shmirzaev/milana-erp-frontend:<release_id>
```

Never rebuild a release on a production VM.

## Stage source, backup, and migration

Verify the downloaded archive hash, extract the same archive on both VMs under `/opt/milana-erp/releases/<release_id>`, then run:

```sh
cd /opt/milana-erp/releases/<release_id>
sha256sum -c SOURCE_MANIFEST.sha256
```

Create a unique PostgreSQL custom-format backup without printing `DATABASE_URL`. Requirements:

- non-empty mode-`0600` dump;
- successful `pg_restore --list`;
- more than 100 restore objects;
- recorded dump/restore-list sizes and SHA-256 values.

Uploaded files are on the backend host's `/app/storage` bind mount, outside the
database dump. For an approved coordinated recovery point, quiesce database and
upload writes, take the dump and a snapshot/copy of the entire mount, then run
this on an isolated host with `pg_restore` and both copied artifacts. Create a
pairing manifest **outside** both artifacts:

```sh
python scripts/storage_recovery_manifest.py create \
  --database-dump <path-to-custom-format.dump> \
  --storage-root <path-to-storage-snapshot> \
  --output <path-to-pairing-manifest.json>
python scripts/storage_recovery_manifest.py verify \
  --manifest <path-to-pairing-manifest.json> \
  --database-dump <path-to-custom-format.dump> \
  --storage-root <path-to-storage-snapshot>
```

The verifier reads the supplied artifacts only. It checks the dump hash,
every storage file hash, missing/extra files, and known database upload URLs
and stored filenames using local `pg_restore`; it does not connect to a
database. A nonzero result blocks use of the pair (1 is a mismatch; 2 is
invalid input or an unreadable artifact). Keep the mode-`0600` manifest
with the artifacts. A manifest cannot prove the dump and file snapshot were
captured at the same instant; record the quiesce interval and backup identities.
It does not replace an isolated restore drill or establish the zero-RPO target.

Before applying a new revision, prove the retained rollback backend can start
on the target schema with its actual image command and strict production settings.
Inspect the effective environment of every candidate and rollback backend: startup
seeding and schema bootstrap must be disabled. Updating the shared environment file
does not change an existing container's environment; recreate only the inactive slot.
Startup seeding can reset configured credentials or permissions even when no business
form is submitted. An omitted Docker image entrypoint is equivalent to a null default;
still verify the actual command and refuse overrides.
An additive table alone does not establish compatibility: the exact-head startup
verifier also runs on worker replacement. In isolated owned infrastructure, verify
two fresh workers, child replacement, full container restart, health and readiness.
If the old image rejects the new head, first build and test an immutable compatibility
image containing the exact old application plus the reviewed migration metadata.
Do not downgrade/stamp production or bypass startup/security checks to make it boot.

After the feature cutover and closing gates, a compatible previous application may
replace the inactive rollback slot. Hold owned deployment locks on both hosts,
retain the original state/resource evidence, and verify source manifests, exact
image digests/revisions, real default command, strict schema head, workers, zero
OOM/restarts and unchanged business ledger. Confirm actual proxy routing agrees
with active state before replacing any inactive container. Register the compatible
release through an atomic compare-and-set of only rollback fields using the
installed controller; leave active routing, source and container IDs unchanged.
Record each host's phase because cross-host writes are not globally atomic. Recovery
attempts each host independently, preserves all data and uses its inactive color;
never replace an active slot or relabel an old image as a different source commit.

Run candidate migrations before traffic switch:

```sh
docker run --rm \
  --env-file /opt/milana-erp/shared/backend.env \
  -v /app/storage:/app/storage \
  ghcr.io/shmirzaev/milana-erp-backend:<release_id> \
  sh -c 'PYTHONPATH=/app:/app/backend alembic -c /app/alembic.ini upgrade head'

docker run --rm \
  --env-file /opt/milana-erp/shared/backend.env \
  -v /app/storage:/app/storage \
  ghcr.io/shmirzaev/milana-erp-backend:<release_id> \
  sh -c 'PYTHONPATH=/app:/app/backend alembic -c /app/alembic.ini current'
```

Prefer forward-compatible migrations. Application rollback does not downgrade the database.

## Stage inactive slots

On the backend VM, install the reviewed slot manager from the extracted release
before staging. The shared copy is not updated by extracting source:

```sh
sudo install -m 0644 /opt/milana-erp/releases/<release_id>/deploy/slotctl.py /opt/milana-erp/shared/deploy/slotctl.py
cmp /opt/milana-erp/releases/<release_id>/deploy/slotctl.py /opt/milana-erp/shared/deploy/slotctl.py
```

Read slot state:

```sh
sudo python /opt/milana-erp/shared/deploy/slotctl.py status
```

Choose the inactive slot, then on the backend VM:

```sh
sudo python /opt/milana-erp/shared/deploy/slotctl.py stage \
  --role backend --slot <inactive-slot> --release <release_id> \
  --image ghcr.io/shmirzaev/milana-erp-backend:<release_id>
```

On the frontend VM:

```sh
sudo python /opt/milana-erp/shared/deploy/slotctl.py stage \
  --role frontend --slot <inactive-slot> --release <release_id> \
  --image ghcr.io/shmirzaev/milana-erp-frontend:<release_id>
```

The manager binds loopback-only candidates, refuses to replace the active slot, waits for health, and warms routes. Backend slots use two workers and an 8+4 pool per worker, keeping overlap below the 100-connection PostgreSQL ceiling.
For the backend, `slotctl.py` also passes the staged release ID to the container as `RELEASE_ID`; `/health` and `/ready` report it as `release`. Use the ID from the reviewed release manifest when staging, and compare the stable endpoint's reported value after switching traffic. A backend started without this variable reports `unknown`.

## Performance and functional gate

Benchmark active and candidate backend slots:

```sh
sudo python /opt/milana-erp/shared/deploy/slotctl.py benchmark \
  --slot <active-slot> --output /tmp/erp-active.json
sudo python /opt/milana-erp/shared/deploy/slotctl.py benchmark \
  --slot <inactive-slot> --output /tmp/erp-candidate.json

python /opt/milana-erp/releases/<release_id>/scripts/compare_performance.py \
  /tmp/erp-active.json /tmp/erp-candidate.json
```

The gate requires identical result rows and bounded median, p95, and payload changes. Also complete signed-in read-only browser QA for each changed workflow and require zero console errors.

## Activate

Immediately before activation, fetch GitHub again and recheck both active source
manifests and slot states against the baseline used for this candidate. If another
PC/task has changed production or introduced unreviewed changes on `main`, stop
and reconcile before proceeding. Review candidate additions, modifications and
deletions against active production; a passing cached build does not prove that
another PC's work was included. Work from every PC must be committed, pushed and
reconciled into the reviewed candidate. Do not overlap production deployments or
replace a rollback slot while another release is still under observation.

Switch backend first:

```sh
sudo python /opt/milana-erp/shared/deploy/slotctl.py activate \
  --role backend --slot <inactive-slot> --release <release_id>
```

After stable backend health succeeds, switch frontend:

```sh
sudo python /opt/milana-erp/shared/deploy/slotctl.py activate \
  --role frontend --slot <inactive-slot> --release <release_id>
```

Activation validates HAProxy and performs a graceful reload: existing connections finish while new traffic reaches the warmed candidate. Then update `current` on both VMs:

```sh
ln -sfn /opt/milana-erp/releases/<release_id> /opt/milana-erp/current
```

## Required postflight

```sh
curl --fail http://172.16.10.4:8000/health
curl --fail --head http://172.16.10.5:3000/login
curl --fail https://erp.milanapremium.uz/health
curl --fail --head https://erp.milanapremium.uz/login
```

Also verify:

- both symlinks and slot states name the same release;
- `milana-router` is active and HAProxy validates;
- backend has exactly two workers, zero restarts/OOM, and clean logs;
- PostgreSQL has headroom and zero invalid indexes;
- result counts, ordering, permissions, and business actions match;
- changed-workflow signed browser QA passes;
- public post-cutover benchmark stays within budget.

Choose and record the observation window before cutover, using the complete
candidate-versus-production diff (including changes from other PCs):

| Risk | Minimum observation | Criteria |
| --- | --- | --- |
| Low | 10 minutes | Small, isolated changes such as display wording or presentation, with no effect on data, authorization or workflow behavior. Record why the complete change is low risk. |
| High or uncertain | 30 minutes | Any database/schema/data operation, permission or authentication change, inventory/stock behavior, payroll calculation or scan behavior, or major workflow change. Mixed or uncertain changes use this window. |

Keep the previous slot live throughout either window and retain its release/image
for rollback afterward. The shorter window changes only post-cutover observation;
source reconciliation, all tests, backup/migration, candidate QA, performance and
health gates remain required. It cannot be used to bypass unfinished checks.

### Automatic health observation

After immediate postflight passes, run the observer from the clean deployment
worktree on a machine that can reach both internal VMs and the public domain:

```sh
python scripts/observe_release.py \
  --release <active-release> --commit <full-reviewed-git-sha> \
  --risk low --reason "Reviewed isolated display change; no data, permission or workflow effect" \
  --output outputs/deployment/<active-release>-observation.json
```

For high or uncertain risk, use `--risk high` (the default); record the affected
area in `--reason`. There is no arbitrary duration override. Before starting,
verify that the supplied identity matches both active slot states and the reviewed
artifact. Compare the `release` field from internal and public `/health` with that
identity: the observer records the supplied ID but checks HTTP status only.

The observer automatically checks all four required endpoints every 30 seconds
using GET/HEAD only, records evidence, and reports start, failures and finish.
Run it as a tracked background process during the deployment task so the user
does not need to poll. Continue following that process through closing checks;
do not abandon it when reporting Live. A failed probe stays a failure even if
later probes recover; interruption or missed monitoring intervals cannot pass.
Do not overwrite an earlier evidence file: investigate a failed/interrupted run
and use a new evidence filename for a reviewed retry.

Exit code zero means **health checks passed, closing checks still required**.
After it finishes, repeat the runtime, slot/release, log, database and performance
checks listed above. Report Observation complete only when these also pass. The
observer never activates, rolls back, cleans up, or changes business data.

### Report deployment progress

Report these milestones separately, with the release and source commit:

1. **Artifacts ready — activation pending:** GitHub validation, image publication
   and source artifact upload passed. Production has not switched.
2. **Live — observation in progress:** both roles have switched, both symlinks and
   slot states agree, and every immediate postflight check above passed. Tell the
   user that the update is usable, give the observation end time, and keep the
   rollback release live. Continue monitoring; this is not task completion.
3. **Observation complete:** after the full reviewed 10- or 30-minute window, health monitoring
   and closing runtime/performance checks passed. Record the evidence and finish
   the deployment handoff. If a check fails, report that failure and follow the
   rollback procedure as appropriate; never report success just because time elapsed.

These are reporting milestones only. They do not shorten the selected window, waive a
gate, authorize another deployment, or permit early rollback-slot cleanup.

## Rollback

Read rollback slot/release from `slots.json`, activate backend rollback first and frontend second, repoint both `current` symlinks, and rerun every health check:

```sh
sudo python /opt/milana-erp/shared/deploy/slotctl.py activate \
  --role backend --slot <rollback-slot> --release <rollback-release>
sudo python /opt/milana-erp/shared/deploy/slotctl.py activate \
  --role frontend --slot <rollback-slot> --release <rollback-release>
```

Do not downgrade the database without an explicit reviewed procedure and verified backup.

## Retention and disk safety

Dry-run first on each VM:

```sh
python /opt/milana-erp/current/scripts/release_retention.py
```

The tool verifies manifests, archives source, protects active/rollback/recent releases, and skips anything unsafe. Cleanup requires both `--apply` and the exact hostname from dry-run:

```sh
sudo python /opt/milana-erp/current/scripts/release_retention.py \
  --apply --confirm-host <exact-hostname>
```

Never glob-delete releases. Alert at 70% disk and block staging at 80%.

## One-time blue-green bootstrap

Once per VM:

1. install the distribution HAProxy package;
2. copy `deploy/slotctl.py` to `/opt/milana-erp/shared/deploy/slotctl.py`;
3. stage the current/new release in blue;
4. verify, warm, and benchmark it;
5. run `install-router --stop-legacy` for the VM role;
6. immediately run internal/public health and signed read-only checks;
7. retain legacy service/image until bootstrap verification finishes.

The one-time bootstrap has a short stable-port handoff because legacy processes own ports 8000/3000. Future releases are graceful blue-green reloads.

## Completion record

After every deployment update `docs/PROJECT_CONTEXT.md` and its Obsidian mirror with active/rollback releases and slots, source/image hashes, database backup/revision, performance comparison, tests, browser checks, data touched, and unresolved risks.

Finally update `deploy/production-base.json` in Git to the newly verified active release so the next change cannot start from stale production source.
