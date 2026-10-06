"""Whole-pack contention and migration rollback on an opt-in disposable DB."""
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from time import monotonic, sleep

import pytest
from alembic import command
from fastapi import HTTPException
from sqlalchemy import inspect, text
from sqlalchemy.orm import sessionmaker

from app.api.routes.warehouse_reservations import ReservePacks, SelectedPacks, reserve_packs, release_packs
from app.models import Customer, FinishedGoodsStock, Package, Role, User, WarehousePackReservation
from app.tests.test_fresh_migration_bootstrap import postgres_migrations  # noqa: F401
from app.tests.test_warehouse_pack_reservations import fixture_pack


def test_concurrent_customer_holds_and_migration_rollback(postgres_migrations):
    engine, config = postgres_migrations.engine, postgres_migrations.config
    command.upgrade(config, "head")
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    pid, customer_id = fixture_pack(session_factory=sessions)
    with sessions() as db:
        role = Role(name="Super Admin", permissions=["*"])
        other = Customer(name="Second reservation customer")
        db.add_all([role, other]); db.flush()
        user = User(name="Reservation QA", email="reservation@example.test", password_hash="unused", role_id=role.id)
        db.add(user); db.commit()
        uid, second_customer_id = user.id, other.id

    ready = Queue()

    def attempt(cid):
        with sessions() as db:
            actor = db.get(User, uid)
            ready.put(db.scalar(text("SELECT pg_backend_pid()")))
            try:
                reserve_packs(ReservePacks(customer_id=cid, package_ids=[pid]), db, actor, None)
                return 200, cid
            except HTTPException as exc:
                db.rollback()
                return exc.status_code, cid

    with sessions() as blocker, ThreadPoolExecutor(max_workers=2) as workers:
        blocker.query(Package).filter_by(id=pid).with_for_update().one()
        futures = [workers.submit(attempt, cid) for cid in (customer_id, second_customer_id)]
        worker_pids = [ready.get(timeout=10), ready.get(timeout=10)]
        try:
            deadline = monotonic() + 10
            while monotonic() < deadline:
                with engine.connect() as connection:
                    waiting = connection.scalar(text(
                        "SELECT count(*) FROM pg_stat_activity WHERE pid = ANY(:pids) AND wait_event_type = 'Lock'"
                    ), {"pids": worker_pids})
                if waiting == 2:
                    break
                sleep(0.02)
            assert waiting == 2, "Both reservations must contend on the locked pack"
        finally:
            blocker.rollback()
        results = [future.result(timeout=15) for future in futures]
    assert sorted(status for status, _ in results) == [200, 409]
    winner = next(cid for status, cid in results if status == 200)
    with sessions() as db:
        hold = db.query(WarehousePackReservation).one()
        assert hold.customer_id == winner and hold.quantity == 12
        stock = db.query(FinishedGoodsStock).filter_by(package_id=pid).all()
        assert sum(row.reserved_qty for row in stock) == 12
        assert sum(row.available_qty for row in stock) == 0

    with pytest.raises(RuntimeError, match="Release active warehouse pack reservations"):
        command.downgrade(config, "0138_ismail_schema_contract")
    assert "warehouse_pack_reservations" in inspect(engine).get_table_names()
    with sessions() as db:
        release_packs(SelectedPacks(package_ids=[pid]), db, db.get(User, uid))
    command.downgrade(config, "0138_ismail_schema_contract")
    assert "warehouse_pack_reservations" not in inspect(engine).get_table_names()
    command.upgrade(config, "head")
    with sessions() as db:
        assert db.query(WarehousePackReservation).count() == 0
        assert sum(row.available_qty for row in db.query(FinishedGoodsStock).filter_by(package_id=pid)) == 12
