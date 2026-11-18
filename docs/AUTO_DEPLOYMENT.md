# Automatic preparation and promotion

Owner-authorized design, 17 November 2026. Operational coordinator Dilmurod;
human reviewer Mirshoir per TEAM_OWNERSHIP.md. Codex implements the tooling;
independent AI review does not represent either person's approval.

## Installation status, 17 November

Reviewed tooling commit `76c49093d5fc1466399fc2654a03660480d0ff5f` is installed:
host helpers, QA gate, read-only probe, configurations and restricted sudo rules
on both VMs; fixed worker, observer and systemd service on backend. The installed
router/controller remains unchanged. A separately pinned adapter adds only the
backend `RELEASE_ID` argument after validating its complete Docker command.
The real service sandbox passed policy/token reads, both restricted SSH helpers,
Contents writes and commit-status writes. The isolated two-host preparation and
partial-cutover recovery rehearsal passed; its temporary services were removed.
The backend worker is enabled/active and the repository variable
`AUTO_RELEASE_BUILDS=true`. Production application remains `20261116_130518`.
See [installation evidence](archive/AUTO_DEPLOYMENT_IMPLEMENTATION_20261117.md).

## Daily use after installation

1. Start an isolated worktree from current `clone_main`, preserving the recorded
   production baseline. Commit and push a `codex/<task>` branch.
2. GitHub-hosted runners run the existing backend, PostgreSQL, frontend/browser
   and security gates. With `AUTO_RELEASE_BUILDS=true`, the same run publishes
   its already-scanned images and a checksummed source/identity artifact.
   Automatic IDs append the GitHub run and attempt to the UTC timestamp, avoiding
   collisions between simultaneous worktrees; legacy timestamp-only IDs still work.
3. The fixed worker on the **backend VM** polls GitHub. It accepts successful
   same-repository push runs by write/maintain/admin collaborators only; it never
   executes downloaded workflow/helper code. It validates the exact jobs,
   source/tree/archive/image identities, baseline and unchanged migration history.
   The worker installer pins the reviewed CI/scan/packaging recipes and security
   acceptance policy. A branch cannot replace those jobs with empty successes;
   changes to the pinned policy need administrator review and repinning.
4. It transfers source, validates a fresh PostgreSQL backup, stages inactive
   containers, warms them and runs the installed site QA/performance gates.
   Production keeps serving the current application.
5. Wait for **Milana / production: Technical candidate ready**. Perform the normal review
   and required QA-master acceptance, then merge into `clone_main`.
6. The worker checks the **entire merged Git tree** against the prepared tree,
   rechecks both live identities, activates backend then frontend and checks all
   four internal/public endpoints. The final switch targets seconds; this has
   not yet been measured on production. A merge that changes the tree requires
   a fresh combined candidate. Squash/rebase merges are supported by recording
   the accepted integration SHA separately from the immutable image's source SHA.
7. The update is usable while the worker observes for 30 minutes. After closing
   gates pass it commits the baseline, short project context and public release
   metadata to `clone_main` with a fast-forward-only compare-and-set. Health and
   raw QA/backup evidence stays in protected local journals. Sync that new
   integration head before starting the next change.

There is one prepared release at a time. A new push to its branch before merge
releases that candidate's reservation without touching active routing, then waits
for the newer build. A candidate/backup expires after one hour: recover its
reservation and push a new commit to build a fresh release. Keep observation and
source integration serialized. Do not run a legacy deployment while an automatic
reservation exists. This initial version does not automatically migrate schemas;
any migration-file change stops for DEPLOYMENT.md's reviewed recovery procedure.

## Why a fixed worker

This is a public repository. No general GitHub self-hosted runner is placed on
the production network. Hosted jobs cannot SSH into ERP. The worker runs installed,
root-owned Python code as `milana-deploy` with 256 MiB/25% CPU limits, downloads
data-only artifacts and uses a separate SSH key to fixed host helpers. There is
no dependency installation, image build or test suite execution on serving VMs.

The GitHub token is read from a mode-0600 credentials file and never written to
logs. Its repository-scoped permissions are Actions read, Contents read/write,
Commit statuses read/write and metadata needed to check collaborator permission.
Use a dedicated token/account or GitHub App installation token with that scope;
refresh/rotate it outside Git. Never reuse credentials pasted into old chats.
Artifact download verifies GitHub's SHA-256 and strips authentication when following
its HTTPS object-storage redirect. Source extraction rejects traversal, links,
duplicates, secrets, extra files and hash mismatches. Images are pulled by digest.

## One-time administrator installation

**Installed and enabled.** See the current status above before repeating
completed steps. Administrator access and the exact reviewed tooling commit are
required; the existing SSH account's Docker administrator access was used for
the recorded installation. The installer defaults to a dry-run and neither
starts the worker nor activates a release.

1. On both application VMs create a dedicated `milana-deploy` system account
   with an SSH login shell. On the backend also create its protected state and
   credentials directories under `/var/lib/milana-auto-release`. Provision a new
   SSH key, install its public key on both accounts (disable agent/port/X11
   forwarding), and pin both host keys in
   `/var/lib/milana-auto-release/credentials/known_hosts` (the explicit configured
   path). The hardened service hides `/home`; it does not use a home SSH directory.
   The backend worker must be able to SSH to its own backend host as well as the
   frontend. Do not give this account Docker-group membership or general sudo.
2. Install the existing Docker/HAProxy/controller prerequisites and PostgreSQL
   inspection tools. Pin a PostgreSQL client image matching the server major
   version in `backup_client_image`; the installed PostgreSQL 18 tools produced
   a backup that failed the PostgreSQL 16 restore rehearsal. Backups now run the
   pinned PostgreSQL 16 client without a host filesystem mount; its password is
   inherited by environment name. The native newer `pg_restore --list` only
   checks archive structure. Review and pin the installed controller and the
   narrow `auto_release_stage.py` adapter separately; preserve current routing.
3. Install each host's root-owned **site gate** executable and pin its SHA-256.
   This is the adapter for the existing site-specific signed-in read-only
   workflow QA, complete ordered business facts, performance budgets, two-worker
   checks, clean logs and database capacity/index checks. It is intentionally
   required: a green health endpoint must not silently replace these checks.

   Contract: `auto_release_site_gate.py prepare|approval|postflight|closing` receives one JSON
   object on stdin containing `plan` and `host`; it returns only
   `{"passed":true,"identity":"<release_manifest.identity(plan)>"}` on stdout,
   with a nonzero exit on any missing/failed check. `prepare` receives
   `host.candidate_slot`; active `host.slot` remains the baseline. Postflight
   and closing receive the actual new slot. Store detailed evidence mode-0600
   outside stdout; never print cookies, tokens, environment values or business
   payloads. The adapter must be read-only and bound to this exact plan. Review
   every changed-workflow selection before returning success. The supplied
   `auto_release_site_gate.py` and separately pinned `auto_release_probe.py`
   implement the infrastructure/API checks. Both image versions read the same
   exported PostgreSQL snapshot with read-only transactions, plus a real API
   dependency write-refusal challenge. Complete ordered response hashes cover
   seven workflows within the existing reader's authorization. Cutting IDs are
   enumerated within its scope because the normal list has a 500-row limit.
   Live performance probes omit the package list: that GET can repair QR files.
   Probe storage is mounted read-only, runtime is bounded and its named container
   is removed on timeout. Missing QR assets fail verification.

   Application changes additionally require current root-owned QA evidence in
   `/opt/milana-erp/shared/qa-approvals/<commit>.json` on both hosts. Bind the exact
   `identity(plan)`, sorted changed application paths, reviewer and `checked_at`
   (within three hours). Its `evidence` references exactly `browser`, `permissions`,
   `persisted_results` and `adjacent_workflows`, each by protected absolute path
   and SHA-256. Artifacts bind the same identity/kind and contain observed
   `checks` with `name`, `actual` and `expected`; failed or Boolean-only stubs
   are refused. Browser evidence also requires zero console errors and protected
   PNG screenshots. Record actual QA-master results; installation does not supply
   or fabricate application acceptance. Preparation records technical readiness while acceptance is pending. Complete the
   evidence on both hosts before merging. The worker validates both approvals
   before either switch; each host rechecks its own approval on activation.
   Missing evidence stops activation without switching either host.
4. Create root-owned configuration files from the examples. Change frontend
   `role` to `frontend`; fill actual reviewed controller/site-gate hashes. On
   each host run from the reviewed checkout:

   ```sh
   sudo python3 deploy/install_auto_release.py backend --config /secure/backend-host.json
   sudo python3 deploy/install_auto_release.py backend --config /secure/backend-host.json --apply
   # Frontend: use frontend and its own host config instead.
   ```

   The installer copies only the reviewed host helper/manifest module and writes
   a `visudo`-validated rule for its one fixed Python invocation. The helper runs
   under a host operation lock and keeps root-only journals/reservations in
   `/opt/milana-erp/runtime/auto-release`. Failed attempts are retained.
5. On backend, provision the scoped token and key in `credentials/`, accessible
   only to `milana-deploy`. Configure their paths from the worker example and run:

   ```sh
   sudo python3 deploy/install_auto_release.py worker --config /secure/worker.json
   sudo python3 deploy/install_auto_release.py worker --config /secure/worker.json --apply
   ```

   Protect `/etc/milana-auto-release` from non-root writes. Ensure the worker's
   state directory is owned by `milana-deploy`; configuration is root-owned and
   readable by that group. The account must have no write access to installed
   scripts, gate adapters, the shared backend environment or controller.
6. Before starting: independently verify both current manifests/slots/routing,
   strict production startup settings/seeding disabled, current DB revision,
   backup capability, disk below 80%, retained rollback and absence of another
   deployment/observation. Reconcile `clone_main` and production-base.json.
   Run a complete rehearsal with owned containers/database and the installed
   site gates, including partial-cutover recovery, before enabling production.
7. Set repository variable `AUTO_RELEASE_BUILDS=true`. Then explicitly enable
   the worker on backend:

   ```sh
   sudo systemctl enable --now milana-auto-release
   sudo journalctl -u milana-auto-release -f
   ```

   This starts automation for future successful candidates; it is not required
   merely to install the files. Source pushes alone do not change production.

## Failure and recovery

The worker persists its phase before a host mutation. No unattended restart
relabels an interrupted deployment as successful. Failed backups, gates, drift,
missing artifacts and unreviewed schema changes stop promotion. Candidate source
and backup attempts are never overwritten. Hosts refuse another reservation.

If activation/observation failed, inspect both protected journals first. Stop the
worker service; run the installed worker as its dedicated account with `--recover`
for an explicit backend-first recovery. Both hosts are attempted even if one
fails. The old container ID must still match; recovery restores application
routing/source pointers only and never downgrades or changes business data.
Recovering an untouched host is a verified no-op. Start the service again only
after checking all four endpoints and source/slot/proxy readbacks.
This initial policy requires operator action after an uncertain failure; a partial
cutover can leave backend and frontend on different versions until guarded recovery.
It is not automatic rollback. Rehearse that case before enabling the service.

After baseline publication, recovery is forbidden. `publishing`/`finalizing`
resume only idempotent metadata/completion work. A concurrent integration change
blocks metadata publication without rolling the healthy application back. Resolve
that source conflict explicitly; never force-push or overwrite another PC's work.
Do not delete journals/leases to bypass a refusal. Keep active/rollback images,
sources and backups through observation and use protected retention afterward.

## Current verification and limits

The 17 November implementation uses verified live source `4d7cf17e55b165b1edc05407065f92597cebdbe5`
(`20261116_130518`, manifest `bc2e0d4bdbb38f6c06b9f3d5c75f3fdaa1fb5087240ca8f7b49d01318908ce40`).
Both live source manifests pass; all 2,559 declared files match raw Git blobs.
Health/readiness reported the same release. Installed-helper snapshots now pass
both protected slot/router/container checks and the real backend database-head
check. The worker is enabled after the owned rehearsal. All 55 Linux
deployment tests and independent source review pass. The actual hardened service
sandbox now passes; the earlier denied attempt remains historical failed evidence.
The PostgreSQL 16 dump restored successfully to a private PostgreSQL 16 database.
Production application slots/source/router/schema remain unchanged. An early
live package-GET diagnostic may have regenerated missing QR cache/metadata;
its exact effect was not fingerprinted. Later package verification is protected
by read-only transactions and storage. See the task record for actual rehearsal
results and remaining limits; laboratory timing is not a production latency guarantee.
