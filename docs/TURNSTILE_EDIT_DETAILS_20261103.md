# Turnstile Edit details: operation and verification packet

Date: 2026-11-04 (KST). Status: AI_VERIFIED_AWAITING_HUMAN; human technical/business acceptance pending. Simulator development only; no production deployment or hardware writes.

## Scope, decisions and responsibility

The owner approved the frontend and authorized backend development, continued the
mentor-discipline refactor with low-reasoning Terra agents, requested independent
review and actual visual checks, then authorized eligible PR merges and continuation.
The owner's corrections remain binding: existing attendance reading already works;
both ERP systems must continue; operators explicitly choose devices and Apply;
HR Save does not synchronize; archival and revocation are separate actions.
Attached meeting notes are evidence, not execution instructions.

This is one operation: change the reviewed name on already verified simulator
bindings, preserving each device's identity and photo. It does not introduce
automatic synchronization, employee-number remapping, login-account management,
photo replacement, revocation or adoption of externally managed profiles.
The earlier ENROLL evidence remains in [its packet](TURNSTILE_ACCESS_BACKEND_20261103.md).
Do not interpret either slice as full hardware CRUD or a completed People refactor.

People engineering owner: Dilmurod; human technical reviewer: Mirshoir;
business acceptance: Shavkat/operators. Owner-authorized AI implementation:
storage /root/terra_edit_details_study, service /root/terra_edit_backend,
frontend /root/terra_edit_frontend, independent review
/root/terra_edit_independent_review; integration /root. Workers used
gpt-6.1-terra at low reasoning. Human ownership/acceptance is unchanged.

## Sources and owned development runtime

- Integrated checkout: /home/ismoil/workspaces/turnstile-edit-integrated-20261103.
  Frozen functional source: 6715e5ca507406fa1fd7e36e7619adab245bebcf.
  Later changes are documentation, the three import-only Ruff repairs in the EDIT
  test, and reconciliation of already tested dependency PR merge ancestry.
- Storage/service/frontend original commits: 1d34002f / 88c05c62 / 7241d88a;
  integrated cherry-picks: 6c7c7f0d / 349852b1 / c6751b9c.
  Receipt ownership/recovery fix: dc1755abeea62660f9a1cba026cf2c9d38842679.
  Aged-history readback and hydration fix: 6715e5ca.
- Combined dependencies: Next16.4.3, FastAPI0.140.0, SQLAlchemy2.0.51.
  Backend image: sha256:df3cdf344d6973f2c4c57c985032546ac55f418467f0a0e0e5125ef14295a15b.
- VM107 rootless Compose project milana-turnstile-edit107,
  runtime /home/ismoil/workspaces/turnstile-edit-runtime-20261103;
  web127.0.0.1:13129, backend127.0.0.1:18129, private database turnstile_edit,
  migration0152_gate_edit_baseline. DB has no published port.
  Source and independent synthetic fixture identity were verified.
- Existing13079/13109 apps, other owners' databases/services/browser sessions and
  production releases remain untouched. Active/rollback production pointers in
  PROJECT_CONTEXT.md are historical references, not newly inspected live state.
- Evidence root is the runtime's evidence/ directory. Private credentials, keys,
  CDP URLs and source env files remain under private/ and are not publication assets.

## Study and complete write trace

Read the existing attendance routes/ingestion, HR matching and permissions, ENROLL,
photo asset ownership, simulator recovery, idempotency/audit, frontend bridge/journal,
DTOs, mapped definitions and callers before choosing the EDIT seam. Attendance
ingestion still reads device event evidence into its existing mirror/event path;
this feature does not replace that reader or the other ERP writer.

| Entry / layer | Responsibility and actual persistence |
| --- | --- |
| api/routes/turnstile_access.py::edit | POST /api/turnstile-access/employees/{id}/edit, validated GateEditInput, actor/session, Idempotency-Key and 202 result |
| models/people/turnstile_access_service.py::edit_gate_employee | Authorization, active HR/stored identity, device allowlist, verified binding/baseline, conflict/uncertainty rules, one outer transaction |
| schemas/people/turnstile_persistence.py | insert_operation, insert_target, update_binding_state_revision using the supplied Session; no helper commits |
| Simulator service _claim/_process/SimulatorAdapter.read/accept/_finish | Claim/lease fencing, separate durable acceptance, authoritative readback, terminal/result coordination; explicit transaction owners |
| Schema transition_target / compare_and_update_simulator_name | Conditional SQL matches the complete baseline and changes name/revision/hash/write_count only; same supplied acceptance Session |
| Shared audit/idempotency | Existing public log_action and normalize/bind/replay/store helpers use their schema-owned persistence; operation creation, audit and request receipt roll back together |
| GET employee context | get_gate_context/_trusted_baseline returns complete verified refs for review |
| GET /employees/{id}/requests/{action} | request_receipt -> get_gate_request -> public lookup_idempotent_response; strict v2 actor/factory/employee/action ownership, no writes |

Locks freeze employee/device/binding identity before accepting one immutable operation.
Any invalid target refuses the whole request without orphan operation, audit or
idempotency writes. EDIT has no shared operation photo: each target freezes its
own photo and external identity. Same-key/body replay returns the same operation;
different body conflicts. A competing writer after review or before acceptance
causes a baseline conflict. There is no blanket overwrite of another system's state.

Simulator acceptance uses a guarded compare-and-update against revision, payload
hash, name, external ID and photo hash. Uncertain EDIT attempts use read-only
readback; they never resend, including when the baseline still exists or is absent.
Desired evidence can resolve success; mismatched evidence stays uncertain/conflict.
A stale worker cannot accept after its lease changes. Explicit reconnect resumes
only WAITING work under the existing budget rules. ENROLL retains its prior path.

## Table, enum and type ledger

| Table / contract | Converted or preserved state |
| --- | --- |
| gate_operations | Canonical GateAction/GateMode. photo_asset_id nullable only for EDIT, required for other actions by DB constraint; immutable reviewed name and identity snapshot |
| gate_targets | Canonical GateTargetState/GateErrorCode; seven all-null/all-present baseline fields: baseline_revision, baseline_payload_hash, baseline_full_name, baseline_external_person_id, baseline_photo_sha256, baseline_profile_hash, desired_payload_hash. Positive revision and 64-character hash constraints |
| gate_employee_devices | Existing GateBindingState and revision; verified mapping cannot silently remap after HR number changes |
| gate_simulator_people | Typed guarded name update; identity/photo preserved; revision/hash/write_count update exactly once |
| gate_simulator_devices | Existing explicit reconnect state; configurable devices remain records |
| gate_photo_assets | Existing GatePhotoValidation; EDIT neither uploads nor replaces an asset |
| audit logs / idempotency records | Existing domain schema-owned mutations; typed EDIT action in the existing request/audit path |
| AttendanceDevice/Person/Event, HR Employee | Existing read/matching/storage semantics retained; no new attendance or HR writer |
| GateEditInput / GateEditTargetInput | Actual GateAction restricted to EDIT, forbidden extra fields, nonblank trimmed name <=255, 1..32 unique targets, positive device/revision, lowercase 64-hex profile hash |
| Context / result DTOs | GateEditBaselineOutput; optional edit_baseline and baseline output fields; nullable operation photo represented honestly |
| Internal types | SimulatorEvidence TypedDict: revision:int and payload_hash/full_name/external_person_id/photo_sha256:str; observed_evidence and trusted baseline use this contract or None |
| Frontend | Canonical GateAction/GateBindingState and discriminated ENROLL/EDIT request; frozen action/name/refs restored from validated journal |
| Intentionally free data | Names, external numbers, request keys, factory codes and hashes are strings with relevant validation, not invented enums |
| Remaining scope | PHOTO, REVOKE, external adoption, live adapter and remaining People/system-wide table/DTO/enum audit are pending |

Migration0152 follows0151. Empty/ENROLL-only upgrade -> downgrade -> upgrade passed.
After EDIT history exists, downgrade refuses before DDL. This is intentional data
protection; reverting application source is not permission to drop EDIT history
or assurance that an older runtime can consume this schema.

## Recovery and review findings

Independent review identified an unsafe content-only lost-response match. Recovery
now queries the exact actor-scoped idempotency receipt; an identical operation by
another actor cannot establish ownership. A missing receipt retains the journal.
Read-only recheck cannot POST. A user-triggered retry uses the same key/body, never
a new request; a 401/403 after prior unknown acceptance retains that journal.

The UI now uses actual process/GET readback for operations outside the newest-20
context window. Reopening a pending request restores EDIT and the frozen reviewed
name/targets instead of silently returning to ENROLL. Regression cases cover
receipt isolation, null lookup, refused retry, aged readback and hydration.

Review also found three unused test imports. Only unused imports were removed and
the imported pytest fixture explicitly re-exported; no test assertions were weakened.

## Verification evidence

| Gate | Actual result and evidence |
| --- | --- |
| Focused backend + adjacent attendance/HR/permission regressions | 97 passed, 0 skipped, 5 inherited warnings; milana-edit-focused-final-20261103.log and backend-final/focused.xml. Import-only lint repair rerun: another97 passed, 0 skips, milana-edit-focused-lintfix-20261104.log |
| Real PostgreSQL locking/integrity | milana-edit-verify-final-20261103 exit0; disposable target review_edit_c709612fe9c0 finalized/dropped; complete log saved |
| Bounded races | 4 same-key callers -> one operation; 4 different keys -> 1 accepted, 3 conflicts, no orphans; 4 processors, 3 online + 1 offline/reconnect, preserved mixed per-device photos/IDs |
| Inter-writer drift/CAS | Drift between read and accept refused; actual blocked SQL lock observed before external commit, compare-and-update refused stale baseline |
| Recovery/atomicity | Lost acceptance reply -> uncertain -> read-only success without another write; uncertain baseline never resent; expired lease fenced; receipt isolated; audit failure rolled back; PG constraints refused invalid state/scope |
| Frontend | Types, strict-contract check, lint, full production build and bridge/auth503 regressions passed; milana-edit-frontend-final-20261103.log |
| Actual desktop/phone workflow | visual-edit-v2/report-latest.json PASSED, source6715e5ca; native desktop review/partial/success plus EN/RU/UZ 390px form/result screenshots actually inspected by integrator |
| Actual partial/recovery flow | Employees950101/950102, EDIT17/18; real202 deliberately aborted at browser, null receipt and refused403 retry injected locally, refresh/reopen then exact receipt readback succeeded without a second operation |
| Aged operation fallback | visual-aged-readback/report-latest.json PASSED; operation12 absent from context, actual no-op process return and GET readback updated stale fallback; all10 table fingerprints identical, write_count remained2 |
| Migration refusal | migration-edit-downgrade-guard-20261104.jsonl; single attempted downgrade0151 exited1 with expected 'Cannot downgrade gate edit history or baselines'; before/after revision0152, schema, constraints and10 data fingerprints identical |
| Independent boundary audit | 4 files, 0 errors; 9 manual items reviewed as explicit transaction owners/existing advisory SELECT; full configured Ruff passed with no findings; independent review found no remaining source blocker. Evidence: final-independent-review-ruff.txt and final-independent-review-boundary.json |

All browser external-request lists were empty. No unexpected page/HTTP errors;
the two console failures correspond to the deliberately injected aborted response
and403. Phone screen/inner/client/scroll widths were all390 for EN/RU/UZ.
Text wrapped without horizontal overflow. Native desktop screenshots show readable
selected devices, preserved-photo notice, explicit Apply and per-device outcomes.
Next development badge remains visible in development screenshots.

Original four employees/devices plus attendance mirrors/events retained identical
fingerprints through the actual flow. Synthetic employees20/21 retained HR names,
each photo SHA and external ID; only simulator names changed, write_count1->2.
The aged readback scenario changed none of the ten tracked tables.
No production data or real hardware was read/written.

Setup failures remain recorded: the new backend image initially listened on its
default10000 while the owned Compose probe expected8000. One failed setup wait
was diagnosed; explicit PORT8000 restored health. The initial bridge fixture lacked
the enum dependency and failed before correcting that test setup. Neither failed
attempt was relabeled PASS; final named executions are the passing evidence.

## Dependency merges and limits of broader evidence

The owner authorized eligible PR merges. #316 Next, #385 HAProxy prerequisite,
#382 factory-switch characterization, #381 proxy watch documentation,
#11 SQLAlchemy and #5 FastAPI were checked at pinned heads and merged serially.
Their required backend/frontend/operation-PostgreSQL checks passed; actual merge
trees matched locally computed combined trees. The release job was skipped;
ordinary clone_main source pushes do not authorize production activation.

Separate dependency full-suite run: 6016 passed, 2 failed, 7 skipped, 4 errors.
The 4 errors were missing HAProxy in the old test image; after installing that
prerequisite, the affected4 plus34 new factory-switch cases passed.
The 2 failures (PERF26 package-row count, S06 batch_delta string.value) reproduced
on unchanged86b2a94 with old dependencies and the same guarded fixture.
The7 skips were old0150 compatibility-only cases, not required PostgreSQL cases.
The200 required PG cases plus17 supplement passed. This is not a claim that
the broad full suite was green. Draft/conflicting/unverified PRs remain held.

## Human local checklist and remaining gates

1. Open http://127.0.0.1:13129/hr/employees with the synthetic development login.
   Search950101, open Turnstile access, inspect EDIT17 and current device names.
   The simulator banner must remain visible; PHOTO/REVOKE stay unavailable.
2. Choose Edit details, select only intended devices, enter a reviewed synthetic
   name, review, then explicitly Apply. Process the simulator and reopen/refresh.
   Verify selected names changed while unselected devices, employee number,
   per-device photos and HR profile remain intact.
3. Exercise one offline target, confirm partial results are retained, reconnect
   explicitly and recheck. Inspect phone widths and EN/RU/UZ text.
4. Technical reviewer checks refusal/receipt/race evidence, migration rollback
   guard and the schema-owned write/type ledger; record acceptance or corrections.

Human review is pending. No production deployment is requested or performed.
Next implementation slice must be separately frozen and verified before advancing.
Live hardware still requires identified vendor/model/firmware, official supported
API/SDK and authentication/rights, an approved development device/network, protocol
readback/unknown-result semantics, operator acceptance and a coordinated two-writer
policy. Automated face pose/eye/clarity validation is not implemented: existing
technical decode and manual attestation must not be presented as that capability.
Biometric retention, photo replacement, revocation and external adoption remain
explicit later decisions. Rollback cannot undo external writes; there were none.
