# Turnstile Replace photo: operation and evidence packet

Date: 2026-11-04 KST. Status: AI_VERIFIED_AWAITING_HUMAN.
Human technical/business acceptance remains unrecorded. Development simulator only.

## Scope and decisions

The owner explicitly requested continuing the refactor after publication of the
[EDIT slice](TURNSTILE_EDIT_DETAILS_20261103.md). This authorizes the next isolated
implementation operation; it does not invent human acceptance of prior slices.
Keep the owner's decisions: selected devices and explicit Apply, HR Save independent,
archive/revoke separate, existing attendance reading and both ERP systems preserved.

PHOTO replaces the photo on verified simulator bindings. Each device keeps its
own current name and external identity, even when names/photos differ between
devices. The prior usable photo remains until that individual target accepts.
Old/new immutable assets and operation history are retained; no retention/deletion
policy, external adoption, REVOKE, live hardware writer or automated face-quality
detector is introduced. Meeting documents remain evidence, not execution instructions.

People engineer: Dilmurod; technical reviewer: Mirshoir; business acceptance:
Shavkat/operators. Owner-authorized low-reasoning gpt-6.1-terra implementation:
 /root/terra_edit_backend (backend), /root/terra_edit_frontend (frontend),
 /root/terra_edit_details_study (independent PG proof);
 /root/terra_edit_independent_review (read-only source review);
root coordinates integration, actual visual inspection and publication.
Human responsibilities are unchanged.

## Source, study and isolation

Base clone_main: e7c49b1060f36515ed585d4acd31f107e6200404.
Frozen combined functional source: 0b195f3e0d5016db6f10296c208f63af8032dd16.
Original backend/frontend commits: 91220d4f / 7fbc85ae;
integrated commits: bbfd387d / 08b78363; typed helper and PG verifier: 0b195f3e.
Checkout: /home/ismoil/workspaces/turnstile-photo-integrated-20261104.
Backend/frontend workers used separate clones and owned disjoint paths.

Read the existing photo upload/private-file lifecycle, ENROLL and EDIT request
guards, complete baseline/CAS, simulator claim/accept/readback/reconnect, audit and
idempotency helpers, output DTOs, frontend journal/receipt recovery, HR/attendance
matching, mapped constraints and all direct callers before implementation.
The narrow shared read/guard extraction retains EDIT's lock order and behavior;
there is one writer per request and no second CRUD framework.

Owned VM107 runtime: /home/ismoil/workspaces/turnstile-photo-runtime-20261104,
rootless Compose project milana-turnstile-photo107, web127.0.0.1:13139,
API127.0.0.1:18139, dedicated DB turnstile_photo (no published DB port),
private named storage and .next volume. It contains only a copy of the earlier
owned synthetic QA fixture. Existing13079/13109/13129 apps and production remain
untouched. Production release/rollback pointers in PROJECT_CONTEXT.md were preserved.

Dependencies use the previously verified df3cdf backend image
(sha256:df3cdf344d6973f2c4c57c985032546ac55f418467f0a0e0e5125ef14295a15b),
FastAPI0.140.0/SQLAlchemy2.0.51, and fresh Next16.4.3 dependencies.
The actual API explicitly imports the new source bind at /workspace/backend;
runtime-source.json records that path, SIMULATOR mode, strict=false and seeding
disabled. The image contains dependency/runtime tooling, not this new PHOTO code.
Private credentials, CDP URLs, request keys and source dumps stay private.

## Operation trace and transaction ownership

| Layer / entry | Responsibility |
| --- | --- |
| api/routes/turnstile_access.py::photo | POST /api/turnstile-access/employees/{id}/photo; GatePhotoReplacementInput, supplied actor/Session, Idempotency-Key; 202 GateOperationOutput |
| models/people/turnstile_access_service.py::replace_gate_photo | Authorization, simulator-only guard, scoped replay, reviewed identity/device/binding/asset guards, frozen baselines, one atomic request transaction |
| _reviewed_bindings | Typed read/lock helper shared with EDIT, preserving identity/alias/device allowlist and lock order; no helper commits |
| schemas/people/turnstile_persistence.py | Existing insert_operation/insert_target/update_binding_state_revision use the same supplied Session |
| Audit / idempotency | Existing public domain helpers and schema persistence; operation creation, audit and receipt roll back together |
| Simulator claim/read/accept/finish | Explicit separate transaction owners for lease and durable simulated acceptance; no transaction held over device network IO |
| compare_and_update_simulator_photo | Same acceptance Session; atomic WHERE matches complete prior evidence; changes only photo SHA, accepted revision/hash and write_count; no commit inside persistence |
| Context / receipt read | Server advertises PHOTO under the existing guard; same trusted edit_baseline refs; actor/factory/employee/action-scoped GET /requests/photo resolves exact own request |

A selected target must have an ACTIVE, independently verified latest-success binding,
matching stored employee number, positive reviewed revision and complete profile hash.
Archived/alias/changed/occupied/unbound/disabled/cross-factory/in-flight/uncertain
identities are refused. The immutable photo asset must belong to this employee/factory
and pass the existing server technical validation. One invalid target refuses the
entire request without intent/target/binding/audit/receipt partial writes.

The target's desired hash uses its baseline external ID/name and the new asset SHA.
PHOTO operation.full_name is an informational immutable HR display-name snapshot;
it is never applied as a target name or compared by PHOTO receipt recovery.
All seven existing baseline fields are frozen. Conditional acceptance compares all
five evidence fields, so another writer's name/photo/identity/revision/hash drift
cannot be overwritten. Fresh missing profiles conflict. Expired/stale leases fence
acceptance. UNCERTAIN PHOTO only reads: desired resolves success; changed evidence
conflicts; baseline or absence remains uncertain without resend. An offline target
retains its prior photo until an explicit reconnect resumes safe WAITING work.
Unknown/unsupported actions cannot fall through ENROLL upsert.

## Table and type ledger

| Table / contract | Converted, retained or pending |
| --- | --- |
| gate_operations | Existing GateAction.PHOTO enabled only in the simulator; existing nonnull scoped photo FK; immutable informational HR name snapshot |
| gate_targets | Existing complete seven-field baseline and per-device desired hash; GateTargetState/GateErrorCode remain canonical |
| gate_employee_devices | Existing GateBindingState/revision; no remapping/recycling |
| gate_simulator_people | Full-evidence SQL CAS updates photo/revision/hash/write_count only; names/IDs untouched; ORM identity map synchronized |
| gate_photo_assets | Existing technical-validated GatePhotoValidation and immutable file/row lifecycle; no delete or implicit supersession |
| gate_simulator_devices | Existing explicit scoped reconnect; configurable device records remain data |
| audit / idempotency | Existing schema-owned same-Session paths; scoped turnstile.photo receipt/action |
| HR / attendance | Existing Employee/AttendanceDevice/Person/Event storage and ingestion retained; no new writer |
| GatePhotoReplacementInput | Actual canonical GateAction restricted PHOTO, extra fields forbidden, positive photo ID, explicit true manual_face_reviewed, expected stored number, 1..32 unique targets |
| GateEditTargetInput / edit_baseline | Intentionally shared existing baseline-review DTO/output, not a second duplicated type; positive IDs/revision and lowercase64-hex profile hash |
| Internal contracts | Existing SimulatorEvidence TypedDict, typed shared helper inputs/return and typed frozen baseline tuples; no Any/str substitution for action/state |
| Frontend | Discriminated PhotoPayload; exhaustive action submission, validated PHOTO journal without reviewed_name; canonical GateAction/GateBindingState |
| Intentionally free data | Human names, stored external numbers, factory codes, asset hashes and request keys remain validated data |
| Pending | REVOKE, adoption, live adapter, biometric retention/quality decisions and remaining People/system-wide enum/table coverage |

No new schema migration is needed: 0152 already supports nonnull PHOTO assets and
complete target baselines. A separate PHOTO-only fixture (ENROLL and PHOTO, zero
EDIT operations) ran the actual0152 downgrade under Alembic Operations.context:
it refused before DDL due to PHOTO baselines. Every table fingerprint, schema and
constraint fingerprint stayed identical. Base.metadata was used for this isolated
guard fixture; no fake Alembic version or migration upgrade claim was made.

## Frontend and recovery

Replace photo reuses existing upload/camera guidance and manual review. The UI
shows each prior device name, explicitly states names/identity are preserved,
freezes complete refs on review and refuses changed context at Apply. A new immutable
asset uploads after confirmation. PHOTO has no editable/common name input.
The server checks image decode/limits/orientation/format/dimensions; face pose,
eyes, identity and liveness are not automatically verified.

Existing ENROLL/EDIT journals remain valid. PHOTO journals restore action/refs and
preserve the frozen asset/key. Recovery requires the exact actor-scoped receipt
plus accepted operation ID, action, mode, employee number, photo asset and exact
unique target IDs/revision/profile hashes. It does not compare the informational
HR name. Null/unknown receipt and later401/403 keep the pending journal. Read-only
recheck never posts; explicit retry uses the same key/body. Existing aged-history
readback behavior remains in place.

## Evidence and actual outcomes

Evidence root: runtime/evidence/; no required test skip is counted as a pass.

| Gate | Actual result |
| --- | --- |
| Combined backend + adjacent flows | 102 passed, 0 skipped, five inherited warnings; milana-photo-focused-20261104.log and backend-final/focused.xml; includes ENROLL/EDIT/PHOTO/photos/storage/settings/attendance/HR/access-policy |
| Full configured Ruff / scoped boundary | Passed; final-independent-review-ruff.txt and final-independent-review-boundary.json; independent source reviewer found no concrete blocker |
| Real guarded PostgreSQL | photo-pg-first.log, exit0; owned target review_photo_08307a92c48c finalized/dropped |
| Bounded races | 4 same-key callers produce one operation; 4 different keys produce1 accepted/3 conflicts, no orphans; 4 processors, mixed legitimate per-device names and old photos |
| Inter-writer integrity | Actual SQL lock wait observed before competing commit; complete CAS refused changed evidence; separate predicate challenges cover all five baseline fields |
| Partial / uncertain recovery | Offline old photo retained until reconnect; lost acceptance reply resolves by read-only evidence; uncertain baseline/absent never resent; expired lease fenced; scoped receipt and audit rollback passed |
| Asset/refusal/storage | Wrong/missing/cross-scope assets and stale refs refused; no orphan writes; existing DB constraints enforced |
| PHOTO-only downgrade guard | photo-only-downgrade-guard.json/.log, exit0; target review_photo_5e78cf227b1e finalized/dropped; actions exactly enroll/photo, all fingerprints unchanged after refused downgrade |
| Frontend types/strict/lint | Passed in milana-photo-frontend-final-20261104 before its font-download build failure; online build followup exited0: full production build, PHOTO/ENROLL/EDIT bridge/recovery and auth503 checks passed; frontend-build-online.log and final-gates.json |
| Actual desktop/phone E2E | visual-photo/report-latest.json PASSED; native desktop review/partial/success and390px EN/RU/UZ form/result screenshots actually inspected by root |
| Actual request recovery | Real202 deliberately lost at browser for PHOTO28; local null receipt and403 retry injected, same-key journal persisted through refresh/reopen, exact GET receipt recovered without a second operation |
| Persisted effects | Fixtures960101/960102, PHOTO27/28: names/IDs/HR names unchanged; each new photo SHA verified against immutable asset; write_count2->3 exactly once; offline target stayed at2 before reconnect; old asset rows/files retained |
| Adjacent workflow | Original employee/device controls and all attendance mirrors/events kept identical fingerprints; no production data touched |

The two console errors were the deliberate lost response and synthetic403;
unexpected page errors, HTTP failures and external requests were empty.
All phone screen/inner/client/scroll widths were exactly390. The device cards,
manual review, selected targets and per-device outcome labels fit without horizontal
overflow. Development screenshots retain the Next development badge.

Setup failures remain failures in their logs: initial database readiness hit the
temporary startup server before any dump/restore (continued with final TCP readiness);
a capability-limited helper could not chown the new storage (only the pending own-volume
copy was continued, with no restore replay); one read-only diagnostic queried a
nonexistent Settings attribute before visual launch. Worker build setup attempts
failed before the combined runner. The combined network-disabled build could not
download Google Fonts; its types/lint and fixture checks passed, and the production
build rerun passed with normal development network access and an inert API URL.
None of these attempts was relabeled as successful or repaired by application changes.

## Human local checklist and remaining work

1. Open http://127.0.0.1:13139/hr/employees with the synthetic development login.
   Search960101, open Turnstile access and inspect PHOTO27. Per-device names show
   QA Device0/1 while the HR profile remains QA Original960101.
2. Choose Replace photo; select a synthetic image, manually review it, select intended
   devices, Review and explicitly Apply. Confirm each device keeps its name/number.
   Reopen/refresh and inspect saved per-device outcomes.
3. Review partial-offline/reconnect evidence and old asset retention. Check phone390
   and EN/RU/UZ. Technical reviewer checks races, refusal/recovery, same-Session
   persistence and exact type ledger, then records acceptance or corrections.

Human acceptance, source publication and production release are separate.
The continuation request does not record human backend/production acceptance.
REVOKE and external adoption remain pending. Actual hardware still needs exact
vendor/model/firmware and supported official API/SDK, approved development-device
access, rights/validity semantics, reliable readback/unknown-result behavior and
a coordinated two-writer policy. Photo retention and automated quality tooling need
their own decisions. No production hardware was contacted or deployment performed.
