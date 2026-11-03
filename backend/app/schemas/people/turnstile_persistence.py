from app.libs.types.turnstile_simulator import SimulatorEvidence
"""Persistence mechanics only; transaction and policy belong to the caller."""
from datetime import datetime
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from app.libs.enums.turnstile import GateAction, GateMode, GateTargetState, GatePhotoValidation, GateBindingState, GateErrorCode
from app.schemas.people.turnstile import GatePhotoAsset, GateEmployeeDevice, GateOperation, GateTarget, GateSimulatorDevice, GateSimulatorPerson

def insert_photo_asset(session: Session, *, employee_id: int, factory_code: str, created_by: int, stored_name: str, sha256: str, width: int, height: int, content_type: str, validation: GatePhotoValidation = GatePhotoValidation.TECHNICAL_VALIDATED) -> GatePhotoAsset:
    row = GatePhotoAsset(employee_id=employee_id, factory_code=factory_code, created_by=created_by, stored_name=stored_name, sha256=sha256, width=width, height=height, content_type=content_type, validation=validation)
    session.add(row); session.flush(); return row

def insert_binding(session: Session, *, employee_id: int, factory_code: str, device_id: int, external_person_id: str, state: GateBindingState, desired_revision: int) -> GateEmployeeDevice:
    row = GateEmployeeDevice(employee_id=employee_id, factory_code=factory_code, device_id=device_id, external_person_id=external_person_id, state=state, desired_revision=desired_revision)
    session.add(row); session.flush(); return row

def insert_operation(session: Session, *, employee_id: int, factory_code: str, requested_by: int, action: GateAction, mode: GateMode, revision: int, full_name: str, photo_asset_id: int | None, external_person_id: str, snapshot_hash: str) -> GateOperation:
    row = GateOperation(employee_id=employee_id, factory_code=factory_code, requested_by=requested_by, action=action, mode=mode, revision=revision, full_name=full_name, photo_asset_id=photo_asset_id, external_person_id=external_person_id, snapshot_hash=snapshot_hash)
    session.add(row); session.flush(); return row

def insert_target(session: Session, *, operation_id: int, binding_id: int, device_id: int, device_name: str, factory_code: str, employee_id: int, revision: int, state: GateTargetState = GateTargetState.QUEUED, baseline: SimulatorEvidence | None = None, baseline_profile_hash: str | None = None, desired_payload_hash: str | None = None) -> GateTarget:
    row = GateTarget(operation_id=operation_id, binding_id=binding_id, device_id=device_id, device_name=device_name, factory_code=factory_code, employee_id=employee_id, revision=revision, state=state, attempts=0, baseline_revision=baseline["revision"] if baseline else None, baseline_payload_hash=baseline["payload_hash"] if baseline else None, baseline_full_name=baseline["full_name"] if baseline else None, baseline_external_person_id=baseline["external_person_id"] if baseline else None, baseline_photo_sha256=baseline["photo_sha256"] if baseline else None, baseline_profile_hash=baseline_profile_hash, desired_payload_hash=desired_payload_hash)
    session.add(row); session.flush(); return row

def transition_target(session: Session, target: GateTarget, *, state: GateTargetState, attempts: int, error_code: GateErrorCode | None, lease_token: str | None, lease_expires_at: datetime | None, observed_evidence: SimulatorEvidence | None) -> GateTarget:
    target.state = state
    target.attempts = attempts
    target.error_code = error_code
    target.lease_token = lease_token
    target.lease_expires_at = lease_expires_at
    target.observed_evidence = observed_evidence
    session.flush(); return target

def update_binding_state_revision(session: Session, binding: GateEmployeeDevice, *, state: GateBindingState, desired_revision: int) -> GateEmployeeDevice:
    binding.state = state
    binding.desired_revision = desired_revision
    session.flush(); return binding

def set_simulator_device(session: Session, *, device_id: int, factory_code: str, online: bool, mode: GateMode) -> GateSimulatorDevice:
    row = session.scalar(select(GateSimulatorDevice).where(GateSimulatorDevice.device_id == device_id))
    if row is None:
        row = GateSimulatorDevice(device_id=device_id, factory_code=factory_code, online=online, mode=mode)
        session.add(row)
    else:
        row.factory_code = factory_code
        row.online = online
        row.mode = mode
    session.flush(); return row

def upsert_simulator_person(session: Session, *, binding: GateEmployeeDevice, external_person_id: str, accepted_payload_hash: str, accepted_revision: int, full_name: str, photo_sha256: str) -> GateSimulatorPerson:
    row = session.scalar(select(GateSimulatorPerson).where(GateSimulatorPerson.binding_id == binding.id))
    if row is None:
        row = GateSimulatorPerson(binding_id=binding.id, external_person_id=external_person_id, accepted_payload_hash=accepted_payload_hash, accepted_revision=accepted_revision, full_name=full_name, photo_sha256=photo_sha256, write_count=1)
        session.add(row)
    else:
        row.external_person_id = external_person_id
        row.accepted_payload_hash = accepted_payload_hash
        row.accepted_revision = accepted_revision
        row.full_name = full_name
        row.photo_sha256 = photo_sha256
        row.write_count += 1
    session.flush(); return row


def compare_and_update_simulator_name(session: Session, *, binding_id: int, baseline: SimulatorEvidence, accepted_revision: int, accepted_payload_hash: str, full_name: str) -> bool:
    session.flush()
    result = session.execute(update(GateSimulatorPerson).where(
        GateSimulatorPerson.binding_id == binding_id,
        GateSimulatorPerson.accepted_revision == baseline["revision"],
        GateSimulatorPerson.accepted_payload_hash == baseline["payload_hash"],
        GateSimulatorPerson.full_name == baseline["full_name"],
        GateSimulatorPerson.external_person_id == baseline["external_person_id"],
        GateSimulatorPerson.photo_sha256 == baseline["photo_sha256"],
    ).values(full_name=full_name, accepted_revision=accepted_revision,
             accepted_payload_hash=accepted_payload_hash, write_count=GateSimulatorPerson.write_count + 1)
      .execution_options(synchronize_session="fetch"))
    session.flush()
    return result.rowcount == 1


def compare_and_update_simulator_photo(session: Session, *, binding_id: int, baseline: SimulatorEvidence, accepted_revision: int, accepted_payload_hash: str, photo_sha256: str) -> bool:
    session.flush()
    result = session.execute(update(GateSimulatorPerson).where(
        GateSimulatorPerson.binding_id == binding_id,
        GateSimulatorPerson.accepted_revision == baseline["revision"],
        GateSimulatorPerson.accepted_payload_hash == baseline["payload_hash"],
        GateSimulatorPerson.full_name == baseline["full_name"],
        GateSimulatorPerson.external_person_id == baseline["external_person_id"],
        GateSimulatorPerson.photo_sha256 == baseline["photo_sha256"],
    ).values(photo_sha256=photo_sha256, accepted_revision=accepted_revision,
             accepted_payload_hash=accepted_payload_hash, write_count=GateSimulatorPerson.write_count + 1)
      .execution_options(synchronize_session="fetch"))
    session.flush()
    return result.rowcount == 1
