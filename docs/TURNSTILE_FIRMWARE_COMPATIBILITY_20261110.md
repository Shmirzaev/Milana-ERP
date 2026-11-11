# Hikvision compatibility follow-up — 10 November 2026

Local code candidate; **not deployment-ready**. No physical enrollment, face
upload, name edit, revoke, restore or deletion was performed. No old-ERP or
terminal setting, installed reader, task, credential or connection was changed.
The owner confirmed that the support question concerns Hikvision, and requested
continuing independent local fixes while retaining his later supervised pilot.

Owner: Dilmurod; human reviewer: Mirshoir; implementation: Codex /root;
independent AI reviewer: /root/review_hr_scope. Shavkat/operator and QA-master
acceptance remain pending. The owner chose Milana as sole writer after an agreed
handover; the previous ERP remains the current writer. The owner later restored
Docker and expressly authorized Edge testing, while deferring real-person testing.
He manually started/restarted the loopback-only preview after automatic approval
review rejected the agent's launch with only "blocked by policy".

## Source and production reconciliation

Fresh dedicated worktree: `C:/ERP/.codex-work/hr-hikvision-compat-20261110`, branch
`codex/hr-hikvision-compat-20261110`, from fetched `origin/clone_main`
`2bb66fc44475c50cfe4f9d979b2e184b8a127f56`. Its production baseline records green
`20261109_163130`, application `271c5005e12d1efc65d6358756862d8c243685a5`, manifest
`535aa197ba218b0d0e867480d6a6570a25273307dfdea2185ce28d383f4e56d7`.
Public `/health` returned HTTP 200, status ok, this release on 10 November.
Authenticated VM inspection was unavailable; failed SSH authentication changed
nothing. The original HR worktree and legacy checkout were preserved.

During these tests production advanced independently: closing public health
reported `20261110_070607`. Fresh fetched `origin/clone_main` is
`8ae2429cbd39c5f33ba17aab75d36949180e0c19`, whose baseline records application
`843adaf3bda1b1f2d234e68b6763bbc649d3b72a`, manifest
`7bf0a59c139cf8a46fc6af7a3a0c5457795ba7b1de7fe57e70c76b31481fac32`, unchanged
schema `0155_eco_gate_merge`. This isolated candidate retains its tested 2bb base
under the owner's instruction to fix/test separately and integrate with the latest
source later. Its production-base file was not rewritten. Latest-source
reconciliation and combined validation remain release gates; no test result here
claims coverage of that unperformed merge.

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
  scoped ESLint passed. After the Edge-discovered status fix below, the full npm
  build contract chain and production webpack build passed again. Final scoped
  lint and all seven status regressions passed after correcting a test-only
  reserved variable name; that initial lint failure is not a runtime failure.
- Full Windows fallback was **not a pass**: 450 passed, 135 skipped, 24 failed.
  Failures include 22 response-header assertions plus Windows symlink privilege
  and POSIX file-mode expectations. Its shared environment has FastAPI 0.136.3
  versus repository requirement 0.140.0, so it is not a pinned release environment.
  Raw failures remain in `backend-windows.xml` and log. No unrelated middleware,
  tests or security expectations were changed to make this attempt green.
- Docker was initially unavailable. After the owner restored it, the full scoped
  HR/People/attendance/affected-payroll suite passed **609 tests, zero failures or
  skips**, including all eight live PostgreSQL cases, on backend source
  `301ec63cb`. Evidence: `backend-compat.xml` and log. No backend/connector runtime
  file changed afterward. This resolves the fresh Linux/PG gate; the earlier
  Windows failure/skip evidence remains intact. **19 release-policy tests and
  six subtests** also passed on Linux (`release-policies-20261110.xml`). No security
  image scan, image publication or deployment workflow ran.
- Pinned read-only six-terminal metadata/absence evidence is in
  `device-compatibility-readonly.json` and log; the different lane-31 native error
  is separately recorded in `device-31-delete-progress.json`.
- Six installed reader/config/secret/wrapper hashes and the scheduled-task
  definition match the prior baseline (`reader-preservation.json`). Normal reader
  cursors may advance independently. The separately staged writer remains source
  only; no installation, task registration, activation or live writer ran.

Independent AI review found no actionable source blocker. These results are not
full physical acceptance: local automated and Edge gates passed, while the
real-device pilot, human acceptance and latest-source release gates remain open.
No human acceptance or deployment approval is implied.

## Completed Edge session and status repair

The owner-started frontend used only `127.0.0.1:31169`, proxying the owned test API
at `127.0.0.1:18169`. An exact disposable PostgreSQL database and pinned synthetic
HTTPS terminal were used. No factory addresses, real photos or reader credentials
were loaded into that UI harness.

- Ten persisted UI requests succeeded: observation, enrollment, name edit, photo
  replacement, revoke, restore, revoke, delete and two final observations. There
  were nine writes to the **synthetic** terminal and zero factory-device writes.
  The explicit active-profile delete attempt returned refusal and created no job.
- Deletion reached native success in the simulation and separately proved absent
  credentials. HR employee `LIVE-UI-1` remained active, the device profile/photo
  became absent, and the unrelated synthetic terminal profile remained present.
- A separate HR employee was saved, edited, archived, restored and reloaded.
  Browser validation rejected an invalid employee-number format. The valid
  synthetic number `990002` retained the saved name/HR department and active status.
  Its terminal action stayed disabled because it was not allowlisted.
- An HR-only staff fixture without `attendance.provision` had zero terminal
  management buttons. Direct context and submission requests both returned 403.
  HR employee rights remained available; this was not a read-only HR role.
- EN/RU/UZ turnstile controls and saved history were inspected. Database readback
  verified both employee rows, ten successful jobs and all 25 audit-chain records.
  Final captured browser console had zero errors/warnings. This desktop session
  does not certify phone/scanner use or actual face recognition/passage.

The first build exposed a genuine UI defect: the status stayed "waiting" after
the job/history was verified. The repaired component tracks the accepted job and
renders the polled enum state. Typed receipts seed the cache before refresh;
failed refresh cannot resurrect a previous Failed retry state, and a delayed
receipt cannot overwrite cached Succeeded evidence. Seven permanent regressions
exercise the actual TypeScript helper. Removing the success-preservation guard
produced the expected **three failures/four passes**; restoring exact source
returned seven passes. Independent review confirmed both ordering fixes.

The rebuilt preview's final observations showed Verified in both DOM and rendered
screenshots. Evidence includes `edge-status-before-fix.jpg`,
`edge-verified-final.jpg`, RU/UZ and restricted-role captures, final DOM, the seven
regression/fault logs, `edge-db-readback.json`, `edge-permission-readback.json` and
`live-ui-readback.json` under `outputs/hr-readiness/`. An earlier screenshot named
`edge-status-fixed-verified.jpg` caught a pending Queued paint; it is not the final
verified screenshot. The final image was separately visually inspected.

Cleanup completed: owned tab/preview/API/synthetic terminal stopped; the original
target-lifecycle finalizer removed its exact database. A separate read-only census
verified that exact name absent and zero remaining sessions, without FORCE.
Only the owned HR PostgreSQL container was stopped afterward; Docker and unrelated
containers were left running. The installed reader's six hashes and task definition
still match. See `edge-cleanup-verified.json` and
`reader-preservation-edge-final.json`.

## Remaining deployment and physical gates

1. Integrate the isolated candidate with latest verified deployment source and
   rerun affected combined checks. Local Docker/PG, Linux-policy and Edge gates
   above are now complete for the identified tested source.
2. Keep the real-person pilot deferred as the owner requested; no physical grant,
   biometric enrollment, revoke, restore, deletion or passage was tested here.
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
