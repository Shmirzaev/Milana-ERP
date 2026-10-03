"""ST03: batchless movement aggregation must be scoped by warehouse and transfer direction."""

from uuid import uuid4

import pytest

from app.db.session import SessionLocal
from app.models import Item, StockBatch, StockMovement, Warehouse
from app.services.inventory import current_stock_for_item


def _setup():
    marker = uuid4().hex[:10]
    with SessionLocal() as db:
        item = Item(
            sku=f"ST03-{marker}", name=f"ST03 item {marker}",
            category="material", unit="kg", is_active=True,
        )
        source = Warehouse(name=f"ST03 source {marker}", type="material_storage")
        other = Warehouse(name=f"ST03 other {marker}", type="material_storage")
        db.add_all([item, source, other])
        db.flush()
        db.add(StockBatch(
            item_id=item.id, batch_no=f"ST03-{marker}-1", quantity=10,
            warehouse_id=source.id, unit="kg",
        ))
        db.commit()
        return {
            "item_id": item.id, "source_id": source.id, "other_id": other.id, "marker": marker,
        }


def _batchless(db, fixture, *, movement_type, quantity, from_wh=None, to_wh=None):
    db.add(StockMovement(
        movement_type=movement_type, item_id=fixture["item_id"], batch_id=None,
        from_warehouse_id=from_wh, to_warehouse_id=to_wh,
        quantity=quantity, unit="kg",
    ))


# ------------------------------------------------- warehouse scoping (the leak)

def test_batchless_movement_in_another_warehouse_does_not_leak():
    fixture = _setup()
    with SessionLocal() as db:
        # A return into warehouse "other" must not raise warehouse "source".
        _batchless(db, fixture, movement_type="return", quantity=7, to_wh=fixture["other_id"])
        db.commit()
        assert float(current_stock_for_item(db, fixture["item_id"], fixture["source_id"])) == 10.0
        assert float(current_stock_for_item(db, fixture["item_id"], fixture["other_id"])) == 7.0


def test_batchless_issue_in_another_warehouse_does_not_debit_source():
    fixture = _setup()
    with SessionLocal() as db:
        _batchless(db, fixture, movement_type="issue", quantity=4, from_wh=fixture["other_id"])
        db.commit()
        assert float(current_stock_for_item(db, fixture["item_id"], fixture["source_id"])) == 10.0


def test_global_balance_still_sums_every_warehouse():
    fixture = _setup()
    with SessionLocal() as db:
        _batchless(db, fixture, movement_type="return", quantity=7, to_wh=fixture["other_id"])
        _batchless(db, fixture, movement_type="issue", quantity=3, from_wh=fixture["source_id"])
        db.commit()
        assert float(current_stock_for_item(db, fixture["item_id"])) == 10.0 + 7.0 - 3.0


# ----------------------------------------------- transfer direction + no double count

def test_batchless_transfer_debits_source_and_credits_destination():
    fixture = _setup()
    with SessionLocal() as db:
        _batchless(
            db, fixture, movement_type="transfer", quantity=6,
            from_wh=fixture["source_id"], to_wh=fixture["other_id"],
        )
        db.commit()
        assert float(current_stock_for_item(db, fixture["item_id"], fixture["source_id"])) == 4.0
        assert float(current_stock_for_item(db, fixture["item_id"], fixture["other_id"])) == 6.0


def test_batchless_transfer_does_not_change_the_global_total():
    """A transfer moves stock between warehouses; it must not create or destroy any."""
    fixture = _setup()
    with SessionLocal() as db:
        _batchless(
            db, fixture, movement_type="transfer", quantity=6,
            from_wh=fixture["source_id"], to_wh=fixture["other_id"],
        )
        db.commit()
        assert float(current_stock_for_item(db, fixture["item_id"])) == 10.0


def test_batchless_transfer_to_the_same_warehouse_is_counted_once():
    """Directional counting must not both debit and credit the same warehouse."""
    fixture = _setup()
    with SessionLocal() as db:
        _batchless(
            db, fixture, movement_type="transfer", quantity=2,
            from_wh=fixture["source_id"], to_wh=fixture["source_id"],
        )
        db.commit()
        assert float(current_stock_for_item(db, fixture["item_id"], fixture["source_id"])) == 10.0


# ------------------------------------------------------ batch-linked stays ignored

def test_batch_linked_movement_is_not_counted_twice():
    """Batch quantities are canonical; a batch-linked movement must not add again."""
    fixture = _setup()
    with SessionLocal() as db:
        batch = db.query(StockBatch).filter(StockBatch.item_id == fixture["item_id"]).one()
        db.add(StockMovement(
            movement_type="receive", item_id=fixture["item_id"], batch_id=batch.id,
            to_warehouse_id=fixture["source_id"], quantity=10, unit="kg",
        ))
        db.commit()
        assert float(current_stock_for_item(db, fixture["item_id"], fixture["source_id"])) == 10.0


def test_legacy_unlocated_movement_still_counts_in_the_global_balance():
    """A movement with no warehouse must not be lost from the global figure."""
    fixture = _setup()
    with SessionLocal() as db:
        _batchless(db, fixture, movement_type="produce", quantity=5)
        db.commit()
        assert float(current_stock_for_item(db, fixture["item_id"])) == 15.0
        # It is not attributable to any single warehouse.
        assert float(current_stock_for_item(db, fixture["item_id"], fixture["source_id"])) == 10.0
        assert float(current_stock_for_item(db, fixture["item_id"], fixture["other_id"])) == 0.0


@pytest.mark.parametrize("movement_type", ["issue", "consume", "waste", "shipment"])
def test_outgoing_types_still_debit_their_own_warehouse(movement_type):
    fixture = _setup()
    with SessionLocal() as db:
        _batchless(db, fixture, movement_type=movement_type, quantity=2, from_wh=fixture["source_id"])
        db.commit()
        assert float(current_stock_for_item(db, fixture["item_id"], fixture["source_id"])) == 8.0


@pytest.mark.parametrize("movement_type", ["produce", "return", "adjustment"])
def test_incoming_types_still_credit_their_own_warehouse(movement_type):
    fixture = _setup()
    with SessionLocal() as db:
        _batchless(db, fixture, movement_type=movement_type, quantity=3, to_wh=fixture["source_id"])
        db.commit()
        assert float(current_stock_for_item(db, fixture["item_id"], fixture["source_id"])) == 13.0
