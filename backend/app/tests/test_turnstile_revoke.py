import pytest
from fastapi import HTTPException
from sqlalchemy import select
from app.libs.dto.people.turnstile_input import GateRevokeInput
from app.libs.enums.turnstile import GateAction, GateBindingState, GateErrorCode, GateTargetState
from app.models.people import turnstile_access_service as access, turnstile_simulator_service as sim
from app.schemas import Employee, IdempotencyRecord
from app.schemas.core import AuditLog
from app.schemas.people import turnstile_persistence as persistence
from app.schemas.people.turnstile import GateEmployeeDevice, GateOperation, GateSimulatorPerson, GateTarget
from app.tests.test_turnstile_simulator import case as case, snapshot
from app.tests.test_turnstile_edit import prepare


def payload(refs):
    return GateRevokeInput(expected_employee_no="S001", action=GateAction.REVOKE, targets=refs)


def test_archived_revoke_once_and_no_reuse(case):
    factory, actor, employee_id, refs = prepare(case)
    with factory() as db:
        db.get(Employee, employee_id).status = "archived"; db.commit()
        op = access.revoke_gate_employee(db, actor, employee_id, payload(refs), "revoke")
        assert access.revoke_gate_employee(db, actor, employee_id, payload(refs), "revoke").id == op.id
        assert access.get_gate_request(db, actor, employee_id, GateAction.REVOKE, "revoke").id == op.id
    result = sim.run_simulator_operation(factory, actor, op.id)
    assert all(t.state == GateTargetState.SUCCEEDED for t in result.targets)
    sim.run_simulator_operation(factory, actor, op.id)
    with factory() as db:
        for item in result.targets:
            target = db.get(GateTarget, item.id); binding = db.get(GateEmployeeDevice, target.binding_id)
            person = db.scalar(select(GateSimulatorPerson).where(GateSimulatorPerson.binding_id == binding.id))
            assert binding.state == GateBindingState.REVOKED and not person.present and person.write_count == 2
            assert (person.full_name, person.external_person_id, person.photo_sha256) == ("Synthetic Person", "S001", "a" * 64)
            assert target.observed_evidence == {"action":"revoke", "revision":op.revision, "payload_hash":target.desired_payload_hash, "external_person_id":"S001", "present":False}
            with pytest.raises(RuntimeError):
                persistence.upsert_simulator_person(db, binding=binding, accepted_payload_hash="a" * 64,
                    accepted_revision=1, external_person_id="S001", full_name="New", photo_sha256="b" * 64)
        assert db.get(Employee, employee_id).status == "archived"
        assert all(b.edit_baseline is None for b in access.get_gate_context(db, actor, employee_id).bindings)


def test_lost_accept_and_uncertain_baseline_are_read_only(case):
    factory, actor, employee_id, refs = prepare(case)
    with factory() as db:
        op = access.revoke_gate_employee(db, actor, employee_id, payload(refs), "uncertain")
        target = db.get(GateTarget, op.targets[1].id)
        persistence.transition_target(db, target, state=GateTargetState.UNCERTAIN, attempts=1,
            error_code=GateErrorCode.LEASE_EXPIRED, lease_token=None, lease_expires_at=None, observed_evidence=None); db.commit()
    class Lost(sim.SimulatorAdapter):
        def accept(self, target_id, token):
            super().accept(target_id, token); raise TimeoutError()
    first = op.targets[0].id
    sim._process(factory, first, Lost(factory))
    assert snapshot(factory, first)[0::3] == (GateTargetState.UNCERTAIN, 2)
    sim._process(factory, first, sim.SimulatorAdapter(factory))
    assert snapshot(factory, first)[0::3] == (GateTargetState.SUCCEEDED, 2)
    sim._process(factory, target.id, sim.SimulatorAdapter(factory))
    assert snapshot(factory, target.id)[0::3] == (GateTargetState.UNCERTAIN, 1)


def test_refusals_and_audit_rollback(case, monkeypatch):
    factory, actor, employee_id, refs = prepare(case)
    with factory() as db:
        models = (GateOperation, GateTarget, IdempotencyRecord, AuditLog)
        before = tuple(db.query(m).count() for m in models)
        stale = [dict(r) for r in refs]; stale[0]["expected_profile_hash"] = "0" * 64
        with pytest.raises(HTTPException) as error:
            access.revoke_gate_employee(db, actor, employee_id, payload(stale), "stale")
        assert error.value.status_code == 409
        actor.extra_permissions = ["attendance.provision"]
        with pytest.raises(HTTPException) as error:
            access.revoke_gate_employee(db, actor, employee_id, payload(refs), "denied")
        assert error.value.status_code == 403
        actor.extra_permissions = ["attendance.provision", "hr.employees"]
        def fail(*args, **kwargs): raise RuntimeError("audit failed")
        monkeypatch.setattr(access, "log_action", fail)
        with pytest.raises(RuntimeError): access.revoke_gate_employee(db, actor, employee_id, payload(refs), "audit")
        assert tuple(db.query(m).count() for m in models) == before


def test_revoke_dto_rejects_unknown_and_duplicates():
    ref = {"device_id":1,"expected_revision":1,"expected_profile_hash":"a" * 64}
    valid = {"expected_employee_no":"S001","targets":[ref]}
    for bad in ({"action":"photo"}, {"targets":[ref,ref]}, {"photo_asset_id":1}):
        with pytest.raises(ValueError): GateRevokeInput(**(valid | bad))


def test_uncertain_missing_row_does_not_claim_success(case):
    factory, actor, employee_id, refs = prepare(case)
    with factory() as db:
        op = access.revoke_gate_employee(db, actor, employee_id, payload(refs), "missing-read")
        target = db.get(GateTarget, op.targets[0].id)
        person = db.scalar(select(GateSimulatorPerson).where(GateSimulatorPerson.binding_id == target.binding_id))
        db.delete(person)
        persistence.transition_target(db, target, state=GateTargetState.UNCERTAIN, attempts=1,
            error_code=GateErrorCode.LEASE_EXPIRED, lease_token=None, lease_expires_at=None, observed_evidence=None)
        db.commit()
    sim._process(factory, target.id, sim.SimulatorAdapter(factory))
    assert snapshot(factory, target.id)[0::3] == (GateTargetState.UNCERTAIN, 0)


def test_offline_target_remains_present_until_reconnect(case):
    from app.libs.enums.turnstile import GateMode
    factory, actor, employee_id, refs = prepare(case)
    with factory() as db:
        persistence.set_simulator_device(db, device_id=refs[-1]["device_id"], factory_code="MIL", online=False, mode=GateMode.SIMULATOR)
        db.commit()
        op = access.revoke_gate_employee(db, actor, employee_id, payload(refs), "partial")
    result = sim.run_simulator_operation(factory, actor, op.id)
    assert [t.state for t in result.targets] == [GateTargetState.SUCCEEDED, GateTargetState.SUCCEEDED, GateTargetState.WAITING]
    assert snapshot(factory, result.targets[-1].id)[3] == 1
    result = sim.reconnect_simulator_operation(factory, actor, op.id)
    assert all(t.state == GateTargetState.SUCCEEDED for t in result.targets)
    assert snapshot(factory, result.targets[-1].id)[3] == 2


def test_revoke_route_openapi_contract():
    from fastapi import FastAPI
    from app.api.routes.turnstile_access import router
    app = FastAPI(); app.include_router(router)
    schema = app.openapi()
    route = schema["paths"]["/turnstile-access/employees/{employee_id}/revoke"]["post"]
    assert route["responses"]["202"]["content"]["application/json"]["schema"]["$ref"].endswith("/GateOperationOutput")
    assert route["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith("/GateRevokeInput")
