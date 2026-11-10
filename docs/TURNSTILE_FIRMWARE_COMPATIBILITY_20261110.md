# Hikvision compatibility follow-up — 10 November 2026

Local code candidate; **not deployment-ready**. No physical enrollment, face
upload, name edit, revoke, restore or deletion was performed. No old-ERP or
terminal setting, installed reader, task, credential or connection was changed.
The owner confirmed that the support question concerns Hikvision, and requested
continuing independent local fixes while retaining his later supervised pilot.

Owner: Dilmurod; human reviewer: Mirshoir; implementation: Codex /root;
independent AI reviewer: /root/review_hr_scope. Shavkat/operator and QA-master
acceptance remain pending. The owner chose Milana as sole writer after an agreed
handover; the previous ERP remains the current writer. New browser testing was
expressly deferred by the owner after automatic review rejected preview startup.

## Source and production reconciliation

Fresh dedicated worktree: `C:/ERP/.codex-work/hr-hikvision-compat-20261110`, branch
`codex/hr-hikvision-compat-20261110`, from fetched `origin/clone_main`
`2bb66fc44475c50cfe4f9d979b2e184b8a127f56`. Its production baseline records green
`20261109_163130`, application `271c5005e12d1efc65d6358756862d8c243685a5`, manifest
`535aa197ba218b0d0e867480d6a6570a25273307dfdea2185ce28d383f4e56d7`.
Public `/health` returned HTTP 200, status ok, this release on 10 November.
Authenticated VM inspection was unavailable; failed SSH authentication changed
nothing. The original HR worktree and legacy checkout were preserved.

Five previously reviewed HR commits ending at original `32a9d3e27` were cleanly
ported, ending at `3e283695b` in this new worktree. This follow-up changes only
the reviewed optional-permission and deletion-progress compatibility seam plus
tests, frontend contract and documentation. It adds no migration beyond the
already reviewed additive `0156` migration. No push, merge or deployment occurred.
Final local revision and source hashes are recorded in local Git and
`outputs/hr-readiness/compat-handoff.json`.

## What the native responses actually establish

The earlier blanket interpretation of HTTP 404 as an unsupported deletion API
was incorrect. Five pinned terminals return exactly HTTP 404, `statusCode=4`,
`subStatusCode=taskNotExist`, `errorCode=1073746095`. This is an idle deletion
queue, never successful deletion. The driver now preserves bounded native error
codes and recognizes only this combination at this exact read endpoint.

`turnstile-31` instead returns HTTP 404, `statusCode=3`, `subStatusCode=deviceError`,
`errorCode=805306369`. Its deletion path stays refused before any dispatch. No
reboot, settings change, write-based probing or old-ERP disconnection was tried.
That device still needs diagnosis; another terminal can host the first pilot.

The earlier absence identifier was rejected with HTTP 400 and `employeeNo`.
An exact short synthetic identifier accepted by the firmware returns zero people,
cards and faces plus `NoFP` on all six devices. No real employee number is
truncated, replaced or remapped. An HTTP error never proves absence.

All six also passed pinned ordinary-person capability and face-capacity reads.
Their complete ordinary-person capability responses advertise local UI rights,
but do not advertise the optional double-lock right. These are different rights
in the [vendor's ISAPI reference](https://open.hikvision.com/hardware/v2/08%E5%8D%8F%E8%AE%AE%E9%80%8F%E4%BC%A0/%E6%98%8E%E7%9C%B8%E9%97%A8%E7%A6%81.html).
The response hash is retained as evidence, without retaining personal bodies.
No real profile photo or fingerprint template was fetched during these checks.

## Conditional verification, without inventing a false permission

New enrollment always creates a blocked person with `localUIRight=false` and
requires explicit false readback. A complete capability response is required:
typed employee-number bounds, supported normal/blocked types, all three explicit
credential counters, nonempty validity/door-plan objects and local-UI false
support. Incomplete or malformed responses refuse before creation.

If `doubleLockRight` is advertised, creation sends false and readback must
explicitly be false. If the complete response omits it, creation omits only that
optional property and records `not_advertised`; readback may be missing or false,
never true. Missing is not represented as observed false. Capability evidence
must remain identical across blocked and face readbacks before activation.
Unknown evidence or drift leaves the profile blocked and the operation uncertain.

Backend DTO/service checks independently enforce the same enrollment outcome.
`DoubleLockCapability` is a canonical backend/frontend enum with `unknown`,
`advertised`, `not_advertised`; `user_info_sha256` requires lowercase SHA-256.
The JSON evidence is optional for legacy reads and forbidden on absent profiles;
new enrollment cannot succeed without it. Legacy reviewed baselines require a
fresh observation/adoption before mutation. No stored evidence is backfilled.
Connector `DeleteProgress` is a distinct internal protocol enum, not an ERP job
state or database column.

Deletion still requires a previously revoked exact identity, complete credential
inventory, one single-use permit and one exact-person delete request. Post-write
idle is only pending: bounded polling must reach explicit native success, then
independent person/card/face/fingerprint absence must all be proved. Failure,
timeout, generic 404 and deviceError remain uncertain/refused. Writes are never
automatically retried. Existing HR, payroll, attendance and audit history remain.

## Evidence on this candidate

- **224 Windows connector tests passed**, zero failures/skips, including actual
  current-user DPAPI, strict TLS pinning, omission/elevated-right/malformed-policy
  cases, capability drift and exact idle versus generic/native device errors.
  `connector-compat-final.xml` and log are under `outputs/hr-readiness/`.
- **96 focused backend tests passed**, zero failures/skips: new 55-case server
  matrix, existing 37 receipt/lock cases and four actual backend-to-worker-to-
  synthetic-HTTPS scenarios. The seven-action lifecycle runs with both advertised
  and unadvertised double-lock capability, preserving HR and unrelated profiles.
  Evidence: `backend-focused-final.xml` and log.
- Red/green: the new omission and idle-to-success connector cases both fail
  against pre-fix `3e283695b` source, then pass with this change. The independent
  backend seam run first had 4 failures / 51 passes before the matcher fix, then
  all 55 passed. Red connector log/XML are retained; no threshold was relaxed.
- Frontend webpack production build with the live flag enabled, TypeScript and
  scoped ESLint passed. No preview server or browser test was launched.
- Full Windows fallback was **not a pass**: 450 passed, 135 skipped, 24 failed.
  Failures include 22 response-header assertions plus Windows symlink privilege
  and POSIX file-mode expectations. Its shared environment has FastAPI 0.136.3
  versus repository requirement 0.140.0, so it is not a pinned release environment.
  Raw failures remain in `backend-windows.xml` and log. No unrelated middleware,
  tests or security expectations were changed to make this attempt green.
- Fresh Linux/required PostgreSQL checks are **blocked** by unavailable Docker.
  The eight live PostgreSQL cases were skipped in the Windows fallback. Prior
  553-backend/8-PG and Linux release-policy results belong to the original 9
  November source, not automatically this combined candidate. The new full PG
  bootstrap is prepared locally, but was not run successfully.
- Pinned read-only six-terminal metadata/absence evidence is in
  `device-compatibility-readonly.json` and log; the different lane-31 native error
  is separately recorded in `device-31-delete-progress.json`.
- Six installed reader/config/secret/wrapper hashes and the scheduled-task
  definition match the prior baseline (`reader-preservation.json`). Normal reader
  cursors may advance independently. The separately staged writer remains source
  only; no installation, task registration, activation or live writer ran.

Independent AI review found no actionable source blocker. These results are not
`AI_VERIFIED_AWAITING_HUMAN`: pinned Linux/PG, browser and physical acceptance
gates remain incomplete. No human acceptance or deployment approval is implied.

## Remaining deployment and physical gates

1. Restore the local Docker test engine and run the prepared full scoped suite
   against real disposable PostgreSQL with required checks, plus Linux policies.
   Reconcile the candidate with the latest deployment source before release.
2. Complete the owner-deferred Edge visual workflow and persisted readback.
3. With the owner, select his exact employee number, one terminal and approved
   access/validity rules. Agree a limited pilot identity the previous ERP will
   not overwrite. Keep unrestricted Milana write gates off until handover.
4. Physically test add, name/photo edit, passage, revoke, restore, exact deletion,
   denied passage after revoke/delete, uncertain/offline recovery, unchanged
   unrelated profiles and fresh scan receipt in both ERPs. These have only been
   simulated so far. Diagnose lane-31 progress separately before deleting there.
5. Record Mirshoir/QA-master and operator acceptance, prepare database backup,
   additive migration/rollback, immutable reviewed images and an explicitly
   authorized blue/green release. Physical device writes need their own recovery
   plan: rolling back application code does not restore deleted credentials.

Hikvision support is not necessary to continue local preparation and a supervised
pilot on the five terminals with verifiable reads. It may still be needed for
lane-31 if read-only diagnosis cannot establish a supported completion route.
