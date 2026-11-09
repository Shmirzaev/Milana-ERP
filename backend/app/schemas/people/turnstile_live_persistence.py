"""Decided live-device writes in the caller's transaction; no independent commits."""
from datetime import datetime
from sqlalchemy.orm import Session
from app.libs.dto.people.turnstile_live import LiveDeviceInput, LiveRequestInput, LiveSnapshot, LiveResultInput, LiveAccessPolicy
from app.libs.enums.turnstile import GateBindingState, GateMode, LiveGateState
from app.schemas.people.turnstile import GateEmployeeDevice
from app.schemas.people.turnstile_live import GateLiveDevice, GateLiveJob, GateLiveProfile


def save_live_device(db: Session, row: GateLiveDevice | None, *, device_id: int, factory: str, token_hash: str, source_host: str, certificate_sha256: str, payload: LiveDeviceInput) -> GateLiveDevice:
    if row is None:
        row = GateLiveDevice(device_id=device_id, factory_code=factory, worker_token_hash=token_hash, config_revision=1)
        db.add(row)
    else:
        row.config_revision += 1
    row.worker_token_hash = token_hash
    row.source_host = source_host; row.certificate_sha256 = certificate_sha256
    row.enabled = payload.enabled
    row.writes_enabled = payload.writes_enabled
    row.configuration = payload.model_dump(mode="json")
    db.flush()
    return row


def insert_live_binding(db: Session, *, employee_id: int, factory: str, device_id: int, number: str, adopted: bool) -> tuple[GateEmployeeDevice, GateLiveProfile]:
    binding = GateEmployeeDevice(employee_id=employee_id, factory_code=factory, device_id=device_id,
        external_person_id=number, mode=GateMode.HIKVISION, state=GateBindingState.ACTIVE if adopted else GateBindingState.PENDING, desired_revision=1)
    db.add(binding); db.flush()
    profile = GateLiveProfile(binding_id=binding.id, adopted=adopted)
    db.add(profile); db.flush()
    return binding, profile


def insert_live_job(db: Session, *, actor_id: int, factory: str, employee_id: int, payload: LiveRequestInput,
                    request_key: str, request_hash: str, config_revision: int, binding_id: int | None,
                    baseline: LiveSnapshot | None, policy: LiveAccessPolicy | None, photo_hash: str | None) -> GateLiveJob:
    row = GateLiveJob(requested_by=actor_id, factory_code=factory, employee_id=employee_id, device_id=payload.device_id,
        binding_id=binding_id, action=payload.action, state=LiveGateState.QUEUED,
        request_key=request_key, request_hash=request_hash, request=payload.model_dump(mode="json"),
        config_revision=config_revision, baseline=baseline.model_dump(mode="json") if baseline else None,
        desired_policy=policy.model_dump(mode="json") if policy else None,
        photo_asset_id=payload.photo_asset_id, photo_sha256=photo_hash)
    db.add(row); db.flush(); return row


def lease_live_job(db: Session, job: GateLiveJob, *, token_hash: str, expires: datetime) -> None:
    job.state = LiveGateState.PROCESSING; job.lease_token_hash = token_hash; job.lease_expires_at = expires
    job.attempt_count += 1
    db.flush()


def dispatch_live_job(db: Session, job: GateLiveJob) -> None:
    job.dispatched = True; job.state = LiveGateState.DISPATCHING
    job.dispatch_count += 1
    db.flush()


def retry_unsent_live_job(db: Session, job: GateLiveJob) -> None:
    job.result_history = [*job.result_history, {"result": job.result, "result_hash": job.result_hash, "attempt": job.attempt_count}]
    job.result = None; job.result_hash = None; job.completed_at = None
    job.lease_token_hash = None; job.lease_expires_at = None; job.state = LiveGateState.QUEUED
    db.flush()


def finish_live_job(db: Session, job: GateLiveJob, *, state: LiveGateState, result: LiveResultInput | None = None, result_hash: str | None = None, completed_at: datetime | None = None) -> None:
    job.state = state
    if completed_at is not None:
        job.completed_at = completed_at
    if result is not None:
        # Never persist the bearer lease secret in result/audit JSON.
        job.result = result.model_dump(mode="json", exclude={"lease_token"})
        job.result_hash = result_hash
    db.flush()


def save_live_profile(db: Session, profile: GateLiveProfile, binding: GateEmployeeDevice, *, snapshot: LiveSnapshot,
                      profile_hash: str, observed_at: datetime, adopted: bool, state: GateBindingState) -> None:
    profile.snapshot = snapshot.model_dump(mode="json"); profile.profile_hash = profile_hash
    profile.observed_at = observed_at; profile.adopted = adopted
    binding.state = state; binding.desired_revision += 1
    db.flush()
