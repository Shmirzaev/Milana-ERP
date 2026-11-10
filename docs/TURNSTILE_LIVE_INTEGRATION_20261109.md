# Real Hikvision integration — local implementation

Historical 9 November evidence below is preserved. See the
[10 November compatibility follow-up](TURNSTILE_FIRMWARE_COMPATIBILITY_20261110.md)
for the corrected native error interpretation, optional capability contract,
new-base test results and current deployment gates. The five idle deletion
responses no longer establish an unsupported endpoint; lane-31 remains refused.

9 November 2026. Local code candidate; browser checks owner-deferred; physical
enrollment/deletion compatibility BLOCKED. No live device writes, activation,
push, merge or deployment. Do not label this AI_VERIFIED_AWAITING_HUMAN: the new
browser and physical acceptance gates have not passed.

Owner: Dilmurod; human technical reviewer: Mirshoir; implementation: Codex /root;
independent AI reviewer: /root/review_hr_scope. Shavkat/operator and QA-master
acceptance remain separate. Base: local 9a4ef3fc2 on codex/hr-readiness-fixes-20261109
in C:/ERP/.codex-work/hr-readiness-fixes-20261109. Fresh origin/clone_main is
14f6670de; both active release paths remain 20261109_035740 and match the baseline.

The owner explicitly requested finishing real integration and local testing, then
testing physical devices together later. The previous ERP must remain connected;
Milana becomes sole writer only after an agreed handover. He will add himself for
the supervised pilot. On 9 November he approved separate actions: Revoke disables
access while retaining the device profile; Delete device profile explicitly removes
its face/card/fingerprint credentials. Neither action deletes HR/history/payroll.

## Operation order and implementation boundary

1. Worker-scoped read-only observation and explicit reviewed identity adoption.
2. New identity enrollment with approved per-device access/validity and private photo.
3. Name edit and photo replacement against a fresh complete physical baseline.
4. Revoke without deletion, then separate deletion of an already revoked profile.

Restore is a separate explicit action: it grants normal entry only to an already
blocked profile with a verified single face and exactly the configured approved
access policy. It preserves other fields. This also provides a reviewed route
after a partial blocked enrollment: stop/reconcile the original attempt, review
the current identity, repair/verify its photo, then explicitly Restore. No retry
ever automatically resumes a partly dispatched enrollment.

Use dedicated live jobs/evidence rather than simulator profile/revision evidence.
Share existing employee/device bindings with an explicit mode discriminator to
prevent cross-mode ownership. Routes call People services; schema-owned functions
perform persistence in the supplied transaction. No migration of attendance rows,
employee identities or existing simulator history. Additive migration only.

The LAN worker resolves immutable device keys through a separate private local map;
the API never accepts arbitrary device URLs, credentials or endpoint commands.
Separate device-scoped worker tokens cannot be reader-ingestion tokens or user
cookies. Live writes require the global live mode, enabled backend device policy,
an explicit handover reference and employee allowlist, plus local worker approval.
All defaults keep writes off; no installer activates or changes the existing reader.

Commit intent before I/O; journal each dispatch durably before sending. No write
retry, endpoint fallback or automatic compensation after uncertainty. A device
without CAS cannot be physically fenced by database leases: uncertain/dispatched
work blocks later writes until the former worker is quiescent and reviewed
read-only reconciliation is complete. Results derive from vendor acceptance and
complete readback, never HTTP 200 or face-count presence alone. Photo byte equality
is a conservative verification requirement; hardware recompression or missing
readback stays unresolved for the physical pilot rather than becoming a false pass.

## Vocabulary and value inventory

Existing GateMode gains hikvision; disabled remains the default and simulator
remains forbidden in strict environments. Existing simulator action/state types
and storage remain intact. Live action/state/outcome values have canonical enums
and typed DTOs; JSON is used only for immutable structured physical snapshots,
approved configurable access policy and normalized request receipts. Employee
numbers, device keys, door/plan references and handover references remain data.
No access plan, validity window, identity or biometric policy is guessed.

## Required evidence

For each operation: meaningful local refusal/success/red-green tests, isolated real
PostgreSQL constraints/concurrency/recovery, connected Edge UI/save/readback and
bounded integrity/stress checks, then independent AI review. Worker transport is
tested against an isolated fake HTTPS terminal and explicitly labeled protocol
simulation; it is not physical acceptance. Preserve existing attendance reader,
task/configuration/pins/cursors and the active previous ERP. Device commands,
reboots, disconnect/deploy/settings changes and live profiles are out of scope.

Human pilot must verify actual firmware routes, face readback/capacity, passage,
both attendance reports, edit/revoke/delete, offline/unknown recovery and unchanged
other profiles. Deployment still needs latest-source integration, QA-master review,
supported immutable-image release/backup/rollback and separate owner authorization.

## Implementation and local verification

Common boundary: dedicated GateLiveDevice/Job/Profile tables; mode-tagged existing
identity bindings; frozen additive migration 0156. New /turnstile-live API handles
admin device approval/token issuance, employee intent/receipts, explicit adoption,
worker claim/single-use step permit/result/private photo, bounded never-sent retry
and administrator quiescent resolution. Simulator paths remain separate.

LAN source: connectors/hikvision_attendance/live_device.py and live_worker.py.
Both are excluded from the existing reader's update allowlist. The writer uses
per-connection TLS pins before HTTP credentials, Digest, no redirects/proxies,
exact protocol paths, DPAPI/write-through journals and no automatic write retry.
The old reader/configuration/task is untouched.

Initial checks: 24 backend observation/adoption/settings cases; 24 Linux protocol
cases plus one Windows-only DPAPI skip; 25 Windows protocol cases including actual
DPAPI encryption; 3 backend-to-worker-to-fake-HTTPS integration scenarios covering
full seven-action lifecycle, adoption/drift and uncertain-write resolution passed.
At that checkpoint the full regression, PostgreSQL concurrency, browser/readback,
stress and independent final review were still pending. Final code evidence is
recorded below; the owner later deferred browser checks and physical gates remain.
Initial Linux protocol run failed for missing test-only cryptography; the isolated
test dependency was installed and the rerun passed. This was an environment failure,
not physical hardware evidence. Test dependencies currently cryptography 50.0.2
and Pillow 13.0.0 on Windows; product reader requirements are unchanged.

Native protocol references: Hikvision's official [access-control ISAPI reference](https://open.hikvision.com/hardware/v2/08%E5%8D%8F%E8%AE%AE%E9%80%8F%E4%BC%A0/%E6%98%8E%E7%9C%B8%E9%97%A8%E7%A6%81.html)
and [face remote-configuration reference](https://open.hikvision.com/hardware/v2/%E6%8E%A5%E5%8F%A3%E5%AE%9A%E4%B9%89/NET_DVR_SendWithRecvRemoteConfig%28ACS_USERFACE%29.html).
Hardware model/firmware acceptance is still pending. Enrollment requires a reliable
face-capacity query and advertised/verifiable nonprivileged security flags.
Missing capabilities refuse before creation. Unexpected flags or missing exact
photo readback after a dispatch leave an uncertain operation, rather than
substituting person counts or face-present booleans for proof.

Independent final review found and verified fixes for stale ORM job state after
lock waits, separate deletion-completion/credential proofs, synchronous UI
submission guarding, receipt recovery before clearing refused replays, truthful
profile-type labels, default-off immutable build wiring and lane failure isolation.
The reviewer independently reran 20 service cases, 56 writer/stager cases, then
the last 2 reservation and 9 protocol cases. No human review is inferred.

## Actual hardware reads and open firmware gates

Read-only pinned HTTPS probes on all six devices at 14:57–14:58 Tashkent verified
face capacity and exact existing-person face/card/fingerprint inventories against
the native profile counts. The older V3.14 device also passed. A sampled profile
on lane 115 has one fingerprint and no face; the others sampled have one face.
No employee numbers, names, card values, fingerprint/face model data or image
bytes were retained by those probes. FDLib Count reported 1396–1399 blackFD
records against the previously advertised 1500-face limit.

The earlier face-search HTTP 400 was caused by a wrapped JSON request. Corrected
root-level `FPID` requests work, including exact identity matching where a face
exists. The product worker now uses this shape with no write fallback/retry.
Repeated authenticated HTTP errors also revealed urllib's retained Digest retry
counter; each independent request now starts a fresh bounded challenge budget.
A same-instance test sends eight HTTP 400 responses, then authenticates a good
read. This never repeats a failed physical command.

Two unresolved factory-device gates remain:

1. All six sampled profiles omit `doubleLockRight`; their user capability result
   advertises `localUIRight` but not `doubleLockRight`. New enrollment now refuses
   during capability preflight, before creating a blocked profile. Vendor-supported
   evidence for the unsupported flag or an alternative exact security readback
   must be reviewed before changing that rule. Absence is not assumed false.
2. All six return HTTP 404 for `UserInfoDetail/DeleteProcess`. Existing-identity
   credential reads work, but the main device returned HTTP 400 for the synthetic
   absent-identity queries. Verify the firmware's supported completion and negative
   credential-read semantics before permitting deletion. The current strict worker
   refuses before a delete when progress verification is unavailable; HTTP 400/404
   is never interpreted as proof that credentials were erased.

Exact JPEG readback, actual passage and add/edit/photo/revoke/restore/delete on
factory hardware remain for the supervised pilot. These successful reads are
not physical-write acceptance or proof of continuous scans from every door.
The earlier old-ERP receipt evidence remains the two door-3 events at 13:04:25
and 13:06:34; this task did not change that ERP or any terminal settings.

## Recovery, release and owner decisions

Separate Revoke and Delete were explicitly approved by the owner. Restore is an
explicit grant against the exact approved policy and a verified face. Neither
HR archive nor device deletion removes payroll, attendance or audit history.
An exhausted never-sent request can be followed by a new fully reviewed request
using its exact same pending/unadopted reservation only when no prior dispatch
or mirror/profile evidence exists. Dispatched/deleted identities are not recycled.

The new frontend exposes saved-request receipt checks and bounded never-sent
retry. Its synchronous lock precedes key/journal creation; a refusal to replay
does not discard a possibly accepted request without scoped receipt lookup.
Administrator unknown-outcome resolution remains an operator procedure in
`connectors/hikvision_attendance/README_LIVE.md`, after proven worker quiescence
and terminal completion plus a fresh observation. It closes ambiguity as conflict,
never manufactures successful credential deletion.

Manual release workflows now accept default-false `turnstile_live_ui` and pass
the matching default-zero `NEXT_PUBLIC_TURNSTILE_LIVE` Docker build argument.
Runtime variables cannot enable an already compiled-off UI. This is preparation
only; no workflow was dispatched and no image was published here. The LAN writer
has a separate source-only stager/manifest and is excluded from reader updates.

Automatic policy rejected starting the loopback frontend preview with only
“blocked by policy.” The owner answered “Finish the code checks; visual testing
later.” No new browser screenshot/save/readback gate is claimed. The disposable
UI backend and fake terminal were stopped with zero device writes. Its fixture
generator cleanup initially retained a server thread; after stopping that exact
owned container, its exact recorded test database was removed only after proving
zero sessions/prepared transactions, without FORCE. Factory infrastructure was
not involved. Earlier collection failure from a missing copied backend/scripts
folder and Windows POSIX-path expectations in two release-script tests are retained;
the complete source copy and Linux release-script reruns supersede those attempts.

Before activation, obtain the vendor/firmware evidence above, the owner's chosen
test employee and target lane, approved door/plan/validity references and a limited
handover window in which the old ERP cannot overwrite that identity. Keep both
attendance readers connected. Then perform deferred EN/RU/UZ browser/save/readback,
actual passage and both-ERP scan receipt checks, failure recovery and unrelated-
profile preservation. QA master must review that exact build. Latest-source merge,
full CI/security/image publication, PostgreSQL backup, migration/rollback rehearsal
and supported blue/green deployment still require separate release authorization.

## Storage and vocabulary inventory

Scope: source definitions plus disposable PostgreSQL at migration 0156, not a
production-value audit. The three new tables have 42 columns; the existing binding
adds one mode column. No production rows were created or migrated by this task.

| Table / every scoped field | Fixed vocabulary and treatment |
| --- | --- |
| `gate_live_devices`: id, device_id, factory_code, enabled, writes_enabled, worker_token_hash, source_host, certificate_sha256, config_revision, configuration | IDs/factory/device references, pins/hashes, flags and positive revision are data. Configuration is validated `LiveDeviceInput`: allowlist, approved local validity and door/plan references, approval/handover references and library ID. No configurable reference is promoted to enum. |
| `gate_live_jobs`: id, requested_by, factory_code, employee_id, device_id, binding_id, action, state, request_key, request_hash, request, config_revision, baseline, desired_policy, photo_asset_id, photo_sha256, lease_token_hash, lease_expires_at, dispatched, dispatch_count, attempt_count, result_history, result_hash, result, created_at, completed_at | Action/state use canonical `LiveGateAction`/`LiveGateState`, SQL string checks, DTOs, services and frontend enums. Worker outcome/permit use `LiveGateOutcome`/`LiveWriteStep`. Request/policy/snapshot/result JSON come from typed DTO serialization; result history retains earlier typed result objects and attempts. Other fields are scoped references, timestamps, hashes and bounded counters/flags. Lease secrets are never persisted in result/audit JSON. |
| `gate_live_profiles`: id, binding_id, snapshot, profile_hash, observed_at, adopted | Snapshot is `LiveSnapshot`: fixed native user type uses `HikvisionUserType`; complete policy, exact photo digest, explicit credential counts and nullable security flags. Unmanaged native fields are hashed, not retained as passwords/card/templates. Other fields are identifiers, hashes, timestamp and review flag. |
| Existing `gate_employee_devices.mode` and consumers | `GateMode` gains `hikvision`; existing rows default to simulator. Existing `GateBindingState` is reused in typed output and frontend. Simulator baseline/edit guards refuse physical ownership. Existing operation/simulator mode SQL checks are extended without rewriting history. |

HTTP routes call the People service; schema-owned persistence participates in its
outer transaction, including audit. FKs protect employee/device/binding/photo
factory scope. Unique constraints protect identity, device approval and actor-
scoped receipt. Real PostgreSQL tests cover migration roundtrip, invalid vocabulary,
cross-factory writes, audit rollback, duplicate intent and serialized claims plus
four workers/96 attempts processing 24 unique jobs without duplicate dispatch or
attendance loss. The separate worker and TypeScript adapters deliberately mirror
the wire enum strings; they do not import backend application internals. Local
journal phases/CLI status are separate transport diagnostics, not business states.

## Final code-check result and handoff

- **553 backend tests passed**, zero skips/failures, including the 8 required real
  PostgreSQL cases, full seven-action backend/worker/fake-HTTPS lifecycle, scope,
  receipt, dispatch, retry, recovery, unchanged HR data and unrelated profile checks.
  Evidence: `outputs/hr-readiness/backend-live-final.xml` and corresponding log.
- **194 connector tests passed on Windows**, zero skips/failures, including real
  current-user DPAPI roundtrip, same-transport Digest error recovery, strict
  capability/count/readback gates, per-lane failures, reader preservation and
  separate source packaging. Evidence: `connector-live-final.xml`.
- **19 release/security-policy tests and 6 subtests passed on Linux**. The two
  POSIX-path expectations that failed on Windows passed there without source edits.
  Evidence: `live-release-contracts-linux.xml`; no CI/security image scan or image
  publication was run.
- Final frontend production build **passed with webpack and live UI enabled**;
  full TypeScript and scoped ESLint passed. The npm contract chain passed. Earlier
  local Next attempts failed for an unset API build variable and Turbopack's
  inability to resolve the shared Windows dependency junction; the configured
  webpack rerun succeeded. Browser interaction remains owner-deferred.
- Independent reviewer completed the final narrow review with no remaining source
  blocker, separately retaining the firmware, browser and human acceptance gates.
- The installed reader's six source/config/DPAPI/wrapper hashes and scheduled-task
  definition match the preservation baseline. Normal scheduled cursor advancement
  was not interfered with. The source-only writer package is staged in
  `outputs/hr-readiness/live-writer-candidate-20261109-final`, not installed or run
  against factory devices. Its five files and hashes are in `WRITER_MANIFEST.json`.

Worktree: `C:/ERP/.codex-work/hr-readiness-fixes-20261109`.
Branch: `codex/hr-readiness-fixes-20261109`; the final commit is recorded in the
local Git log and `outputs/hr-readiness/live-handoff.json`. Source hashes are in
`live-source-manifest.json`. Branch remains unpushed/unmerged. Production was not
deployed; last verified active release remains `20261109_035740`, app `4f33eba77628`.
Only synthetic disposable databases/files and staged local source were changed;
no factory employee, biometric, access right, attendance, payroll, old-ERP setting,
terminal connection or production database was changed.
