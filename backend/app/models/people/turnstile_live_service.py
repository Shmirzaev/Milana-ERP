"""Scoped physical-device intent, observation, adoption and worker receipts.

No device I/O occurs here. The LAN worker holds device credentials. Writes use
schema-owned persistence, and each public operation owns its outer transaction.
"""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.deps import user_permissions
from app.libs.dto.people.turnstile_live import (LiveAccessPolicy, LiveAdoptInput, LiveClaimOutput,
    LiveDeviceInput, LiveJobOutput, LiveRequestInput, LiveResolutionInput, LiveResultInput, LiveSnapshot)
from app.libs.enums.turnstile import (GateBindingState, GateMode, GatePhotoValidation, HikvisionUserType,
    LiveGateAction as Action, LiveGateOutcome as Outcome, LiveGateState as State, LiveWriteStep as Step)
from app.models.audit_service import log_action
from app.models.factory_scope_service import selected_factory_code
from app.models.idempotency_service import request_fingerprint
from app.models.people.turnstile_access_service import authorize_gate_employee, authorize_gate_actor
from app.schemas import AttendanceDevice, AttendancePerson, Employee, SystemSetting, User
from app.schemas.people.turnstile import GateEmployeeDevice, GatePhotoAsset
from app.schemas.people.turnstile_live import GateLiveDevice, GateLiveJob, GateLiveProfile
from app.schemas.people.turnstile_live_persistence import (dispatch_live_job, finish_live_job,
    insert_live_binding, insert_live_job, lease_live_job, save_live_device, save_live_profile, retry_unsent_live_job)

OPEN = (State.QUEUED, State.PROCESSING, State.DISPATCHING, State.UNCERTAIN)
RUNNING = (State.PROCESSING, State.DISPATCHING)
WRITE_STEPS = {
    Action.OBSERVE: (), Action.ENROLL: (Step.CREATE_BLOCKED_PERSON, Step.UPLOAD_FACE, Step.ACTIVATE_ACCESS),
    Action.EDIT: (Step.MODIFY_PROFILE,), Action.PHOTO: (Step.UPLOAD_FACE,),
    Action.REVOKE: (Step.MODIFY_PROFILE,), Action.DELETE: (Step.DELETE_PROFILE,),
    Action.RESTORE: (Step.MODIFY_PROFILE,),
}


def now() -> datetime:
    return datetime.now(timezone.utc)


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def require_live() -> None:
    if settings.TURNSTILE_PROVISIONING_MODE is not GateMode.HIKVISION:
        raise HTTPException(403, "Real turnstile integration is disabled")


def _device(db: Session, actor: User, device_id: int) -> AttendanceDevice:
    row = db.query(AttendanceDevice).filter_by(id=device_id, factory_code=selected_factory_code(actor)).with_for_update().first()
    if row is None:
        raise HTTPException(404, "Device not found")
    return row


def _config(db: Session, device_id: int) -> GateLiveDevice | None:
    return db.query(GateLiveDevice).filter_by(device_id=device_id).with_for_update().first()


def configure_device(db: Session, actor: User, device_id: int, payload: LiveDeviceInput) -> dict:
    require_live()
    if "*" not in user_permissions(actor):
        raise HTTPException(403, "Administrator approval required")
    try:
        device = _device(db, actor, device_id)
        if not device.source_host or not device.certificate_sha256 or len(device.certificate_sha256) != 64:
            raise HTTPException(409, "Verified source host and certificate pin are required")
        if payload.enabled and not payload.allowed_employee_numbers:
            raise HTTPException(422, "Explicit employee allowlist required for observation and writing")
        config = _config(db, device.id)
        if db.query(GateLiveJob.id).filter(GateLiveJob.device_id == device.id, GateLiveJob.state.in_(RUNNING)).first():
            raise HTTPException(409, "Stop the worker and resolve running work before rotating configuration")
        token = secrets.token_urlsafe(48)
        row = save_live_device(db, config, device_id=device.id, factory=device.factory_code,
            token_hash=token_hash(token), source_host=device.source_host,
            certificate_sha256=device.certificate_sha256, payload=payload)
        log_action(db, actor, "turnstile.live.configure", "attendance_device", device.id,
            new_value={"enabled": row.enabled, "writes_enabled": row.writes_enabled,
                       "config_revision": row.config_revision, "policy_reference": payload.policy_reference,
                       "handover_reference": payload.handover_reference})
        db.commit()
        return {"device_id": device.id, "worker_token": token, "config_revision": row.config_revision}
    except Exception:
        db.rollback(); raise


def worker_identity(db: Session, supplied: str | None) -> GateLiveDevice:
    require_live()
    if not supplied or len(supplied) > 256:
        raise HTTPException(401, "Worker credentials required")
    row = db.query(GateLiveDevice).filter_by(worker_token_hash=token_hash(supplied)).with_for_update().first()
    if row is None or not row.enabled:
        raise HTTPException(401, "Invalid or disabled worker credentials")
    return row


def job_output(job: GateLiveJob) -> LiveJobOutput:
    snapshot = LiveSnapshot.model_validate(job.result["after"]) if job.result and job.result.get("after") else None
    return LiveJobOutput(id=job.id, employee_id=job.employee_id, device_id=job.device_id,
        action=job.action, state=job.state, created_at=job.created_at, observation=snapshot,
        profile_hash=request_fingerprint(snapshot.model_dump(mode="json")) if snapshot else None)


def get_job(db: Session, actor: User, job_id: int) -> LiveJobOutput:
    authorize_gate_actor(actor)
    job = db.get(GateLiveJob, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    authorize_gate_employee(db, actor, job.employee_id)
    if job.factory_code != selected_factory_code(actor):
        raise HTTPException(404, "Job not found")
    return job_output(job)


def context(db: Session, actor: User, employee_id: int) -> dict:
    employee = authorize_gate_employee(db, actor, employee_id)
    enabled = settings.TURNSTILE_PROVISIONING_MODE is GateMode.HIKVISION
    devices = db.query(AttendanceDevice, GateLiveDevice).join(GateLiveDevice, GateLiveDevice.device_id == AttendanceDevice.id).filter(
        AttendanceDevice.factory_code == employee.factory_code, GateLiveDevice.enabled.is_(True)).order_by(AttendanceDevice.id).all() if enabled else []
    profiles = db.query(GateEmployeeDevice, GateLiveProfile).join(GateLiveProfile, GateLiveProfile.binding_id == GateEmployeeDevice.id).filter(
        GateEmployeeDevice.employee_id == employee_id, GateEmployeeDevice.factory_code == employee.factory_code,
        GateEmployeeDevice.mode == GateMode.HIKVISION).all()
    jobs = db.query(GateLiveJob).filter_by(employee_id=employee_id, factory_code=employee.factory_code).order_by(GateLiveJob.id.desc()).limit(30).all()
    return {"enabled": enabled, "employee_no": employee.employee_no,
        "devices": [{"id": d.id, "name": d.name, "writes_enabled": c.writes_enabled,
                     "identity_allowed": employee.employee_no in c.configuration["allowed_employee_numbers"]} for d, c in devices],
        "profiles": [{"device_id": b.device_id, "state": b.state, "profile_hash": p.profile_hash,
                      "snapshot": p.snapshot, "observed_at": p.observed_at} for b, p in profiles],
        "jobs": [job_output(j) for j in jobs]}


def _identity(db: Session, employee: Employee, expected: str) -> str:
    number = (employee.employee_no or "").strip()
    if not number or number != employee.employee_no or expected != number:
        raise HTTPException(409, "Stored employee identity changed or is missing")
    aliases = db.query(SystemSetting.value_json).filter_by(key=f"employee_merge_aliases:{employee.factory_code}").scalar()
    if isinstance(aliases, dict) and (str(employee.id) in aliases.get("ids", {}) or number in aliases.get("numbers", {})):
        raise HTTPException(409, "Identity reserved by reviewed merge")
    return number


def submit(db: Session, actor: User, employee_id: int, payload: LiveRequestInput, key: str | None) -> LiveJobOutput:
    require_live()
    if not key or len(key) > 128 or key != key.strip():
        raise HTTPException(400, "An Idempotency-Key of at most 128 characters is required")
    try:
        employee = authorize_gate_employee(db, actor, employee_id, lock=True)
        fingerprint = request_fingerprint({"employee_id": employee.id, **payload.model_dump(mode="json")})
        prior = db.query(GateLiveJob).filter_by(requested_by=actor.id, factory_code=employee.factory_code, request_key=key).first()
        if prior:
            if prior.request_hash != fingerprint:
                raise HTTPException(409, "Request key belongs to another payload")
            result = job_output(prior); db.rollback(); return result
        number = _identity(db, employee, payload.expected_employee_no)
        device = _device(db, actor, payload.device_id)
        config = _config(db, device.id)
        if not config or not config.enabled or not device.sync_enabled:
            raise HTTPException(409, "Device integration is not enabled")
        policy = LiveDeviceInput.model_validate(config.configuration)
        if number not in policy.allowed_employee_numbers:
            raise HTTPException(403, "Identity is outside the approved device scope")
        if payload.action is not Action.OBSERVE and not policy.writes_enabled:
            raise HTTPException(403, "Device writes await an agreed handover")
        if payload.action not in (Action.OBSERVE, Action.REVOKE, Action.DELETE) and employee.status != "active":
            raise HTTPException(409, "Active employee required")
        # An uncertain device write prevents subsequent writes on the whole device.
        pending = db.query(GateLiveJob).filter(GateLiveJob.device_id == device.id, GateLiveJob.state.in_(OPEN))
        if payload.action is not Action.OBSERVE and pending.first():
            raise HTTPException(409, "Device work is pending or uncertain; reconcile it first")
        binding = db.query(GateEmployeeDevice).filter_by(device_id=device.id, external_person_id=number).with_for_update().first()
        if binding and (binding.employee_id != employee.id or binding.mode != GateMode.HIKVISION):
            raise HTTPException(409, "Identity already belongs to a different binding or mode")
        baseline = None
        if payload.action is Action.ENROLL:
            if db.query(AttendancePerson.id).filter_by(device_id=device.id, external_person_id=number).first():
                raise HTTPException(409, "Occupied identity requires explicit observation and adoption")
            if binding:
                reserved = db.query(GateLiveProfile).filter_by(binding_id=binding.id).first()
                if (binding.state is not GateBindingState.PENDING or not reserved or reserved.adopted or reserved.snapshot
                        or db.query(GateLiveJob.id).filter_by(binding_id=binding.id, dispatched=True).first()):
                    raise HTTPException(409, "Occupied or previously dispatched identity requires separate review")
                # Reuse only this exact never-written reservation. A new explicit
                # request can follow exhausted unsent attempts or a reviewed
                # policy revision; retain all prior jobs and ownership.
            else:
                binding, _ = insert_live_binding(db, employee_id=employee.id, factory=employee.factory_code,
                    device_id=device.id, number=number, adopted=False)
        elif payload.action is not Action.OBSERVE:
            profile = db.query(GateLiveProfile).filter_by(binding_id=binding.id).first() if binding else None
            if not profile or not profile.adopted or not profile.snapshot or profile.profile_hash != payload.expected_profile_hash:
                raise HTTPException(409, "Review and adopt a complete physical baseline first")
            baseline = LiveSnapshot.model_validate(profile.snapshot)
            if not baseline.present:
                raise HTTPException(409, "Deleted identities cannot be reused automatically")
            if payload.action is Action.DELETE and baseline.user_type is not HikvisionUserType.BLOCKED:
                raise HTTPException(409, "Revoke access before deleting credentials")
            if payload.action is Action.RESTORE and (baseline.user_type is not HikvisionUserType.BLOCKED
                    or baseline.face_count != 1 or baseline.policy != policy.access_policy):
                raise HTTPException(409, "Restore requires a blocked, verified face profile with exactly the approved access policy")
        photo = None
        if payload.photo_asset_id:
            photo = db.query(GatePhotoAsset).filter_by(id=payload.photo_asset_id, employee_id=employee.id,
                factory_code=employee.factory_code, validation=GatePhotoValidation.TECHNICAL_VALIDATED).first()
            if not photo:
                raise HTTPException(422, "Validated employee photo required")
        frozen_payload = payload.model_copy(update={"reviewed_name": (payload.reviewed_name or employee.full_name).strip()}) if payload.action in (Action.ENROLL, Action.EDIT) else payload
        job = insert_live_job(db, actor_id=actor.id, factory=employee.factory_code, employee_id=employee.id,
            payload=frozen_payload, request_key=key, request_hash=fingerprint, config_revision=config.config_revision,
            binding_id=binding.id if binding and payload.action is not Action.OBSERVE else None,
            baseline=baseline, policy=policy.access_policy if payload.action in (Action.ENROLL, Action.RESTORE) else None,
            photo_hash=photo.sha256 if photo else None)
        log_action(db, actor, "turnstile.live.request", "gate_live_job", job.id,
            new_value={"employee_id": employee.id, "device_id": device.id, "action": payload.action.value})
        result = job_output(job); db.commit(); return result
    except IntegrityError as exc:
        db.rollback()
        constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        if constraint in {"uq_gate_live_request", "uq_gate_binding_device_external", "uq_gate_binding_employee_device"}:
            raise HTTPException(409, "Concurrent turnstile identity or request conflict; reload the saved receipt") from exc
        raise
    except Exception:
        db.rollback(); raise


def adopt(db: Session, actor: User, employee_id: int, payload: LiveAdoptInput) -> dict:
    require_live()
    try:
        employee = authorize_gate_employee(db, actor, employee_id, lock=True)
        number = _identity(db, employee, payload.expected_employee_no)
        job = db.get(GateLiveJob, payload.observation_job_id)
        if (not payload.identity_reviewed or not job or job.employee_id != employee.id or job.factory_code != employee.factory_code
                or job.action is not Action.OBSERVE or job.state is not State.SUCCEEDED or not job.completed_at
                or utc(job.completed_at) < now() - timedelta(minutes=5)):
            raise HTTPException(409, "A fresh completed physical observation and explicit identity review are required")
        device = _device(db, actor, job.device_id); config = _config(db, device.id)
        if not config or not config.enabled or config.config_revision != job.config_revision:
            raise HTTPException(409, "Device configuration changed")
        snapshot = job_output(job).observation
        if not snapshot or not snapshot.present or snapshot.external_person_id != number or request_fingerprint(snapshot.model_dump(mode="json")) != payload.expected_profile_hash:
            raise HTTPException(409, "Observed identity or baseline changed")
        if db.query(GateLiveJob.id).filter(GateLiveJob.device_id == device.id, GateLiveJob.state.in_(OPEN), GateLiveJob.action != Action.OBSERVE).first():
            raise HTTPException(409, "Resolve outstanding device writes first")
        occupied = db.query(GateEmployeeDevice).filter(GateEmployeeDevice.device_id == device.id,
            or_(GateEmployeeDevice.external_person_id == number, GateEmployeeDevice.employee_id == employee.id)).first()
        if occupied:
            profile = db.query(GateLiveProfile).filter_by(binding_id=occupied.id).first()
            if (occupied.mode == GateMode.HIKVISION and occupied.employee_id == employee.id and occupied.external_person_id == number
                    and profile and profile.snapshot and profile.snapshot.get("present") is True):
                if profile.profile_hash == payload.expected_profile_hash:
                    db.rollback(); return {"binding_id": occupied.id, "profile_hash": profile.profile_hash}
                if profile.observed_at and utc(job.completed_at) <= utc(profile.observed_at):
                    raise HTTPException(409, "A newer device baseline already exists; observe the profile again")
                save_live_profile(db, profile, occupied, snapshot=snapshot, profile_hash=payload.expected_profile_hash,
                    observed_at=utc(job.completed_at), adopted=True,
                    state=GateBindingState.REVOKED if snapshot.user_type is HikvisionUserType.BLOCKED else GateBindingState.ACTIVE)
                log_action(db, actor, "turnstile.live.review_baseline", "gate_employee_device", occupied.id,
                    new_value={"observation_job_id": job.id, "profile_hash": payload.expected_profile_hash})
                db.commit(); return {"binding_id": occupied.id, "profile_hash": profile.profile_hash}
            raise HTTPException(409, "Existing binding cannot be remapped or overwritten by adoption")
        binding, profile = insert_live_binding(db, employee_id=employee.id, factory=employee.factory_code,
            device_id=device.id, number=number, adopted=True)
        save_live_profile(db, profile, binding, snapshot=snapshot, profile_hash=payload.expected_profile_hash,
            observed_at=utc(job.completed_at), adopted=True,
            state=GateBindingState.REVOKED if snapshot.user_type is HikvisionUserType.BLOCKED else GateBindingState.ACTIVE)
        log_action(db, actor, "turnstile.live.adopt", "gate_employee_device", binding.id,
            new_value={"observation_job_id": job.id, "device_id": device.id, "profile_hash": payload.expected_profile_hash})
        db.commit(); return {"binding_id": binding.id, "profile_hash": payload.expected_profile_hash}
    except Exception:
        db.rollback(); raise


def _worker_job(db: Session, identity: GateLiveDevice, job_id: int, token: str) -> GateLiveJob:
    job = db.query(GateLiveJob).filter_by(id=job_id, device_id=identity.device_id, factory_code=identity.factory_code).with_for_update().first()
    if not job or not job.lease_token_hash or not hmac.compare_digest(job.lease_token_hash, token_hash(token)):
        raise HTTPException(404, "Assigned worker job not found")
    return job


def _revalidate_intent(db: Session, job: GateLiveJob, config: GateLiveDevice) -> None:
    actor = db.get(User, job.requested_by)
    employee = authorize_gate_employee(db, actor, job.employee_id)
    number = _identity(db, employee, job.request["expected_employee_no"])
    device = db.get(AttendanceDevice, job.device_id)
    policy = LiveDeviceInput.model_validate(config.configuration)
    if (not config.enabled or not device.sync_enabled or job.config_revision != config.config_revision
            or device.source_host != config.source_host or device.certificate_sha256 != config.certificate_sha256
            or number not in policy.allowed_employee_numbers or (job.action is not Action.OBSERVE and not config.writes_enabled)
            or (job.action not in (Action.OBSERVE, Action.REVOKE, Action.DELETE) and employee.status != "active")):
        raise HTTPException(409, "Queued intent authorization, identity, status or device policy changed")


def claim(db: Session, identity: GateLiveDevice) -> LiveClaimOutput | None:
    try:
        config = _config(db, identity.device_id)
        active = db.query(GateLiveJob).filter(GateLiveJob.device_id == identity.device_id, GateLiveJob.state.in_(RUNNING)).with_for_update().all()
        for job in active:
            if job.lease_expires_at and utc(job.lease_expires_at) <= now():
                finish_live_job(db, job, state=State.UNCERTAIN)
            else:
                db.rollback(); return None
        uncertain = db.query(GateLiveJob.id).filter_by(device_id=identity.device_id, state=State.UNCERTAIN).first()
        query = db.query(GateLiveJob).filter_by(device_id=identity.device_id, factory_code=identity.factory_code, state=State.QUEUED)
        if uncertain:
            query = query.filter(GateLiveJob.action == Action.OBSERVE)
        job = query.order_by(GateLiveJob.id).with_for_update().first()
        if job is None:
            db.commit(); return None
        policy = LiveDeviceInput.model_validate(config.configuration)
        employee = db.get(Employee, job.employee_id)
        try:
            _revalidate_intent(db, job, config)
        except HTTPException:
            finish_live_job(db, job, state=State.CONFLICT, completed_at=now()); db.commit(); return None
        device = db.get(AttendanceDevice, job.device_id)
        if not device.sync_enabled or not device.source_host or not device.certificate_sha256:
            finish_live_job(db, job, state=State.CONFLICT, completed_at=now()); db.commit(); return None
        token = secrets.token_urlsafe(48); expires = now() + timedelta(seconds=180)
        lease_live_job(db, job, token_hash=token_hash(token), expires=expires)
        result = LiveClaimOutput(job_id=job.id, device_key=device.device_key, source_host=config.source_host,
            certificate_sha256=config.certificate_sha256, external_person_id=employee.employee_no, action=job.action,
            lease_token=token, lease_expires_at=expires, face_library_id=policy.face_library_id,
            baseline=LiveSnapshot.model_validate(job.baseline) if job.baseline else None,
            desired_name=(job.request.get("reviewed_name") or employee.full_name) if job.action in (Action.ENROLL, Action.EDIT) else None,
            desired_policy=LiveAccessPolicy.model_validate(job.desired_policy) if job.desired_policy else None,
            photo_asset_id=job.photo_asset_id, photo_sha256=job.photo_sha256)
        db.commit(); return result
    except Exception:
        db.rollback(); raise


def permit_dispatch(db: Session, identity: GateLiveDevice, job_id: int, token: str, step: Step) -> dict:
    try:
        config = _config(db, identity.device_id); job = _worker_job(db, identity, job_id, token)
        _revalidate_intent(db, job, config)
        steps = WRITE_STEPS[job.action]
        if (job.action is Action.OBSERVE or not config.writes_enabled or config.config_revision != job.config_revision
                or job.state not in RUNNING or not job.lease_expires_at or utc(job.lease_expires_at) <= now()
                or job.dispatch_count >= len(steps) or steps[job.dispatch_count] is not step):
            raise HTTPException(409, "Write permit is unavailable or expired; reconcile without writing")
        dispatch_live_job(db, job); db.commit(); return {"permitted": True}
    except Exception:
        db.rollback(); raise


def _matches(job: GateLiveJob, result: LiveResultInput) -> bool:
    before, after = result.before, result.after
    number = job.request["expected_employee_no"]
    if after is None or after.external_person_id != number:
        return False
    if job.action is Action.OBSERVE:
        return not job.dispatched and not result.vendor_accepted
    if not job.dispatched or job.dispatch_count != len(WRITE_STEPS[job.action]) or not result.vendor_accepted or before is None or before.external_person_id != number:
        return False
    if job.action is Action.ENROLL:
        return (not before.present and after.present and after.full_name == job.request["reviewed_name"]
            and after.user_type is HikvisionUserType.NORMAL and after.policy.model_dump(mode="json") == job.desired_policy
            and after.photo_sha256 == job.photo_sha256 and after.face_count == 1 and after.card_count == after.fingerprint_count == 0
            and after.local_ui_right is False and after.double_lock_right is False)
    if before.model_dump(mode="json") != job.baseline:
        return False
    expected = dict(job.baseline)
    if job.action is Action.DELETE:
        return (before.user_type is HikvisionUserType.BLOCKED and not after.present
            and result.delete_completed and result.credentials_absent)
    if job.action is Action.EDIT:
        expected["full_name"] = job.request["reviewed_name"].strip()
    elif job.action is Action.PHOTO:
        expected.update(photo_sha256=job.photo_sha256, face_count=1)
    elif job.action is Action.REVOKE:
        expected["user_type"] = HikvisionUserType.BLOCKED.value
    elif job.action is Action.RESTORE:
        if before.user_type is not HikvisionUserType.BLOCKED or before.face_count != 1 or before.policy.model_dump(mode="json") != job.desired_policy:
            return False
        expected["user_type"] = HikvisionUserType.NORMAL.value
    return after.model_dump(mode="json") == expected


def record_result(db: Session, identity: GateLiveDevice, job_id: int, payload: LiveResultInput) -> LiveJobOutput:
    try:
        _config(db, identity.device_id); job = _worker_job(db, identity, job_id, payload.lease_token)
        fingerprint = request_fingerprint(payload.model_dump(mode="json", exclude={"lease_token"}))
        if job.result_hash:
            if job.result_hash != fingerprint:
                raise HTTPException(409, "A different worker result is already retained")
            result = job_output(job); db.rollback(); return result
        if job.state not in (*RUNNING, State.UNCERTAIN):
            raise HTTPException(409, "Worker result is not expected")
        if payload.worker_quiescent and payload.outcome is Outcome.READBACK and _matches(job, payload):
            state = State.SUCCEEDED
        elif job.dispatched or not payload.worker_quiescent:
            state = State.UNCERTAIN
        else:
            state = State.CONFLICT if payload.outcome is Outcome.READBACK else State.FAILED
        finish_live_job(db, job, state=state, result=payload, result_hash=fingerprint, completed_at=now())
        if state is State.SUCCEEDED and job.binding_id and payload.after:
            binding = db.query(GateEmployeeDevice).filter_by(id=job.binding_id, mode=GateMode.HIKVISION).with_for_update().one()
            profile = db.query(GateLiveProfile).filter_by(binding_id=binding.id).one()
            save_live_profile(db, profile, binding, snapshot=payload.after,
                profile_hash=request_fingerprint(payload.after.model_dump(mode="json")), observed_at=now(), adopted=True,
                state=GateBindingState.REVOKED if not payload.after.present or payload.after.user_type is HikvisionUserType.BLOCKED else GateBindingState.ACTIVE)
        log_action(db, None, "turnstile.live.result", "gate_live_job", job.id,
            new_value={"device_id": job.device_id, "state": state.value, "action": job.action.value})
        result = job_output(job); db.commit(); return result
    except Exception:
        db.rollback(); raise


def worker_photo(db: Session, identity: GateLiveDevice, job_id: int, token: str) -> Path:
    job = _worker_job(db, identity, job_id, token)
    _revalidate_intent(db, job, identity)
    if job.state not in RUNNING or not job.lease_expires_at or utc(job.lease_expires_at) <= now() or not job.photo_asset_id:
        raise HTTPException(404, "Assigned photo unavailable")
    asset = db.get(GatePhotoAsset, job.photo_asset_id)
    root = Path(settings.TURNSTILE_PHOTOS_DIR).resolve()
    path = (root / asset.stored_name).resolve()
    if path.parent != root or not path.is_file():
        raise HTTPException(404, "Photo unavailable")
    if hashlib.sha256(path.read_bytes()).hexdigest() != job.photo_sha256:
        raise HTTPException(409, "Photo integrity check failed")
    return path


def resolve_uncertain(db: Session, actor: User, job_id: int, payload: LiveResolutionInput) -> LiveJobOutput:
    require_live()
    if "*" not in user_permissions(actor):
        raise HTTPException(403, "Administrator review required")
    try:
        job = db.get(GateLiveJob, job_id)
        if not job:
            raise HTTPException(404, "Job not found")
        authorize_gate_employee(db, actor, job.employee_id, lock=True)
        _device(db, actor, job.device_id); config = _config(db, job.device_id)
        # The initial lookup can become stale while waiting for the scope/config
        # locks. Match worker order (config -> job) and refresh the identity map
        # before deciding whether this ambiguity is still open.
        job = db.query(GateLiveJob).filter_by(id=job_id).populate_existing().with_for_update().first()
        if job is None:
            raise HTTPException(404, "Job not found")
        observation = db.get(GateLiveJob, payload.observation_job_id)
        if (job.state is not State.UNCERTAIN or not observation or observation.action is not Action.OBSERVE
                or observation.state is not State.SUCCEEDED or observation.employee_id != job.employee_id
                or observation.device_id != job.device_id or not observation.completed_at
                or utc(observation.completed_at) < now() - timedelta(minutes=5)
                or observation.id <= job.id or observation.config_revision != job.config_revision
                or not config or config.config_revision != job.config_revision
                or observation.request["expected_employee_no"] != job.request["expected_employee_no"]):
            raise HTTPException(409, "A fresh later read-only observation is required after stopping the worker")
        snapshot = job_output(observation).observation
        if not snapshot or snapshot.external_person_id != job.request["expected_employee_no"]:
            raise HTTPException(409, "Uncertain identity requires separate reconciliation")
        if snapshot and job.binding_id:
            binding = db.get(GateEmployeeDevice, job.binding_id)
            if binding.external_person_id != snapshot.external_person_id or binding.mode is not GateMode.HIKVISION:
                raise HTTPException(409, "Physical binding identity changed")
            profile = db.query(GateLiveProfile).filter_by(binding_id=binding.id).one()
            save_live_profile(db, profile, binding, snapshot=snapshot,
                profile_hash=request_fingerprint(snapshot.model_dump(mode="json")), observed_at=now(), adopted=True,
                state=GateBindingState.REVOKED if not snapshot.present or snapshot.user_type is HikvisionUserType.BLOCKED else GateBindingState.ACTIVE)
        # Close ambiguity as conflict, never manufacture successful deletion.
        finish_live_job(db, job, state=State.CONFLICT)
        log_action(db, actor, "turnstile.live.resolve", "gate_live_job", job.id,
            new_value={"observation_job_id": observation.id, "worker_stopped_reference": payload.worker_stopped_reference})
        result = job_output(job); db.commit(); return result
    except Exception:
        db.rollback(); raise


def retry_unsent(db: Session, actor: User, job_id: int) -> LiveJobOutput:
    require_live()
    try:
        job = db.get(GateLiveJob, job_id)
        if not job:
            raise HTTPException(404, "Job not found")
        authorize_gate_employee(db, actor, job.employee_id, lock=True)
        _device(db, actor, job.device_id); config = _config(db, job.device_id)
        # A different request may already have retried and claimed this job.
        # Never clear that new lease using the pre-lock cached FAILED instance.
        job = db.query(GateLiveJob).filter_by(id=job_id).populate_existing().with_for_update().first()
        if job is None:
            raise HTTPException(404, "Job not found")
        if (job.state is not State.FAILED or job.dispatched or job.attempt_count >= 3
                or not job.result or not job.result.get("worker_quiescent")):
            raise HTTPException(409, "Only a quiescent, never-dispatched failure can be retried, at most three attempts")
        _revalidate_intent(db, job, config)
        if db.query(GateLiveJob.id).filter(GateLiveJob.device_id == job.device_id, GateLiveJob.id != job.id,
                GateLiveJob.state.in_(OPEN), GateLiveJob.action != Action.OBSERVE).first():
            raise HTTPException(409, "Resolve other device work first")
        retry_unsent_live_job(db, job)
        log_action(db, actor, "turnstile.live.retry_unsent", "gate_live_job", job.id)
        result = job_output(job); db.commit(); return result
    except Exception:
        db.rollback(); raise


def request_receipt(db: Session, actor: User, employee_id: int, key: str | None) -> LiveJobOutput | None:
    employee = authorize_gate_employee(db, actor, employee_id)
    if not key or len(key) > 128:
        raise HTTPException(400, "Idempotency-Key is required")
    job = db.query(GateLiveJob).filter_by(requested_by=actor.id, factory_code=employee.factory_code,
        employee_id=employee.id, request_key=key).first()
    return job_output(job) if job else None
