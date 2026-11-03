from datetime import timedelta
import socket

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.schemas import Employee, User
from app.schemas.people.attendance import AttendanceDevice, AttendancePerson, AttendanceEvent
from app.schemas.people.turnstile import GateEmployeeDevice, GateTarget, GateSimulatorPerson
from app.schemas.people import turnstile_persistence as persistence
from app.libs.enums.turnstile import GateAction, GateMode, GateBindingState, GateTargetState, GateErrorCode
from app.models.people import turnstile_simulator_service as sim


@pytest.fixture
def case(monkeypatch):
    monkeypatch.setattr(sim.settings, "TURNSTILE_PROVISIONING_MODE", GateMode.SIMULATOR)
    monkeypatch.setattr(sim.settings, "TURNSTILE_SIMULATOR_LEASE_SECONDS", 60)
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: pytest.fail("network access"))
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory() as db:
        actor = User(name="Tester", email="tester@example.invalid", password_hash="none", factory_code="MIL", extra_permissions=["attendance.provision", "hr.employees"])
        employee = Employee(full_name="Synthetic Person", employee_no="S001", factory_code="MIL")
        db.add_all([actor, employee]); db.flush()
        photo = persistence.insert_photo_asset(db, employee_id=employee.id, factory_code="MIL", created_by=actor.id,
            stored_name="synthetic", sha256="a" * 64, width=10, height=10, content_type="image/jpeg")
        op = persistence.insert_operation(db, employee_id=employee.id, factory_code="MIL", requested_by=actor.id,
            action=GateAction.ENROLL, mode=GateMode.SIMULATOR, revision=1, full_name=employee.full_name,
            photo_asset_id=photo.id, external_person_id=employee.employee_no, snapshot_hash="b" * 64)
        targets = []
        for i in range(4):
            device = AttendanceDevice(factory_code="MIL", device_key=f"test-{i}", name=f"Terminal {i}", read_only=True)
            db.add(device); db.flush()
            binding = persistence.insert_binding(db, employee_id=employee.id, factory_code="MIL", device_id=device.id,
                external_person_id=employee.employee_no, state=GateBindingState.PENDING, desired_revision=1)
            persistence.set_simulator_device(db, device_id=device.id, factory_code="MIL", online=i != 3, mode=GateMode.SIMULATOR)
            target = persistence.insert_target(db, operation_id=op.id, binding_id=binding.id, device_id=device.id, device_name=device.name,
                factory_code="MIL", employee_id=employee.id, revision=1)
            targets.append(target.id)
        db.commit()
        yield factory, actor, op.id, targets
    engine.dispose()


def snapshot(factory, target_id):
    with factory() as db:
        target = db.get(GateTarget, target_id)
        person = db.scalar(select(GateSimulatorPerson).where(GateSimulatorPerson.binding_id == target.binding_id))
        return target.state, target.attempts, target.error_code, person.write_count if person else 0


def test_partial_reconnect_preserves_success_and_attendance(case):
    factory, actor, op, ids = case
    result = sim.run_simulator_operation(factory, actor, op)
    assert [x.state for x in result.targets] == [GateTargetState.SUCCEEDED] * 3 + [GateTargetState.WAITING]
    assert [snapshot(factory, i)[3] for i in ids] == [1, 1, 1, 0]
    sim.run_simulator_operation(factory, actor, op)
    result = sim.reconnect_simulator_operation(factory, actor, op)
    assert all(x.state == GateTargetState.SUCCEEDED for x in result.targets)
    assert [snapshot(factory, i)[3] for i in ids] == [1, 1, 1, 1]
    with factory() as db:
        assert db.query(AttendancePerson).count() == 0
        assert db.query(AttendanceEvent).count() == 0
        assert db.get(Employee, 1).full_name == "Synthetic Person"
        assert all(db.get(GateEmployeeDevice, db.get(GateTarget, i).binding_id).state == GateBindingState.ACTIVE for i in ids)


def test_accepted_then_timeout_reconciles_without_second_write(case):
    factory, actor, op, ids = case
    class LostReply(sim.SimulatorAdapter):
        def accept(self, target_id, token):
            super().accept(target_id, token)
            raise TimeoutError("reply lost")
    sim._process(factory, ids[0], LostReply(factory))
    assert snapshot(factory, ids[0])[0::3] == (GateTargetState.UNCERTAIN, 1)
    sim._process(factory, ids[0], sim.SimulatorAdapter(factory))
    assert snapshot(factory, ids[0])[0::3] == (GateTargetState.SUCCEEDED, 1)


def test_expired_lease_and_stale_callback_cannot_write_or_regress(case):
    factory, actor, op, ids = case
    token, _ = sim._claim(factory, ids[0])
    with factory() as db:
        target = db.get(GateTarget, ids[0])
        persistence.transition_target(db, target, state=GateTargetState.PROCESSING, attempts=target.attempts,
            error_code=None, lease_token=token, lease_expires_at=sim._now() - timedelta(seconds=1), observed_evidence=None)
        db.commit()
    assert sim._claim(factory, ids[0]) is None
    assert snapshot(factory, ids[0])[0] == GateTargetState.UNCERTAIN
    assert not sim._finish(factory, ids[0], token, GateTargetState.SUCCEEDED)
    with pytest.raises(RuntimeError):
        sim.SimulatorAdapter(factory).accept(ids[0], token)
    sim._process(factory, ids[0], sim.SimulatorAdapter(factory))
    assert snapshot(factory, ids[0])[0] == GateTargetState.SUCCEEDED


def test_stale_revision_and_existing_conflict_never_overwrite(case):
    factory, actor, op, ids = case
    with factory() as db:
        first = db.get(GateTarget, ids[0]); binding = db.get(GateEmployeeDevice, first.binding_id)
        persistence.update_binding_state_revision(db, binding, state=GateBindingState.PENDING, desired_revision=2)
        second = db.get(GateTarget, ids[1]); binding2 = db.get(GateEmployeeDevice, second.binding_id)
        persistence.upsert_simulator_person(db, binding=binding2, accepted_payload_hash="c" * 64,
            accepted_revision=2, external_person_id="other", full_name="Other", photo_sha256="d" * 64)
        db.commit()
    sim._process(factory, ids[0], sim.SimulatorAdapter(factory))
    sim._process(factory, ids[1], sim.SimulatorAdapter(factory))
    assert snapshot(factory, ids[0])[0] == GateTargetState.SUPERSEDED
    assert snapshot(factory, ids[1])[0::3] == (GateTargetState.CONFLICT, 1)


def test_attempt_limit_stops_automatic_retry(case, monkeypatch):
    factory, actor, op, ids = case
    monkeypatch.setattr(sim.settings, "TURNSTILE_SIMULATOR_MAX_ATTEMPTS", 2)
    for _ in range(4):
        sim._process(factory, ids[3], sim.SimulatorAdapter(factory))
    state, attempts, error, writes = snapshot(factory, ids[3])
    assert (state, attempts, error, writes) == (GateTargetState.WAITING, 2, GateErrorCode.DEVICE_OFFLINE, 0)


def test_auth_factory_and_disabled_fail_closed(case, monkeypatch):
    factory, actor, op, ids = case
    actor.extra_permissions = ["attendance.provision"]
    with pytest.raises(HTTPException) as error:
        sim.run_simulator_operation(factory, actor, op)
    assert error.value.status_code == 403
    actor.extra_permissions = ["attendance.provision", "hr.employees"]
    actor.session_factory_code = "ECO"
    with pytest.raises(HTTPException) as error:
        sim.run_simulator_operation(factory, actor, op)
    assert error.value.status_code in (403, 404)
    actor.session_factory_code = "MIL"
    monkeypatch.setattr(sim.settings, "TURNSTILE_PROVISIONING_MODE", GateMode.DISABLED)
    with pytest.raises(HTTPException):
        sim.run_simulator_operation(factory, actor, op)
    assert all(snapshot(factory, i)[0] == GateTargetState.QUEUED for i in ids)


def test_production_and_public_deployment_fail_closed(case, monkeypatch):
    factory, actor, op, ids = case
    monkeypatch.setattr(sim.settings, "ENV", "production")
    with pytest.raises(HTTPException):
        sim.run_simulator_operation(factory, actor, op)
    monkeypatch.setattr(sim.settings, "ENV", "development")
    monkeypatch.setenv("PUBLIC_DEPLOYMENT", "1")
    with pytest.raises(HTTPException):
        sim.run_simulator_operation(factory, actor, op)
    assert all(snapshot(factory, i)[0] == GateTargetState.QUEUED for i in ids)


def test_routes_declare_and_return_operation_schema(case, monkeypatch):
    from fastapi import FastAPI
    from app.api.routes import turnstile_simulator as route
    from app.libs.dto.people.turnstile_output import GateOperationOutput
    factory, actor, op, ids = case
    monkeypatch.setattr(route, "SessionLocal", factory)
    result = route.simulate(op, actor)
    assert isinstance(result, GateOperationOutput)
    assert result.id == op
    app = FastAPI()
    app.include_router(route.router)
    paths = app.openapi()["paths"]
    for suffix in ("simulate", "simulator-reconnect"):
        schema = paths[f"/turnstile-access/operations/{{operation_id}}/{suffix}"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]
        assert schema["$ref"].endswith("/GateOperationOutput")


def test_explicit_reconnect_recovers_exhausted_waiting_only(case, monkeypatch):
    factory, actor, op, ids = case
    monkeypatch.setattr(sim.settings, "TURNSTILE_SIMULATOR_MAX_ATTEMPTS", 2)
    for _ in range(2):
        sim._process(factory, ids[3], sim.SimulatorAdapter(factory))
    assert snapshot(factory, ids[3]) == (GateTargetState.WAITING, 2, GateErrorCode.DEVICE_OFFLINE, 0)
    with factory() as db:
        target = db.get(GateTarget, ids[0])
        persistence.transition_target(db, target, state=GateTargetState.UNCERTAIN, attempts=2,
            error_code=GateErrorCode.SIMULATOR_ERROR, lease_token=None, lease_expires_at=None, observed_evidence=None)
        db.commit()
    sim.reconnect_simulator_operation(factory, actor, op)
    assert snapshot(factory, ids[3]) == (GateTargetState.SUCCEEDED, 1, None, 1)
    assert snapshot(factory, ids[0]) == (GateTargetState.UNCERTAIN, 2, GateErrorCode.SIMULATOR_ERROR, 0)
    sim.reconnect_simulator_operation(factory, actor, op)
    assert snapshot(factory, ids[3])[3] == 1
    assert snapshot(factory, ids[0])[1] == 2
