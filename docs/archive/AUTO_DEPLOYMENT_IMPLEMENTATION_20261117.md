# Automatic deployment implementation — 17 November 2026

## Authorized scope and source

The owner requested push -> background validation/preparation -> merge -> a
seconds-scale production switch. He authorized using verified `clone_main`
lineage, reconciling it with the live release first, and selected the backend VM
for the lightweight worker. No application deployment was requested in this task.
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
Protected slots/DB inspection requires sudo and remains unverified by this task.

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

No production worker/controller/site gate was installed or changed. No registry
build/scan dependency was installed on a serving VM. No schema, business row,
stock, payroll, role, user, source pointer, slot or router changed.

## Actual local validation

- 39 deployment contract/fault tests passed in a local Linux Python 3.11 container.
  Windows ran 38 passes plus one explicitly skipped Linux symlink test.
- Seven CI trigger-policy tests, 16 security-gate tests and 12 observer tests pass.
- Scoped Ruff, Python compilation, YAML policy parsing and `git diff --check` pass.
- Independent AI source review reported no remaining blocking findings after
  corrections to subprocess receipts, untouched-host recovery, reservation
  idempotence, post-publication phases, merge ancestry/deleted branches, explicit
  known-hosts, release-ID uniqueness and ready-time runtime checks.
- An additional unchanged router/container test failed on Windows because its
  existing harness generates `/cfg\\frontend-503.http` and `/cfg\\api-503.http`
  paths inside Linux HAProxy. Neither that test nor `deploy/slotctl.py` changed.
  This is not recorded as a pass; exact live-source Linux CI above is separate
  evidence, not a replacement candidate test result.

## Remaining gate: BLOCKED for installation/production E2E

Source approval is not installation or production-readiness approval. The current
SSH account cannot invoke the protected controller without administrator
authentication. The required site-specific signed-in workflow/full-fact/performance
QA adapter, scoped token/new SSH key, protected slot/DB checks and real owned
two-host recovery rehearsal must be installed/proven before enabling automation.
The activation latency target has not been measured on production. No tests,
checks or observations are waived. Follow [the installation/runbook](../AUTO_DEPLOYMENT.md).
