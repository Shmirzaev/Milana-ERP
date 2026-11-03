# Turnstile employee management: plan and UI task packet

Date: 2026-11-03. User request and accepted corrections remain authoritative.

## Scope and decisions

Attendance reading already exists. Add/manage a turnstile person is not ERP login management.
The owner requested a running ERP UI on the existing synthetic development database copy,
after other agents finish pushing. Owner then explicitly authorized starting.

Accepted decisions:
- Explicit **Apply to turnstiles**, with selected target devices; HR Save does not synchronize.
- HR archive and gate access revoke are separate actions.
- Both systems remain operating, including the existing attendance reader and the other writer.
- Preserve the full plan and follow routes -> models/people business operations -> schema-owned
  persistence, typed DTOs/enums, one operation at a time and independent review.

## Historical operation: prepare and review a gate-access change (UI preview)

Base: clone_main 75cf9c53930bdf3508e0d8a38f755a0aa6737a0b (latest pushed when work began).
Checkout: /home/ismoil/workspaces/turnstile-access-20261103, isolated clone, no shared writer.
Runtime: /home/ismoil/workspaces/turnstile-ui-runtime-20261103, Compose project
milana-turnstile-ui107, frontend 127.0.0.1:13079, backend 127.0.0.1:18079.
Database: independent copy of the development synthetic database, not production data.
The original milana-devqa107 containers/volumes/source remain owned by their existing task.

Engineering domain owner recorded in repository: Dilmurod; human reviewer: Mirshoir;
business acceptance: Shavkat/operators. Codex implements this isolated preview; independent
AI review is required before any AI-verified claim. No human approval is inferred.

Owned code: focused frontend HR preview components/types/copy, small employee-page entry
points, this task packet and preview-specific verification. No backend mutation API,
database schema, connector allowlist or live device protocol is changed by the UI operation.
Preview is disabled unless NEXT_PUBLIC_TURNSTILE_UI_PREVIEW=1. Its simulated results never
constitute device acceptance. It reads devices through the existing authorized Attendance API.
Photos remain in memory; simulated metadata is scoped by actor/factory/employee in sessionStorage.
No face recognition, pose detection, eye detection, liveness or server validation is claimed.
The visible checkboxes are manual review guidance only. At this historical preview stage, real enrollments were unimplemented.

UI acceptance: existing HR employee -> Turnstile access -> choose operation -> camera/upload
where needed -> photo review -> device selection -> review -> explicit confirmation -> show
per-device simulated outcomes including waiting -> simulate reconnect -> reopen/refresh.
Require real stored employee number, respect preview management permissions and archived status;
do not submit HR changes when opening/closing/applying a gate preview. Check EN/RU/UZ and exact
390px mobile, cancellation, bad uploads, camera failure, storage failure and unchanged DB history.

## Existing implementation and evidence

Source traced at 1a067b01 and verified unchanged for relevant files at 58bca549. Revalidate
overlaps against this new 75cf9c53 base before changing a later operation.
- api/routes/hr.py: factory-scoped create/update/archive; DELETE archives, no gate operation.
- frontend HR employee page: profile JSON photo_url, stored number or displayed padded fallback.
- api/routes/hr_workspace.py: active HR employees match event external_person_id to employee_no.
- schemas/people/attendance.py: device/person mirror and event tables, not HR enrollment bindings.
- api/routes/attendance.py: token-authenticated people/events/photos ingestion; device-scoped
  UID uniqueness, source-version protection, presence tombstones and protected photo responses.
- models/attendance_event_policy_service.py: explicit success and legacy null are counted.
- Attendance overview merges lanes by external ID and uses first/last scan; minimum one-minute
  span for departure. HR attendance currently lacks that same minimum-span rule.
- connectors/hikvision_attendance/read_only_connector.py: LAN Windows polling, pinned TLS,
  Digest, XML/JSON fallback, only three search POSTs, no person/face writes.
- Source schedule: every minute; five-minute event overlap; roster/photo refresh 24 hours.
- Existing photos become WebP. They are display copies, not verified enrollment assets.
- Employee alias helpers reserve numbers from reviewed consolidations; never merge by name.
- Source migration head inspected: 0149_besttex_cutting_access. Live migration state unknown.

Historical Aug18 records mention six Hikvision lanes, 1500 profiles/lane, union1507,
1183 usable designated-source photos and old ERP remaining writer. These are historical
documentation, not current runtime measurements. Exact hardware/firmware remains unknown.
The meeting's "tools delivery", "expired pictures" and "link field" are unverified terms.

## Subsequent operation boundaries and implementation

1. Confirm/adopt identity bindings. Define employee/factory/device/external-ID relation,
   uniqueness, aliases/collision refusal, ownership evidence, immutable historical identity
   and no first-release ID recycling. Do not silently use padded IDs or renumber terminals
   when an HR number changes. Preserve raw events and legacy unbound attendance behavior.
2. Add access. Reviewed person/photo/access policy -> durable operation and per-device targets
   -> separate narrowly scoped factory-LAN provisioning worker -> vendor acceptance/readback.
3. Edit details. Explicit reviewed patch, only owned fields, preserve other credentials/rights.
4. Replace photo. Immutable validated asset version; keep prior usable asset until confirmed;
   distinguish per-device partial completion. Do not assume device readback is byte-identical.
5. Revoke. Exact person/device selection and explicit confirmation, completion/readback;
   preserve HR/payroll/attendance history. Archive stays separate.

Each operation freezes its candidate, passes automated/PostgreSQL/browser/readback/stress,
gets independent review, then goes to human acceptance before advancing its completion state.

Code belongs in thin api/routes/turnstile_access.py; business rules/queries/authorization/
outer transaction in models/people/turnstile_access_service.py; definitions and typed writes
in schemas/people/turnstile_access.py plus companion persistence operations (same supplied
Session, no helper commit); contracts in libs/dto/people/turnstile_*; fixed vocabulary in
libs/enums/people.py and genuinely shared internal contracts in libs/types/. Register mappings
in schemas/__init__.py. No services/ directory, duplicate ORM mapping or generic CRUD framework.

Proposed additions: employee-device bindings, private photo assets, operation headers and
per-device targets. Record capability/firmware evidence on devices. Reuse actor/factory-scoped
idempotency and existing audit persistence, with no biometric bytes/secrets in logs.
Review composite factory integrity, unique external IDs/device and employee/device bindings,
state/revision constraints, queue indexes and history-preserving FK/delete behavior.

APIs: employee gate-access read; photo validation; explicit operation submission (202 with ID);
operation read; controlled retry/reconciliation; separately authenticated worker lease/result.
New proposed permission attendance.provision is not automatically granted by existing
attendance.view/manage or HR/payroll roles. Backend enforces actor, factory and target scope.
The UI preview uses existing management permission solely to enable simulation, not as a
decision granting future production enrollment authority.

## Durable external work and coexistence

Commit intent/targets/idempotency/audit before network dispatch. Do not hold DB transactions
over device IO. Serialize relevant work per terminal/person; fence worker leases/callbacks.
States: queued, in_progress, verifying, retry_wait, succeeded, failed, conflict, uncertain,
cancelled (proposed canonical vocabulary). Bounded backoff for safe transient failures.
A timeout after send is uncertain; reconcile before replay. A lease expiring is not proof
the write did not execute. Prevent old pending enrollment restoring access after revoke.
Never roll back successful terminals automatically because another terminal failed.

Keep the current reader unchanged. Use a separate provisioning worker and credential boundary,
outbound command pull from the factory LAN; ingestion token cannot execute commands.
Read current profile before write, compare approved baseline, preserve unmanaged fields,
read back and surface drift from the other system. No background overwrite loop. Verify
the other writer's periodic behavior. Simultaneous same-field edits need coordination where
hardware does not offer conditional writes; read-before-write alone is not atomic.

## Hardware and photos: unresolved evidence, not invented support

Official Hikvision references describe person add/modify/delete, asynchronous delete process,
face add/update and application-level responses. They do not prove support on installed devices.
Obtain exact model/firmware and matching official guide; verify capability requests, auth,
ID encoding/length, access rights/validity, image constraints, errors and readback.
No production turnstile is contacted from VM107. Use simulator then approved development device.

Camera/upload guidance: straight face, open eyes, framing/clarity and accessible errors.
Future server validation independently decodes bounded images, normalizes orientation,
checks format/dimensions/bytes and validates face count/quality/pose. Match actual vendor
requirements. Review dependency license, model license, deployment size/CPU and measured errors
before selecting vision technology. Quality is not identity verification or liveness.
Private immutable assets, authenticated reads, retention/deletion and safe replacement are
required before rollout. HR photo_url is not a trusted server-side fetch source.

## Verification ledger and rollout

Existing tests to extend later: test_attendance.py (merge/scans/isolation/photos),
test_attendance_historical_profiles.py, test_attendance_import_races.py,
test_attendance_source_versions.py, test_attendance_photo_upload_lifecycle.py,
test_hr_employee_number.py, test_hr_attendance_validation.py,
test_employee_archive_besttex_teams.py, connector test_read_only_connector.py,
test_event_checkpoint.py and test_sync_stage_isolation.py.
New scenarios: aliases/missing/duplicate IDs, factory/permission denial, retries, stale edits,
concurrent workers, crashes around dispatch, offline/partial results, uncertain outcomes,
superseded photos, async deletion, other-writer conflicts and attendance/history preservation.
Real isolated PostgreSQL verifies migrations, constraints, locking and recovery; no opt-in
skip counts as PASS. Rootless Docker/simulator uses only synthetic fixture data.
Actual desktop/exact390 mobile EN/RU/UZ visual QA includes console/network and DB readback.
Independent AI review then human local acceptance; separately authorized production rollout.
Rollback cannot undo already-written device profiles. Keep reconciliation/recovery evidence.

Current runtime facts still requiring an approved administrative environment: exact deployed
revision/manifests/migration state; aggregate employee number quality and factory distribution;
inventory/freshness; multi-device profile differences/orphans; photo availability and writer
configuration. Use bounded read-only transactions with timeouts; no production photo/data export.
Remaining business choices: approved gate/access-plan/validity policy, role grants, biometric
retention, and coordinated editing rules with the other writer. Not blockers for this UI preview.

## Evidence state

IN_PROGRESS. UI-only preview is not a completed enrollment feature. Append exact source hashes,
commands/results, screenshots, database fingerprints, independent review and human checklist
after actual verification. No push/merge/deployment is part of this preview request.


## UI preview verification - 2026-11-03

**AI_VERIFIED_AWAITING_HUMAN for the UI preview only.** The full device-enrollment
feature remains IN_PROGRESS, with the backend operations and hardware evidence above pending.

Exact base: clone_main 75cf9c53930bdf3508e0d8a38f755a0aa6737a0b. The code is uncommitted
in the dedicated checkout; no push, merge or production deployment occurred.
Independent AI reviewer: /root/review_turnstile_ui, read-only review of exact final component
a83840eccb3af3b0e0300f51b7024d67b58ff92b0d79a4b0c36a9de60cfe7efe.
Findings corrected: focus transitions, historical pending recovery, stale overlapping operations,
late camera callbacks, neutral superseded presentation and initial focus preserving the title.

Automated checks: full frontend TypeScript --noEmit --incremental false and focused ESLint
passed with zero errors/warnings. Private qa_visual + connected Chrome tested invalid uploads,
camera-unavailable fallback, required manual checks, explicit confirm/apply, partial results,
reconnect, reopen, separate revoke, history selection/superseding, missing number refusal and
frontend viewer restrictions. No enrollment HTTP endpoint exists in this preview.
EN/RU/UZ each measured screen/inner/client/scroll width390; screenshots inspected with vision.
Native desktop screenshot and browser desktop screenshots inspected. No horizontal mobile
overflow. Console page errors, failed HTTP responses and external requests: zero.
Successful final QA lane was stopped through qa_stop. Development app containers stay running.

PostgreSQL readback: full-row fingerprints of employees(4), attendance_devices(4),
attendance_people(4), attendance_events(8) match before/after. Synthetic fixture setup is the
only business-data setup performed. Login activity is allowed on the copied synthetic user.
No schema/migration or real terminal writes; backend write/locking/stress gates are not
applicable to this frontend-only operation and are still required for later backend work.

The QA harness lives at scripts/verify_turnstile_ui_preview.py. Run it with the installed
VM107 Milana tools Python after starting the dedicated runtime. Runtime evidence lives in
/home/ismoil/workspaces/turnstile-ui-runtime-20261103/evidence/report.json and matching images.
The original shared stack remains running; only this task's confirmed-drained non-HOLD lanes
were closed. Earlier failed diagnostic runs are retained in runtime evidence and chat:
missing MCP initialization, file watcher exhaustion (owned web switched to polling), copied
origin rejected login (added only explicit preview localhost origins), screenshot/client
coordination, history badge assertion scoping and per-user PID exhaustion. No limits were
raised, shared observers restarted, HOLD budgets reset or production guard modified.

### Preview type/enum ledger

| Contract | Disposition | Producers/consumers |
| --- | --- | --- |
| GateAction | TypeScript Enum: enroll/edit/photo/revoke | buttons, simulation, session validator, labels/history |
| GateState | TypeScript Enum: verified/waiting/revoked/superseded | simulation, reconciliation UI, session validator, labels |
| Employee/device IDs and factory | Existing typed identifiers; not new enums | existing API -> typed props -> actor/factory/employee session key |
| Names/vendor/device key | Existing API text/reference data retained | read-only display and review |
| Employee.status | Existing contract retained; archived gates preview | no global People enum migration claimed |
| Photo review checks | Transient booleans, photo Blob/object URL in memory | capture/upload/manual review; no server validation claimed |

These are simulator contracts, not completed production DTO/DB enums. Future fixed values
must be canonical Python enums in libs/enums and used by actual DTO/persistence consumers.

### Human UI review

1. Open http://127.0.0.1:13079/hr/employees through the development SSH forward, using the
   existing synthetic QA login (private file, never committed).
2. Choose Turnstile access for Preview - Employee001. Review photo upload/camera fallback,
   manual guidance and per-device selection; test confirm/cancel before applying a simulation.
3. Select all four devices: three complete, one waits. Reconnect the waiting target, then
   reopen/refresh and inspect history. Photos deliberately do not persist.
4. Try detail/photo/revoke tabs, older result selection, missing-number employee refusal,
   English/Russian/Uzbek and exact390px phone layout. HR archive remains separate.
5. Record approval or requested changes for this exact UI build. This is not hardware,
   production acceptance or permission to land/release the full feature.

Runtime-only frontend/node_modules symlink and generated next-env.d.ts are excluded from
the source handoff archive and any future staging. Reconcile latest clone_main before landing.


## Owner-authorized source publication

On 2026-11-03 the owner explicitly requested pushing this preview to clone_main and
opening the running development ERP while signed in. This authorizes source publication,
not production activation or a claim of hardware/operator acceptance. At this preview publication stage, the UI remained
disabled unless NEXT_PUBLIC_TURNSTILE_UI_PREVIEW=1; enrollment APIs were pending.
The uncommitted/no-push statements above describe the earlier verification snapshot.

Publication preparation normalized CRLF to LF in owned source/test files only; logical
source is unchanged. The hashes above identify the earlier raw verification snapshot.


## Backend development authorized - 2026-11-03

Owner explicitly approved frontend and requested backend implementation with multiple low-reasoning Terra agents and independent review. First operation is Add access (ENROLL), preserving explicit Apply, separate archive/revoke and both ERP systems. See [backend task packet](TURNSTILE_ACCESS_BACKEND_20261103.md) for exact source, ownership, typed/write ledger and evidence gates. Backend remains IN_PROGRESS; live hardware writes are not enabled.

Backend ENROLL simulator slice is now AI_VERIFIED_AWAITING_HUMAN; final technical evidence and the exact human local checklist are in the backend task packet. This does not mark the full turnstile integration or later business operations complete.

Owner authorized pushing the backend slice on2026-11-03. Publication reconciles latest clone_main54a51d79 and uses turnstile migration0151 after upstream package-customer migration0150. Earlier0150 gate evidence is historical; combined publication checks are recorded in the backend task packet.


## Simulator EDIT details candidate — 2026-11-03

The subsequent private simulator candidate supports ENROLL and name-only EDIT on
selected verified bindings when the server advertises each action. EDIT requires no
photo upload or face-review attestation: it preserves each device's existing photo and
external identity. The operator reviews the prior device name and confirms selected
revision/profile-hash references; changed or stale evidence is refused. HR Save and
archive remain independent, and existing attendance ingestion and the other ERP writer
remain in place. At this EDIT slice, PHOTO replacement, REVOKE, adoption and live hardware
were not implemented.

The 202 EDIT endpoint uses the existing provisioning permission and actor/factory
scope. The service freezes trusted complete baseline evidence under locks and calls
same-session schema persistence; the simulator's conditional update refuses drift.
Migration 0152 adds guarded EDIT baseline storage and refuses downgrade if EDIT history
or baseline data would be lost. The public actor/factory/employee/action-scoped request
receipt lookup reconciles a saved idempotency key; unanchored history is not proof of
acceptance. An uncertain response retains the journal and requires read-only lookup
before any explicit same-key retry. A later refusal cannot erase an earlier unknown
outcome. Recovered operations outside the context history window use operation readback.

The reported candidate checks include 97 automated tests, PostgreSQL races, a full
frontend build, private simulator visual checks in EN/RU/UZ and aged-receipt recovery.
Full configured Ruff and independent boundary review passed. This operation is
AI_VERIFIED_AWAITING_HUMAN; these checks do not imply human technical or
operator acceptance, production release, or real-device support. Exact source, evidence,
limitations and human checklist belong in the [EDIT task packet](TURNSTILE_EDIT_DETAILS_20261103.md).


## Simulator PHOTO replacement candidate — 2026-11-04

The owner authorized continuation to the private simulator PHOTO slice. Verification is
**IN_PROGRESS**; the earlier ENROLL and EDIT evidence remains historical and prior human
acceptance gates are unrecorded. The candidate requires a validated immutable photo asset,
manual review attestation and explicit Apply to selected verified bindings. It shares
`GateEditTargetInput` and the context `edit_baseline` revision/profile-hash review
contract with EDIT. Each device retains its own name and external identity; its prior
photo remains until that target durably accepts the replacement. Old and new asset rows
and files are retained. The PHOTO operation full_name is an informational HR snapshot,
not the target desired name.

The operation uses the existing same-session persistence boundary and migration 0152;
no new migration is required. The 0152 downgrade guard retains PHOTO baseline history.
Unknown acceptance is reconciled by readback, and the actor/factory/employee/action-scoped
receipt lookup matches the saved key, photo asset and exact target baseline references.
HR Save and archive remain separate; existing attendance reading and both ERP writers
continue. REVOKE, adoption and live hardware remain outside this slice. The forthcoming
[PHOTO task packet](TURNSTILE_PHOTO_REPLACEMENT_20261104.md) records source, evidence,
remaining gates and the human checklist; no production or human acceptance is inferred.
