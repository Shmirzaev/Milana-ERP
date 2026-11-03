from datetime import timedelta
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from app.libs.dto.people.turnstile_input import GateEditInput
from app.libs.enums.turnstile import GateTargetState, GateErrorCode
from app.models.people import turnstile_access_service as access, turnstile_simulator_service as sim
from app.schemas.people.turnstile import GateOperation, GateTarget, GateSimulatorPerson
from app.schemas.people import turnstile_persistence as persistence
from app.tests.test_turnstile_simulator import case, snapshot


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
    factory, actor, employee_id, refs = prepare(case)
    # Create a second legitimate verified enrollment with a different photo.
    with factory() as db:
        target = db.query(GateTarget).filter_by(device_id=refs[1]["device_id"]).one()
        person = db.scalar(select(GateSimulatorPerson).where(GateSimulatorPerson.binding_id == target.binding_id))
        person.photo_sha256 = "b" * 64
        evidence = sim._evidence(person, db.get(sim.GateEmployeeDevice, target.binding_id))
        persistence.transition_target(db, target, state=GateTargetState.SUCCEEDED, attempts=target.attempts,
            error_code=None, lease_token=None, lease_expires_at=None, observed_evidence=evidence)
        db.commit()
        context = access.get_gate_context(db, actor, employee_id)
        refs = [{"device_id": b.device_id, "expected_revision": b.edit_baseline.revision,
                 "expected_profile_hash": b.edit_baseline.profile_hash} for b in context.bindings if b.edit_baseline]
        op = access.edit_gate_employee(db, actor, employee_id, payload(refs), "photos")
    sim.run_simulator_operation(factory, actor, op.id)
    with factory() as db:
        persons = [db.scalar(select(GateSimulatorPerson).where(GateSimulatorPerson.binding_id == db.get(GateTarget, t.id).binding_id)) for t in op.targets]
        assert [p.photo_sha256 for p in persons] == ["a" * 64, "b" * 64, "a" * 64]
        assert all(p.full_name == "Updated Name" and p.write_count == 2 for p in persons)
