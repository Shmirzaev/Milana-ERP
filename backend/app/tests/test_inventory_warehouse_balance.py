import pytest

from app.db import session as session_module
from app.models import Item, StockBatch, StockMovement, Warehouse
from app.services.inventory import current_stock_for_item


@pytest.fixture
def warehouse_stock():
    with session_module.SessionLocal() as db:
        item = Item(sku="WAREHOUSE-BALANCE", name="Warehouse balance", category="accessory", unit="pcs")
        other = Item(sku="WAREHOUSE-OTHER", name="Other item", category="accessory", unit="pcs")
        warehouses = [Warehouse(name=f"Balance W{number}", type="accessory_storage") for number in range(1, 4)]
        db.add_all([item, other, *warehouses])
        db.flush()
        batches = [StockBatch(
            item_id=item.id, batch_no=f"WAREHOUSE-{warehouse.id}", quantity=10,
            unit="pcs", warehouse_id=warehouse.id, qc_status="passed",
        ) for warehouse in warehouses[:2]]
        db.add_all(batches)
        db.flush()
        ids = {
            "item_id": item.id, "other_item_id": other.id,
            "warehouses": [warehouse.id for warehouse in warehouses],
            "batches": [batch.id for batch in batches],
        }
        db.commit()
    return ids


def add_movement(stock, movement_type, **overrides):
    values = {
        "item_id": stock["item_id"], "movement_type": movement_type, "quantity": 4, "unit": "pcs",
        "from_warehouse_id": stock["warehouses"][0], "to_warehouse_id": stock["warehouses"][1],
        **overrides,
    }
    with session_module.SessionLocal() as db:
        db.add(StockMovement(**values))
        db.commit()


def balances(stock):
    with session_module.SessionLocal() as db:
        located = [current_stock_for_item(db, stock["item_id"], warehouse_id) for warehouse_id in stock["warehouses"]]
        total = current_stock_for_item(db, stock["item_id"])
        return located, total


@pytest.mark.parametrize("movement_type", ["issue", "consume", "waste", "shipment"])
def test_batchless_outgoing_only_reduces_source_warehouse(warehouse_stock, movement_type):
    add_movement(warehouse_stock, movement_type)
    located, total = balances(warehouse_stock)
    assert located == [6, 10, 0]
    assert total == sum(located) == 16


@pytest.mark.parametrize("movement_type", ["produce", "return", "adjustment"])
def test_batchless_incoming_only_increases_destination_warehouse(warehouse_stock, movement_type):
    add_movement(warehouse_stock, movement_type)
    located, total = balances(warehouse_stock)
    assert located == [10, 14, 0]
    assert total == sum(located) == 24


def test_batchless_transfer_moves_stock_between_warehouses_without_changing_total(warehouse_stock):
    add_movement(warehouse_stock, "transfer")
    located, total = balances(warehouse_stock)
    assert located == [6, 14, 0]
    assert total == sum(located) == 20


def test_same_warehouse_transfer_has_no_stock_effect(warehouse_stock):
    add_movement(warehouse_stock, "transfer", to_warehouse_id=warehouse_stock["warehouses"][0])
    located, total = balances(warehouse_stock)
    assert located == [10, 10, 0]
    assert total == sum(located) == 20


@pytest.mark.parametrize("movement_type", ["receive", "issue", "consume", "waste", "shipment", "produce", "return", "adjustment", "transfer"])
def test_batch_bound_movements_are_not_counted_again(warehouse_stock, movement_type):
    # Batch quantities are current balances, already including their ledger entries.
    add_movement(warehouse_stock, movement_type, batch_id=warehouse_stock["batches"][0])
    located, total = balances(warehouse_stock)
    assert located == [10, 10, 0]
    assert total == sum(located) == 20


@pytest.mark.parametrize(("movement_type", "expected_total"), [("issue", 16), ("adjustment", 24)])
def test_unlocated_legacy_movement_remains_global_without_leaking_into_warehouses(warehouse_stock, movement_type, expected_total):
    add_movement(warehouse_stock, movement_type, from_warehouse_id=None, to_warehouse_id=None)
    located, total = balances(warehouse_stock)
    assert located == [10, 10, 0]
    assert total == expected_total


def test_other_items_movements_do_not_change_balances(warehouse_stock):
    add_movement(warehouse_stock, "issue", item_id=warehouse_stock["other_item_id"])
    located, total = balances(warehouse_stock)
    assert located == [10, 10, 0]
    assert total == sum(located) == 20


def test_mixed_warehouse_movements_reconcile_to_global_balance(warehouse_stock):
    first, second, third = warehouse_stock["warehouses"]
    add_movement(warehouse_stock, "issue", from_warehouse_id=first, to_warehouse_id=None, quantity=2)
    add_movement(warehouse_stock, "adjustment", from_warehouse_id=None, to_warehouse_id=second, quantity=3)
    add_movement(warehouse_stock, "transfer", from_warehouse_id=second, to_warehouse_id=third, quantity=5)
    add_movement(warehouse_stock, "return", from_warehouse_id=first, to_warehouse_id=third, quantity=1)
    located, total = balances(warehouse_stock)
    assert located == [8, 8, 6]
    assert total == sum(located) == 22
