import pytest
from fastapi import HTTPException
from sqlalchemy import select
from app.libs.dto.people.turnstile_input import GateEditInput
from app.libs.enums.turnstile import GateTargetState, GateErrorCode
from app.models.people import turnstile_access_service as access, turnstile_simulator_service as sim
from app.schemas.people.turnstile import GateOperation, GateTarget, GateSimulatorPerson
from app.schemas.people import turnstile_persistence as persistence
from app.tests.test_turnstile_simulator import case as case, snapshot


def prepare(case):
    factory, actor, op, ids = case
    sim.run_simulator_operation(factory, actor, op)
    with factory() as db:
        first = db.get(GateTarget, ids[0])
        employee_id = first.employee_id
        context = access.get_gate_context(db, actor, employee_id)
        refs = [{"device_id": b.device_id, "expected_revision": b.edit_baseline.revision,
                 "expected_profile_hash": b.edit_baseline.profile_hash} for b in context.bindings if b.edit_baseline]
    return factory, actor, employee_id, refs


def payload(refs, name="Updated Name"):
    return GateEditInput(expected_employee_no="S001", reviewed_name=name, action="edit", targets=refs)


def test_edit_replay_and_lost_reply(case):
    factory, actor, employee_id, refs = prepare(case)
    with factory() as db:
        operation = access.edit_gate_employee(db, actor, employee_id, payload(refs), "edit-key")
        assert access.edit_gate_employee(db, actor, employee_id, payload(refs), "edit-key").id == operation.id
        with pytest.raises(HTTPException) as error:
            access.edit_gate_employee(db, actor, employee_id, payload(refs, "Different"), "edit-key")
        assert error.value.status_code == 409
    class LostReply(sim.SimulatorAdapter):
        def accept(self, target_id, token):
            super().accept(target_id, token)
            raise TimeoutError()
    target = operation.targets[0].id
    sim._process(factory, target, LostReply(factory))
    assert snapshot(factory, target)[0::3] == (GateTargetState.UNCERTAIN, 2)
    sim._process(factory, target, sim.SimulatorAdapter(factory))
    assert snapshot(factory, target)[0::3] == (GateTargetState.SUCCEEDED, 2)
    with factory() as db:
        person = db.scalar(select(GateSimulatorPerson).where(GateSimulatorPerson.binding_id == db.get(GateTarget, target).binding_id))
        assert (person.full_name, person.photo_sha256, person.external_person_id) == ("Updated Name", "a" * 64, "S001")


def test_uncertain_baseline_never_resends(case):
    factory, actor, employee_id, refs = prepare(case)
    with factory() as db:
        op = access.edit_gate_employee(db, actor, employee_id, payload(refs), "uncertain")
        target = db.get(GateTarget, op.targets[0].id)
        persistence.transition_target(db, target, state=GateTargetState.UNCERTAIN, attempts=1,
            error_code=GateErrorCode.LEASE_EXPIRED, lease_token=None, lease_expires_at=None, observed_evidence=None)
        db.commit()
    sim._process(factory, op.targets[0].id, sim.SimulatorAdapter(factory))
    assert snapshot(factory, op.targets[0].id)[0::3] == (GateTargetState.UNCERTAIN, 1)


def test_stale_reference_and_mixed_unbound_are_atomic(case):
    factory, actor, employee_id, refs = prepare(case)
    stale = [dict(r) for r in refs]
    stale[0]["expected_profile_hash"] = "0" * 64
    with factory() as db:
        before = db.query(GateOperation).count()
        for bad in (stale, refs + [{"device_id": 4, "expected_revision": 1, "expected_profile_hash": "0" * 64}]):
            with pytest.raises(HTTPException) as error:
                access.edit_gate_employee(db, actor, employee_id, payload(bad), "bad")
            assert error.value.status_code == 409
            assert db.query(GateOperation).count() == before


def test_changed_device_after_review_is_not_overwritten(case):
    factory, actor, employee_id, refs = prepare(case)
    with factory() as db:
        op = access.edit_gate_employee(db, actor, employee_id, payload(refs), "race")
        target = db.get(GateTarget, op.targets[0].id)
        binding = db.get(sim.GateEmployeeDevice, target.binding_id)
        persistence.upsert_simulator_person(db, binding=binding, accepted_payload_hash="c" * 64,
            accepted_revision=1, external_person_id="S001", full_name="Other Writer", photo_sha256="d" * 64)
        db.commit()
    sim._process(factory, op.targets[0].id, sim.SimulatorAdapter(factory))
    assert snapshot(factory, op.targets[0].id)[0::3] == (GateTargetState.CONFLICT, 2)
    with factory() as db:
        person = db.scalar(select(GateSimulatorPerson).where(GateSimulatorPerson.binding_id == target.binding_id))
        assert person.full_name == "Other Writer"


def test_heterogeneous_photos_are_preserved(case):
    from app.libs.dto.people.turnstile_input import GateEnrollmentInput
    from app.libs.enums.turnstile import GateMode
    from app.schemas import AttendanceDevice
    factory, actor, employee_id, refs = prepare(case)
    with factory() as db:
        device = AttendanceDevice(factory_code="MIL", device_key="second-photo", name="Second photo", sync_enabled=True, read_only=True)
        db.add(device); db.flush()
        photo = persistence.insert_photo_asset(db, employee_id=employee_id, factory_code="MIL", created_by=actor.id,
            stored_name="second-photo", sha256="b" * 64, width=10, height=10, content_type="image/jpeg")
        persistence.set_simulator_device(db, device_id=device.id, factory_code="MIL", online=True, mode=GateMode.SIMULATOR)
        db.commit()
        enrollment = access.enroll_gate_employee(db, actor, employee_id, GateEnrollmentInput(expected_employee_no="S001",
            device_ids=[device.id], photo_asset_id=photo.id, manual_face_reviewed=True), "second-enroll")
    sim.run_simulator_operation(factory, actor, enrollment.id)
    with factory() as db:
        context = access.get_gate_context(db, actor, employee_id)
        refs = [{"device_id": b.device_id, "expected_revision": b.edit_baseline.revision,
                 "expected_profile_hash": b.edit_baseline.profile_hash} for b in context.bindings if b.edit_baseline]
        op = access.edit_gate_employee(db, actor, employee_id, payload(refs), "photos")
    result = sim.run_simulator_operation(factory, actor, op.id)
    assert all(t.state == GateTargetState.SUCCEEDED for t in result.targets)
    with factory() as db:
        persons = [db.scalar(select(GateSimulatorPerson).where(GateSimulatorPerson.binding_id == db.get(GateTarget, t.id).binding_id)) for t in op.targets]
        assert [p.photo_sha256 for p in persons] == ["a" * 64, "a" * 64, "a" * 64, "b" * 64]
        assert all(p.full_name == "Updated Name" and p.external_person_id == "S001" and p.write_count == 2 for p in persons)


def test_receipt_lookup_is_actor_and_scope_isolated_without_writes(case):
    from app.libs.enums.turnstile import GateAction
    from app.schemas import User, Employee, IdempotencyRecord
    from app.schemas.core import AuditLog
    factory, actor_b, employee_id, refs = prepare(case)
    with factory() as db:
        actor_a = User(name="Other", email="other@example.invalid", password_hash="none", factory_code="MIL", is_active=True,
                       extra_permissions=["attendance.provision", "hr.employees"])
        other_employee = Employee(factory_code="MIL", employee_no="OTHER", full_name="Other", status="active")
        db.add_all([actor_a, other_employee]); db.commit()
        op = access.edit_gate_employee(db, actor_b, employee_id, payload(refs), "shared-key")
        models = (GateOperation, GateTarget, IdempotencyRecord, AuditLog)
        before = tuple(db.query(m).count() for m in models)
        assert access.get_gate_request(db, actor_a, employee_id, GateAction.EDIT, "shared-key") is None
        assert access.get_gate_request(db, actor_b, employee_id, GateAction.EDIT, "shared-key").id == op.id
        assert access.get_gate_request(db, actor_b, employee_id, GateAction.EDIT, "unknown") is None
        assert access.get_gate_request(db, actor_b, employee_id, GateAction.ENROLL, "shared-key") is None
        assert access.get_gate_request(db, actor_b, other_employee.id, GateAction.EDIT, "shared-key") is None
        actor_a.session_factory_code = "ECO"
        with pytest.raises(HTTPException) as error:
            access.get_gate_request(db, actor_a, employee_id, GateAction.EDIT, "shared-key")
        assert error.value.status_code in (403, 404)
        assert tuple(db.query(m).count() for m in models) == before
        assert not db.new and not db.dirty and not db.deleted


def test_edit_audit_failure_rolls_back_everything(case, monkeypatch):
    from app.schemas import IdempotencyRecord
    from app.schemas.core import AuditLog
    factory, actor, employee_id, refs = prepare(case)
    with factory() as db:
        models = (GateOperation, GateTarget, IdempotencyRecord, AuditLog)
        before = tuple(db.query(m).count() for m in models)
        def fail(*args, **kwargs):
            raise RuntimeError("injected audit failure")
        monkeypatch.setattr(access, "log_action", fail)
        with pytest.raises(RuntimeError, match="injected audit failure"):
            access.edit_gate_employee(db, actor, employee_id, payload(refs), "audit-failure")
        assert tuple(db.query(m).count() for m in models) == before
        context = access.get_gate_context(db, actor, employee_id)
        assert sum(b.edit_baseline is not None for b in context.bindings) == len(refs)


def test_edit_refuses_archived_alias_and_missing(case):
    from app.schemas import Employee, SystemSetting
    factory, actor, employee_id, refs = prepare(case)
    with factory() as db:
        before = db.query(GateOperation).count()
        employee = db.get(Employee, employee_id)
        employee.status = "archived"; db.commit()
        with pytest.raises(HTTPException) as error:
            access.edit_gate_employee(db, actor, employee_id, payload(refs), "archived")
        assert error.value.status_code == 409
        employee.status = "active"
        db.add(SystemSetting(key="employee_merge_aliases:MIL", value_json={"numbers": {"S001": 999}})); db.commit()
        with pytest.raises(HTTPException) as error:
            access.edit_gate_employee(db, actor, employee_id, payload(refs), "alias")
        assert error.value.status_code == 409
        assert db.query(GateOperation).count() == before
        with pytest.raises(HTTPException) as error:
            access.edit_gate_employee(db, actor, 999999, payload(refs), "missing")
        assert error.value.status_code == 404


def test_edit_permission_and_inflight_refusals(case):
    factory, actor, employee_id, refs = prepare(case)
    with factory() as db:
        before = db.query(GateOperation).count()
        actor.extra_permissions = ["attendance.provision"]
        with pytest.raises(HTTPException) as error:
            access.edit_gate_employee(db, actor, employee_id, payload(refs), "permission")
        assert error.value.status_code == 403
        actor.extra_permissions = ["attendance.provision", "hr.employees"]
        op = access.edit_gate_employee(db, actor, employee_id, payload(refs), "first")
        with pytest.raises(HTTPException) as error:
            access.edit_gate_employee(db, actor, employee_id, payload(refs), "inflight")
        assert error.value.status_code == 409
        assert db.query(GateOperation).count() == before + 1
        assert len(op.targets) == len(refs)
