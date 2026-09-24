from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.models import (
    Item,
    MaterialReservation,
    Model,
    ModelBOM,
    ProductionOrder,
    StockBatch,
    StockMovement,
    Warehouse,
)
from app.services.inventory import (
    consume_cutting_materials,
    consume_material_reservation,
    consume_material_reservations_for_stock_batch,
)
from app.services.workflow import consume_item_from_batches, consume_packaging_materials_from_bom, consume_stock_batch
from app.tests.conftest import TestSessionLocal


def _stock_case(db, *, name: str, unit: str = "pcs", quantity: float = 10):
    marker = uuid4().hex[:10]
    item = Item(sku=f"{name}-{marker}", name=f"{name} item", category="packaging", unit=unit)
    warehouse = Warehouse(name=f"{name} warehouse {marker}", type="accessory_storage")
    model = Model(code=f"{name}-MODEL-{marker}", name=f"{name} model")
    db.add_all([item, warehouse, model])
    db.flush()
    batch = StockBatch(
        item_id=item.id,
        batch_no=f"{name}-BATCH-{marker}",
        warehouse_id=warehouse.id,
        quantity=quantity,
        unit=unit,
        qc_status="passed",
    )
    db.add(batch)
    db.flush()
    order = ProductionOrder(
        production_no=f"{name}-PO-{marker}",
        production_type="branded_stock",
        model_id=model.id,
        planned_quantity=10,
    )
    db.add(order)
    db.flush()
    return item, warehouse, batch, model, order


def test_reserved_stock_consumption_accepts_matching_item_and_batch_unit():
    with TestSessionLocal() as db:
        item, warehouse, batch, _model, order = _stock_case(db, name="RES-UNIT")
        reservation = MaterialReservation(
            reservation_no=f"RES-{uuid4().hex[:10]}",
            production_order_id=order.id,
            item_id=item.id,
            stock_batch_id=batch.id,
            warehouse_id=warehouse.id,
            reserved_quantity=3,
            consumed_quantity=0,
            released_quantity=0,
            unit="pcs",
            status="reserved",
            reservation_type="packaging",
            source="manual",
        )
        db.add(reservation)
        db.flush()

        consumed = consume_material_reservations_for_stock_batch(
            db,
            production_order_id=order.id,
            stock_batch_id=batch.id,
            quantity=2,
            reference_type="CuttingRecord",
            reference_id=1,
            user_id=None,
        )
        db.flush()

        movement = db.query(StockMovement).filter_by(batch_id=batch.id).one()
        assert consumed == 2
        assert float(batch.quantity) == 8
        assert float(reservation.consumed_quantity) == 2
        assert movement.unit == item.unit == batch.unit


def test_reserved_stock_consumption_rejects_bad_legacy_reservation_without_writes():
    with TestSessionLocal() as db:
        item, warehouse, batch, _model, order = _stock_case(db, name="RES-BAD")
        reservation = MaterialReservation(
            reservation_no=f"RES-{uuid4().hex[:10]}",
            production_order_id=order.id,
            item_id=item.id,
            stock_batch_id=batch.id,
            warehouse_id=warehouse.id,
            reserved_quantity=3,
            consumed_quantity=0,
            released_quantity=0,
            unit="kg",
            status="reserved",
            reservation_type="packaging",
            source="manual",
        )
        db.add(reservation)
        db.flush()

        with pytest.raises(HTTPException, match="unit") as error:
            consume_material_reservations_for_stock_batch(
                db,
                production_order_id=order.id,
                stock_batch_id=batch.id,
                quantity=2,
                reference_type="CuttingRecord",
                reference_id=1,
                user_id=None,
            )

        assert error.value.status_code == 409
        assert float(batch.quantity) == 10
        assert float(reservation.consumed_quantity) == 0
        assert db.query(StockMovement).filter_by(batch_id=batch.id).count() == 0


def test_item_only_reservation_rejects_mismatched_unit_without_writes():
    with TestSessionLocal() as db:
        item, warehouse, batch, _model, order = _stock_case(db, name="RES-ITEM-BAD")
        reservation = MaterialReservation(
            reservation_no=f"RES-{uuid4().hex[:10]}",
            production_order_id=order.id,
            item_id=item.id,
            stock_batch_id=None,
            warehouse_id=warehouse.id,
            reserved_quantity=3,
            consumed_quantity=0,
            released_quantity=0,
            unit="kg",
            status="reserved",
            reservation_type="packaging",
            source="manual",
        )
        db.add(reservation)
        db.flush()

        with pytest.raises(HTTPException, match="unit") as error:
            consume_material_reservation(
                db,
                reservation.id,
                quantity=2,
                user_id=None,
            )

        assert error.value.status_code == 409
        assert float(batch.quantity) == 10
        assert float(reservation.consumed_quantity) == 0
        assert db.query(StockMovement).filter_by(item_id=item.id).count() == 0

        reservation.unit = item.unit
        consumed = consume_material_reservation(
            db,
            reservation.id,
            quantity=2,
            user_id=None,
        )
        movement = db.query(StockMovement).filter_by(item_id=item.id).one()
        assert float(batch.quantity) == 8
        assert float(consumed.consumed_quantity) == 2
        assert movement.unit == item.unit


def test_cutting_stock_consumption_accepts_matching_units_and_rejects_before_writes():
    with TestSessionLocal() as db:
        item, _warehouse, batch, _model, order = _stock_case(db, name="CUT-UNIT")
        consume_cutting_materials(
            db,
            production_order_id=order.id,
            lines=[{"stock_batch_id": batch.id, "quantity": 2, "unit": item.unit}],
            reference_type="CuttingRecord",
            reference_id=1,
            user_id=None,
        )
        db.flush()
        movement = db.query(StockMovement).filter_by(batch_id=batch.id).one()
        assert float(batch.quantity) == 8
        assert movement.unit == item.unit

    with TestSessionLocal() as db:
        item, _warehouse, batch, _model, order = _stock_case(db, name="CUT-BAD")
        with pytest.raises(HTTPException, match="unit") as error:
            consume_cutting_materials(
                db,
                production_order_id=order.id,
                lines=[{"stock_batch_id": batch.id, "quantity": 2, "unit": "kg"}],
                reference_type="CuttingRecord",
                reference_id=1,
                user_id=None,
            )
        assert error.value.status_code == 409
        assert float(batch.quantity) == 10
        assert db.query(StockMovement).filter_by(batch_id=batch.id).count() == 0


def test_item_consumption_prevalidates_all_batches_before_mutating_any():
    with TestSessionLocal() as db:
        item, warehouse, first, _model, _order = _stock_case(db, name="FIFO-UNIT", quantity=1)
        second = StockBatch(
            item_id=item.id,
            batch_no=f"FIFO-BAD-{uuid4().hex[:8]}",
            warehouse_id=warehouse.id,
            quantity=5,
            unit="kg",
            qc_status="passed",
        )
        db.add(second)
        db.flush()

        with pytest.raises(HTTPException, match="unit"):
            consume_item_from_batches(
                db,
                item_id=item.id,
                quantity=2,
                unit=item.unit,
                reference_type="ProductionOrder",
                reference_id=1,
                user_id=None,
                require_available=True,
            )

        assert float(first.quantity) == 1
        assert float(second.quantity) == 5
        assert db.query(StockMovement).filter(StockMovement.batch_id.in_([first.id, second.id])).count() == 0


def test_batchless_item_consumption_uses_catalog_unit_and_rejects_mismatch_without_writes():
    with TestSessionLocal() as db:
        item, _warehouse, _batch, _model, _order = _stock_case(db, name="BATCHLESS-UNIT")
        _batch.quantity = 0
        db.flush()

        with pytest.raises(HTTPException, match="unit") as error:
            consume_item_from_batches(
                db,
                item_id=item.id,
                quantity=2,
                unit="kg",
                reference_type="ProductionOrder",
                reference_id=1,
                user_id=None,
            )
        assert error.value.status_code == 409
        assert db.query(StockMovement).filter_by(item_id=item.id).count() == 0

        consumed = consume_item_from_batches(
            db,
            item_id=item.id,
            quantity=2,
            unit="",
            reference_type="ProductionOrder",
            reference_id=1,
            user_id=None,
        )
        db.flush()
        movement = db.query(StockMovement).filter_by(item_id=item.id).one()
        assert consumed == 2
        assert movement.batch_id is None
        assert movement.unit == item.unit


def test_packaging_consumption_accepts_matching_units():
    with TestSessionLocal() as db:
        item, _warehouse, batch, model, order = _stock_case(db, name="PKG-UNIT")
        db.add(ModelBOM(model_id=model.id, item_id=item.id, quantity_per_piece=2, unit=item.unit))
        db.flush()

        consume_packaging_materials_from_bom(
            db,
            production_order_id=order.id,
            packed_qty=2,
            reference_type="PackagingRecord",
            reference_id=1,
            user_id=None,
        )
        db.flush()

        movement = db.query(StockMovement).filter_by(batch_id=batch.id).one()
        assert float(batch.quantity) == 6
        assert float(movement.quantity) == 4
        assert movement.unit == item.unit


def test_packaging_unit_mismatch_rolls_back_prior_consumption():
    with TestSessionLocal() as db:
        first_item, warehouse, first_batch, model, order = _stock_case(db, name="PKG-ROLLBACK-A")
        second_item = Item(
            sku=f"PKG-ROLLBACK-B-{uuid4().hex[:8]}",
            name="Mismatched packaging item",
            category="packaging",
            unit="pcs",
        )
        db.add(second_item)
        db.flush()
        second_batch = StockBatch(
            item_id=second_item.id,
            batch_no=f"PKG-ROLLBACK-BATCH-{uuid4().hex[:8]}",
            warehouse_id=warehouse.id,
            quantity=10,
            unit="pcs",
            qc_status="passed",
        )
        db.add(second_batch)
        db.add_all([
            ModelBOM(model_id=model.id, item_id=first_item.id, quantity_per_piece=1, unit=first_item.unit),
            ModelBOM(model_id=model.id, item_id=second_item.id, quantity_per_piece=1, unit="kg"),
        ])
        db.commit()
        first_batch_id, second_batch_id = first_batch.id, second_batch.id

        with pytest.raises(HTTPException, match="unit"):
            consume_packaging_materials_from_bom(
                db,
                production_order_id=order.id,
                packed_qty=2,
                reference_type="PackagingRecord",
                reference_id=1,
                user_id=None,
            )
        assert float(first_batch.quantity) == 8
        db.flush()
        assert db.query(StockMovement).filter_by(batch_id=first_batch_id).count() == 1
        db.rollback()

        assert db.get(StockBatch, first_batch_id).quantity == 10
        assert db.get(StockBatch, second_batch_id).quantity == 10
        assert db.query(StockMovement).filter(
            StockMovement.batch_id.in_([first_batch_id, second_batch_id]),
        ).count() == 0


def test_direct_batch_consumption_rejects_mismatched_item_or_batch_unit_without_writes():
    with TestSessionLocal() as db:
        item, _warehouse, batch, _model, _order = _stock_case(db, name="BATCH-UNIT")
        with pytest.raises(HTTPException, match="unit") as error:
            consume_stock_batch(
                db,
                batch_id=batch.id,
                quantity=2,
                unit="kg",
                reference_type="CuttingRecord",
                reference_id=1,
                user_id=None,
            )
        assert error.value.status_code == 409
        assert float(batch.quantity) == 10
        assert db.query(StockMovement).filter_by(batch_id=batch.id).count() == 0

        batch.unit = "kg"
        db.flush()
        with pytest.raises(HTTPException, match="unit"):
            consume_stock_batch(
                db,
                batch_id=batch.id,
                quantity=2,
                unit=item.unit,
                reference_type="CuttingRecord",
                reference_id=1,
                user_id=None,
            )
        assert float(batch.quantity) == 10
        assert db.query(StockMovement).filter_by(batch_id=batch.id).count() == 0
