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

Before work, verify both application VMs:

```sh
active="$(readlink -f /opt/milana-erp/current)"
cd "$active"
sha256sum -c SOURCE_MANIFEST.sha256
sha256sum SOURCE_MANIFEST.sha256
```

Both VMs must name the same release and manifest. If either differs from `deploy/production-base.json`, stop and create a new clean baseline from the exact active source archive. Preserve the legacy dirty checkout and port reviewed changes individually; never merge it wholesale.

## Make a change

1. Fetch and create a clean worktree from the latest production baseline:

   ```sh
   git fetch origin
   git worktree add ../milana-change -b codex/<short-name> <production-baseline-commit>
   cd ../milana-change
   git status --short
   ```

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
6. Commit, push a change branch, and merge only after CI passes. Never copy uncommitted files directly to production.

## Build immutable artifacts

Run `.github/workflows/ci.yml` with **Run workflow** and provide:

- `release_id`: unique UTC `YYYYMMDD_HHMMSS`;
- `production_base_release`: currently active release;
- `production_base_manifest`: SHA-256 of its `SOURCE_MANIFEST.sha256`.

The workflow validates backend/frontend, verifies the production base, packages deterministic source, builds both images once outside production, pushes release-tagged images to GHCR, and retains the source/evidence artifact.

Docker Buildx imports and exports separate backend/frontend layer caches. A cache
miss uses a normal build. Dependency-file changes invalidate their install layers;
source changes invalidate dependent layers. The frontend `builder` stage explicitly
disables cache reuse, so every release compiles the checked-out application even
when its dependency layer is reused. Both builds still pull base images, and all
local/CI validation and production gates remain required. The first cache export
may add time; later releases can reuse those layers.

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
artifact. The observer records this identity; HTTP health checks alone do not
independently prove which release is serving traffic.

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
