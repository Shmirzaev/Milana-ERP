# Simulator turnstile REVOKE — 4 November 2026

**Status: AI_VERIFIED_AWAITING_HUMAN for the frozen simulator operation.** Owner: Dilmurod;
technical reviewer: Mirshoir; operator/business acceptance: Shavkat. Functional source
freeze: `75083615` in `/home/ismoil/workspaces/turnstile-revoke-integrated-20261104`.
This is a guarded private simulator operation. No production deployment, real terminal
write, or human acceptance is inferred. The owner's latest instruction places the QA
master human check before deployment; it does not pause source integration or the next
refactor slice. Prior ENROLL, EDIT and PHOTO evidence remains historical, with their human
gates unrecorded.

## Contract and operation trace

An authorized actor with attendance provisioning and private HR access explicitly selects
verified ACTIVE simulator bindings, reviews each server-provided revision and complete
profile hash, then confirms REVOKE. The selected factory, stored employee number, known
identity, aliases, device configuration and complete latest successful evidence are
checked under the existing lock order. An archived HR employee remains eligible for this
separate operation. Pending or uncertain overlaps are refused. HR Save and archive do not
send gate writes; other ERP writers and attendance ingestion remain independent.

`POST /api/turnstile-access/employees/{employee_id}/revoke` accepts `GateRevokeInput`
(`GateAction.REVOKE`, stored employee number and unique `GateEditTargetInput` references),
requires `Idempotency-Key` and returns `GateOperationOutput` with status 202. The scoped
request receipt GET supports recovery by actor, factory, employee and action. It matches
the exact accepted operation and target references, not the informational HR name. A
null receipt or later refusal does not settle an unknown earlier submission; the journal
and same key/body remain available for explicit retry or read-only reconciliation.

The route delegates to `revoke_gate_employee`; the service owns one transaction and uses
schema-owned persistence on the supplied Session for operation/target inserts and binding
state/revision updates, plus existing audit and idempotency persistence. No device IO
occurs before request commit. Each target stores the complete immutable baseline and a
revoke-specific desired hash. The separate simulator acceptance transaction uses
`compare_and_revoke_simulator_person`, matching binding and all five baseline evidence
fields atomically. It changes only presence, accepted revision/hash and write count.

A `present=false` simulator row is a durable tombstone, not an active person. Its old
name, external ID and photo hash remain historical metadata; asset rows/files, employee,
attendance and history are retained. A revoked binding and its identity are not reused or
automatically re-enrolled. Existing `SimulatorEvidence` remains the profile shape;
`SimulatorRevocationEvidence` carries canonical REVOKE action, revision, hash, external
ID and false presence. Missing rows are not success evidence. An uncertain revoke only
reads: its exact durable tombstone settles success, changed present evidence conflicts,
and the original baseline or bare absence remains uncertain. Lease/revision fencing
prevents late callbacks; WAITING reconnect is separate from unknown acceptance.

## Schema and type ledger

Migration `0153_gate_revoke_tombstone`, after 0152, adds nonnull simulator presence with
true default/backfill and permits null operation photo for EDIT/REVOKE while requiring it
for ENROLL/PHOTO. It preserves 0152's seven all-or-none target fields:
`baseline_revision`, `baseline_payload_hash`, `baseline_full_name`,
`baseline_external_person_id`, `baseline_photo_sha256`, `baseline_profile_hash`, and
`desired_payload_hash`. Before DDL, downgrade refuses REVOKE operations, tombstones or
exact JSON action evidence; compatible history restores 0152. The preflight checks the
JSON action itself, not incidental profile text.

Fixed action, mode, binding/target state and error fields retain canonical `GateAction`,
`GateMode`, `GateBindingState`, `GateTargetState` and `GateErrorCode`. The new typed
revocation readback is distinct from the existing profile `TypedDict`; names, identity,
hashes and factory codes remain data strings rather than invented enums. No generic CRUD
framework or new permission was introduced. Live hardware, adoption/re-enrollment,
retention policy and broader enum audits remain separate work.

## Verification evidence

Evidence root: `/home/ismoil/workspaces/turnstile-revoke-runtime-20261104/evidence`.
The backend test image is a dependency image with the frozen source bind-mounted; its image
identity alone is not the source revision. PostgreSQL runs used separate owned targets.

| Check | Result and evidence |
| --- | --- |
| Focused backend and adjacent regressions | 113 passed, five existing warnings; `milana-revoke-focused-20261104.log`, `backend-final/focused.xml`. |
| Backend lint | Full configured Ruff passed; `final-independent-review-ruff.txt`. |
| PostgreSQL concurrency/recovery | `milana-revoke-verify-20261104.log`: target `review_revoke_472bb996b558` finalized; same-key four callers one operation, four distinct keys one accepted/three conflicts, four processors, blocking CAS and drift, lease fencing, unknown recovery, archived/offline/late callbacks, receipt isolation and audit rollback. |
| Real 0153 migration semantics | `migration-revoke-semantic.json` and `.log`: target `review_revoke_3b21cfad8a40` finalized; compatible ENROLL/EDIT/PHOTO history roundtrip, exact-action evidence and tombstone-only downgrade refusal before DDL, with fingerprints preserved. |
| Frontend | `milana-revoke-frontend-final-20261104.log`: full frontend checks/build and bridge recovery plus auth503 checks passed. |
| Actual visual/data | `visual-revoke/report-latest.json` and `visual-revoke-resume/report-latest.json`; root inspected four native desktop and six phone EN/RU/UZ images. Review, partial offline, all accepted, archived explicit revoke and 390px form/result were readable without horizontal overflow. |
| Persisted synthetic effects | Employees 970101/970102/970103, REVOKE operations 44/45/46: twelve tombstones, write count 3 to 4 once each; names, IDs, photo hashes, HR and attendance controls retained. Offline target remained present until reconnect. Operation 45's deliberately lost 202, null receipt and synthetic 403 preserved the same-key journal until exact read-only receipt recovery. |

The original migration target `review_revoke_3ee9e509381e` remains **HOLD**: the
roundtrip preserved schema and rows but the verifier's ordinal-column assumption failed.
The later semantic migration proof is a separate finalized target; no cleanup of the HOLD
target is claimed. The initial visual run completed operation 44 and its readback, then
failed locating employee 970102 before issuing secondary or archive writes. Read-only DB
inspection established those cases had not started; a separate owned continuation performed
only the remaining cases. The original lane was retained; the continuation lane was
closed after successful completion. Neither failure is relabeled as a pass.

## Remaining review and deployment boundary

Independent source/evidence review by /root/terra_edit_independent_review found no new blocker at functional freeze 75083615. Full backend Ruff and the four-file schema-write boundary audit passed with zero errors; the latter retains 17 expected transaction-owner/advisory SELECT manual items. Evidence is saved as final-independent-review-ruff.txt, final-independent-review-boundary.json and the independent review in the owned runtime. The reviewer did not personally inspect screenshots; the root integrator inspected the four native and six phone images. The resumed report records PASS and cleanup; no separate process exit record was retained, so an independently proven runner exit code is not claimed. The QA master should review the simulator
confirmation, separate archive/revoke, 3-online/1-offline reconnect, reopen/refresh,
unknown-result receipt recovery and EN/RU/UZ phone evidence before deployment. Technical
review should inspect the migration guard, complete CAS, typed tombstone and write/lease
fencing. Source integration and further refactoring may continue while the human check
remains unrecorded. Real hardware requires separately approved vendor/API, device,
rights, readback and two-writer decisions; this packet does not authorize production
access or release.

## Final combined verification and resource follow-up

Combined functional source 72bb4dc6 includes current integration, reviewed user creation
and factory-switch/audit changes, and PR373 auth outage/localization. The functional
Revoke files are byte-identical to freeze 75083615; relevant auth files match 97aee2fa.
See owned-runtime evidence/combined-source-equivalence.json and
evidence/combined-72bb-manifest.json for exact paths, commands, images and exits.

- 407 combined backend tests passed with zero skips. The compound command subsequently
  exited 127 because that dependency image lacked Ruff; the separate networkless lint
  image ran full backend Ruff successfully. Passed pytest was not replayed.
- A fresh guarded PostgreSQL proof passed and finalized review_revoke_26e3dcb43170.
- Frontend typecheck, strict checks and lint passed. Build v2's static worker aborted
  with SIGABRT; OOMKilled=false alone does not establish its cause. Evidence remains.
  After six confirmed-drained, non-HOLD owned QA lanes closed, build-only v3 passed
  all 98 static pages with 2CPU/4GiB/1024 task limits and no production config change.
  Its cgroup samples recorded no OOM or task-limit event; earlier failure is not relabeled.
- Turnstile bridge and localized auth503 error checks passed separately.
- After the owned backend restart loaded 72bb4dc6, authenticated GETs reopened operations
  44/45/46 and all revoked contexts, and read attendance overview. HR/attendance controls,
  simulator bindings, assets and operation metadata matched the earlier visual evidence.
  This extra native screenshot attempt timed out; its formal HOLD lane is retained.
  Its memory-only user security snapshot was unavailable, so that additional comparison
  is not claimed. The original functional Revoke UI screenshots remain valid by exact
  source equivalence; no additional combined native screenshot pass is inferred.
- The original locator-failure lane agent-bcd7af6c was later closed through the supported
  lane manager after exact ownership, no HOLD marker, terminal operations and drained
  connections were verified. Formal HOLD lanes and their evidence remain untouched.
  No system task limit, shared observer or other service was changed.

These are development evidence updates, not human acceptance or deployment.
