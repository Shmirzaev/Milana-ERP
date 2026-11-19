from datetime import datetime, timedelta, timezone
from uuid import uuid4
from sqlalchemy.orm import Session, sessionmaker
from app.schemas import User
from app.libs.dto.people.turnstile_output import GateOperationOutput
from app.libs.types.turnstile_simulator import SimulatorEvidence, SimulatorReadback

from fastapi import HTTPException
from sqlalchemy import select

from app.core.config import settings
from app.libs.enums.turnstile import GateAction, GateBindingState, GateErrorCode, GateMode, GateTargetState
from app.models.people.turnstile_access_service import authorize_gate_employee, get_gate_operation
from app.schemas.people.turnstile import (GateEmployeeDevice, GateOperation, GatePhotoAsset,
    GateSimulatorDevice, GateSimulatorPerson, GateTarget)
from app.schemas.people.turnstile_persistence import (set_simulator_device, transition_target,
    update_binding_state_revision, upsert_simulator_person, compare_and_update_simulator_name, compare_and_update_simulator_photo, compare_and_revoke_simulator_person)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _expired(value: datetime | None) -> bool:
    if value is None:
        return True
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value <= _now()


def _guard() -> None:
    if settings.strict_security_required or settings.TURNSTILE_PROVISIONING_MODE != GateMode.SIMULATOR:
        raise HTTPException(status_code=404, detail="Simulator unavailable")


def _transition(db: Session, target: GateTarget, state: GateTargetState, error: GateErrorCode | None = None, token: str | None = None, expires: datetime | None = None, evidence: SimulatorReadback | None = None, attempts: int | None = None) -> None:
    transition_target(db, target, state=state, attempts=target.attempts if attempts is None else attempts,
        error_code=error, lease_token=token, lease_expires_at=expires, observed_evidence=evidence)


def _target(db: Session, target_id: int) -> GateTarget | None:
    return db.scalar(select(GateTarget).where(GateTarget.id == target_id).with_for_update())


def _binding(db: Session, binding_id: int) -> GateEmployeeDevice | None:
    return db.scalar(select(GateEmployeeDevice).where(GateEmployeeDevice.id == binding_id).with_for_update())


def _evidence(person: GateSimulatorPerson | None, binding: GateEmployeeDevice) -> SimulatorReadback | None:
    if person is None:
        return None
    if not person.present:
        return {"action": GateAction.REVOKE, "revision": person.accepted_revision,
            "payload_hash": person.accepted_payload_hash, "external_person_id": person.external_person_id, "present": False}
    return {"revision": person.accepted_revision, "payload_hash": person.accepted_payload_hash,
        "full_name": person.full_name, "external_person_id": person.external_person_id,
        "photo_sha256": person.photo_sha256}


def _matches(evidence: SimulatorEvidence | None, op: GateOperation, photo: GatePhotoAsset) -> bool:
    return bool(evidence and evidence == {"revision": op.revision, "payload_hash": op.snapshot_hash,
        "full_name": op.full_name, "external_person_id": op.external_person_id, "photo_sha256": photo.sha256})


def _baseline(target: GateTarget) -> SimulatorEvidence:
    if (target.baseline_revision is None or target.baseline_payload_hash is None
            or target.baseline_full_name is None or target.baseline_external_person_id is None
            or target.baseline_photo_sha256 is None or target.baseline_profile_hash is None
            or target.desired_payload_hash is None):
        raise RuntimeError("Edit baseline is incomplete")
    return {"revision": target.baseline_revision, "payload_hash": target.baseline_payload_hash,
            "full_name": target.baseline_full_name, "external_person_id": target.baseline_external_person_id,
            "photo_sha256": target.baseline_photo_sha256}


def _desired(target: GateTarget, op: GateOperation, photo: GatePhotoAsset | None) -> SimulatorEvidence:
    baseline = _baseline(target)
    if target.desired_payload_hash is None:
        raise RuntimeError("Edit desired hash is missing")
    if op.action == GateAction.EDIT:
        name, photo_hash = op.full_name, baseline["photo_sha256"]
    elif op.action == GateAction.PHOTO and photo is not None:
        name, photo_hash = baseline["full_name"], photo.sha256
    else:
        raise RuntimeError("Unsupported simulator action or missing photo")
    return {"revision": op.revision, "payload_hash": target.desired_payload_hash,
            "full_name": name, "external_person_id": baseline["external_person_id"],
            "photo_sha256": photo_hash}


class SimulatorAdapter:
    """In-process terminal with durable, independently committed acceptance."""
    def __init__(self, factory: sessionmaker[Session]) -> None:
        self.factory = factory

    def read(self, target_id: int, token: str) -> tuple[bool, SimulatorReadback | None]:
        with self.factory() as db:
            target = _target(db, target_id)
            if not target or target.lease_token != token or _expired(target.lease_expires_at):
                raise RuntimeError("stale lease")
            binding = _binding(db, target.binding_id)
            device = db.scalar(select(GateSimulatorDevice).where(GateSimulatorDevice.device_id == target.device_id))
            if not device or device.factory_code != target.factory_code or device.mode != GateMode.SIMULATOR or not device.online:
                return False, None
            person = db.scalar(select(GateSimulatorPerson).where(GateSimulatorPerson.binding_id == binding.id))
            return True, _evidence(person, binding)

    def accept(self, target_id: int, token: str) -> None:
        with self.factory() as db:
            target = _target(db, target_id)
            if not target or target.lease_token != token or _expired(target.lease_expires_at):
                raise RuntimeError("stale lease")
            binding = _binding(db, target.binding_id)
            op = db.get(GateOperation, target.operation_id)
            photo = db.get(GatePhotoAsset, op.photo_asset_id) if op.photo_asset_id is not None else None
            device = db.scalar(select(GateSimulatorDevice).where(GateSimulatorDevice.device_id == target.device_id).with_for_update())
            if binding.desired_revision != target.revision or binding.external_person_id != op.external_person_id:
                raise RuntimeError("stale revision")
            if not device or device.factory_code != target.factory_code or device.mode != GateMode.SIMULATOR or not device.online:
                return
            person = db.scalar(select(GateSimulatorPerson).where(GateSimulatorPerson.binding_id == binding.id))
            evidence = _evidence(person, binding)
            if op.action in (GateAction.EDIT, GateAction.PHOTO, GateAction.REVOKE):
                if target.state != GateTargetState.PROCESSING:
                    raise RuntimeError("Edit reconciliation cannot accept a write")
                if evidence == _baseline(target):
                    if op.action == GateAction.REVOKE:
                        compare_and_revoke_simulator_person(db, binding_id=binding.id, baseline=_baseline(target),
                            accepted_revision=target.revision, accepted_payload_hash=target.desired_payload_hash)
                        db.commit()
                        return
                    desired = _desired(target, op, photo)
                    if op.action == GateAction.EDIT:
                        compare_and_update_simulator_name(db, binding_id=binding.id, baseline=_baseline(target),
                            accepted_revision=target.revision, accepted_payload_hash=desired["payload_hash"], full_name=op.full_name)
                    else:
                        compare_and_update_simulator_photo(db, binding_id=binding.id, baseline=_baseline(target),
                            accepted_revision=target.revision, accepted_payload_hash=desired["payload_hash"], photo_sha256=desired["photo_sha256"])
                db.commit()
                return
            if op.action != GateAction.ENROLL or photo is None:
                raise RuntimeError("Unsupported simulator action or missing photo")
            if evidence is not None:
                if not _matches(evidence, op, photo):
                    return
            else:
                upsert_simulator_person(db, binding=binding, accepted_payload_hash=op.snapshot_hash,
                    accepted_revision=op.revision, external_person_id=op.external_person_id, full_name=op.full_name, photo_sha256=photo.sha256)
            db.commit()


def _claim(factory: sessionmaker[Session], target_id: int) -> tuple[str, bool] | None:
    with factory() as db:
        target = _target(db, target_id)
        if not target:
            return None
        binding = _binding(db, target.binding_id)
        if target.state in (GateTargetState.PROCESSING, GateTargetState.VERIFYING):
            if not _expired(target.lease_expires_at):
                return None
            _transition(db, target, GateTargetState.UNCERTAIN, GateErrorCode.LEASE_EXPIRED)
            db.commit()
            # Expiry is not evidence of failure: a later explicit run reconciles.
            return None
        if target.state not in (GateTargetState.QUEUED, GateTargetState.WAITING, GateTargetState.UNCERTAIN):
            return None
        if binding.desired_revision != target.revision:
            _transition(db, target, GateTargetState.SUPERSEDED, GateErrorCode.STALE_REVISION)
            db.commit()
            return None
        # Uncertain targets remain readable after the attempt limit, but cannot be written again.
        if target.attempts >= settings.TURNSTILE_SIMULATOR_MAX_ATTEMPTS and target.state != GateTargetState.UNCERTAIN:
            return None
        was_uncertain = target.state == GateTargetState.UNCERTAIN
        token = uuid4().hex
        _transition(db, target, GateTargetState.VERIFYING if was_uncertain else GateTargetState.PROCESSING,
            token=token, expires=_now() + timedelta(seconds=settings.TURNSTILE_SIMULATOR_LEASE_SECONDS),
            attempts=min(settings.TURNSTILE_SIMULATOR_MAX_ATTEMPTS, target.attempts + 1))
        db.commit()
        return token, was_uncertain


def _finish(factory: sessionmaker[Session], target_id: int, token: str, state: GateTargetState, error: GateErrorCode | None = None, evidence: SimulatorReadback | None = None) -> bool:
    with factory() as db:
        target = _target(db, target_id)
        if not target or target.lease_token != token or _expired(target.lease_expires_at):
            return False
        binding = _binding(db, target.binding_id)
        if binding.desired_revision != target.revision:
            state, error = GateTargetState.SUPERSEDED, GateErrorCode.STALE_REVISION
        if state == GateTargetState.SUCCEEDED:
            op = db.get(GateOperation, target.operation_id)
            update_binding_state_revision(db, binding, state=GateBindingState.REVOKED if op.action == GateAction.REVOKE else GateBindingState.ACTIVE, desired_revision=target.revision)
        _transition(db, target, state, error, evidence=evidence)
        db.commit()
        return True


def _process(factory: sessionmaker[Session], target_id: int, adapter: SimulatorAdapter) -> None:
    claim = _claim(factory, target_id)
    if not claim:
        return
    token, was_uncertain = claim
    try:
        online, evidence = adapter.read(target_id, token)
        if not online:
            _finish(factory, target_id, token, GateTargetState.UNCERTAIN if was_uncertain else GateTargetState.WAITING,
                GateErrorCode.DEVICE_OFFLINE)
            return
        with factory() as db:
            target = db.get(GateTarget, target_id)
            op = db.get(GateOperation, target.operation_id)
            photo = db.get(GatePhotoAsset, op.photo_asset_id) if op.photo_asset_id is not None else None
            mutation = op.action in (GateAction.EDIT, GateAction.PHOTO, GateAction.REVOKE)
            if not mutation and (op.action != GateAction.ENROLL or photo is None):
                raise RuntimeError("Unsupported simulator action or missing photo")
            if op.action == GateAction.REVOKE:
                desired = {"action": GateAction.REVOKE, "revision": op.revision, "payload_hash": target.desired_payload_hash,
                           "external_person_id": target.baseline_external_person_id, "present": False}
                _baseline(target)
            else:
                desired = _desired(target, op, photo) if mutation else None
            matches = evidence == desired if mutation else _matches(evidence, op, photo)
            baseline = _baseline(target) if mutation else None
            exhausted = target.attempts >= settings.TURNSTILE_SIMULATOR_MAX_ATTEMPTS
        if matches:
            _finish(factory, target_id, token, GateTargetState.SUCCEEDED, evidence=evidence)
        elif mutation and was_uncertain:
            if evidence is not None and evidence != baseline:
                _finish(factory, target_id, token, GateTargetState.CONFLICT, GateErrorCode.PAYLOAD_CONFLICT, evidence)
            else:
                _finish(factory, target_id, token, GateTargetState.UNCERTAIN, GateErrorCode.SIMULATOR_ERROR, evidence)
        elif evidence is not None and (not mutation or evidence != baseline):
            _finish(factory, target_id, token, GateTargetState.CONFLICT, GateErrorCode.PAYLOAD_CONFLICT, evidence)
        elif mutation and evidence is None:
            _finish(factory, target_id, token, GateTargetState.CONFLICT, GateErrorCode.PAYLOAD_CONFLICT)
        elif was_uncertain and exhausted:
            _finish(factory, target_id, token, GateTargetState.UNCERTAIN, GateErrorCode.SIMULATOR_ERROR)
        else:
            adapter.accept(target_id, token)
            online, evidence = adapter.read(target_id, token)
            if not online:
                _finish(factory, target_id, token, GateTargetState.UNCERTAIN, GateErrorCode.DEVICE_OFFLINE)
            elif (evidence == desired if mutation else _matches(evidence, op, photo)):
                _finish(factory, target_id, token, GateTargetState.SUCCEEDED, evidence=evidence)
            elif evidence is not None:
                _finish(factory, target_id, token, GateTargetState.CONFLICT, GateErrorCode.PAYLOAD_CONFLICT, evidence)
            else:
                _finish(factory, target_id, token, GateTargetState.UNCERTAIN, GateErrorCode.SIMULATOR_ERROR)
    except Exception:
        _finish(factory, target_id, token, GateTargetState.UNCERTAIN, GateErrorCode.SIMULATOR_ERROR)


def _authorized_targets(factory: sessionmaker[Session], actor: User, operation_id: int) -> list[int]:
    _guard()
    with factory() as db:
        # The public service enforces both selected factory and employee authorization.
        get_gate_operation(db, actor, operation_id)
        op = db.get(GateOperation, operation_id)
        authorize_gate_employee(db, actor, op.employee_id)
        if op.mode != GateMode.SIMULATOR:
            raise HTTPException(status_code=404, detail="Operation unavailable")
        ids = list(db.scalars(select(GateTarget.id).where(GateTarget.operation_id == operation_id).order_by(GateTarget.id)))
        return ids


def run_simulator_operation(factory: sessionmaker[Session], actor: User, operation_id: int, *, adapter: SimulatorAdapter | None = None) -> GateOperationOutput:
    ids = _authorized_targets(factory, actor, operation_id)
    adapter = adapter or SimulatorAdapter(factory)
    for target_id in ids:
        _process(factory, target_id, adapter)
    with factory() as db:
        return get_gate_operation(db, actor, operation_id)


def reconnect_simulator_operation(factory: sessionmaker[Session], actor: User, operation_id: int) -> GateOperationOutput:
    ids = _authorized_targets(factory, actor, operation_id)
    with factory() as db:
        for target_id in ids:
            target = _target(db, target_id)
            if target.state != GateTargetState.WAITING:
                continue
            device = db.scalar(select(GateSimulatorDevice).where(GateSimulatorDevice.device_id == target.device_id).with_for_update())
            if device and device.factory_code == target.factory_code and device.mode == GateMode.SIMULATOR:
                set_simulator_device(db, device_id=device.device_id, factory_code=device.factory_code, online=True, mode=device.mode)
                # WAITING means the initial read was offline, before any acceptance.
                # This explicit dev-only action starts a fresh bounded attempt budget.
                _transition(db, target, GateTargetState.WAITING, GateErrorCode.DEVICE_OFFLINE, attempts=0)
        db.commit()
    return run_simulator_operation(factory, actor, operation_id)
