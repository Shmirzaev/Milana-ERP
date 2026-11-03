"""Real PostgreSQL checks on an identity-pinned disposable target only."""
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.libs.dto.production.production import ProductionOrderIn
from app.models.planning import production_planning_service as service
from app.schemas import AuditLog, BrandedPlanningOrder, Department, Model, ProductionBatch, ProductionOrder, ProductionOrderItem, User, WorkOrder
from app.tests.pg_approved_instance import (
    ApprovedInstanceUnavailable, create_target_database, finalize_target, load_approved_instance,
    owned_target_name, preflight_connection, require_or_skip, target_engine,
)


@pytest.fixture(scope="module")
def sessions():
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
    factory = sessionmaker(autoflush=False, expire_on_commit=False)
    try:
        engine = target_engine(target, options="-c statement_timeout=20000 -c lock_timeout=10000")
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(settings, "DATABASE_URL", engine.url.render_as_string(hide_password=False).replace("%", "%%"))
            patch.setattr(sa, "engine_from_config", lambda *args, **kwargs: engine)
            command.upgrade(Config(str(alembic_ini)), "head")
        factory.configure(bind=engine)
        yield factory
    finally:
        factory.configure(bind=None)
        finalize_target(target, engine)
        admin = sa.create_engine(instance.admin_url, connect_args={"connect_timeout": 5}, future=True)
        try:
            with admin.connect() as connection:
                connection.execute(sa.text("SET TRANSACTION READ ONLY"))
                preflight_connection(connection, instance, "postgres")
                exists = connection.execute(sa.text("SELECT EXISTS (SELECT 1 FROM pg_database WHERE datname = :name)"),
                                            {"name": target_name}).scalar_one()
                if exists:
                    raise RuntimeError("owned test database still exists after cleanup")
        finally:
            admin.dispose()


@pytest.fixture
def seed(sessions):
    marker = uuid4().hex
    with sessions() as db:
        for code in ("CUT", "MIL", "PKG", "FGS"):
            if not db.query(Department).filter_by(code=code).first():
                db.add(Department(code=code, name=f"Synthetic {code}"))
        actor = User(name="Synthetic planning actor", email=f"planning-{marker}@example.test", password_hash="unused")
        model = Model(code=f"PLANNING-{marker}", name="Synthetic planning model", status="approved")
        db.add_all([actor, model]); db.commit()
        return actor.id, model.id


def payload(model_id, **kwargs):
    return ProductionOrderIn(production_type="branded_stock", model_id=model_id, planned_quantity=20,
                             items=[{"model_id": model_id, "color": "white", "size": "M", "planned_quantity": 20}],
                             batches=[{"planned_quantity": 20}], **kwargs)


def counts(db):
    return tuple(db.query(cls).count() for cls in (BrandedPlanningOrder, ProductionOrder, ProductionOrderItem, ProductionBatch, WorkOrder, AuditLog))


def test_pg_alternate_create_and_existing_order_handoff(sessions, seed):
    actor_id, model_id = seed
    with sessions() as db:
        po = service.create_branded_stock_production(db, payload(model_id), db.get(User, actor_id))
        po_id, order_id = po.id, po.planning_order_id
    with sessions() as db:
        po, order = db.get(ProductionOrder, po_id), db.get(BrandedPlanningOrder, order_id)
        assert (order.ordered_for_type, order.ordered_for_name, order.status, order.customer_id, order.notes) == (
            "milana", "Milana", "open", None, None)
        assert po.planning_order_id == order.id
        assert len(po.items) == 1 and po.items[0].model_id == model_id and po.items[0].planned_quantity == 20
        assert len(po.batches) == 1 and po.batches[0].production_order_id == po_id
        assert any(wo.operation == "cutting" and wo.production_order_id == po_id for wo in po.work_orders)
        assert db.query(AuditLog).filter_by(entity_type="ProductionOrder", entity_id=po_id, action="create").count() == 1
        assert db.query(AuditLog).filter_by(entity_type="BrandedPlanningOrder", entity_id=order_id, action="create").count() == 0
        existing = BrandedPlanningOrder(order_no=f"EXISTING-{uuid4().hex}", ordered_for_type="eco_cotton",
                                       ordered_for_name="Eco Cotton", status="open", notes="preserve")
        db.add(existing); db.commit(); existing_id = existing.id
    with sessions() as db:
        before = db.query(BrandedPlanningOrder).count()
        po = service.create_branded_stock_production(db, payload(model_id, planning_order_id=existing_id), db.get(User, actor_id))
        second_id = po.id
        assert db.query(BrandedPlanningOrder).count() == before
    with sessions() as db:
        existing = db.get(BrandedPlanningOrder, existing_id)
        assert (existing.ordered_for_type, existing.ordered_for_name, existing.status, existing.notes) == (
            "eco_cotton", "Eco Cotton", "open", "preserve")
        assert db.get(ProductionOrder, second_id).planning_order_id == existing_id


@pytest.mark.parametrize("case,code", [("closed", 400), ("missing", 404)])
def test_pg_alternate_missing_and_closed_orders_refused(sessions, seed, case, code):
    actor_id, model_id = seed
    with sessions() as db:
        row = BrandedPlanningOrder(order_no=f"CLOSED-{uuid4().hex}", ordered_for_type="milana",
                                   ordered_for_name="Milana", status="closed")
        db.add(row); db.commit(); closed_id = row.id
        before = counts(db)
    order_id = closed_id if case == "closed" else 2147483647
    with sessions() as db:
        with pytest.raises(HTTPException) as failure:
            service.create_branded_stock_production(db, payload(model_id, planning_order_id=order_id), db.get(User, actor_id))
        assert failure.value.status_code == code
        db.rollback()
    with sessions() as db:
        assert counts(db) == before


@pytest.mark.parametrize("hook", ["insert_branded_planning_order", "log_action"])
def test_pg_alternate_postflush_and_audit_failure_rollback_retry(sessions, seed, monkeypatch, hook):
    actor_id, model_id = seed
    with sessions() as db:
        before = counts(db)
    original = getattr(service, hook)

    def fail_after_write(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("injected after participant write")

    with monkeypatch.context() as patch:
        patch.setattr(service, hook, fail_after_write)
        with sessions() as db:
            with pytest.raises(RuntimeError, match="injected after participant write"):
                service.create_branded_stock_production(db, payload(model_id), db.get(User, actor_id))
            db.rollback()
    with sessions() as db:
        assert counts(db) == before
    with sessions() as db:
        po = service.create_branded_stock_production(db, payload(model_id), db.get(User, actor_id))
        po_id = po.id
    with sessions() as db:
        after = counts(db)
        assert after[0] == before[0] + 1 and after[1] == before[1] + 1
        assert after[2] == before[2] + 1 and after[3] == before[3] + 1
        assert after[4] > before[4] and after[5] > before[5]
        assert db.get(ProductionOrder, po_id).planning_order_id is not None
