"""Real PostgreSQL locks/constraints on an explicitly approved disposable target."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from threading import Barrier
from uuid import uuid4
import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from app.core.config import settings
from app.libs.dto.people.turnstile_live import LiveDeviceInput, LiveRequestInput, LiveResultInput
from app.libs.enums.turnstile import GateMode, LiveGateAction, LiveGateState
from app.models.people import turnstile_live_service as service
from app.schemas import AttendanceDevice, AttendanceEvent, Employee, Model, PriceCalculationRequest, User
from app.schemas.people.turnstile_live import GateLiveJob
from app.tests.test_customer_create_postgres import customer_pg_sessions as customer_pg_sessions


def test_live_migration_roundtrip_preserves_prior_schema(customer_pg_sessions):
    engine = customer_pg_sessions.kw["bind"]
    ini = str(Path(__file__).resolve().parents[2] / "alembic.ini")
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(settings, "DATABASE_URL", engine.url.render_as_string(hide_password=False).replace("%", "%%"))
        patch.setattr(sa, "engine_from_config", lambda *args, **kwargs: engine)
        # Undo only the additive gate branch. Deployed pricing is forward-only;
        # it and its saved business rows must survive a gate storage roundtrip.
        def remove_gate_storage():
            command.downgrade(Config(ini), "0156_variant_price_workflow")
            with engine.connect() as connection:
                assert set(connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalars()) == {
                    "0156_variant_price_workflow", "0156_gate_live_integration"}
            command.downgrade(Config(ini), "0156_gate_live_integration@-1")
            with engine.connect() as connection:
                assert connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalars().all() == ["0156_variant_price_workflow"]
        remove_gate_storage()
        assert "gate_live_jobs" not in sa.inspect(engine).get_table_names()
        assert "mode" not in {c["name"] for c in sa.inspect(engine).get_columns("gate_employee_devices")}
        assert "workflow_state" in {c["name"] for c in sa.inspect(engine).get_columns("price_calculation_requests")}
        with customer_pg_sessions.begin() as db:
            actor = User(name="Migration preservation", email=uuid4().hex+"@example.invalid", password_hash="unused")
            model = Model(code=uuid4().hex, name="Migration preservation", status="approved")
            employee = Employee(full_name="Migration preservation", employee_no="PG-MERGE", factory_code="MIL", status="active")
            db.add_all([actor, model, employee]); db.flush()
            db.add(PriceCalculationRequest(model_id=model.id, active_model_id=model.id,
                created_by_id=actor.id, workflow_state="approved", factory_code="MIL",
                revision=7, selling_price=12.34, materials_json=[{"key":"preserve","rate":2.5}],
                approval_snapshot_json={"preserve":"approved pricing"}))
        def facts():
            with engine.connect() as connection:
                return {name: (
                    connection.execute(sa.text("SELECT to_regclass(:name)::oid"), {"name":name}).scalar_one(),
                    connection.execute(sa.text(f"SELECT row_to_json(t)::text FROM {name} t ORDER BY 1")).scalars().all(),
                ) for name in ("users", "models", "employees", "price_calculation_requests")}
        before = facts()
        command.upgrade(Config(ini), "head")
        assert facts() == before
        remove_gate_storage()
        assert facts() == before
        command.upgrade(Config(ini), "head")
        assert facts() == before
    assert "gate_live_jobs" in sa.inspect(engine).get_table_names()


@pytest.fixture
def pg_live(customer_pg_sessions, monkeypatch):
    sessions = customer_pg_sessions
    monkeypatch.setattr(settings, "TURNSTILE_PROVISIONING_MODE", GateMode.HIKVISION)
    number = "PG-" + uuid4().hex[:16]
    with sessions.begin() as db:
        actor = User(name="Synthetic live PG", email=uuid4().hex+"@example.invalid", password_hash="unused",
            factory_code="MIL", extra_permissions=["*"], is_active=True)
        employee = Employee(factory_code="MIL", employee_no=number, full_name="Synthetic live PG", status="active")
        device = AttendanceDevice(factory_code="MIL", device_key=uuid4().hex, name="Synthetic live PG",
            source_host="127.0.0.1", certificate_sha256="c"*64, sync_enabled=True, read_only=True)
        db.add_all([actor, employee, device]); db.flush()
        actor_id, employee_id, device_id = actor.id, employee.id, device.id
        db.add(AttendanceEvent(factory_code="MIL", device_id=device.id, event_uid=uuid4().hex,
            occurred_at=datetime.now(timezone.utc), received_at=datetime.now(timezone.utc)))
    with sessions() as db:
        token = service.configure_device(db, db.get(User, actor_id), device_id, LiveDeviceInput(
            enabled=True, allowed_employee_numbers=[number], face_library_id="1"))["worker_token"]
    return sessions, actor_id, employee_id, device_id, number, token


def request(pg_live, key):
    sessions, actor, employee, device, number, _ = pg_live
    with sessions() as db:
        return service.submit(db, db.get(User, actor), employee,
            LiveRequestInput(expected_employee_no=number, device_id=device, action=LiveGateAction.OBSERVE), key)


def test_pg_parallel_same_request_and_claim_have_single_owner(pg_live):
    sessions, actor, employee, device, number, token = pg_live
    barrier = Barrier(4)
    def submit(_): barrier.wait(); return request(pg_live, "same-receipt").id
    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(submit, range(4)))
    assert len(set(ids)) == 1
    barrier = Barrier(4)
    def claim(_):
        barrier.wait()
        with sessions() as db:
            return service.claim(db, service.worker_identity(db, token))
    with ThreadPoolExecutor(max_workers=4) as pool:
        claims = list(pool.map(claim, range(4)))
    claimed = [c for c in claims if c is not None]
    assert len(claimed) == 1 and claimed[0].job_id == ids[0]
    with sessions() as db:
        assert db.get(GateLiveJob, ids[0]).attempt_count == 1
        assert db.query(AttendanceEvent).filter_by(device_id=device).count() == 1


def test_pg_bounded_workers_and_expired_claim_never_repeat(pg_live):
    sessions, actor, employee, device, number, token = pg_live
    ids = [request(pg_live, "stress-"+str(i)).id for i in range(24)]
    def process(_):
        receipts = []
        for _ in range(24):
            with sessions() as db:
                claim = service.claim(db, service.worker_identity(db, token))
            if claim:
                with sessions() as db:
                    service.record_result(db, service.worker_identity(db, token), claim.job_id, LiveResultInput(
                        lease_token=claim.lease_token, outcome="refused", worker_quiescent=True))
                receipts.append(claim.job_id)
        return receipts
    with ThreadPoolExecutor(max_workers=4) as pool:
        seen = [job for jobs in pool.map(process, range(4)) for job in jobs]
    assert sorted(seen) == sorted(ids)
    with sessions() as db:
        rows = db.query(GateLiveJob).filter(GateLiveJob.id.in_(ids)).all()
        assert all(j.state is LiveGateState.FAILED and j.attempt_count == 1 and not j.dispatched for j in rows)
        assert db.query(AttendanceEvent).filter_by(device_id=device).count() == 1
        assert db.get(Employee, employee).employee_no == number


def test_pg_audit_failure_rolls_back_intent_and_same_key_retries(pg_live, monkeypatch):
    sessions, _, _, device, _, _ = pg_live
    def fail(*args, **kwargs): raise RuntimeError("synthetic audit failure")
    with monkeypatch.context() as patch:
        patch.setattr(service, "log_action", fail)
        with pytest.raises(RuntimeError, match="synthetic"): request(pg_live, "audit-retry")
    with sessions() as db:
        assert db.query(GateLiveJob).filter_by(device_id=device).count() == 0
    assert request(pg_live, "audit-retry").state is LiveGateState.QUEUED


@pytest.mark.parametrize("field,value", [("factory_code", "ECO"), ("state", "made_up"), ("attempt_count", 4), ("dispatch_count", -1)])
def test_pg_constraints_reject_cross_factory_and_invalid_vocabulary(pg_live, field, value):
    sessions, _, _, _, _, _ = pg_live
    result = request(pg_live, "constraint")
    with sessions() as db:
        with pytest.raises((sa.exc.IntegrityError, sa.exc.StatementError)):
            db.execute(sa.text("UPDATE gate_live_jobs SET " + field + "=:value WHERE id=:id"), {"value":value,"id":result.id})
            db.commit()
        db.rollback()
    with sessions() as db:
        assert db.get(GateLiveJob, result.id).state is LiveGateState.QUEUED
