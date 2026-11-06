from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic, sleep
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.schemas import AuditLog, Item, PurchaseOrder, PurchaseOrderLine, StockBatch, StockMovement, Warehouse
from app.models.purchasing_service import receive_purchase_order
from app.tests.test_customer_create_postgres import customer_pg_sessions  # noqa: F401


@pytest.fixture(scope="module")
def receipt_postgres_engine(customer_pg_sessions):
    return customer_pg_sessions.kw["bind"]


@pytest.mark.parametrize("close_first", [False, True])
def test_postgres_receipts_serialize_line_totals_and_closed_order_no_write(receipt_postgres_engine, close_first):
    session_factory = sessionmaker(receipt_postgres_engine, expire_on_commit=False)
    marker = uuid4().hex[:10]
    with session_factory() as db:
        item = Item(sku=f"RECEIPT-RACE-{marker}", name="Receipt race", category="accessory", unit="pcs")
        warehouse = Warehouse(name=f"Receipt race {marker}", type="accessory_storage")
        order = PurchaseOrder(po_no=f"PUR-RACE-{marker}", status="sent")
        db.add_all([item, warehouse, order])
        db.flush()
        line = PurchaseOrderLine(
            purchase_order_id=order.id, item_id=item.id, ordered_quantity=10,
            received_quantity=0, unit="pcs", unit_cost=1, warehouse_id=warehouse.id,
        )
        db.add(line)
        db.commit()
        order_id, line_id, item_id, warehouse_id = order.id, line.id, item.id, warehouse.id

    def payload(batch_suffix: str, *, close_order: bool = False):
        return {
            "close_order": close_order,
            "lines": [{
                "purchase_order_line_id": line_id, "received_quantity": 5,
                "batch_no": f"RECEIPT-RACE-{marker}-{batch_suffix}", "warehouse_id": warehouse_id,
            }],
        }

    with session_factory() as first:
        first_pid = first.execute(text("SELECT pg_backend_pid()")).scalar_one()
        receive_purchase_order(
            first, order_id=order_id, data=payload("A", close_order=close_first),
            current=SimpleNamespace(id=None),
        )
        started = Event()
        second_pid = []

        def second_receipt():
            with session_factory() as second:
                second_pid.append(second.execute(text("SELECT pg_backend_pid()")).scalar_one())
                started.set()
                try:
                    receive_purchase_order(
                        second, order_id=order_id, data=payload("B"), current=SimpleNamespace(id=None),
                    )
                    second.commit()
                    return 200
                except HTTPException as error:
                    second.rollback()
                    return error.status_code

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(second_receipt)
            assert started.wait(5)
            deadline = monotonic() + 5
            blocked = False
            while monotonic() < deadline and not future.done():
                with receipt_postgres_engine.connect() as observer:
                    blockers = observer.execute(
                        text("SELECT pg_blocking_pids(:pid)"), {"pid": second_pid[0]},
                    ).scalar_one()
                if first_pid in blockers:
                    blocked = True
                    break
                sleep(0.02)
            assert blocked, "Concurrent receipt did not wait for the order lock"
            first.commit()
            assert future.result(timeout=10) == (409 if close_first else 200)

    with session_factory() as db:
        line = db.get(PurchaseOrderLine, line_id)
        order = db.get(PurchaseOrder, order_id)
        expected = 5 if close_first else 10
        expected_count = 1 if close_first else 2
        assert float(line.received_quantity) == expected
        assert order.status == "received"
        assert db.query(StockBatch).filter_by(item_id=item_id).count() == expected_count
        assert db.query(StockMovement).filter_by(
            item_id=item_id, reference_type="PurchaseOrderLine", reference_id=line_id,
        ).count() == expected_count
