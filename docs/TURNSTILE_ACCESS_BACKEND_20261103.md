# Turnstile Add access - backend task packet
Status: AI_VERIFIED_AWAITING_HUMAN for ENROLL in the private simulator only. Initial verification base clone_main 77d090f69c293f716adf9e2df6227d9543552442.
Source: /home/ismoil/workspaces/turnstile-backend-20261103.
2026-11-03 owner approved frontend and authorized backend implementation using multiple low-reasoning Terra workers followed by independent review. Earlier decisions remain binding: explicit Apply to selected devices; HR archive separate from revoke; both ERP writers and existing attendance ingestion must continue.

Engineering owner Dilmurod; human technical reviewer Mirshoir; Shavkat/operators business acceptance.
Coordinator/integrator /root; actual workers gpt-6.1-terra, low:
gate_contracts_storage (DTO/enums/schema/persistence/migration), gate_enrollment_api (authorization/enrollment routes/service), gate_photo_service (technical normalization/private assets), gate_simulator (durable simulator acceptance/recovery). Each has isolated clone at same base. Independent AI reviewer /root/review_turnstile_ui. No human approval of backend recorded.

## Single operation and boundaries
ENROLL only. Supporting private photo upload/read and durable development simulator processing.
HTTP routes -> models/people dedicated services -> schemas/people explicit persistence using supplied Session.
Enrollment transaction includes binding + immutable operation snapshot + per-device target + existing audit/idempotency schema helpers. No terminal IO before commit.
Existing AttendancePerson/Event/device read_only and HR/user profiles are not mutated. Any occupied mirror identity is refused, even matching name. Adoption needs its own reviewed operation.
No live adapter exists; disabled by default, fail closed for strict/public environments. Synthetic simulator configuration only, no caller host/credentials/policy.
Photo validation is technical JPEG/PNG decode, EXIF normalization and bounds; manual face review is operator attestation, no pose/eyes/liveness detector claim.
Private file commit ambiguity preserves the owned file, which may leave an orphan; retention/reconciliation policy remains pending.

## Trace and vocabulary ledger
- Context/enroll/operation routes -> turnstile_access_service -> GateEnrollmentInput/GateEmployeeContextOutput/GateOperationOutput -> GatePhotoAsset/GateEmployeeDevice/GateOperation/GateTarget.
- Photo routes -> turnstile_photo_service -> GatePhotoOutput -> GatePhotoAsset, private immutable random JPEG file.
- Simulator routes -> turnstile_simulator_service -> typed SimulatorEvidence and GateOperationOutput -> GateSimulatorDevice/GateSimulatorPerson; separate acceptance commit, lease fencing/readback.
- Fixed GateAction, GateMode, GateTargetState, GateBindingState, GatePhotoValidation, GateErrorCode canonical enums used by DTOs/mappings/services; frozen migration local definitions preserve migration stability.
- Employee number/name, factory/device references and hashes remain data, not enums. Existing Employee.status retained; no system-wide People type-completion claim.
- Edit/photo replacement/revoke/adoption/live hardware pending, owned by People engineer/reviewer. Other ERP editing coordination and real access-plan/validity/retention policy pending Shavkat. Existing attendance reading remains unchanged.

## Acceptance examples and refusal gates
1. Authorized scoped actor uploads technical-valid image and explicitly enrolls employee on four trusted fake devices: 202 durable queued targets; processing gives three verified simulator targets and one offline WAITING; trusted reconnect recovers last.
2. Same idempotency key/payload replays same operation ID and current states; changed payload/key conflict leaves no partial rows.
3. Wrong factory/role, archived/missing stored number, wrong-owner photo, duplicate devices, occupied external identity and aliases refuse atomically.
4. Lost response after durable terminal acceptance becomes UNCERTAIN; reconciliation reads existing evidence and never duplicates write. Expired/stale lease/revision cannot overwrite newer state. Attempts bounded; explicit reconnect may reset only trusted WAITING targets, never uncertain/in-flight.
5. HR archive, attendance mirror/event totals and device read_only remain unchanged; both ERP systems retain their read/write roles.

## Candidate and evidence
Own runtime /home/ismoil/workspaces/turnstile-backend-runtime-20261103, Compose milana-turnstile-backend107; UI13109/API18109 loopback, separate DB/volumes. Copied only synthetic preview DB; approved preview UI13079 untouched.
Worker focused results: storage2 SQLite, photo6 mock lifecycle, simulator9 SQLite; enrollment rerun pending. These are supporting evidence, not combined acceptance.
Required integrated gates still pending: exact source/hash freeze, authenticated API role/scope + persisted effects, real PostgreSQL upgrade/downgrade/constraints/concurrency/recovery, frontend bridge build/type/lint and actual desktop/exact390 EN/RU/UZ screenshots/readback, bounded load, final independent AI review, human local checklist.
No merge/deploy/production/device access. No source publication yet for backend.

## Final technical evidence - 2026-11-03
Source remains uncommitted on clone_main in the owned checkout; no push/merge/deployment.
Exact base77d090f69c293f716adf9e2df6227d9543552442; executable source manifest
83784de5500579e82e577b3d99cef9fd4f6c8286274d467e97aabaade5248882 (35 files), retained in runtime evidence/source-manifest.json.
The initial pending statements above are historical; the following are final checks.

- Final backend focused suite:47 passed, existing5 deprecation/model warnings.
  python -m pytest app/tests/test_turnstile_enrollment.py app/tests/test_turnstile_photos.py
  app/tests/test_turnstile_simulator.py tests/test_turnstile_storage.py
  tests/test_turnstile_settings.py -q -p no:cacheprovider.
- Adjacent existing attendance reader/HR validation/historical profiles/user-access policy:
 38 passed. test_attendance.py, test_hr_attendance_validation.py,
 test_attendance_historical_profiles.py, test_user_access_policy.py.
- Full frontend TypeScript --noEmit --incremental false, focused ESLint and executable
 test-turnstile-backend.mjs passed on combined source; no new dependencies.
- Schema-write tripwire6 operation files,0 errors. Manual transaction-owner findings:
 enrollment request owns commit/rollback; photo upload owns file/asset transaction.
 Simulator phase commits are intentionally separate from durable fake terminal acceptance;
 persistence helpers never commit, and no lock is held across external-effect simulation.
- Real PostgreSQL0150 upgrade/downgrade/reapply passed with original4 HR employees,
 4 devices,4 mirrored people,8 events preserved. Synthetic source was metadata-created
 with no Alembic version: all97 baseline tables/column names were checked before assigning
 0149 only to this owned copy. This is not fresh whole-chain or production migration proof.
 The first attempt failed Alembic annotation loading; fixed before any0150 DDL. A subsequent
 attempt without a baseline stamp hit existing historical tables and rolled back; retained.
- Dedicated turnstile_verify_20261103_v2:4 concurrent identical requests ->1 operation/4 targets;
 4 distinct keys ->1 accepted/3 conflicts/no orphan rows. PostgreSQL rejects cross-factory
 photo, cross-scope target and unknown enum; injected audit failure rolls back request,
 bindings, targets and idempotency.4 concurrent processors ->3 successes/1 offline,
 explicit reconnect ->4 successes, write_count1 each. Lost reply reconciled with no duplicate.
 Earlier verification DB retained; no budgets or state reset after unknown writes.
- Actual loopback HTTP with cookie auth and3 scoped roles passed:401/403/404 refusals,
 real multipart JPEG/PNG/corrupt/oversize/pixel checks, EXIF rotation/metadata stripping,
 private no-store JPEG bytes/hash/file mode0600, reviewed-number drift409, enrollment202,
 stable replay, changed-payload409, simulated3+1/reconnect4, persisted audit/idempotency
 and unchanged control fingerprints. Initial upload500 was private-volume UID mismatch;
 inspection proved no new asset/enrollment/binding, then API UID aligned to volume1000,
 permissions remained private, failed-run fixtures retained/only exact fake configs disabled.
- qa_visual main laneagent-ea15d7bf passed: actual photo/enrollment queued4, process3+1,
 reconnect4; close/reopen/refresh persisted; occupied-ID409 preserves inputs/no false history.
 Exact390 screen/inner/client/scroll widths in EN/RU/UZ, desktop native and browser images;
 root visually inspected desktop review/results, mobile form and all locale results.
 No page errors/external requests; only expected409. Original control fingerprints unchanged.
- Controlled recovery laneagent-f7023d68 captured real202 for operation3 before deliberately
 dropping the browser reply. Unknown journal survived close/reload. The runner asserted
 journal deletion before the async GET finished and reported HOLD; no enrollment replay.
 Read-only inspection of the same retained lane proved journal cleared and queued4.
 A bounded continuation blocked all enrollment POSTs, processed that same operation,
 injected UNCERTAIN only into one already-accepted synthetic target, then used the actual
 UI reconcile action: succeeded4, each write_count1, original controls unchanged.
 Both original report and continuation are retained; exact known-drained lane stopped.
 Browser recovery screenshots are separate evidence. The original runner's wait was fixed;
 it was not blindly rerun against the already-enrolled employee.
- Independent /root/review_turnstile_ui reported no remaining source blockers after fixes.
 Final component2106d423c74bd79dbcd2a233d094717a935a61a0f23d2fa6e6147d073609db1e;
 final bridge helper7b583933083141906f4378354ffc222ea426af26f681da264fdae1977a98dda0.

Review fixes include occupied-ID refusal, strict/public guards, pre-lookup private authorization,
actual enum/internal evidence typing, bounded retries and WAITING-only explicit recovery,
valid MIME filenames, truthful partial/unknown UI, key-fenced journal with definitive4xx handling,
precommit DTO serialization, reviewed number drift refusal, mounted upload continuation guard,
persisted business device names and identity-aware receipt reconciliation.

## Human local checklist and remaining scope
Open http://127.0.0.1:13109/hr/employees (visible connected tab is signed in).
Backend - Employee EN/920001 shows saved simulator history;920002 demonstrates recovered
lost-response/readback history. Fresh synthetic920003 is available for manual Add access.
Use a synthetic JPEG/PNG; check photo/manual attestation, selected targets/explicit Apply,
queued status, Process/Reconcile, reopening/refresh and EN/RU/UZ phone usability.
Preview - Employee001/910001 is deliberately refused because existing mirrored IDs are occupied.
Missing stored number and archived employees cannot enroll. Inspect existing attendance page.
Do not test with real employee biometric data or hardware in this synthetic runtime.

The feature discipline requires human repetition and recorded approval/rejection of this build.
This only gates ENROLL in private simulator mode; frontend approval does not approve the backend.
Edit, photo replacement, revoke, adoption, real-device write adapter/model/firmware/access-plan/
validity/two-writer coordination and biometric retention/reconciliation remain pending.
Production/current/rollback release records remain unchanged; no production endpoint was used.

Final visual inspection also covered the controlled unknown-response and reconciled native screenshots. Root confirmed the unknown state kept Apply disabled and exposed explicit recheck/retry; final readback showed four accepted simulator targets with no duplicate writes. The connected signed-in browser is left on920001 saved results. No remaining source-review blocker is recorded for this bounded slice.

## Fresh visual recheck requested by owner - 2026-11-03

Owner requested another visual inspection. The in-app browser control returned
browser.user unavailable; selected-browser recovery alternatives also failed.
A fresh qa_visual private lane agent-5662a819 inspected the same healthy13109 build.

Desktop native screenshots show the full header/actions, four saved simulator results
and visible missing-photo validation. Reopen/refresh retained saved results. Pending
edit/photo/revoke controls stayed disabled. Exact390 screen/inner/client/scroll widths
passed for EN/RU/UZ, with separate top and results images. Root visually inspected all
nine fresh images: text wraps within the viewport, controls/results are readable, and
no blocking clipping/overlap was observed. The floating Next development badge remains
an expected development-runtime overlay.

Provisioning POSTs were explicitly blocked throughout this inspection. No page errors,
HTTP errors, external requests or attempted provisioning writes occurred. All ten affected
business-table count/fingerprint pairs were identical before/after (employees, devices,
attendance people/events, operations/targets/bindings/assets, simulator people/devices).
The exact owned lane was stopped after success. No product source change or new enrollment.
Evidence: runtime evidence/visual-recheck-20261103/report.json and nine matching PNGs;
local copy outputs/turnstile-backend-20261103/visual-recheck/.

## Owner-authorized publication and upstream reconciliation
2026-11-03 owner explicitly requested push after the fresh visual review.
Publication target is clone_main, based on latest54a51d7954f5eacc103a8960faef5b8c947ed1d3.
An isolated publication checkout preserves the serving source and synthetic databases.
The upstream package customer-release0150 migration is retained; turnstile enrollment
is renamed0151_gate_enrollment with predecessor0150_package_customer_release, yielding
one migration head. Shared schema registration preserves both features; project context
retains both upstream sections and this task. Historical0150 verification above belongs
to the earlier candidate; the publication candidate requires its own combined checks.
Push authorization is source publication, not production deployment or invented human
business acceptance. No production activation workflow is being invoked.

Publication places the two new storage/settings test files under backend/app/tests so the existing CI pytest testpaths collects them automatically. The earlier explicit backend/tests command records its historical location.

### Combined publication checks
Publication source: /home/ismoil/workspaces/turnstile-backend-publish-20261103,
base54a51d7954f5eacc103a8960faef5b8c947ed1d3. Serving13109 source remains unchanged.

-151 selected backend/adjacent/upstream cases passed;7 upstream PostgreSQL cases
 initially skipped without a PG URL, then all7 passed in an isolated loopback-namespace
 database. They are not counted as skipped passes. Final47 turnstile cases passed again
 from CI-collected app/tests after the export correction.
-Full CI Ruff app gate, full frontend TypeScript and bridge recovery tests passed.
-Corrected6 mapped exports in schemas.__all__ and removed3 unused test imports.
-Single head0151 verified. Real PG0149 -> upstream0150 -> gate0151, gate-only rollback,
 both-feature rollback and reapply passed with11 copied employees,12 devices,
 4 mirror people and8 events preserved. Publication DB was independently created from
 a synthetic baseline export excluding gate tables/version, never the serving DB.
-Turnstile real PG4-thread replay/conflict/rollback/constraints/concurrent processing/
 lost-reply checks passed. Real authenticated HTTP/photo-byte/scoped refusal/replay/
 readback/integrity checks passed on the publication API.
-qa_visual agent-fc21cad0 on13119 passed actual upload/enroll queued4, process3+1,
 reconnect4, reopen/refresh, occupied-ID409 retaining inputs, desktop and exact390
 EN/RU/UZ. Original control fingerprints unchanged; one fake terminal write each.
 Root inspected publication desktop/native and mobile evidence. Evidence lives in
 runtime evidence/publication. Existing serving preview and databases were preserved.
-Independent publication delta review found no source blockers and preserved all upstream
 package-release/FG changes. Full GitHub CI has not yet run on this new commit; push
 triggers validation only, with manual dispatch required for release artifacts and no
 automatic production activation.
