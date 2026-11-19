"""Real PostgreSQL atomic receipt retries, lock ordering and bounded stress."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from time import monotonic

import pytest
from fastapi import HTTPException

from app.libs.dto.inventory.eco_inventory_input import EcoMaterialBulkReceiveIn
from app.models.inventory import eco_inventory_service as eco
from app.schemas import Item, StockBatch
from app.schemas.inventory.eco_inventory import EcoMaterialBatch, EcoMaterialMovement
from app.tests.test_eco_inventory_postgres import pg_case, actor  # noqa: F401


def receipt(item_id, key="table-race", lots=("LOT-A", "LOT-B")):
    return EcoMaterialBulkReceiveIn(request_key=key, lines=[
        {"kind": "fabric", "item_id": item_id, "batch_no": lot, "quantity": "0.1", "unit": "kg"}
        for lot in lots])


@pytest.mark.parametrize("changed_retry", [False, True])
def test_concurrent_bulk_replay_has_exactly_one_complete_effect(pg_case, changed_retry):
    sessions, (user_id, central_id) = pg_case
    with sessions() as db:
        item_id = db.get(StockBatch, central_id).item_id
    barrier = Barrier(2)

    def receive(index):
        with sessions() as db:
            user = actor(db, user_id, "ECO")
            payload = receipt(item_id)
            if changed_retry and index:
                payload.lines[1].quantity = Decimal("0.2")
            barrier.wait(timeout=10)
            try:
                return [row.batch.id for row in eco.receive_stock_bulk(db, payload, user)]
            except HTTPException as exc:
                db.rollback()
                assert changed_retry and exc.status_code == 409
                return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(receive, range(2)))
    if changed_retry:
        assert sum(result is not None for result in results) == 1
    else:
        assert results[0] == results[1]
    with sessions() as db:
        assert db.query(EcoMaterialBatch).count() == db.query(EcoMaterialMovement).count() == 2
        assert db.get(StockBatch, central_id).quantity == Decimal("100")


def test_bulk_reverse_row_order_does_not_deadlock_or_mix_receipts(pg_case):
    sessions, (user_id, central_id) = pg_case
    with sessions() as db:
        first_id = db.get(StockBatch, central_id).item_id
        second = Item(name="Second bulk fabric", sku="PG-SECOND-BULK", category="fabric", unit="kg")
        db.add(second); db.commit(); second_id = second.id
    barrier = Barrier(2)

    def receive(index):
        with sessions() as db:
            user = actor(db, user_id, "ECO")
            item_ids = [first_id, second_id] if index == 0 else [second_id, first_id]
            payload = EcoMaterialBulkReceiveIn(request_key=f"different-{index}", lines=[
                {"kind": "fabric", "item_id": material, "batch_no": f"{index}-{material}", "quantity": "2", "unit": "kg"}
                for material in item_ids])
            barrier.wait(timeout=10)
            return [row.batch.id for row in eco.receive_stock_bulk(db, payload, user)]

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(receive, range(2)))
    assert len({batch_id for group in results for batch_id in group}) == 4
    with sessions() as db:
        assert db.query(EcoMaterialBatch).count() == db.query(EcoMaterialMovement).count() == 4
        assert sum(row.quantity for row in db.query(EcoMaterialBatch)) == Decimal("8")


def test_invalid_tail_rolls_back_postgres_then_same_key_recovers(pg_case):
    sessions, (user_id, central_id) = pg_case
    with sessions() as db:
        item_id = db.get(StockBatch, central_id).item_id
        user = actor(db, user_id, "ECO")
        invalid = receipt(item_id)
        invalid.lines[1].item_id = 999999999
        with pytest.raises(HTTPException) as exc:
            eco.receive_stock_bulk(db, invalid, user)
        assert exc.value.status_code == 400
        db.rollback()
    with sessions() as db:
        assert db.query(EcoMaterialBatch).count() == db.query(EcoMaterialMovement).count() == 0
        assert len(eco.receive_stock_bulk(db, receipt(item_id), actor(db, user_id, "ECO"))) == 2


def test_bounded_hundred_row_receipt_and_lost_response_replay(pg_case):
    sessions, (user_id, central_id) = pg_case
    with sessions() as db:
        item_id = db.get(StockBatch, central_id).item_id
        payload = receipt(item_id, lots=[f"STRESS-{i}" for i in range(100)])
        started = monotonic()
        first = eco.receive_stock_bulk(db, payload, actor(db, user_id, "ECO"))
        assert monotonic() - started < 20
    with sessions() as db:
        replay = eco.receive_stock_bulk(db, payload, actor(db, user_id, "ECO"))
        assert [row.batch.id for row in first] == [row.batch.id for row in replay]
        assert db.query(EcoMaterialBatch).count() == db.query(EcoMaterialMovement).count() == 100
        assert sum(row.quantity for row in db.query(EcoMaterialBatch)) == Decimal("10")
        assert db.get(StockBatch, central_id).quantity == Decimal("100")
