"""Real PostgreSQL serialization against item-only material reservations."""

from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.api.routes import eco_transfers
from app.db.base import Base
from app.models import EcoFabricDispatch, EcoFabricRoll, MaterialReservation, StockBatch, StockMovement, User
from app.services import inventory
from app.tests.test_material_reservation_concurrency import _line, _stock, reservation_postgres_engine  # noqa: F401


def test_postgres_dispatch_waits_for_item_only_reservation(reservation_postgres_engine):
    engine = reservation_postgres_engine
    Base.metadata.create_all(engine, tables=[EcoFabricDispatch.__table__, EcoFabricRoll.__table__])
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    ids = _stock(sessions)
    with sessions() as db:
        batch = db.get(StockBatch, ids["batches"][0])
        batch.piece_count = 2
        batch.roll_weights_kg = [6, 4]
        user = User(name="Eco race tester", email=f"eco-race-{uuid4().hex}@example.test", password_hash="test")
        db.add(user)
        db.commit()
        user_id = user.id

    reserved = Event()
    release = Event()
    pids = Queue()

    def reserve():
        with sessions() as db:
            pids.put(("reserve", db.execute(text("SELECT pg_backend_pid()")).scalar_one()))
            inventory.create_material_reservations(
                db, production_order_id=ids["orders"][1], lines=[_line(ids, 5)], user_id=None,
            )
            reserved.set()
            assert release.wait(10), "Coordinator did not release reservation transaction"
            db.commit()

    def dispatch():
        with sessions() as db:
            pids.put(("dispatch", db.execute(text("SELECT pg_backend_pid()")).scalar_one()))
            try:
                eco_transfers.send(
                    eco_transfers.SendIn(request_key=uuid4(), codes=[f"B{ids['batches'][0]}-R1"]),
                    db, db.get(User, user_id),
                )
                return 200
            except HTTPException as error:
                db.rollback()
                return error.status_code

    with sessions() as observer, ThreadPoolExecutor(max_workers=2) as workers:
        first = workers.submit(reserve)
        try:
            kind, reservation_pid = pids.get(timeout=10)
            assert kind == "reserve"
            assert reserved.wait(10), "Reservation did not reach its item availability lock"
            second = workers.submit(dispatch)
            kind, dispatch_pid = pids.get(timeout=10)
            assert kind == "dispatch"
            deadline = monotonic() + 10
            while monotonic() < deadline:
                blocking = observer.execute(text("SELECT pg_blocking_pids(:pid)"), {"pid": dispatch_pid}).scalar_one()
                if reservation_pid in blocking:
                    break
                if second.done():
                    pytest.fail(f"Dispatch ended before reservation committed: {second.result()}")
                sleep(0.02)
            else:
                pytest.fail("Dispatch did not wait for the item-only reservation lock")
        finally:
            release.set()
        first.result(timeout=10)
        assert second.result(timeout=10) == 409

    with sessions() as db:
        assert float(db.get(StockBatch, ids["batches"][0]).quantity) == 10
        assert db.query(EcoFabricDispatch).count() == 0
        assert db.query(EcoFabricRoll).count() == 0
        assert db.query(StockMovement).filter_by(reference_type="EcoFabricDispatch").count() == 0
        assert db.query(MaterialReservation).filter_by(production_order_id=ids["orders"][1]).count() == 1
