"""Real row-lock/migration gates. SQLite cannot substitute for these checks."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import os
from threading import Barrier
from uuid import uuid4
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
from sqlalchemy import create_engine, func
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from app.db.base import Base
from app.libs.dto.inventory.eco_inventory_input import FactoryFabricDispatchIn, FactoryFabricReceiptIn
from app.models.factory_scope_service import bind_session_factory
from app.models.idempotency_service import bind_idempotency_identity
from app.models.inventory import factory_fabric_transfers_service as transfers
from app.schemas import Item, Role, StockBatch, User, Warehouse
from app.schemas.inventory.eco_inventory import EcoMaterialBatch, EcoMaterialMovement, FactoryFabricTransferLine
from app.tests.test_eco_schema_migrations import NEW_TABLES, migration


@pytest.fixture
def pg_case():
    raw = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw:
        pytest.skip("Real PostgreSQL ECO migration/concurrency gate needs STABILIZATION_POSTGRES_URL")
    url = make_url(raw)
    if (url.get_backend_name() != "postgresql" or url.host not in {"localhost", "127.0.0.1", "::1"}
            or url.query or not (url.database or "").endswith(("_ci", "_qa"))):
        pytest.fail("ECO concurrency gates require an explicitly disposable loopback *_ci or *_qa database")
    schema = f"eco_feature_{uuid4().hex}"
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema} -clock_timeout=10000 -cstatement_timeout=20000"}, pool_size=4, max_overflow=0)
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        Base.metadata.create_all(engine, tables=[t for t in Base.metadata.sorted_tables if t.name not in NEW_TABLES])
        with engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                migration("0150_eco_inventory_transfers.py").upgrade()
                migration("0151_eco_accessory_approval.py").upgrade()
        sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        with sessions() as db:
            role = Role(name="Super Admin", permissions=["*"])
            warehouse = Warehouse(name="Milana test store", type="fabric_storage")
            item = Item(sku="PG-ECO-FABRIC", name="PG fabric", category="fabric", unit="kg")
            db.add_all([role, warehouse, item]); db.flush()
            user = User(email="pg-eco@example.invalid", name="PG review actor", password_hash="unused-test-hash", role_id=role.id, factory_code="MIL")
            db.add(user); db.flush()
            batch = StockBatch(item_id=item.id, batch_no="PG-ECO-B1", quantity=100, unit="kg", cost_per_unit=0, warehouse_id=warehouse.id, qc_status="passed")
            db.add(batch); db.commit()
            ids = user.id, batch.id
        yield sessions, ids
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()


def actor(db, user_id, factory):
    user = db.get(User, user_id)
    bind_session_factory(user, factory)
    bind_idempotency_identity(db, user)
    return user


def test_competing_dispatch_cannot_overdraw_source(pg_case):
    sessions, (user_id, batch_id) = pg_case
    barrier = Barrier(2)
    def dispatch(index):
        with sessions() as db:
            user = actor(db, user_id, "MIL")
            barrier.wait(timeout=10)
            try:
                result = transfers.dispatch(db, FactoryFabricDispatchIn(request_key=f"competing-{index}",
                    lines=[{"source_batch_id": batch_id, "quantity": "70"}]), user)
                return result.id
            except HTTPException as error:
                db.rollback()
                assert error.status_code == 409
                return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(dispatch, range(2)))
    assert sum(result is not None for result in results) == 1
    with sessions() as db:
        assert db.get(StockBatch, batch_id).quantity == Decimal("30")


@pytest.mark.parametrize("same_key", [False, True])
def test_concurrent_receipts_conserve_in_transit_stock(pg_case, same_key):
    sessions, (user_id, batch_id) = pg_case
    with sessions() as db:
        dispatch = transfers.dispatch(db, FactoryFabricDispatchIn(request_key="send",
            lines=[{"source_batch_id": batch_id, "quantity": "30"}]), actor(db, user_id, "MIL"))
        transfer_id, line_id = dispatch.id, dispatch.lines[0].id
    barrier = Barrier(2)
    def receive(index):
        with sessions() as db:
            user = actor(db, user_id, "ECO")
            barrier.wait(timeout=10)
            try:
                return transfers.receive(db, transfer_id, FactoryFabricReceiptIn(request_key="same" if same_key else f"receipt-{index}",
                    lines=[{"line_id": line_id, "quantity": "20"}]), user).id
            except HTTPException as error:
                db.rollback()
                assert error.status_code == 409
                return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(receive, range(2)))
    assert sum(result is not None for result in results) == (2 if same_key else 1)
    with sessions() as db:
        assert db.query(func.sum(EcoMaterialBatch.quantity)).scalar() == Decimal("20")
        assert db.get(FactoryFabricTransferLine, line_id).received_quantity == Decimal("20")
        assert db.query(EcoMaterialMovement).count() == 1
        assert db.get(StockBatch, batch_id).quantity == Decimal("70")
