"""Real PostgreSQL atomicity and unique-number contention for Employee CREATE."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.libs.dto.people.employee_input import EmployeeCreateIn
from app.models import audit_service
from app.models.people import employees_service as service
from app.schemas import AuditLog, Employee, User
from app.tests.pg_approved_instance import (
    ApprovedInstanceUnavailable,
    create_target_database,
    finalize_target,
    load_approved_instance,
    owned_target_name,
    preflight_connection,
    require_or_skip,
    target_engine,
)


@pytest.fixture(scope="module")
def employee_create_postgres_sessions():
    # Verify placement before any database mutation. No default database fallback.
    test_path = Path(__file__).resolve()
    backend = test_path.parents[2]
    if test_path.parent.name != "tests" or test_path.parent.parent.name != "app":
        raise RuntimeError("Place test under backend/app/tests before execution")
    alembic_ini = backend / "alembic.ini"
    if not alembic_ini.is_file():
        raise RuntimeError("Candidate backend/alembic.ini not found")
    try:
        instance = load_approved_instance()
    except ApprovedInstanceUnavailable as error:
        require_or_skip(error)
    target = create_target_database(instance)
    target_name = owned_target_name(target)
    engine = None
    sessions = sessionmaker(autoflush=False, expire_on_commit=False)
    try:
        engine = target_engine(target, options="-c statement_timeout=20000 -c lock_timeout=10000")
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(
                settings,
                "DATABASE_URL",
                engine.url.render_as_string(hide_password=False).replace("%", "%%"),
            )
            patch.setattr(sa, "engine_from_config", lambda *args, **kwargs: engine)
            command.upgrade(Config(str(alembic_ini)), "head")
        sessions.configure(bind=engine)
        yield sessions
    finally:
        try:
            sessions.configure(bind=None)
        finally:
            finalize_target(target, engine)
            # Verify exact-name absence on the same identity-pinned server.
            # Never search or drop by prefix.
            admin = sa.create_engine(instance.admin_url, connect_args={"connect_timeout": 5}, future=True)
            try:
                with admin.connect() as connection:
                    connection.execute(sa.text("SET TRANSACTION READ ONLY"))
                    preflight_connection(connection, instance, "postgres")
                    exists = connection.execute(
                        sa.text("SELECT EXISTS (SELECT 1 FROM pg_database WHERE datname = :name)"),
                        {"name": target_name},
                    ).scalar_one()
                    if exists:
                        raise RuntimeError("owned test database still exists after cleanup")
            finally:
                admin.dispose()


def _seed_actor(sessions, *, factory_code="MIL") -> int:
    with sessions() as db:
        actor = User(
            name="Employee CREATE PG actor",
            email=f"employee-create-pg-{uuid4().hex}@example.invalid",
            password_hash="synthetic",
            factory_code=factory_code,
            extra_permissions=["hr.employees"],
        )
        db.add(actor)
        db.commit()
        return int(actor.id)


def test_pg_employee_and_audit_commit_together_and_read_back(employee_create_postgres_sessions):
    sessions = employee_create_postgres_sessions
    actor_id = _seed_actor(sessions)
    number = f"81{uuid4().int % 10**10:010d}"

    with sessions() as db:
        actor = db.get(User, actor_id)
        actor.session_factory_code = "MIL"
        created = service.create_employee(
            actor, db, EmployeeCreateIn(employee_no=number, full_name="Atomic PG worker")
        )

    with sessions() as db:
        employee = db.query(Employee).filter_by(factory_code="MIL", employee_no=number).one()
        audit = db.query(AuditLog).filter_by(
            entity_type="Employee", entity_id=employee.id, action="create"
        ).one()
        assert created.id == employee.id
        assert employee.full_name == "Atomic PG worker"
        assert employee.status == "active"
        assert audit.user_id == actor_id
        assert audit.new_value_json == {"employee_no": number, "full_name": "Atomic PG worker"}
        assert audit.entry_hash and len(audit.entry_hash) == 64
        assert audit_service.verify_audit_hash_chain(db)["ok"] is True


def test_pg_audit_fk_failure_rolls_back_employee_insert(employee_create_postgres_sessions, monkeypatch):
    sessions = employee_create_postgres_sessions
    actor_id = _seed_actor(sessions)
    number = f"82{uuid4().int % 10**10:010d}"
    with sessions() as db:
        audit_ids_before = {
            row.id for row in db.query(AuditLog).filter_by(entity_type="Employee", action="create")
        }
    attempted_ids = []

    def fail_with_real_audit_fk(db, actor, action, entity_type, entity_id, **kwargs):
        attempted_ids.append(entity_id)
        db.add(AuditLog(
            user_id=2_147_483_647,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            new_value_json=kwargs.get("new_value"),
        ))
        db.flush()

    monkeypatch.setattr(service, "log_action", fail_with_real_audit_fk)
    with sessions() as db:
        actor = db.get(User, actor_id)
        actor.session_factory_code = "MIL"
        with pytest.raises(service.EmployeeCreateConflict):
            service.create_employee(
                actor, db, EmployeeCreateIn(employee_no=number, full_name="Must roll back")
            )

    with sessions() as db:
        assert db.query(Employee).filter_by(factory_code="MIL", employee_no=number).count() == 0
        assert len(attempted_ids) == 1
        assert db.get(Employee, attempted_ids[0]) is None
        assert {
            row.id for row in db.query(AuditLog).filter_by(entity_type="Employee", action="create")
        } == audit_ids_before
        assert db.query(AuditLog).filter_by(
            entity_type="Employee", action="create", entity_id=attempted_ids[0]
        ).count() == 0
        assert audit_service.verify_audit_hash_chain(db)["ok"] is True


def test_pg_same_factory_number_race_has_one_employee_and_one_audit(
    employee_create_postgres_sessions,
    monkeypatch,
):
    sessions = employee_create_postgres_sessions
    actor_id = _seed_actor(sessions)
    number = f"83{uuid4().int % 10**10:010d}"
    rendezvous = Barrier(2, timeout=15)
    original_ensure = service.ensure_employee_no_available

    def ensure_both_prechecks_pass(db, factory_code, employee_no, *, exclude_id=None):
        original_ensure(db, factory_code, employee_no, exclude_id=exclude_id)
        rendezvous.wait()

    monkeypatch.setattr(service, "ensure_employee_no_available", ensure_both_prechecks_pass)

    def create(name):
        with sessions() as db:
            actor = db.get(User, actor_id)
            actor.session_factory_code = "MIL"
            try:
                result = service.create_employee(
                    actor,
                    db,
                    EmployeeCreateIn(employee_no=number, full_name=name),
                )
                return ("created", result.id)
            except service.EmployeeCreateConflict:
                return ("conflict", None)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(create, ("Race worker A", "Race worker B")))

    assert sorted(kind for kind, _ in outcomes) == ["conflict", "created"]
    with sessions() as db:
        employee = db.query(Employee).filter_by(factory_code="MIL", employee_no=number).one()
        assert db.query(Employee).filter_by(factory_code="MIL", employee_no=number).count() == 1
        assert db.query(AuditLog).filter_by(
            entity_type="Employee", entity_id=employee.id, action="create"
        ).count() == 1
        assert audit_service.verify_audit_hash_chain(db)["ok"] is True
