from uuid import uuid4
from datetime import datetime, timezone

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


@pytest.mark.parametrize("packaging", [False, True])
def test_batch_id_lock_order_keeps_oldest_batch_first_for_consumption(packaging):
    with TestSessionLocal() as db:
        item, warehouse, later, model, order = _stock_case(db, name="FIFO-LOCK", quantity=2)
        later.received_date = datetime(2026, 2, 1, tzinfo=timezone.utc)
        earlier = StockBatch(
            item_id=item.id,
            batch_no=f"FIFO-EARLIER-{uuid4().hex[:8]}",
            warehouse_id=warehouse.id,
            quantity=2,
            unit=item.unit,
            qc_status="passed",
            received_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        db.add(earlier)
        db.flush()
        assert later.id < earlier.id

        if packaging:
            db.add(ModelBOM(model_id=model.id, item_id=item.id, quantity_per_piece=1, unit=item.unit))
            db.flush()
            consume_packaging_materials_from_bom(
                db, production_order_id=order.id, packed_qty=1,
                reference_type="PackagingRecord", reference_id=1, user_id=None,
            )
        else:
            consume_item_from_batches(
                db, item_id=item.id, quantity=1, unit=item.unit,
                reference_type="ProductionOrder", reference_id=order.id,
                user_id=None, require_available=True,
            )
        db.flush()

        movement = db.query(StockMovement).filter_by(item_id=item.id).one()
        assert movement.batch_id == earlier.id
        assert float(earlier.quantity) == 1
        assert float(later.quantity) == 2


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


@pytest.mark.parametrize("same_order", [False, True])
def test_packaging_consumes_own_batch_reservation_and_preserves_other_orders(same_order):
    with TestSessionLocal() as db:
        item, warehouse, first, model, order = _stock_case(db, name="PKG-RESERVE", quantity=5)
        second = StockBatch(
            item_id=item.id, batch_no=f"PKG-FREE-{uuid4().hex[:8]}",
            warehouse_id=warehouse.id, quantity=5, unit=item.unit, qc_status="passed",
        )
        db.add(second)
        if same_order:
            reserved_order = order
        else:
            reserved_order = ProductionOrder(
                production_no=f"PKG-OTHER-{uuid4().hex[:8]}",
                production_type="branded_stock", model_id=model.id, planned_quantity=10,
            )
            db.add(reserved_order)
        db.flush()
        reservation = MaterialReservation(
            reservation_no=f"PKG-RES-{uuid4().hex[:8]}",
            production_order_id=reserved_order.id,
            item_id=item.id, stock_batch_id=first.id, warehouse_id=warehouse.id,
            reserved_quantity=5, consumed_quantity=0, released_quantity=0,
            unit=item.unit, status="reserved", reservation_type="packaging", source="manual",
        )
        db.add_all([
            reservation,
            ModelBOM(model_id=model.id, item_id=item.id,
                     quantity_per_piece=7 if same_order else 5, unit=item.unit),
        ])
        db.flush()

        consume_packaging_materials_from_bom(
            db, production_order_id=order.id, packed_qty=1,
            reference_type="PackagingRecord", reference_id=73, user_id=None,
        )
        db.flush()

        movements = db.query(StockMovement).filter_by(
            item_id=item.id, reference_type="PackagingRecord", reference_id=73,
        ).order_by(StockMovement.id).all()
        if same_order:
            assert [(row.batch_id, float(row.quantity)) for row in movements] == [
                (first.id, 5), (second.id, 2),
            ]
            assert float(first.quantity) == 0
            assert float(second.quantity) == 3
            assert float(reservation.consumed_quantity) == 5
            assert reservation.status == "consumed"
        else:
            assert [(row.batch_id, float(row.quantity)) for row in movements] == [(second.id, 5)]
            assert float(first.quantity) == 5
            assert float(second.quantity) == 0
            assert float(reservation.consumed_quantity) == 0
            assert reservation.status == "reserved"
        assert sum(float(row.quantity) for row in movements) == (7 if same_order else 5)


def test_packaging_consumes_own_item_only_reservation_once():
    with TestSessionLocal() as db:
        item, warehouse, batch, model, order = _stock_case(db, name="PKG-OWN-ITEM", quantity=5)
        reservation = MaterialReservation(
            reservation_no=f"PKG-OWN-ITEM-{uuid4().hex[:8]}",
            production_order_id=order.id, item_id=item.id,
            stock_batch_id=None, warehouse_id=warehouse.id,
            reserved_quantity=5, consumed_quantity=0, released_quantity=0,
            unit=item.unit, status="reserved", reservation_type="packaging", source="manual",
        )
        db.add_all([
            reservation,
            ModelBOM(model_id=model.id, item_id=item.id, quantity_per_piece=5, unit=item.unit),
        ])
        db.flush()

        consume_packaging_materials_from_bom(
            db, production_order_id=order.id, packed_qty=1,
            reference_type="PackagingRecord", reference_id=80, user_id=None,
        )
        db.flush()

        movement = db.query(StockMovement).filter_by(reference_type="PackagingRecord", reference_id=80).one()
        assert movement.batch_id == batch.id
        assert float(movement.quantity) == 5
        assert float(batch.quantity) == 0
        assert float(reservation.consumed_quantity) == 5
        assert reservation.status == "consumed"


def test_packaging_does_not_forgive_unconsumed_own_item_only_claim():
    with TestSessionLocal() as db:
        item, _warehouse, batch, model, order = _stock_case(db, name="PKG-OWN-LEGACY", quantity=1)
        reservation = MaterialReservation(
            reservation_no=f"PKG-OWN-LEGACY-{uuid4().hex[:8]}",
            production_order_id=order.id, item_id=item.id,
            stock_batch_id=None, warehouse_id=None,
            reserved_quantity=10, consumed_quantity=0, released_quantity=0,
            unit=item.unit, status="reserved", reservation_type="packaging", source="manual",
        )
        db.add_all([
            reservation,
            ModelBOM(model_id=model.id, item_id=item.id, quantity_per_piece=1, unit=item.unit),
        ])
        db.flush()

        with pytest.raises(HTTPException) as rejected:
            consume_packaging_materials_from_bom(
                db, production_order_id=order.id, packed_qty=1,
                reference_type="PackagingRecord", reference_id=82, user_id=None,
            )
        db.flush()

        assert rejected.value.status_code == 409
        assert float(batch.quantity) == 1
        assert float(reservation.consumed_quantity) == 0
        assert db.query(StockMovement).filter_by(reference_type="PackagingRecord", reference_id=82).count() == 0


def test_packaging_item_only_reservation_uses_its_warehouse_and_preserves_other_order():
    with TestSessionLocal() as db:
        item, reserved_warehouse, other_batch, model, order = _stock_case(
            db, name="PKG-OWN-SCOPED", quantity=5,
        )
        own_warehouse = Warehouse(name=f"PKG-OWN-WH-{uuid4().hex[:8]}", type="accessory_storage")
        db.add(own_warehouse)
        db.flush()
        own_batch = StockBatch(
            item_id=item.id, batch_no=f"PKG-OWN-BATCH-{uuid4().hex[:8]}",
            warehouse_id=own_warehouse.id, quantity=5, unit=item.unit, qc_status="passed",
        )
        other_order = ProductionOrder(
            production_no=f"PKG-OWN-OTHER-{uuid4().hex[:8]}",
            production_type="branded_stock", model_id=model.id, planned_quantity=10,
        )
        db.add_all([own_batch, other_order])
        db.flush()
        other_reservation = MaterialReservation(
            reservation_no=f"PKG-OTHER-ITEM-{uuid4().hex[:8]}",
            production_order_id=other_order.id, item_id=item.id,
            stock_batch_id=None, warehouse_id=reserved_warehouse.id,
            reserved_quantity=5, consumed_quantity=0, released_quantity=0,
            unit=item.unit, status="reserved", reservation_type="packaging", source="manual",
        )
        own_reservation = MaterialReservation(
            reservation_no=f"PKG-OWN-SCOPED-{uuid4().hex[:8]}",
            production_order_id=order.id, item_id=item.id,
            stock_batch_id=None, warehouse_id=own_warehouse.id,
            reserved_quantity=5, consumed_quantity=0, released_quantity=0,
            unit=item.unit, status="reserved", reservation_type="packaging", source="manual",
        )
        db.add_all([
            other_reservation, own_reservation,
            ModelBOM(model_id=model.id, item_id=item.id, quantity_per_piece=5, unit=item.unit),
        ])
        db.flush()

        consume_packaging_materials_from_bom(
            db, production_order_id=order.id, packed_qty=1,
            reference_type="PackagingRecord", reference_id=81, user_id=None,
        )
        db.flush()

        movement = db.query(StockMovement).filter_by(reference_type="PackagingRecord", reference_id=81).one()
        assert movement.batch_id == own_batch.id
        assert float(own_batch.quantity) == 0
        assert float(other_batch.quantity) == 5
        assert float(own_reservation.consumed_quantity) == 5
        assert own_reservation.status == "consumed"
        assert float(other_reservation.consumed_quantity) == 0
        assert other_reservation.status == "reserved"


def test_packaging_reserved_batch_shortage_rejects_without_writes():
    with TestSessionLocal() as db:
        item, warehouse, batch, model, order = _stock_case(db, name="PKG-RES-SHORT", quantity=5)
        other_order = ProductionOrder(
            production_no=f"PKG-SHORT-OTHER-{uuid4().hex[:8]}",
            production_type="branded_stock", model_id=model.id, planned_quantity=10,
        )
        db.add(other_order)
        db.flush()
        reservation = MaterialReservation(
            reservation_no=f"PKG-SHORT-RES-{uuid4().hex[:8]}",
            production_order_id=other_order.id,
            item_id=item.id, stock_batch_id=batch.id, warehouse_id=warehouse.id,
            reserved_quantity=5, consumed_quantity=0, released_quantity=0,
            unit=item.unit, status="reserved", reservation_type="packaging", source="manual",
        )
        db.add_all([
            reservation,
            ModelBOM(model_id=model.id, item_id=item.id, quantity_per_piece=2, unit=item.unit),
        ])
        db.flush()

        with pytest.raises(HTTPException) as rejected:
            consume_packaging_materials_from_bom(
                db, production_order_id=order.id, packed_qty=1,
                reference_type="PackagingRecord", reference_id=74, user_id=None,
            )
        db.flush()

        assert rejected.value.status_code == 409
        assert db.query(StockMovement).filter_by(item_id=item.id, reference_id=74).count() == 0
        assert float(batch.quantity) == 5
        assert float(reservation.consumed_quantity) == 0
        assert reservation.status == "reserved"


def test_packaging_uses_free_batch_despite_existing_batchless_debt():
    with TestSessionLocal() as db:
        item, warehouse, reserved_batch, model, order = _stock_case(
            db, name="PKG-RES-DEBT", quantity=5,
        )
        free_batch = StockBatch(
            item_id=item.id, batch_no=f"PKG-DEBT-FREE-{uuid4().hex[:8]}",
            warehouse_id=warehouse.id, quantity=5, unit=item.unit, qc_status="passed",
        )
        other_order = ProductionOrder(
            production_no=f"PKG-DEBT-OTHER-{uuid4().hex[:8]}",
            production_type="branded_stock", model_id=model.id, planned_quantity=10,
        )
        db.add_all([free_batch, other_order])
        db.flush()
        db.add_all([
            MaterialReservation(
                reservation_no=f"PKG-DEBT-RES-{uuid4().hex[:8]}",
                production_order_id=other_order.id, item_id=item.id,
                stock_batch_id=reserved_batch.id, warehouse_id=warehouse.id,
                reserved_quantity=5, consumed_quantity=0, released_quantity=0,
                unit=item.unit, status="reserved", reservation_type="packaging", source="manual",
            ),
            StockMovement(
                movement_type="consume", item_id=item.id, batch_id=None,
                from_warehouse_id=warehouse.id, quantity=3, unit=item.unit,
                reference_type="LegacyDebt", reference_id=1,
            ),
            ModelBOM(model_id=model.id, item_id=item.id, quantity_per_piece=5, unit=item.unit),
        ])
        db.flush()

        consume_packaging_materials_from_bom(
            db, production_order_id=order.id, packed_qty=1,
            reference_type="PackagingRecord", reference_id=76, user_id=None,
        )
        db.flush()

        movement = db.query(StockMovement).filter_by(reference_type="PackagingRecord", reference_id=76).one()
        assert movement.batch_id == free_batch.id
        assert float(movement.quantity) == 5
        assert float(reserved_batch.quantity) == 5
        assert float(free_batch.quantity) == 0


@pytest.mark.parametrize("batch_quantity,should_reject", [(5, True), (7, False)])
def test_packaging_preserves_other_orders_item_only_reservation(batch_quantity, should_reject):
    with TestSessionLocal() as db:
        item, warehouse, batch, model, order = _stock_case(
            db, name="PKG-ITEM-RES", quantity=batch_quantity,
        )
        other_order = ProductionOrder(
            production_no=f"PKG-ITEM-OTHER-{uuid4().hex[:8]}",
            production_type="branded_stock", model_id=model.id, planned_quantity=10,
        )
        db.add(other_order)
        db.flush()
        reservation = MaterialReservation(
            reservation_no=f"PKG-ITEM-RES-{uuid4().hex[:8]}",
            production_order_id=other_order.id,
            item_id=item.id, stock_batch_id=None, warehouse_id=warehouse.id,
            reserved_quantity=5, consumed_quantity=0, released_quantity=0,
            unit=item.unit, status="reserved", reservation_type="packaging", source="manual",
        )
        db.add_all([
            reservation,
            ModelBOM(model_id=model.id, item_id=item.id, quantity_per_piece=2, unit=item.unit),
        ])
        db.flush()

        if should_reject:
            with pytest.raises(HTTPException) as rejected:
                consume_packaging_materials_from_bom(
                    db, production_order_id=order.id, packed_qty=1,
                    reference_type="PackagingRecord", reference_id=75, user_id=None,
                )
            assert rejected.value.status_code == 409
        else:
            consume_packaging_materials_from_bom(
                db, production_order_id=order.id, packed_qty=1,
                reference_type="PackagingRecord", reference_id=75, user_id=None,
            )
        db.flush()

        movements = db.query(StockMovement).filter_by(item_id=item.id, reference_id=75).all()
        assert len(movements) == (0 if should_reject else 1)
        assert float(batch.quantity) == 5
        if movements:
            assert movements[0].batch_id == batch.id
            assert float(movements[0].quantity) == 2
        assert float(reservation.consumed_quantity) == 0
        assert reservation.status == "reserved"


def test_packaging_item_only_reservation_keeps_its_warehouse_backed():
    with TestSessionLocal() as db:
        item, reserved_warehouse, reserved_batch, model, order = _stock_case(
            db, name="PKG-SCOPED-RES", quantity=5,
        )
        free_warehouse = Warehouse(name=f"PKG-FREE-WH-{uuid4().hex[:8]}", type="accessory_storage")
        db.add(free_warehouse)
        db.flush()
        free_batch = StockBatch(
            item_id=item.id, batch_no=f"PKG-FREE-BATCH-{uuid4().hex[:8]}",
            warehouse_id=free_warehouse.id, quantity=5, unit=item.unit, qc_status="passed",
        )
        other_order = ProductionOrder(
            production_no=f"PKG-SCOPED-OTHER-{uuid4().hex[:8]}",
            production_type="branded_stock", model_id=model.id, planned_quantity=10,
        )
        db.add_all([free_batch, other_order])
        db.flush()
        reservation = MaterialReservation(
            reservation_no=f"PKG-SCOPED-RES-{uuid4().hex[:8]}",
            production_order_id=other_order.id,
            item_id=item.id, stock_batch_id=None, warehouse_id=reserved_warehouse.id,
            reserved_quantity=5, consumed_quantity=0, released_quantity=0,
            unit=item.unit, status="reserved", reservation_type="packaging", source="manual",
        )
        db.add_all([
            reservation,
            ModelBOM(model_id=model.id, item_id=item.id, quantity_per_piece=5, unit=item.unit),
        ])
        db.flush()

        consume_packaging_materials_from_bom(
            db, production_order_id=order.id, packed_qty=1,
            reference_type="PackagingRecord", reference_id=77, user_id=None,
        )
        db.flush()

        movement = db.query(StockMovement).filter_by(reference_type="PackagingRecord", reference_id=77).one()
        assert movement.batch_id == free_batch.id
        assert float(reserved_batch.quantity) == 5
        assert float(free_batch.quantity) == 0
        assert float(reservation.consumed_quantity) == 0
        assert reservation.status == "reserved"


@pytest.mark.parametrize("scoped_batchless,should_reject", [(0, True), (2, False)])
def test_packaging_rechecks_scoped_reservation_batchless_backing(scoped_batchless, should_reject):
    with TestSessionLocal() as db:
        item, reserved_warehouse, reserved_batch, model, order = _stock_case(
            db, name="PKG-SCOPED-LEDGER", quantity=3,
        )
        free_warehouse = Warehouse(name=f"PKG-LEDGER-FREE-{uuid4().hex[:8]}", type="accessory_storage")
        db.add(free_warehouse)
        db.flush()
        free_batch = StockBatch(
            item_id=item.id, batch_no=f"PKG-LEDGER-BATCH-{uuid4().hex[:8]}",
            warehouse_id=free_warehouse.id, quantity=10, unit=item.unit, qc_status="passed",
        )
        other_order = ProductionOrder(
            production_no=f"PKG-LEDGER-OTHER-{uuid4().hex[:8]}",
            production_type="branded_stock", model_id=model.id, planned_quantity=10,
        )
        db.add_all([free_batch, other_order])
        db.flush()
        db.add_all([
            MaterialReservation(
                reservation_no=f"PKG-LEDGER-RES-{uuid4().hex[:8]}",
                production_order_id=other_order.id, item_id=item.id,
                stock_batch_id=None, warehouse_id=reserved_warehouse.id,
                reserved_quantity=5, consumed_quantity=0, released_quantity=0,
                unit=item.unit, status="reserved", reservation_type="packaging", source="manual",
            ),
            ModelBOM(model_id=model.id, item_id=item.id, quantity_per_piece=5, unit=item.unit),
        ])
        if scoped_batchless:
            db.add(StockMovement(
                movement_type="adjustment", item_id=item.id, batch_id=None,
                to_warehouse_id=reserved_warehouse.id, quantity=scoped_batchless, unit=item.unit,
            ))
        db.flush()

        if should_reject:
            with pytest.raises(HTTPException) as rejected:
                consume_packaging_materials_from_bom(
                    db, production_order_id=order.id, packed_qty=1,
                    reference_type="PackagingRecord", reference_id=78, user_id=None,
                )
            assert rejected.value.status_code == 409
        else:
            consume_packaging_materials_from_bom(
                db, production_order_id=order.id, packed_qty=1,
                reference_type="PackagingRecord", reference_id=78, user_id=None,
            )
        db.flush()

        movements = db.query(StockMovement).filter_by(reference_type="PackagingRecord", reference_id=78).all()
        assert len(movements) == (0 if should_reject else 1)
        if movements:
            assert movements[0].batch_id == free_batch.id
            assert float(movements[0].quantity) == 5
        assert float(reserved_batch.quantity) == 3
        assert float(free_batch.quantity) == (10 if should_reject else 5)


def test_packaging_scoped_reservation_rejects_unattributed_batchless_fallback():
    with TestSessionLocal() as db:
        item, warehouse, batch, model, order = _stock_case(
            db, name="PKG-SCOPED-FALLBACK", quantity=5,
        )
        other_order = ProductionOrder(
            production_no=f"PKG-FALLBACK-OTHER-{uuid4().hex[:8]}",
            production_type="branded_stock", model_id=model.id, planned_quantity=10,
        )
        db.add(other_order)
        db.flush()
        db.add_all([
            MaterialReservation(
                reservation_no=f"PKG-FALLBACK-RES-{uuid4().hex[:8]}",
                production_order_id=other_order.id, item_id=item.id,
                stock_batch_id=None, warehouse_id=warehouse.id,
                reserved_quantity=5, consumed_quantity=0, released_quantity=0,
                unit=item.unit, status="reserved", reservation_type="packaging", source="manual",
            ),
            StockMovement(
                movement_type="adjustment", item_id=item.id, batch_id=None,
                to_warehouse_id=warehouse.id, quantity=5, unit=item.unit,
            ),
            ModelBOM(model_id=model.id, item_id=item.id, quantity_per_piece=5, unit=item.unit),
        ])
        db.flush()

        with pytest.raises(HTTPException) as rejected:
            consume_packaging_materials_from_bom(
                db, production_order_id=order.id, packed_qty=1,
                reference_type="PackagingRecord", reference_id=79, user_id=None,
            )
        db.flush()

        assert rejected.value.status_code == 409
        assert db.query(StockMovement).filter_by(reference_type="PackagingRecord", reference_id=79).count() == 0
        assert float(batch.quantity) == 5


def test_packaging_partial_batch_shortage_records_complete_consumption():
    with TestSessionLocal() as db:
        item, _warehouse, batch, model, order = _stock_case(db, name="PKG-PARTIAL", quantity=2)
        db.add(ModelBOM(model_id=model.id, item_id=item.id, quantity_per_piece=5, unit=item.unit))
        db.flush()

        consume_packaging_materials_from_bom(
            db,
            production_order_id=order.id,
            packed_qty=1,
            reference_type="PackagingRecord",
            reference_id=847,
            user_id=None,
        )
        db.flush()

        movements = db.query(StockMovement).filter_by(
            item_id=item.id, movement_type="consume",
            reference_type="PackagingRecord", reference_id=847,
        ).order_by(StockMovement.id).all()
        assert len(movements) == 2
        assert [(row.batch_id, float(row.quantity), row.unit) for row in movements] == [
            (batch.id, 2, item.unit), (None, 3, item.unit),
        ]
        assert float(batch.quantity) == 0


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
