# Automatic deployment implementation — 17 November 2026

## Authorized scope and source

The owner requested push -> background validation/preparation -> merge -> a
seconds-scale production switch. He authorized using verified `clone_main`
lineage, reconciling it with the live release first, and selected the backend VM
for the lightweight worker, then explicitly requested installation. No application
deployment was requested in this task.
Human infrastructure ownership remains Dilmurod/Mirshoir; Codex implements, with
independent source review by `/root/review_auto_deploy`. Neither human approval
nor production acceptance is invented here.

Both VM source pointers/manifests verified `20261116_130518` /
`bc2e0d4bdbb38f6c06b9f3d5c75f3fdaa1fb5087240ca8f7b49d01318908ce40`.
All 2,559 declared files matched raw Git blobs at
`4d7cf17e55b165b1edc05407065f92597cebdbe5`. Exact-source CI
[43872462960](https://github.com/Shmirzaev/Milana-ERP/actions/runs/43872462960)
passed backend, frontend, security and publication. Source-only reconciliation
commit `88b3e8455f83e6f98a9b36b5c15d7a1ac84b70ab` fast-forwarded `clone_main`
under the owner's authorization, independent review and expected-head CAS.
No application file was changed relative to verified live source in that step.
Protected slots/DB inspection was initially blocked on sudo. Subsequent authorized
installation used the existing SSH account's Docker administrator access and
completed both installed-helper snapshots, including real database-head readback.

## Implemented source

- Hosted CI validates `codex/**` pushes; publication is opt-in through
  `AUTO_RELEASE_BUILDS`. Automatic release IDs include run/attempt. Manual
  publication remains available. The already-scanned images are promoted by
  immutable digest; no server build was introduced.
- A manifest binds CI run, Git commit/tree, source archive/manifest, migration
  history, images and production baseline. The fixed LAN worker verifies the
  run/repository/actor/jobs, GitHub artifact checksum, source ancestry and
  administrator-pinned CI/scan/security recipes before host changes.
- Root-owned host helpers validate source, fresh backup and inactive containers;
  enforce site-gate attestations and reservations; then recheck the exact image,
  command, restart/OOM flags, strict startup settings and served release before
  activation. The fixed service runs on backend with bounded resources.
- Complete-tree merge matching supports ordinary, squash and rebase merges.
  Activation is backend-first, followed by all four health checks and conservative
  30-minute observation. Metadata publication uses a non-forced Git CAS and keeps
  runtime source provenance distinct from accepted integration ancestry.
- Durable phases, reservation ownership and guarded recovery cover partial and
  interrupted operations. Publication/finalization retries cannot roll production
  back after its Git baseline has advanced. Partial activation requires operator
  recovery and can temporarily leave mixed application versions; rehearse it.

The initial static installation changed no schema, business row, stock, payroll,
ERP role/user, source pointer, slot or router. No registry build/scan dependency
was installed on a serving VM. The later package-GET diagnostic has the separate
QR-side-effect uncertainty recorded below.

## Actual local validation

- 40 deployment contract/fault tests passed in a local Linux Python 3.11 container.
  Windows ran 39 passes plus one explicitly skipped Linux symlink test.
- Seven CI trigger-policy tests, 16 security-gate tests and 12 observer tests pass.
- Scoped Ruff, Python compilation, YAML policy parsing and `git diff --check` pass.
- Independent AI source review reported no remaining blocking findings after
  corrections to subprocess receipts, untouched-host recovery, reservation
  idempotence, post-publication phases, merge ancestry/deleted branches, explicit
  known-hosts, release-ID uniqueness and ready-time runtime checks.
- Exact installed-code push CI [44014036422](https://github.com/Shmirzaev/Milana-ERP/actions/runs/44014036422)
  completed successfully, including backend, frontend and image/security scans.
  Release publication was skipped because automatic builds remain disabled.
- An additional unchanged router/container test failed on Windows because its
  existing harness generates `/cfg\\frontend-503.http` and `/cfg\\api-503.http`
  paths inside Linux HAProxy. Neither that test nor `deploy/slotctl.py` changed.
  This is not recorded as a pass; exact live-source Linux CI above is separate
  evidence, not a replacement candidate test result.

## Authorized installation follow-up

Raw Git bytes from reviewed tooling commit
`c0fc78660cd2d77409b23608fa841180e9fa4355` were installed using temporary
utility containers through the existing Docker administrator access. Container
entrypoints were explicitly overridden; no application startup/migration ran.
Static file installation used no network and narrowly scoped writable mounts;
account/configuration setup used host tools with explicit filesystem scopes.
The service-manager reload required host PID visibility; it started no service.

- Both VMs: root-owned helper and manifest module in
  `/opt/milana-erp/shared/deploy/`, plus an installation receipt naming the commit.
- Backend: fixed worker, manifest module, observer and installer under
  `/opt/milana-auto-release/`; systemd unit under `/etc/systemd/system/`;
  root-owned/group-readable worker configuration with CI policy hashes calculated
  from raw reviewed Git blobs. The flat installer copy is archival tooling: its
  worker-install command still requires the reviewed checkout's CI policy files.
- Both VMs: locked-password `milana-deploy` Linux account, SSH login shell,
  protected home/inbox and `restrict` public-key authorization. The accounts have
  only their own group, no Docker membership and no general sudo privilege.
  Backend has account-owned mode-0700 state/credentials directories and a new
  mode-0600 Ed25519 private key; only its public key went to frontend. Host keys
  were copied from the already verified local known-hosts entries.

Installed hashes/root ownership/write permissions and host Python compilation
pass. Worker configuration parses and matches the reviewed CI policy pins.
Backend-to-backend/frontend SSH passes with strict host checking as the new
account. Systemd reload and unit validation pass; `is-enabled` reports `disabled`
and `is-active` reports `inactive`. No worker run or candidate staging occurred.
All four required internal/public health/login endpoints return HTTP 200.
An independent review found no additional blocker to this limited installation
handoff. An attempted transient check with the service's namespace restrictions
was refused by systemd with `Access denied`; it never ran and is not a pass.
Account SSH success does not prove access under the full service sandbox.

Both installed-helper `snapshot()` calls pass: complete source-manifest checks,
active green release `20261116_130518`, actual container/default-command identity,
source pointers, stable router state/configuration, and backend strict startup/
seeding settings and the real Alembic-head check. Blue rollback remains
`20261116_092917`. Installed controller SHA-256 is
`13a9e19d5b266c87d138cb2866a185fedf45a089b85534d26fb28667eb95c3f3` on both
hosts. Its backend staging command lacks `RELEASE_ID`; upgrade that exact command
under review before enablement, preserving installed routing. The archived
candidate controller was not copied over the installed one.

## Credential provisioning follow-up

The owner supplied a credential and explicitly authorized its use after being
advised to replace it. That authorization supersedes the earlier absent-token
status; rotation remains recorded as a follow-up. No credential value or
credential fingerprint is retained in source or this record.

The credential was transferred over the verified SSH connection directly to
`/var/lib/milana-auto-release/credentials/github.token` on backend, owned by
`milana-deploy` with mode `0600` inside its mode-`0700` credentials directory.
It was not written into a shell command, repository file or local token file.
The terminal reader disabled input echo; credential validation reported only
sanitized results.

GitHub accepted repository, Actions and integration-branch read requests. A
second server-side check as `milana-deploy`, using the installed worker's GitHub
client and actual credential file, passed Actions, branch and collaborator
permission reads and verification of every installed CI recipe pin. This did
not exercise Contents/status write permissions or the full systemd sandbox.
An initial diagnostic used an unused trailing-slash repository URL and returned
404; the corrected check used the worker's actual endpoints and passed.
The worker remains inactive; active release is still `20261116_130518`.

## Earlier blocked checkpoint (superseded by installation below)

Source approval and static installation are not production-readiness approval.
The GitHub credential is now provisioned as recorded above. The earlier browser
credential-creation attempt failed before navigation and created no token.
The real signed-in workflow/full-fact/performance
QA adapter is absent. Consequently host configuration and the restricted sudo rule
were deliberately not installed. Connect the real QA suite, review the controller
staging update and complete an owned two-host
recovery rehearsal before enabling automation. No pass-through gate was created.
The activation latency target has not been measured on production. No tests,
checks or observations are waived. Follow [the installation/runbook](../AUTO_DEPLOYMENT.md).

## Completion of host installation and actual verification

The owner explicitly requested completing the outstanding work and enablement.
Reviewed fixed tooling `76c49093d5fc1466399fc2654a03660480d0ff5f` is installed
on both VMs. Root-owned host configurations pin the original controller,
separate staging adapter, executable site gate and read-only probe. The exact
restricted sudo invocation is validated by `visudo`; the dedicated account has
no Docker group or general sudo access. The original controller remains
`13a9e19d5b266c87d138cb2866a185fedf45a089b85534d26fb28667eb95c3f3`.
Its full real staging function is covered by the regression fixture; the adapter
adds only `RELEASE_ID` and preserves the original routing implementation.

The actual service sandbox now passes with User/Group `milana-deploy`, strict
filesystem/home restrictions, private temporary storage, no new privileges,
256 MiB memory and 25% CPU. It read the protected credential and policy pins,
ran both restricted SSH snapshots, created an unreferenced Git blob and recorded
a truthful `Milana / installation` status. This validates Contents/status writes
without merging or publishing an application. Earlier denied sandbox attempts
remain failed evidence; the successful transient unit was
`milana-auto-release-install-check-1794894655`.

The fixed site gate checks complete ordered API facts on one exported PostgreSQL
snapshot, using read-only sessions and a real SQLSTATE `25006` write-refusal
challenge through the API dependency. An actual production-source probe passed
for scoped Sales 100, Production 699, material batches 865, Packages 10,501,
Cutting 847, work orders 2,846 and shipments 272. This is an authorized reader's
scope, not a claim about every factory/user. Cutting's ordinary UI-list cap is
handled through authoritative scoped IDs and every actual detail route; its
UI list ordering is not independently compared. Other full paginated responses
retain all ordered fields in their hashes. Runtime HTTP checks cover signed
identity, anonymous denial and unchanged 10% median/15% p95/15% payload budgets.
Application changes also require actual exact-plan browser/permission/persisted/
adjacent-workflow evidence and QA-master results; no acceptance was fabricated.

Two real environment failures were corrected without bypassing their gates:

- The initial 512 MiB verification utility exhausted its container limit. The
  same bounded read-only probe passed at 1 GiB. Unique names, a 600-second bound
  and exact-name cleanup prevent orphaned verification containers.
- Native backend PostgreSQL clients are 18.6, while the real server is 16.14.
  The first private restore stopped at an unsupported configuration statement,
  with zero public tables created. That failed 128,031,668-byte dump is retained.
  A fresh 127,449,666-byte dump from the existing pinned official PostgreSQL 16
  image restored successfully into private PostgreSQL 16. Host backups now use
  that matching immutable client, a read-only container and inherited password
  environment name, never a password argument or filesystem mount.

The private two-host rehearsal uses
`/opt/milana-auto-release-rehearsal-20261117`, separate source/state/storage,
generated JWT/file-signing/counter settings and a restored private database.
Real application images/default commands run on isolated Docker internal
networks. Distinct loopback ports and separately named HAProxy/systemd units
serve only the laboratory. Docker 29 suppresses ordinary published ports on an
internal network, so scoped socket-proxyd units bridge inward to verified private
container IPs. Fixed QA/backup utilities intentionally use host networking with
laboratory-only connection settings. Production source/slot/proxy/container and
controller fingerprints are checked before and after.

The real worker/account/sandbox and SSH helpers exercised the first private
preparation. Its fresh backup passed (127,673,516 bytes, 1,399 restore objects)
and its inactive backend started; the site gate correctly stopped on Docker 29's
requirement for a PID column in `docker top`. The corrected `pid,args` command
returned two actual workers on that VM. The failed `20261117_180000` journal is
preserved as recovered: actual worker recovery passed on both hosts and released
only its own reservation. The fresh `20261117_180001` result is recorded below.

The installed tooling passes 55 Linux deployment tests, scoped Ruff and independent
AI review. Activation verifies immediate source/container/served-health identity,
then the coordinator switches frontend before running the complete postflight
gates on both hosts. The four health checks, full postflight, 30-minute production
observer and closing gates remain required. This prevents a multi-minute full
business scan between the two traffic switches.

An early diagnostic called the live package-list GET before its QR-repair behavior
was identified. It may have regenerated missing QR cache files/metadata; no
before/after fingerprint exists to establish its exact effect. No orders, stock,
shipments, payroll or users were intentionally changed. Later live benchmarks
exclude that route, and frozen package probes enforce both read-only PostgreSQL
transactions and read-only storage, failing closed if QR repair would be needed.

## Actual two-host recovery and enablement result

The fresh owned attempt reached technical readiness through the real worker
account, SSH helpers and hardened service sandbox. Backend preparation took
341.604 seconds, frontend 7.451 seconds. It passed fresh-backup validation,
two actual workers per backend slot, clean logs, full same-snapshot fact equality
and SQLSTATE `25006`, signed identity/anonymous denial, database index/capacity
and all unchanged performance budgets. The restored snapshot contained 100 Sales,
699 Production, 865 material batches, 10,501 Packages, 847 scoped Cutting,
2,846 work orders and 274 shipments. Database capacity was 10/100 connections,
with zero invalid indexes. Twenty-one samples per slot passed for Sales,
Production and material batches; worst p95 growth was approximately 5.46%.
The validated private backup is 127,673,516 bytes with 1,399 restore objects,
SHA-256 `e7eb1d3b20b0293679048305e47c13a518099d9b1ec738f31e6f4a119da66c3b`.

Technical preparation used `63bcb243`; its complete technical gate is unchanged
by the final `76c49093` approval-order correction. The owned tooling was then
updated for the actual final-worker approval/activation/recovery phase, retaining
the identical prepared images/source. Both actual approval actions passed before
any switch. The injected frontend exception happened after HAProxy and slot-state
activation but before the helper could update `current`; its durable journal
remained `activating`. Actual guarded recovery restored both original container
IDs, sources, manifests and green routing, marked both journals `recovered` and
released both owned reservations. No fake GitHub production status or merge was
used for the laboratory; its integration responses were explicit fixtures and
its source archive was administrator-preseeded, while host operations used real SSH.

The bounded laboratory allowed 0.5 CPU per application container. The guarded
request reached the injected fault after 84.467 seconds, including repeated
full identity/database-head checks. The backend-confirmed activation to frontend
fault interval was 21.297 seconds; explicit recovery took 41.368 seconds.
These are actual laboratory results, not a seconds-from-push or production
activation guarantee. No production application cutover or 30-minute production
observer was run; those remain mandatory for a real release.

Before/after production controller, proxy, source-manifest, slot state and active
container identities matched on both VMs. The private application/database
containers, internal networks and laboratory router/socket services were stopped
and removed, and the temporary laboratory sudo rules removed. Root-protected
backup/restore data, code and receipts remain in the owned laboratory directory.

PR [#558](https://github.com/Shmirzaev/Milana-ERP/pull/558) merged source into
`clone_main` at `61f3686c0775b03318bd5c38e560b80ee1759972`. Final source has
55 passing Linux deployment tests and independent AI review; latest frontend and
security CI pass. The broader unchanged application backend suite is still running
in [44029834048](https://github.com/Shmirzaev/Milana-ERP/actions/runs/44029834048);
it is not claimed passed. There are no required GitHub PR checks configured.
This infrastructure source integration performs no application release; future
deployment candidates must still pass every required CI job.

The owner-authorized backend worker is now enabled/active, and repository
`AUTO_RELEASE_BUILDS` is `true`. It remains bounded to 256 MiB/25% CPU as
`milana-deploy`; initial polling is idle. The active application is still
`20261116_130518`, green, with rollback `20261116_092917`, blue, and schema
`0157_package_allocation_items`. Future flow is push -> technical readiness ->
real exact-plan QA evidence on both hosts -> merge -> guarded traffic switch.
Missing evidence on either host prevents every traffic switch, and direct host
activation rechecks approval. Human acceptance is not inferred from installation.
