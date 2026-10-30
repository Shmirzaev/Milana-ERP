"""Executable parity checks for the Inventory batch-edit persistence boundary."""

import ast
import inspect

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, lazyload

from app.libs.dto.inventory.stock_batch_update import StockBatchUpdate
from app.libs.enums.inventory import StockBatchQcStatus
from app.libs.types.inventory import StockBatchEditCommand, StockBatchEditValues
from app.models.catalog import models_service as catalog_models_service
from app.models.inventory import stock_service
from app.db.base import Base
from app.schemas import MaterialReservation, ModelBOM, StockBatch, StockMovement, WasteRecord
from app.schemas.inventory import stock_batch_persistence


def _session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[
        StockBatch.__table__, StockMovement.__table__, MaterialReservation.__table__,
        ModelBOM.__table__, WasteRecord.__table__,
    ])
    return Session(engine)


def _table_value(db, mapped, column: str, row_id: int):
    table = mapped.__table__
    return db.execute(select(table.c[column]).where(table.c.id == row_id)).scalar_one()


def _batch(db, batch_id: int):
    return db.query(StockBatch).options(lazyload(StockBatch.item)).filter_by(id=batch_id).one()


def test_batch_edit_patch_contract_keeps_omitted_and_explicit_null_distinct():
    omitted = StockBatchUpdate.model_validate({"color": None})
    assert omitted.model_dump(exclude_unset=True) == {"color": None}
    assert "supplier_id" not in omitted.model_dump(exclude_unset=True)
    assert "qc_status" not in omitted.model_dump(exclude_unset=True)
    assert StockBatchEditValues.__annotations__["qc_status"]
    typed_values: StockBatchEditValues = {"color": None, "qc_status": StockBatchQcStatus.PASSED}
    assert typed_values["qc_status"] is StockBatchQcStatus.PASSED


def test_batch_edit_persists_patch_and_balanced_movements_and_cross_domain_links():
    db = _session()
    batch = StockBatch(
        item_id=10, batch_no="B-1", quantity=8, piece_count=2, unit="kg",
        cost_per_unit=1, warehouse_id=20, qc_status="pending",
    )
    db.add(batch)
    db.flush()
    existing_movement = StockMovement(
        movement_type="receive", item_id=10, batch_id=batch.id, to_warehouse_id=20,
        quantity=8, unit="kg", reference_type="StockBatch", reference_id=batch.id,
    )
    reservation = MaterialReservation(
        reservation_no="R-1", production_order_id=1, item_id=10, stock_batch_id=batch.id,
        reserved_quantity=1, unit="kg", status="reserved",
    )
    bom = ModelBOM(model_id=55, item_id=10, stock_batch_id=batch.id, quantity_per_piece=1, unit="kg")
    waste = WasteRecord(item_id=10, batch_id=batch.id, waste_type="scrap", quantity=0, unit="kg")
    db.add_all([existing_movement, reservation, bom, waste])
    db.flush()

    counts = stock_batch_persistence.apply_batch_edit(
        db, batch, StockBatchEditCommand(
            values={"quantity": 6, "warehouse_id": 21, "qc_status": StockBatchQcStatus.PASSED},
            old_warehouse_id=20, target_warehouse_id=21, target_quantity=6, old_quantity=8,
            target_unit="kg", actor_id=7, relink_item_id=11, item_movements=(existing_movement,),
        ),
    )
    counts["model_bom"] = catalog_models_service.relink_stock_batch_boms_for_inventory(
        db, stock_batch_id=batch.id, item_id=11,
    )
    counts["waste_records"] = stock_batch_persistence.relink_batch_waste_items(
        db, batch_id=batch.id, item_id=11,
    )
    stock_batch_persistence.add_batch_edit_movements(
        db, batch, StockBatchEditCommand(
            values={"quantity": 6, "warehouse_id": 21, "qc_status": StockBatchQcStatus.PASSED},
            old_warehouse_id=20, target_warehouse_id=21, target_quantity=6, old_quantity=8,
            target_unit="kg", actor_id=7, relink_item_id=11, item_movements=(existing_movement,),
        ),
    )
    db.flush()

    rows = db.query(StockMovement).filter(StockMovement.batch_id == batch.id).all()
    assert (_table_value(db, StockBatch, "quantity", batch.id),
            _table_value(db, StockBatch, "warehouse_id", batch.id),
            _table_value(db, StockBatch, "qc_status", batch.id)) == (6, 21, "passed")
    assert _table_value(db, StockMovement, "item_id", existing_movement.id) == 11
    assert _table_value(db, MaterialReservation, "item_id", reservation.id) == 11
    assert _table_value(db, ModelBOM, "item_id", bom.id) == 11
    assert _table_value(db, WasteRecord, "item_id", waste.id) == 11
    assert counts == {
        "stock_movements": 1, "material_reservations": 1,
        "model_bom": 1, "waste_records": 1,
    }
    edit_movements = {
        row.movement_type: (float(row.quantity), row.from_warehouse_id, row.to_warehouse_id)
        for row in rows if row.movement_type != "receive"
    }
    assert edit_movements == {"issue": (2.0, 20, None), "transfer": (6.0, 20, 21)}


def test_batch_edit_outer_rollback_restores_all_participants_and_retry_can_commit():
    db = _session()
    batch = StockBatch(item_id=10, batch_no="B-2", quantity=5, unit="kg", cost_per_unit=1,
                       warehouse_id=20, qc_status="pending")
    movement = StockMovement(movement_type="receive", item_id=10, batch_id=None,
                             quantity=5, unit="kg", reference_type="StockBatch", reference_id=1)
    db.add_all([batch, movement])
    db.flush()
    movement.batch_id = batch.id
    reservation = MaterialReservation(
        reservation_no="R-2", production_order_id=1, item_id=10, stock_batch_id=batch.id,
        reserved_quantity=1, unit="kg", status="reserved",
    )
    bom = ModelBOM(model_id=55, item_id=10, stock_batch_id=batch.id, quantity_per_piece=1, unit="kg")
    waste = WasteRecord(item_id=10, batch_id=batch.id, waste_type="scrap", quantity=0, unit="kg")
    db.add_all([reservation, bom, waste])
    db.flush()
    batch_id = batch.id
    movement_id = movement.id
    reservation_id = reservation.id
    bom_id = bom.id
    waste_id = waste.id
    db.commit()

    command = StockBatchEditCommand(
        values={"quantity": 4}, old_warehouse_id=20, target_warehouse_id=20,
        target_quantity=4, old_quantity=5, target_unit="kg", actor_id=7,
        relink_item_id=11, item_movements=(movement,),
    )
    initial_edit_batch = _batch(db, batch_id)
    stock_batch_persistence.apply_batch_edit(db, initial_edit_batch, command)
    catalog_models_service.relink_stock_batch_boms_for_inventory(db, stock_batch_id=batch_id, item_id=11)
    stock_batch_persistence.relink_batch_waste_items(db, batch_id=batch_id, item_id=11)
    stock_batch_persistence.add_batch_edit_movements(db, initial_edit_batch, command)
    db.rollback()

    assert _table_value(db, StockBatch, "quantity", batch_id) == 5
    assert _table_value(db, StockMovement, "item_id", movement_id) == 10
    assert _table_value(db, MaterialReservation, "item_id", reservation_id) == 10
    assert _table_value(db, ModelBOM, "item_id", bom_id) == 10
    assert _table_value(db, WasteRecord, "item_id", waste_id) == 10

    retry_batch = _batch(db, batch_id)
    stock_batch_persistence.apply_batch_edit(db, retry_batch, command)
    catalog_models_service.relink_stock_batch_boms_for_inventory(db, stock_batch_id=batch_id, item_id=11)
    stock_batch_persistence.relink_batch_waste_items(db, batch_id=batch_id, item_id=11)
    stock_batch_persistence.add_batch_edit_movements(db, retry_batch, command)
    db.commit()
    assert _table_value(db, StockBatch, "quantity", batch_id) == 4
    assert _table_value(db, StockMovement, "item_id", movement_id) == 11
    assert _table_value(db, ModelBOM, "item_id", bom_id) == 11


def test_service_keeps_validation_refusal_before_any_schema_writer():
    source = inspect.getsource(stock_service.update_batch)
    assert source.index("Cannot change roll count") < source.index("stock_batch_persistence.apply_batch_edit(")
    assert source.index("cannot change material") < source.index("stock_batch_persistence.apply_batch_edit(")
    assert "payload.model_dump(exclude_unset=True)" in source


def test_persistence_modules_do_not_commit_or_import_business_services():
    for module in (stock_batch_persistence,):
        tree = ast.parse(inspect.getsource(module))
        imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        calls = {node.func.attr for node in ast.walk(tree)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
        assert not any(name.startswith("app.models") or name.startswith("app.api") for name in imports)
        assert not {"commit", "rollback", "begin"} & calls
