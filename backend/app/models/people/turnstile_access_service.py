"""Simulator-only turnstile enrollment business operation.

The caller supplies an authenticated actor and session. Writes are delegated to
schema persistence; this operation commits its complete request before processing.
"""
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.deps import user_permissions
from app.models.factory_scope_service import selected_factory_code
from app.schemas import Employee, User, SystemSetting


def authorize_gate_actor(actor: User) -> None:
    if actor is None or not getattr(actor, "id", None) or not getattr(actor, "is_active", False):
        raise HTTPException(401, "Authenticated active user required")
    permissions = set(user_permissions(actor))
    if not permissions.intersection({"*", "attendance.provision"}):
        raise HTTPException(403, "Turnstile provisioning permission required")
    if not permissions.intersection({"*", "hr.employees", "payroll.manage"}):
        raise HTTPException(403, "Private employee access required")


def authorize_gate_employee(db: Session, actor: User, employee_id: int, *, lock: bool = False) -> Employee:
    """Authorize both provisioning and private HR visibility in selected factory."""
    authorize_gate_actor(actor)
    query = db.query(Employee).filter(Employee.id == employee_id, Employee.factory_code == selected_factory_code(actor))
    if lock:
        query = query.with_for_update()
    employee = query.first()
    if employee is None:
        raise HTTPException(404, "Employee not found")
    return employee

from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from app.core.config import settings
from app.libs.types.turnstile_simulator import SimulatorEvidence
from app.libs.dto.people.turnstile_input import GateEnrollmentInput, GateEditInput, GatePhotoReplacementInput, GateRevokeInput, GateEditTargetInput
from app.libs.dto.people.turnstile_output import GateOperationOutput
from app.libs.dto.people.turnstile_context_output import GateEmployeeContextOutput
from app.libs.enums.turnstile import GateAction, GateBindingState, GateMode, GatePhotoValidation, GateTargetState
from app.models.audit_service import log_action
from app.models.idempotency_service import (bind_idempotency_identity, normalize_idempotency_key,
    replay_idempotent_response, request_fingerprint, store_idempotent_response, lookup_idempotent_response)
from app.schemas.people.attendance import AttendanceDevice, AttendancePerson
from app.schemas.people.turnstile import GateEmployeeDevice, GateOperation, GatePhotoAsset, GateSimulatorDevice, GateSimulatorPerson, GateTarget
from app.schemas.people.turnstile_persistence import insert_binding, insert_operation, insert_target, update_binding_state_revision


def _simulator_enabled() -> bool:
    return settings.TURNSTILE_PROVISIONING_MODE == GateMode.SIMULATOR and not settings.strict_security_required


def get_gate_operation(db: Session, actor: User, operation_id: int) -> GateOperationOutput:
    authorize_gate_actor(actor)
    operation = db.query(GateOperation).filter(GateOperation.id == operation_id, GateOperation.factory_code == selected_factory_code(actor)).first()
    if operation is None:
        raise HTTPException(404, "Operation not found")
    authorize_gate_employee(db, actor, operation.employee_id)
    return GateOperationOutput.model_validate(operation)


def _trusted_baseline(db: Session, binding: GateEmployeeDevice, *, lock: bool = False) -> SimulatorEvidence | None:
    if binding.state != GateBindingState.ACTIVE or binding.mode != GateMode.SIMULATOR:
        return None
    targets = (db.query(GateTarget).filter_by(binding_id=binding.id)
               .order_by(GateTarget.revision.desc(), GateTarget.id.desc()).all())
    if any(t.state in (GateTargetState.QUEUED, GateTargetState.PROCESSING, GateTargetState.VERIFYING,
                       GateTargetState.WAITING, GateTargetState.UNCERTAIN) for t in targets):
        return None
    target = next((t for t in targets if t.revision == binding.desired_revision and t.state == GateTargetState.SUCCEEDED), None)
    person_query = db.query(GateSimulatorPerson).filter_by(binding_id=binding.id)
    person = (person_query.with_for_update() if lock else person_query).first()
    if target is None or person is None or not person.present:
        return None
    evidence: SimulatorEvidence = {"revision": person.accepted_revision, "payload_hash": person.accepted_payload_hash,
                "full_name": person.full_name, "external_person_id": person.external_person_id,
                "photo_sha256": person.photo_sha256}
    if (evidence != target.observed_evidence or evidence["revision"] != binding.desired_revision
            or evidence["external_person_id"] != binding.external_person_id):
        return None
    return evidence

def get_gate_context(db: Session, actor: User, employee_id: int) -> GateEmployeeContextOutput:
    employee = authorize_gate_employee(db, actor, employee_id)
    factory = selected_factory_code(actor)
    devices = (db.query(AttendanceDevice, GateSimulatorDevice).join(GateSimulatorDevice, GateSimulatorDevice.device_id == AttendanceDevice.id)
        .filter(AttendanceDevice.factory_code == factory, AttendanceDevice.sync_enabled.is_(True),
                AttendanceDevice.read_only.is_(True), GateSimulatorDevice.factory_code == factory,
                GateSimulatorDevice.mode == GateMode.SIMULATOR).order_by(AttendanceDevice.id).all())
    bindings = db.query(GateEmployeeDevice).filter_by(employee_id=employee.id, factory_code=factory).order_by(GateEmployeeDevice.device_id).all()
    operations = db.query(GateOperation).filter_by(employee_id=employee.id, factory_code=factory).order_by(GateOperation.revision.desc()).limit(20).all()
    return GateEmployeeContextOutput.model_validate({"employee_id": employee.id, "employee_no": employee.employee_no, "supported_actions": [GateAction.ENROLL, GateAction.EDIT, GateAction.PHOTO, GateAction.REVOKE] if _simulator_enabled() else [],
            "simulator_enabled": _simulator_enabled(),
            "devices": [{"id": d.id, "name": d.name, "device_key": d.device_key, "online": config.online} for d, config in devices],
            "bindings": [{"device_id": b.device_id, "state": b.state, "desired_revision": b.desired_revision, "edit_baseline": ({"revision": evidence["revision"], "profile_hash": request_fingerprint(evidence), "full_name": evidence["full_name"]} if (evidence := _trusted_baseline(db, b)) else None)} for b in bindings],
            "operations": [GateOperationOutput.model_validate(o) for o in operations]})


def enroll_gate_employee(db: Session, actor: User, employee_id: int, payload: GateEnrollmentInput, idempotency_key: str | None) -> GateOperationOutput:
    """Persist one all-or-nothing enrollment request; never contact a device."""
    try:
        employee = authorize_gate_employee(db, actor, employee_id, lock=True)
        if not _simulator_enabled():
            raise HTTPException(403, "Simulator provisioning is disabled")
        key = normalize_idempotency_key(idempotency_key)
        if not key:
            raise HTTPException(400, "Idempotency-Key is required")
        factory = selected_factory_code(actor)
        bind_idempotency_identity(db, actor)
        scope = f"turnstile:employee:{employee_id}:enroll"
        body = payload.model_dump(mode="json")
        replay = replay_idempotent_response(db, scope=scope, key=key, payload=body)
        if replay is not None:
            result = get_gate_operation(db, actor, replay["operation_id"])
            db.rollback()
            return result
        if employee.status != "active":
            raise HTTPException(409, "Employee is not active")
        if payload.expected_employee_no != employee.employee_no:
            raise HTTPException(409, "Employee number changed; review the current identity")
        number = (employee.employee_no or "").strip()
        if not number or number != employee.employee_no:
            raise HTTPException(409, "A stored employee number is required")
        prior_bindings = db.query(GateEmployeeDevice).filter_by(employee_id=employee.id, factory_code=factory).all()
        if any(binding.external_person_id != number for binding in prior_bindings):
            raise HTTPException(409, "Existing turnstile identity requires separate reconciliation")
        aliases = db.query(SystemSetting.value_json).filter(SystemSetting.key == f"employee_merge_aliases:{factory}").scalar()
        if isinstance(aliases, dict) and (str(employee.id) in aliases.get("ids", {}) or number in aliases.get("numbers", {})):
            raise HTTPException(409, "Employee identity is reserved by a reviewed merge")
        photo = db.query(GatePhotoAsset).filter_by(id=payload.photo_asset_id, employee_id=employee.id, factory_code=factory).first()
        if photo is None or photo.validation != GatePhotoValidation.TECHNICAL_VALIDATED:
            raise HTTPException(422, "A validated photo belonging to this employee is required")
        ids = sorted(payload.device_ids)
        devices = (db.query(AttendanceDevice).filter(AttendanceDevice.id.in_(ids), AttendanceDevice.factory_code == factory)
                   .order_by(AttendanceDevice.id).with_for_update().all())
        if len(devices) != len(ids):
            raise HTTPException(404, "Device not found")
        configs = db.query(GateSimulatorDevice).filter(GateSimulatorDevice.device_id.in_(ids), GateSimulatorDevice.factory_code == factory, GateSimulatorDevice.mode == GateMode.SIMULATOR).all()
        if len(configs) != len(ids) or any(not d.sync_enabled or not d.read_only for d in devices):
            raise HTTPException(409, "Every target must be an enabled read-only simulator device")
        conflicts = (db.query(GateEmployeeDevice).filter(GateEmployeeDevice.device_id.in_(ids),
             or_(GateEmployeeDevice.employee_id == employee.id, GateEmployeeDevice.external_person_id == number))
             .order_by(GateEmployeeDevice.device_id).with_for_update().all())
        if conflicts:
            raise HTTPException(409, "Device identity or employee binding already exists")
        mirrors = db.query(AttendancePerson).filter(AttendancePerson.device_id.in_(ids), AttendancePerson.external_person_id == number).all()
        if mirrors:
            raise HTTPException(409, "Device profile is already occupied; reviewed adoption is required")
        name = (payload.reviewed_name or employee.full_name).strip()
        if not name:
            raise HTTPException(422, "Reviewed name is required")
        revision = (db.query(func.max(GateOperation.revision)).filter_by(employee_id=employee.id, factory_code=factory).scalar() or 0) + 1
        snapshot_hash = request_fingerprint({"external_person_id": number, "full_name": name, "photo_sha256": photo.sha256, "access_policy": "SIMULATOR_ONLY"})
        operation = insert_operation(db, employee_id=employee.id, factory_code=factory, requested_by=actor.id,
             action=GateAction.ENROLL, mode=GateMode.SIMULATOR, revision=revision, full_name=name,
             photo_asset_id=photo.id, external_person_id=number, snapshot_hash=snapshot_hash)
        for device in devices:
            binding = insert_binding(db, employee_id=employee.id, factory_code=factory, device_id=device.id,
                external_person_id=number, state=GateBindingState.PENDING, desired_revision=revision)
            insert_target(db, operation_id=operation.id, binding_id=binding.id, device_id=device.id, device_name=device.name,
                factory_code=factory, employee_id=employee.id, revision=revision)
        log_action(db, actor, "turnstile.enroll", "gate_operation", operation.id,
                   new_value={"employee_id": employee.id, "device_ids": ids, "revision": revision})
        store_idempotent_response(db, scope=scope, key=key, payload=body, response={"operation_id": operation.id}, user=actor, status_code=202)
        result = GateOperationOutput.model_validate(operation)
        db.commit()
        return result
    except IntegrityError as exc:
        db.rollback()
        constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        if constraint in {"uq_gate_binding_device_external", "uq_gate_binding_employee_device", "uq_gate_target_operation_device"}:
            raise HTTPException(409, "Concurrent device binding conflict") from exc
        raise
    except Exception:
        db.rollback()
        raise



def _reviewed_bindings(db: Session, employee: Employee, factory: str, expected_employee_no: str, targets: list[GateEditTargetInput], *, require_active: bool = True) -> tuple[str, list[int], list[AttendanceDevice], list[GateEmployeeDevice], dict[int, GateEditTargetInput]]:
    number = (employee.employee_no or "").strip()
    if employee.status not in ("active", "inactive", "on_leave", "terminated", "archived") or (require_active and employee.status != "active") or not number or number != employee.employee_no or expected_employee_no != number:
        raise HTTPException(409, "Employee identity is inactive or changed")
    prior = db.query(GateEmployeeDevice).filter_by(employee_id=employee.id, factory_code=factory).all()
    if any(b.external_person_id != number for b in prior):
        raise HTTPException(409, "Existing turnstile identity requires separate reconciliation")
    aliases = db.query(SystemSetting.value_json).filter(SystemSetting.key == f"employee_merge_aliases:{factory}").scalar()
    if isinstance(aliases, dict) and (str(employee.id) in aliases.get("ids", {}) or number in aliases.get("numbers", {})):
        raise HTTPException(409, "Employee identity is reserved by a reviewed merge")
    refs = {t.device_id: t for t in targets}
    ids = sorted(refs)
    devices = (db.query(AttendanceDevice).filter(AttendanceDevice.id.in_(ids), AttendanceDevice.factory_code == factory)
           .order_by(AttendanceDevice.id).with_for_update().all())
    if len(devices) != len(ids):
        raise HTTPException(404, "Device not found")
    configs = db.query(GateSimulatorDevice).filter(GateSimulatorDevice.device_id.in_(ids), GateSimulatorDevice.factory_code == factory, GateSimulatorDevice.mode == GateMode.SIMULATOR).all()
    if len(configs) != len(ids) or any(not d.sync_enabled or not d.read_only for d in devices):
        raise HTTPException(409, "Every target must be an enabled read-only simulator device")
    bindings = (db.query(GateEmployeeDevice).filter(GateEmployeeDevice.device_id.in_(ids), GateEmployeeDevice.employee_id == employee.id, GateEmployeeDevice.factory_code == factory)
            .order_by(GateEmployeeDevice.device_id).with_for_update().all())
    if len(bindings) != len(ids):
        raise HTTPException(409, "Every target must have a verified binding")
    if any(binding.mode != GateMode.SIMULATOR for binding in bindings):
        raise HTTPException(409, "Physical bindings cannot use simulator operations")
    return number, ids, devices, bindings, refs

def edit_gate_employee(db: Session, actor: User, employee_id: int, payload: GateEditInput, idempotency_key: str | None) -> GateOperationOutput:
    """Freeze verified per-device baselines in one transaction without device IO."""
    try:
        employee = authorize_gate_employee(db, actor, employee_id, lock=True)
        if not _simulator_enabled():
            raise HTTPException(403, "Simulator provisioning is disabled")
        key = normalize_idempotency_key(idempotency_key)
        if not key:
            raise HTTPException(400, "Idempotency-Key is required")
        factory = selected_factory_code(actor)
        bind_idempotency_identity(db, actor)
        scope = f"turnstile:employee:{employee_id}:edit"
        body = payload.model_dump(mode="json")
        replay = replay_idempotent_response(db, scope=scope, key=key, payload=body)
        if replay is not None:
            result = get_gate_operation(db, actor, replay["operation_id"])
            db.rollback()
            return result
        number, ids, devices, bindings, refs = _reviewed_bindings(db, employee, factory, payload.expected_employee_no, payload.targets)
        frozen: list[tuple[GateEmployeeDevice, SimulatorEvidence, str, str]] = []
        for binding in bindings:
            evidence = _trusted_baseline(db, binding, lock=True)
            ref = refs[binding.device_id]
            if evidence is None or ref.expected_revision != evidence["revision"] or ref.expected_profile_hash != request_fingerprint(evidence):
                raise HTTPException(409, "Device profile changed; review the current baseline")
            profile_hash = request_fingerprint(evidence)
            desired_hash = request_fingerprint({"external_person_id": evidence["external_person_id"], "full_name": payload.reviewed_name,
                                                "photo_sha256": evidence["photo_sha256"], "access_policy": "SIMULATOR_ONLY"})
            frozen.append((binding, evidence, profile_hash, desired_hash))
        revision = (db.query(func.max(GateOperation.revision)).filter_by(employee_id=employee.id, factory_code=factory).scalar() or 0) + 1
        snapshot_hash = request_fingerprint({"external_person_id": number, "full_name": payload.reviewed_name,
            "targets": [{"device_id": b.device_id, "baseline_profile_hash": h, "desired_payload_hash": d} for b, _, h, d in frozen]})
        operation = insert_operation(db, employee_id=employee.id, factory_code=factory, requested_by=actor.id,
            action=GateAction.EDIT, mode=GateMode.SIMULATOR, revision=revision, full_name=payload.reviewed_name,
            photo_asset_id=None, external_person_id=number, snapshot_hash=snapshot_hash)
        names = {d.id: d.name for d in devices}
        for binding, evidence, profile_hash, desired_hash in frozen:
            update_binding_state_revision(db, binding, state=GateBindingState.PENDING, desired_revision=revision)
            insert_target(db, operation_id=operation.id, binding_id=binding.id, device_id=binding.device_id,
                device_name=names[binding.device_id], factory_code=factory, employee_id=employee.id, revision=revision,
                baseline=evidence, baseline_profile_hash=profile_hash, desired_payload_hash=desired_hash)
        log_action(db, actor, "turnstile.edit", "gate_operation", operation.id,
                   new_value={"employee_id": employee.id, "device_ids": ids, "revision": revision})
        store_idempotent_response(db, scope=scope, key=key, payload=body, response={"operation_id": operation.id}, user=actor, status_code=202)
        result = GateOperationOutput.model_validate(operation)
        db.commit()
        return result
    except IntegrityError as exc:
        db.rollback()
        constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        if constraint in {"uq_gate_target_operation_device"}:
            raise HTTPException(409, "Concurrent device binding conflict") from exc
        raise
    except Exception:
        db.rollback()
        raise



def replace_gate_photo(db: Session, actor: User, employee_id: int, payload: GatePhotoReplacementInput, idempotency_key: str | None) -> GateOperationOutput:
    """Freeze verified per-device baselines in one transaction without device IO."""
    try:
        employee = authorize_gate_employee(db, actor, employee_id, lock=True)
        if not _simulator_enabled():
            raise HTTPException(403, "Simulator provisioning is disabled")
        key = normalize_idempotency_key(idempotency_key)
        if not key:
            raise HTTPException(400, "Idempotency-Key is required")
        factory = selected_factory_code(actor)
        bind_idempotency_identity(db, actor)
        scope = f"turnstile:employee:{employee_id}:photo"
        body = payload.model_dump(mode="json")
        replay = replay_idempotent_response(db, scope=scope, key=key, payload=body)
        if replay is not None:
            result = get_gate_operation(db, actor, replay["operation_id"])
            db.rollback()
            return result
        number, ids, devices, bindings, refs = _reviewed_bindings(db, employee, factory, payload.expected_employee_no, payload.targets)
        photo = db.query(GatePhotoAsset).filter_by(id=payload.photo_asset_id, employee_id=employee.id, factory_code=factory).first()
        if photo is None or photo.validation != GatePhotoValidation.TECHNICAL_VALIDATED:
            raise HTTPException(422, "A validated photo belonging to this employee is required")
        frozen: list[tuple[GateEmployeeDevice, SimulatorEvidence, str, str]] = []
        for binding in bindings:
            evidence = _trusted_baseline(db, binding, lock=True)
            ref = refs[binding.device_id]
            if evidence is None or ref.expected_revision != evidence["revision"] or ref.expected_profile_hash != request_fingerprint(evidence):
                raise HTTPException(409, "Device profile changed; review the current baseline")
            profile_hash = request_fingerprint(evidence)
            desired_hash = request_fingerprint({"external_person_id": evidence["external_person_id"], "full_name": evidence["full_name"],
                                                "photo_sha256": photo.sha256, "access_policy": "SIMULATOR_ONLY"})
            frozen.append((binding, evidence, profile_hash, desired_hash))
        revision = (db.query(func.max(GateOperation.revision)).filter_by(employee_id=employee.id, factory_code=factory).scalar() or 0) + 1
        snapshot_hash = request_fingerprint({"action": GateAction.PHOTO, "external_person_id": number, "photo_asset_id": photo.id, "photo_sha256": photo.sha256,
            "targets": [{"device_id": b.device_id, "baseline_profile_hash": h, "desired_payload_hash": d} for b, _, h, d in frozen]})
        operation = insert_operation(db, employee_id=employee.id, factory_code=factory, requested_by=actor.id,
            action=GateAction.PHOTO, mode=GateMode.SIMULATOR, revision=revision, full_name=employee.full_name,
            photo_asset_id=photo.id, external_person_id=number, snapshot_hash=snapshot_hash)
        names = {d.id: d.name for d in devices}
        for binding, evidence, profile_hash, desired_hash in frozen:
            update_binding_state_revision(db, binding, state=GateBindingState.PENDING, desired_revision=revision)
            insert_target(db, operation_id=operation.id, binding_id=binding.id, device_id=binding.device_id,
                device_name=names[binding.device_id], factory_code=factory, employee_id=employee.id, revision=revision,
                baseline=evidence, baseline_profile_hash=profile_hash, desired_payload_hash=desired_hash)
        log_action(db, actor, "turnstile.photo", "gate_operation", operation.id,
                   new_value={"employee_id": employee.id, "device_ids": ids, "revision": revision})
        store_idempotent_response(db, scope=scope, key=key, payload=body, response={"operation_id": operation.id}, user=actor, status_code=202)
        result = GateOperationOutput.model_validate(operation)
        db.commit()
        return result
    except IntegrityError as exc:
        db.rollback()
        constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        if constraint in {"uq_gate_target_operation_device"}:
            raise HTTPException(409, "Concurrent device binding conflict") from exc
        raise
    except Exception:
        db.rollback()
        raise



def revoke_gate_employee(db: Session, actor: User, employee_id: int, payload: GateRevokeInput, idempotency_key: str | None) -> GateOperationOutput:
    """Freeze verified per-device baselines in one transaction without device IO."""
    try:
        employee = authorize_gate_employee(db, actor, employee_id, lock=True)
        if not _simulator_enabled():
            raise HTTPException(403, "Simulator provisioning is disabled")
        key = normalize_idempotency_key(idempotency_key)
        if not key:
            raise HTTPException(400, "Idempotency-Key is required")
        factory = selected_factory_code(actor)
        bind_idempotency_identity(db, actor)
        scope = f"turnstile:employee:{employee_id}:revoke"
        body = payload.model_dump(mode="json")
        replay = replay_idempotent_response(db, scope=scope, key=key, payload=body)
        if replay is not None:
            result = get_gate_operation(db, actor, replay["operation_id"])
            db.rollback()
            return result
        number, ids, devices, bindings, refs = _reviewed_bindings(db, employee, factory, payload.expected_employee_no, payload.targets, require_active=False)
        frozen: list[tuple[GateEmployeeDevice, SimulatorEvidence, str, str]] = []
        for binding in bindings:
            evidence = _trusted_baseline(db, binding, lock=True)
            ref = refs[binding.device_id]
            if evidence is None or ref.expected_revision != evidence["revision"] or ref.expected_profile_hash != request_fingerprint(evidence):
                raise HTTPException(409, "Device profile changed; review the current baseline")
            profile_hash = request_fingerprint(evidence)
            desired_hash = request_fingerprint({"action": GateAction.REVOKE, "binding_id": binding.id,
                                                "device_id": binding.device_id, "baseline": evidence})
            frozen.append((binding, evidence, profile_hash, desired_hash))
        revision = (db.query(func.max(GateOperation.revision)).filter_by(employee_id=employee.id, factory_code=factory).scalar() or 0) + 1
        snapshot_hash = request_fingerprint({"action": GateAction.REVOKE, "external_person_id": number,
            "targets": [{"device_id": b.device_id, "baseline_profile_hash": h, "desired_payload_hash": d} for b, _, h, d in frozen]})
        operation = insert_operation(db, employee_id=employee.id, factory_code=factory, requested_by=actor.id,
            action=GateAction.REVOKE, mode=GateMode.SIMULATOR, revision=revision, full_name=employee.full_name,
            photo_asset_id=None, external_person_id=number, snapshot_hash=snapshot_hash)
        names = {d.id: d.name for d in devices}
        for binding, evidence, profile_hash, desired_hash in frozen:
            update_binding_state_revision(db, binding, state=GateBindingState.PENDING, desired_revision=revision)
            insert_target(db, operation_id=operation.id, binding_id=binding.id, device_id=binding.device_id,
                device_name=names[binding.device_id], factory_code=factory, employee_id=employee.id, revision=revision,
                baseline=evidence, baseline_profile_hash=profile_hash, desired_payload_hash=desired_hash)
        log_action(db, actor, "turnstile.revoke", "gate_operation", operation.id,
                   new_value={"employee_id": employee.id, "device_ids": ids, "revision": revision})
        store_idempotent_response(db, scope=scope, key=key, payload=body, response={"operation_id": operation.id}, user=actor, status_code=202)
        result = GateOperationOutput.model_validate(operation)
        db.commit()
        return result
    except IntegrityError as exc:
        db.rollback()
        constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        if constraint in {"uq_gate_target_operation_device"}:
            raise HTTPException(409, "Concurrent device binding conflict") from exc
        raise
    except Exception:
        db.rollback()
        raise


def get_gate_request(db: Session, actor: User, employee_id: int, action: GateAction, idempotency_key: str | None) -> GateOperationOutput | None:
    """Resolve only this actor's committed request; absence never proves no work is in flight."""
    authorize_gate_employee(db, actor, employee_id)
    if action not in (GateAction.ENROLL, GateAction.EDIT, GateAction.PHOTO, GateAction.REVOKE):
        raise HTTPException(422, "Unsupported turnstile request action")
    bind_idempotency_identity(db, actor)
    receipt = lookup_idempotent_response(db, scope=f"turnstile:employee:{employee_id}:{action.value}", key=idempotency_key)
    if receipt is None:
        return None
    operation_id = receipt.get("operation_id")
    if type(operation_id) is not int or operation_id <= 0:
        raise HTTPException(409, "Saved request receipt is inconsistent")
    operation = db.get(GateOperation, operation_id)
    if (operation is None or operation.requested_by != actor.id or operation.employee_id != employee_id
            or operation.factory_code != selected_factory_code(actor) or operation.action != action):
        raise HTTPException(409, "Saved request receipt scope is inconsistent")
    return get_gate_operation(db, actor, operation.id)
