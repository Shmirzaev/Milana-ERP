# HR readiness fixes — 9 November 2026

Status: AI_VERIFIED_AWAITING_HUMAN for the local fix set below. Full physical
turnstile management remains BLOCKED on implementation and business decisions.
No push, merge, deployment, connector activation or terminal writes.

User scope: fix the 7 November audit findings, test locally, and identify the
remaining inputs for deployment and physical Hikvision management. On 9 November
the owner explicitly authorized isolated work before later integration with the
latest shared source. Edge is the only authorized browser.

Base: `14f6670de874f66eba3112281ab5a8dd4f388280` (`origin/clone_main`), whose
application is `4f33eba776284b2e950e201a29c9da06cf7bd237`. Both production hosts
were verified on `20261109_035740`, manifest
`e5d56b822d8a48d327429a5e6a59cd87111b81bb193a2fd8cf120d007a7fafb1`.
The deployment owner's baseline-record correction landed before this worktree
was created. This task does not change that baseline or authorize a release.

Worktree: `C:/ERP/.codex-work/hr-readiness-fixes-20261109`.
Branch: `codex/hr-readiness-fixes-20261109`.
People/connectors engineering owner: Dilmurod. Technical reviewer: Mirshoir.
Implementation: coordinating Codex agent `/root`. Independent source review:
`/root/review_hr_scope`, a different Codex agent; no blocking findings remain.
Business acceptance: Shavkat/operators; not inferred from automated checks.

## Operation and evidence ledger

1. Organization creation: actual HR page -> `POST /api/hr/organization` ->
   `hr_workspace_service.create_org_unit` -> `OrgUnitIn` -> existing
   `HrOrgUnit` persistence/audit. Preserve all five canonical stored codes,
   permissions, factory scope and transaction behavior. Correct option values
   independently of translated labels, including initial `section` selection.
   Required: actual local EN/RU/UZ save/reopen/readback, invalid/denied rollback
   checks, scoped backend tests, frontend lint/types/build and independent review.
2. Repair the stale payroll employee-options verification script after the
   reviewed route/service/DTO moves. Keep its factory, page bounds, selected-ID,
   privacy and row-label checks. No payroll runtime behavior change.
3. Prepare and locally verify the current read-only connector upgrade. Preserve
   installed device keys, pins, DPAPI secrets, per-device state/cursors and the
   hidden task wrapper. Do not run initial setup over the existing installation.
   No scheduled-task or running-connector change is authorized in this local task.
4. Employee numbers, device-identity adoption and staffing setup require reviewed
   business data. Never infer employee identity from a name or fabricate numbers,
   staffing rows or access policy. Prepare explicit remaining-input evidence.
5. Real device enrollment/edit/photo/revoke remains a separate vendor integration,
   not a switch enabling the simulator in production. Await approved access policy,
   test person/device and coordination with the existing ERP writer. No live
   management or physical access acceptance can be claimed from simulator tests.

No schema migration, permission expansion or system-wide enum completion is
included. Existing organization codes and DTO validation are retained; no new
vocabulary is introduced. Other People tables and biometric retention/access-plan
policy remain owned pending work, rather than being silently marked complete.

## Validation

The 7 November audit remains historical evidence, including the broken translated
option values and displayed Company versus React's default `section`. The final
candidate changes only the option's explicit value; API/storage vocabulary and
authorization are unchanged. The auxiliary payroll verifier now reads the actual
DTO and service locations. The update stager and timezone dependency are new.

All evidence is under this worktree's ignored `outputs/hr-readiness/` directory:

| Gate | Final result |
| --- | --- |
| Linux backend / isolated PostgreSQL 16 and disposable SQLite | 505 passed, zero failed/errors/skipped; `backend-linux.xml`, 274.968 seconds |
| Fresh Windows connector virtual environment | 49 passed; `connector-tests.xml`; pinned requirements installed, `pip check` clean |
| Independent connector package test run | 5 passed using the fresh candidate environment |
| Actual connected Edge, local application | All five types saved in EN/RU/UZ, including untouched default Section; 15 saves survive reload |
| Direct PostgreSQL readback | Exactly 15 canonical MIL rows and 15 create audits, null parent/manager as requested; zero employees/devices created |
| Refusal and bounded read checks | Translated Team/Команда/Jamoa -> 422, missing parent -> 404, unauthenticated -> 401; no row changes. 20 reads / concurrency 4 / 10-second request timeout; p95 32 ms, max 47 ms |
| PostgreSQL simulator stress | Edit, photo and revoke scripts passed; idempotency/conflicts, constraints, audit rollback, CAS races, lease fencing, scope and unknown-result recovery; disposable targets finalized |
| Frontend | Full `npm run build -- --webpack` including prerequisite contracts and TypeScript passed; scoped ESLint and strict TypeScript passed |
| Supplemental frontend contracts | Turnstile enroll/edit/photo/revoke refusal/recovery bridges, repaired payroll options, HR employee pagination, employee-number payload and attendance Excel contract passed |
| Independent source review | Organization, verifier, requirements, staging tool/tests and upgrade instructions reviewed; README invocation clarified and exact timezone-path restoration checked |

Fresh environment: `outputs/hr-readiness/connector-venv/Scripts/python.exe`,
requirements `httpx==0.27.2`, `tzdata==2026.3`; test runner `pytest==9.0.2`.
The reviewer's first default-interpreter timezone test failed because that Python
lacked tzdata; the independent rerun in the dependency-installed environment
passed. This earlier environment failure is not silently classified as a pass.

Browser origin was `http://127.0.0.1:31169`, API `http://127.0.0.1:18169`.
Only loopback was published; the API used the dedicated container database
`hr_local_qa`. Screenshots `organization-default-en.png` and
`organization-saved-{en,ru,uz}.png` show the actual local UI. The browser emitted
development hydration warnings showing extension-injected `bis_skin_checked`,
`bis_register` and `__processed_*` attributes. Do not claim a clean console or
change the user's extensions. Initial screenshots caught a loading frame; these
were replaced with inspected settled-page captures. The browser gate used the
development server; an optimized-server launch was blocked by automatic command
policy, so no optimized-runtime browser pass is claimed. The optimized build
itself passed. The first private API launch also rejected a truthy
`PUBLIC_DEPLOYMENT=0` marker; the isolated private environment was corrected
before testing, without changing production security code.

The initial four-file read-only update was staged at
`outputs/hr-readiness/attendance-candidate/` with SHA-256 `UPDATE_MANIFEST.json`.
That initial connector source is `71ec1656631f2e55667dafc2de949d69a9fba893de92316bda0a8abe3154992a`.
The installed scheduled reader was not modified, stopped or upgraded. Activation
must preserve its six device keys, certificate pins, DPAPI files and cursors,
especially existing `main-turnstile` / `state.json` identity.

## Remaining work and owner inputs

These are unresolved, not passed or removed from the user's full-readiness scope:

1. **Software implementation:** a real LAN Hikvision write worker/adapter and a
   scoped credential/claim/result boundary, vendor capability validation, trusted
   physical-device readback/baselines and explicit adoption of already occupied
   identities. Current `disabled`/`simulator` modes do not provide this. Never
   enable the simulator in production or remove the occupied-identity guard.
2. **Business decisions:** approved door/access-plan and validity rules, an agreed
   handover from the existing ERP writer, and photo/biometric retention/access policy.
   The owner chose **Milana as the only writer after an agreed handover** on
   9 November. This settles ownership; it does not authorize stopping the old
   writer or performing live writes now.
   An employee name or an attendance roster is not proof of approved access.
   These decisions must precede a live implementation's final acceptance.
3. **Reviewed HR setup:** missing employee numbers, exact employee/device identity
   reconciliation, and organization/staffing assignments. No IDs or staffing rows
   were fabricated. Counts in the 7 November audit are dated baseline observations,
   not a fresh production recount in this local task.
4. **Supervised physical pilot:** the owner explicitly deferred the test identity
   to the end: "we can do it in last with me I will add my self". Do this with him,
   after the live integration and policy gates; do not request another test person
   or alter live access during this task.
5. **Release integration:** owner said to merge with the latest source later.
   Reconcile this patch with fresh `clone_main`, rerun checks on the combined exact
   commit, obtain QA-master/operator acceptance and deployment authorization, then
   follow `DEPLOYMENT.md`. The baseline was reconciled by the deployment owner;
   this branch does not edit it. Connector activation is a separate release step.

Human local checklist: open Organization in each language; confirm default Section;
save Company/Factory/Department/Section/Team and reopen; verify saved scope and
audit; inspect the read-only update manifest and private-file preservation plan.
Later physical checklist: enroll the owner's reviewed identity, verify terminal
readback and actual lane passage, edit/photo/revoke and offline/unknown-result
recovery without affecting another occupied profile. No human acceptance is
inferred from the AI checks.

Rollback of the application fix is an ordinary reviewed source revert; it does
not remove already-created organization rows. No production data or schema changed.
Local fixtures/evidence are retained; owned preview services are stopped at handoff.
No merge, push or deployment was performed; the commit containing this packet is
the local review candidate, not an approved production release.

Closing read-only checks found both production hosts still on `20261109_035740`
with the same manifest above. A fresh fetch still found `origin/clone_main` at
`14f6670de874f66eba3112281ab5a8dd4f388280`; no intervening overlapping changes
were found. The dedicated API/PostgreSQL containers are stopped, both loopback
listeners are closed and only the agent-created Edge tab was closed. The HR
candidate summary was mirrored to the existing Obsidian context note without
replacing its other contents. Independent AI evidence review confirmed the
results and this limited status. The explicit sole-writer answer is recorded
above; no handover time or live-write approval is inferred from the deferred pilot.

## Read-only hardware follow-up after the ownership decision

At approximately 11:12–11:13 Asia/Tashkent on 9 November, a bounded read-only
probe used the installed configuration and DPAPI-owned Hikvision credential,
without decrypting/using the ERP integration token. It validated configured
certificate pins and requested only device information, access-control capabilities
and face-library capabilities. There were no person searches, photo reads, device
writes, ERP uploads or state/cursor writes. Evidence:
`outputs/hr-readiness/hardware-capabilities.json` and `reader-task-status.json`.
The two retry log lines and final timeout are retained as tool-output excerpts in
`hardware-probe-attempts.txt`; the reviewed certificate-check loop raises on the
third failure. This records one probe with three attempts, not three separate runs.

| Lane / key | Current result |
| --- | --- |
| 1 / turnstile-73 | Pin, Digest authentication and all three GETs passed; V3.16.1 |
| 2 / turnstile-31 | Pin, Digest authentication and all three GETs passed; V3.14.0 |
| 3 / turnstile-91 | Pin, Digest authentication and all three GETs passed; V3.16.1 |
| 4 / main-turnstile, 10.100.50.41 | Timeout before certificate validation, after three bounded connection attempts; not a verified certificate mismatch or authentication failure |
| 5 / turnstile-115 | Pin, Digest authentication and all three GETs passed; V3.16.1 |
| 6 / turnstile-104 | Pin, Digest authentication and all three GETs passed; V3.16.1 |

All five reachable devices advertise UserInfo, card, face-library and user-detail
deletion support. This is capability evidence, not acceptance of a write action.
All advertise face-library `FDRecordDataMaxNum=1500` and `customInfoMaxLen=0`.
Current face occupancy/headroom must be checked before enrollment; the older
audit's 1,500 **people** is not automatically a current face count or proof of
full face capacity. Lane 2 advertises `isSuportFDSearch=false`, whereas the four
reachable newer-firmware lanes advertise true. The adapter must verify a supported
readback route per firmware and cannot assume a device-stored custom revision
marker or pass simulator evidence off as real terminal evidence.

The installed scheduled reader was Running at the observation (task result
267009 / 0x41301 means running, not successful completion). Lane 4's local state
file timestamp was 10:45:16; other state timestamps are in the evidence. File
timestamps alone do not prove ERP ingestion or diagnose the network fault.
Restore/check lane 4's power, LAN/IP and HTTPS reachability before a six-lane
physical acceptance test; do not repin its certificate or reset its state as a
workaround. The existing reader/task was left running and unchanged.

Next live-integration operation: confirm firmware-specific person/face readback,
freeze an explicitly approved access/validity policy and the sole-writer handover
contract, then implement the scoped LAN worker and occupied-identity adoption.
Before the handover, protect/export the existing device profiles and credentials,
verify recovery, and coordinate stopping the old writer in an agreed window.
The owner's own-profile pilot remains the final supervised test, not an approved
source of guessed rights or permission to delete an existing terminal profile.

## Later active-ERP preservation continuation

The owner subsequently reaffirmed that the previous active ERP must remain
connected during every test and supplied its `10.100.50.199:8443` address. The
bounded local reader transport hardening now has 136 passing connector cases,
including 87 new safety cases; a fresh 505-case backend run and frontend build
also pass. All six terminals were reachable at the later read-only rechecks and
the current installed reader/task remained byte-for-byte/configuration unchanged.
The owner manually signed into the old ERP in Edge. Its dashboard was inspected,
and the final browser observation returned to login. Current scan arrival there
still needs the actual attendance report or
operator confirmation. No handover or activation occurred. See the exact
[continuation evidence and remaining gates](archive/HR_ACTIVE_ERP_PRESERVATION_2026-11-09.md).
