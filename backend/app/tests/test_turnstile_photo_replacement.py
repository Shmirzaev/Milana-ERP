import pytest
from fastapi import HTTPException
from sqlalchemy import select
from app.libs.dto.people.turnstile_input import GatePhotoReplacementInput
from app.libs.enums.turnstile import GateAction, GateErrorCode, GateTargetState
from app.models.people import turnstile_access_service as access, turnstile_simulator_service as sim
from app.schemas import IdempotencyRecord
from app.schemas.core import AuditLog
from app.schemas.people import turnstile_persistence as persistence
from app.schemas.people.turnstile import GateOperation, GateTarget, GateSimulatorPerson
from app.tests.test_turnstile_simulator import case as case, snapshot
from app.tests.test_turnstile_edit import prepare, payload


def setup_photo(case):
    factory, actor, employee_id, refs = prepare(case)
    # Establish a genuinely different name through the existing EDIT operation.
    with factory() as db:
        edit = access.edit_gate_employee(db, actor, employee_id, payload([refs[0]], "First Device"), "name-first")
    sim.run_simulator_operation(factory, actor, edit.id)
    with factory() as db:
        asset = persistence.insert_photo_asset(db, employee_id=employee_id, factory_code="MIL", created_by=actor.id,
            stored_name="replacement", sha256="d" * 64, width=10, height=10, content_type="image/jpeg")
        db.commit()
        context = access.get_gate_context(db, actor, employee_id)
        refs = [{"device_id": b.device_id, "expected_revision": b.edit_baseline.revision,
                 "expected_profile_hash": b.edit_baseline.profile_hash} for b in context.bindings if b.edit_baseline]
        return factory, actor, employee_id, refs, asset.id


def request(refs, asset):
    return GatePhotoReplacementInput(expected_employee_no="S001", photo_asset_id=asset,
        manual_face_reviewed=True, targets=refs, action=GateAction.PHOTO)


def test_distinct_names_photo_and_replay(case):
    factory, actor, employee_id, refs, asset = setup_photo(case)
    with factory() as db:
        op = access.replace_gate_photo(db, actor, employee_id, request(refs, asset), "photo-key")
        assert access.replace_gate_photo(db, actor, employee_id, request(refs, asset), "photo-key").id == op.id
        assert access.get_gate_request(db, actor, employee_id, GateAction.PHOTO, "photo-key").id == op.id
        assert op.full_name == "Synthetic Person"
        people = [db.scalar(select(GateSimulatorPerson).where(GateSimulatorPerson.binding_id == db.get(GateTarget, t.id).binding_id)) for t in op.targets]
        assert [p.photo_sha256 for p in people] == ["a" * 64] * 3
    result = sim.run_simulator_operation(factory, actor, op.id)
    assert all(t.state == GateTargetState.SUCCEEDED for t in result.targets)
    with factory() as db:
        people = [db.scalar(select(GateSimulatorPerson).where(GateSimulatorPerson.binding_id == db.get(GateTarget, t.id).binding_id)) for t in op.targets]
        assert [p.full_name for p in people] == ["First Device", "Synthetic Person", "Synthetic Person"]
        assert all(p.photo_sha256 == "d" * 64 and p.external_person_id == "S001" for p in people)
        assert [p.write_count for p in people] == [3, 2, 2]


def test_uncertain_and_lost_response_never_resend(case):
    factory, actor, employee_id, refs, asset = setup_photo(case)
    with factory() as db:
        op = access.replace_gate_photo(db, actor, employee_id, request(refs, asset), "unknown")
        second = db.get(GateTarget, op.targets[1].id)
        persistence.transition_target(db, second, state=GateTargetState.UNCERTAIN, attempts=1,
            error_code=GateErrorCode.LEASE_EXPIRED, lease_token=None, lease_expires_at=None, observed_evidence=None)
        db.commit()
    class Lost(sim.SimulatorAdapter):
        def accept(self, target_id, token):
            super().accept(target_id, token)
            raise TimeoutError()
    first = op.targets[0].id
    sim._process(factory, first, Lost(factory))
    assert snapshot(factory, first)[0::3] == (GateTargetState.UNCERTAIN, 3)
    sim._process(factory, first, sim.SimulatorAdapter(factory))
    assert snapshot(factory, first)[0::3] == (GateTargetState.SUCCEEDED, 3)
    sim._process(factory, second.id, sim.SimulatorAdapter(factory))
    assert snapshot(factory, second.id)[0::3] == (GateTargetState.UNCERTAIN, 1)


def test_stale_bad_asset_and_audit_failure_are_atomic(case, monkeypatch):
    factory, actor, employee_id, refs, asset = setup_photo(case)
    with factory() as db:
        models = (GateOperation, GateTarget, AuditLog, IdempotencyRecord)
        before = tuple(db.query(m).count() for m in models)
        stale = [dict(r) for r in refs]; stale[0]["expected_profile_hash"] = "0" * 64
        for obj in (request(stale, asset), request(refs, 999999)):
            with pytest.raises(HTTPException):
                access.replace_gate_photo(db, actor, employee_id, obj, "bad")
            assert tuple(db.query(m).count() for m in models) == before
        def fail(*args, **kwargs):
            raise RuntimeError("audit failed")
        monkeypatch.setattr(access, "log_action", fail)
        with pytest.raises(RuntimeError, match="audit failed"):
            access.replace_gate_photo(db, actor, employee_id, request(refs, asset), "audit")
        assert tuple(db.query(m).count() for m in models) == before


def test_drift_conflicts_without_photo_overwrite(case):
    factory, actor, employee_id, refs, asset = setup_photo(case)
    with factory() as db:
        op = access.replace_gate_photo(db, actor, employee_id, request(refs, asset), "drift")
        target = db.get(GateTarget, op.targets[0].id)
        binding = db.get(sim.GateEmployeeDevice, target.binding_id)
        persistence.upsert_simulator_person(db, binding=binding, accepted_payload_hash="c" * 64,
            accepted_revision=2, external_person_id="S001", full_name="Other", photo_sha256="b" * 64)
        db.commit()
    sim._process(factory, target.id, sim.SimulatorAdapter(factory))
    assert snapshot(factory, target.id)[0] == GateTargetState.CONFLICT
    with factory() as db:
        person = db.scalar(select(GateSimulatorPerson).where(GateSimulatorPerson.binding_id == target.binding_id))
        assert (person.full_name, person.photo_sha256) == ("Other", "b" * 64)


def test_photo_dto_strict():
    ref = {"device_id": 1, "expected_revision": 1, "expected_profile_hash": "a" * 64}
    valid = {"expected_employee_no": "S001", "photo_asset_id": 1, "manual_face_reviewed": True, "targets": [ref]}
    for invalid in ({"manual_face_reviewed": False}, {"action": "edit"}, {"targets": [ref, ref]}, {"reviewed_name": "X"}):
        with pytest.raises(ValueError):
            GatePhotoReplacementInput(**(valid | invalid))
