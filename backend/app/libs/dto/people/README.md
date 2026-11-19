# People: DTO contracts

**Engineer:** Dilmurod. **Reviewer:** Mirshoir. **Business acceptance:** Shavkat.

Existing Pydantic definitions in this group:

- [payroll.py](payroll.py)

These describe accepted inputs and returned data. They do not execute database
writes, implement permissions or manage transactions. Existing filenames/class
names are retained; the folder move does not alter validation or defaults.

Before adding a file, find the existing contract and its router/service callers.
Keep creation fields/defaults, allowed update fields and response filtering distinct.
For updates preserve omitted versus explicit null; do not apply creation defaults.
Add action/query contracts only for actual operations. New <entity>_input.py, <entity>_update.py or
<entity>_output.py files are useful when the feature needs them, not a quota for every table.

Reuse shared bases from ../common.py and existing fixed values. Test validation,
serialization, denied/privileged fields and the consuming workflow; then perform
the required visual and release acceptance checks.

See [DTO rules](../README.md), [business services](../../../models/README.md),
[database definitions](../../../schemas/README.md) and
[ownership](../../../../../docs/TEAM_OWNERSHIP.md).

Turnstile enrollment, edit, photo replacement and revocation use [turnstile_input.py](turnstile_input.py),
[turnstile_output.py](turnstile_output.py) and
[turnstile_context_output.py](turnstile_context_output.py).
Fixed state/action/mode/error fields use canonical enums. ENROLL requires the
operator-reviewed stored employee number, scoped technical-valid photo, selected
device IDs and manual review attestation. This is not automated identity validation.

EDIT accepts the reviewed employee number and nonblank name plus unique selected device
IDs with expected revision and lower-hex profile hash; callers cannot provide profile
snapshots. Context exposes a nullable trusted edit baseline (revision, profile hash and
prior name) per eligible binding. EDIT output has a null photo asset and target baseline
references; ENROLL retains its required photo. The actor-scoped request receipt lookup
returns the operation for the saved idempotency key, enabling read-only reconciliation
without matching an unanchored history entry. These contracts are for the private
simulator, not live hardware. See the [EDIT evidence packet](../../../../../docs/TURNSTILE_EDIT_DETAILS_20261103.md).

PHOTO uses the same `GateEditTargetInput` and context `edit_baseline` review references
as EDIT: unique device IDs, expected revisions and profile hashes. It requires the
reviewed stored employee number, scoped validated immutable asset ID and true manual
review attestation; it has no reviewed-name input. The operation full_name is an
informational HR snapshot, while each target keeps its own baseline name and identity.
The scoped receipt lookup reconciles the saved key against action, asset and exact target
baseline references; unknown acceptance remains a read-only recovery case. See the
[PHOTO task packet](../../../../../docs/TURNSTILE_PHOTO_REPLACEMENT_20261104.md).


REVOKE accepts the reviewed stored employee number and unique `GateEditTargetInput`
references with expected revision and profile hash. It accepts no name or photo input.
The shared context baseline is offered only for a trusted active binding. Its scoped
receipt identifies the saved action and exact target references; bare profile absence
is not a successful revocation. An archived HR employee can still be revoked separately.
These contracts apply only to the guarded private simulator. See the
[REVOKE packet](../../../../../docs/TURNSTILE_REVOKE_20261104.md); verification remains
**AI_VERIFIED_AWAITING_HUMAN** after independent source/evidence review.
