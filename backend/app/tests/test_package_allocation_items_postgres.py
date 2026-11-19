"""Real PostgreSQL exact-source size races and additive migration preservation."""
from concurrent.futures import ThreadPoolExecutor
import importlib.util
from pathlib import Path
from threading import Barrier
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
import pytest
from sqlalchemy import text

from app.api.routes.package_workflows import create_packages_and_run
from app.libs.dto.fulfillment.package_workflows import PrintRunCreatePackagesIn
from app.schemas import Package, PackageBatchAllocation, ProductionOrderItem, Role, SewingRecord, User
from app.tests.packaging_workflow_fixtures import seed_packaging_workflow
from app.tests.test_direct_packaging import body
from app.tests.test_direct_packaging_postgres import pg_actor
from app.tests.test_package_allocation_items import mixed
from app.tests.test_package_write_postgres import package_write_postgres_sessions  # noqa: F401


def seed_matrix(sessions):
    with sessions.begin() as db:
        role = Role(name=uuid4().hex, permissions=["*"])
        actor = User(name="Matrix PG", email=f"{uuid4().hex}@example.invalid", password_hash="unused",
                     role=role, factory_code="MIL")
        db.add(actor); db.flush()
        facts = seed_packaging_workflow(db)["legacy_later"]
        rows = db.query(SewingRecord).filter_by(work_order_id=facts["sewing_work_order_id"]).order_by(SewingRecord.id).all()
        rows[0].size_quantities = [{"size": "M", "quantity": 25}, {"size": "L", "quantity": 55}]
        rows[1].size_quantities = [{"size": "M", "quantity": 45}, {"size": "L", "quantity": 25}]
        db.add(ProductionOrderItem(production_order_id=facts["order_id"], model_id=facts["model_id"],
                                  color="white", size="L", planned_quantity=80))
        return facts, actor.id


@pytest.mark.parametrize("same_key", [False, True])
def test_eight_mixed_writes_conserve_exact_batch_sizes(package_write_postgres_sessions, same_key):
    sessions, _ = package_write_postgres_sessions
    facts, actor = seed_matrix(sessions)
    request = body(facts, [mixed(facts)])
    barrier = Barrier(8)

    def write(index):
        payload = {**request, "request_key": request["request_key"] if same_key else str(uuid4())}
        barrier.wait(15)
        with sessions() as db:
            try:
                return create_packages_and_run(PrintRunCreatePackagesIn.model_validate(payload), db, pg_actor(db, actor))
            except HTTPException as error:
                db.rollback()
                assert error.status_code == 409, error.detail
                return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(write, range(8)))
    saved = [result for result in results if result is not None]
    assert len(saved) == (8 if same_key else 1)
    assert all(result == saved[0] for result in saved)
    with sessions() as db:
        assert db.query(Package).filter_by(production_order_id=facts["order_id"]).count() == 1
        rows = db.query(PackageBatchAllocation).join(Package).filter(Package.production_order_id == facts["order_id"]).all()
        assert len(rows) == 2 and sum(row.quantity for row in rows) == 60
        assert sum(cell["quantity"] for row in rows if row.production_batch_id == facts["batch_ids"][0]
                   for cell in row.item_breakdown if cell["size"] == "M") == 25


def test_additive_migration_keeps_legacy_unknown_and_refuses_destructive_downgrade(package_write_postgres_sessions):
    sessions, engine = package_write_postgres_sessions
    path = Path(__file__).resolve().parents[2] / "alembic/versions/0157_package_allocation_items.py"
    spec = importlib.util.spec_from_file_location("allocation_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.begin() as connection:
        # A transaction-local table shadows only this fixture's table name; no
        # populated race-test rows or shared/public schema are altered.
        connection.execute(text("CREATE TEMP TABLE package_batch_allocations (id integer, quantity integer) ON COMMIT DROP"))
        connection.execute(text("INSERT INTO package_batch_allocations VALUES (1, 7)"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            assert connection.execute(text("SELECT quantity, item_breakdown FROM package_batch_allocations WHERE id=1")).one() == (7, None)
            migration.downgrade()
            migration.upgrade()
            connection.execute(text("UPDATE package_batch_allocations SET item_breakdown=:matrix WHERE id=1"),
                               {"matrix": '[{"model_id":1,"color":"white","size":"M","quantity":7}]'})
            with pytest.raises(RuntimeError, match="discard traceability"):
                migration.downgrade()
