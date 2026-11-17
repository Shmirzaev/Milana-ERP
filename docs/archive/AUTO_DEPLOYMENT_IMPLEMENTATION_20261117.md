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

The installation follow-up below supersedes the initial source-only status. No
registry build/scan dependency was installed on a serving VM. No schema, business
row, stock, payroll, ERP role/user, source pointer, slot or router changed.

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

## Remaining gate: BLOCKED for enablement/production E2E

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
