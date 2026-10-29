"""StockBatch edit operation against the identity-pinned disposable PostgreSQL fixture."""

from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import lazyload

from app.libs.dto.inventory.stock_batch_update import StockBatchUpdate
from app.libs.enums.inventory import StockBatchQcStatus
from app.models.inventory import stock_service
from app.schemas import (
    AuditLog,
    EcoFabricDispatch,
    EcoFabricRoll,
    Item,
    MaterialReservation,
    Model,
    ModelBOM,
    ProductionOrder,
    StockBatch,
    StockMovement,
    User,
    Warehouse,
    WasteRecord,
)
from app.tests.test_customer_create_postgres import chain, customer_pg_sessions  # noqa: F401


def _seed(sessions, *, quantity=10, roll_lengths=None, reservation_quantity=None, eco_return=False):
    with sessions.begin() as db:
        suffix = uuid4().hex
        actor = User(
            name="Inventory edit PG actor", email=f"inventory-edit-{suffix}@example.invalid",
            password_hash="unused", factory_code="MIL", extra_permissions=["*"], is_active=True,
        )
        old_item = Item(sku=f"INV-OLD-{suffix}", name="Old fabric", category="fabric", unit="kg")
        new_item = Item(sku=f"INV-NEW-{suffix}", name="New fabric", category="fabric", unit="kg")
        inactive_item = Item(
            sku=f"INV-INACTIVE-{suffix}", name="Inactive fabric", category="fabric", unit="kg",
            is_active=False,
        )
        source = Warehouse(name=f"Edit source {suffix}", type="fabric_storage")
        destination = Warehouse(name=f"Edit destination {suffix}", type="fabric_storage")
        model = Model(code=f"INV-{suffix[:12]}", name="Inventory edit test model")
        db.add_all([actor, old_item, new_item, inactive_item, source, destination, model])
        db.flush()
        order = ProductionOrder(
            production_no=f"INV-{suffix[:12]}", production_type="client_order", model_id=model.id,
        )
        batch = StockBatch(
            item_id=old_item.id, batch_no=f"INV-{suffix[:12]}", quantity=quantity,
            piece_count=2 if roll_lengths else 1, roll_lengths_m=roll_lengths or [],
            color="retained color", color_code="retained code", unit="kg", cost_per_unit=2,
            warehouse_id=source.id, qc_status="pending",
        )
        db.add_all([order, batch])
        db.flush()
        receipt = StockMovement(
            movement_type="receive", item_id=old_item.id, batch_id=batch.id,
            to_warehouse_id=source.id, quantity=quantity, unit="kg",
            reference_type="StockBatch", reference_id=batch.id, created_by=actor.id,
        )
        bom = ModelBOM(
            model_id=model.id, item_id=old_item.id, stock_batch_id=batch.id,
            quantity_per_piece=1, unit="kg",
        )
        waste = WasteRecord(
            item_id=old_item.id, batch_id=batch.id, waste_type="scrap", quantity=0.25, unit="kg",
        )
        db.add_all([receipt, bom, waste])
        reservation = None
        if reservation_quantity is not None:
            reservation = MaterialReservation(
                reservation_no=f"INV-{suffix[:12]}", production_order_id=order.id,
                item_id=old_item.id, stock_batch_id=batch.id, reserved_quantity=reservation_quantity,
                unit="kg", status="reserved",
            )
            db.add(reservation)
        dispatch = None
        if eco_return:
            dispatch = EcoFabricDispatch(
                request_key=str(uuid4()), created_by=actor.id, operator_name="PG test",
                remaining_inventory=[],
            )
            db.add(dispatch)
            db.flush()
            db.add(EcoFabricRoll(
                dispatch_id=dispatch.id, batch_id=batch.id, roll_number=1,
                fabric_name=old_item.name, batch_no=batch.batch_no,
                quantity=1, unit="kg", returned_at=None,
            ))
        db.flush()
        return {
            "actor": actor.id,
            "batch": batch.id,
            "old_item": old_item.id,
            "new_item": new_item.id,
            "inactive_item": inactive_item.id,
            "source": source.id,
            "destination": destination.id,
            "receipt": receipt.id,
            "reservation": reservation.id if reservation else None,
            "bom": bom.id,
            "waste": waste.id,
        }


def _actor(db, actor_id):
    return db.query(User).filter_by(id=actor_id).one()


def _snapshot(db, ids):
    batch = db.query(StockBatch).options(lazyload(StockBatch.item)).filter_by(id=ids["batch"]).one()
    return {
        "batch": (batch.item_id, float(batch.quantity), batch.warehouse_id, batch.piece_count, batch.color),
        "movements": tuple(
            (row.id, row.item_id, row.movement_type, float(row.quantity), row.from_warehouse_id, row.to_warehouse_id)
            for row in db.query(StockMovement).filter_by(batch_id=ids["batch"]).order_by(StockMovement.id)
        ),
        "reservation_item": (
            db.query(MaterialReservation.item_id).filter_by(id=ids["reservation"]).scalar()
            if ids["reservation"] else None
        ),
        "bom_item": db.query(ModelBOM.item_id).filter_by(id=ids["bom"]).scalar(),
        "waste_item": db.query(WasteRecord.item_id).filter_by(id=ids["waste"]).scalar(),
        "audit_count": db.query(AuditLog).count(),
    }


def _batch_update_audit(db, ids):
    rows = db.query(AuditLog).filter_by(
        action="update", entity_type="StockBatch", entity_id=ids["batch"],
    ).all()
    assert len(rows) == 1
    row = rows[0]
    assert row.user_id == ids["actor"]
    assert row.entity_type == "StockBatch" and row.entity_id == ids["batch"]
    return row


def test_pg_update_batch_nullable_patch_quantity_warehouse_and_movement_conservation(customer_pg_sessions):
    ids = _seed(customer_pg_sessions)
    with customer_pg_sessions() as db:
        batch = db.query(StockBatch).options(lazyload(StockBatch.item)).filter_by(id=ids["batch"]).one()
        result = stock_service.update_batch(
            db, ids["batch"], StockBatchUpdate.model_validate({
                "color": None,
                "quantity": 8,
                "warehouse_id": ids["destination"],
                "qc_status": StockBatchQcStatus.PASSED,
            }),
            _actor(db, ids["actor"]),
        )
        assert result["item_id"] == ids["old_item"]
    with customer_pg_sessions() as db:
        state = db.query(StockBatch).options(lazyload(StockBatch.item)).filter_by(id=ids["batch"]).one()
        assert state.color is None and state.color_code == "retained code" and state.supplier_id is None
        assert state.qc_status == "passed"
        assert state.quantity == 8 and state.warehouse_id == ids["destination"]
        audit = _batch_update_audit(db, ids)
        assert audit.old_value_json["color"] == "retained color"
        assert audit.old_value_json["color_code"] == "retained code"
        assert audit.old_value_json["quantity"] == 10.0
        assert audit.old_value_json["warehouse_id"] == ids["source"]
        assert audit.old_value_json["qc_status"] == "pending"
        assert audit.new_value_json == {
            "color": None, "quantity": 8.0, "warehouse_id": ids["destination"], "qc_status": "passed",
        }
        movements = db.query(StockMovement).filter_by(batch_id=ids["batch"]).order_by(StockMovement.id).all()
        assert [(row.movement_type, float(row.quantity), row.from_warehouse_id, row.to_warehouse_id)
                for row in movements] == [
            ("receive", 10.0, None, ids["source"]),
            ("issue", 2.0, ids["source"], None),
            ("transfer", 8.0, ids["source"], ids["destination"]),
        ]
    chain(customer_pg_sessions)


def test_pg_forced_batch_item_relink_updates_catalog_and_inventory_participants(customer_pg_sessions):
    ids = _seed(customer_pg_sessions, reservation_quantity=2)
    with customer_pg_sessions() as db:
        audit_count_before = db.query(AuditLog).count()
        result = stock_service.update_batch(
            db, ids["batch"], StockBatchUpdate.model_validate({"item_id": ids["new_item"]}),
            _actor(db, ids["actor"]), force=True,
        )
        assert result["item_id"] == ids["new_item"]
    with customer_pg_sessions() as db:
        state = _snapshot(db, ids)
        assert state["batch"][0] == ids["new_item"]
        assert state["reservation_item"] == ids["new_item"]
        assert state["bom_item"] == ids["new_item"]
        assert state["waste_item"] == ids["new_item"]
        assert state["movements"] == ((ids["receipt"], ids["new_item"], "receive", 10.0, None, ids["source"]),)
        assert state["audit_count"] == audit_count_before + 1
        audit = _batch_update_audit(db, ids)
        assert audit.old_value_json["item_id"] == ids["old_item"]
        assert audit.new_value_json == {
            "item_id": ids["new_item"],
            "relinked_item_references": {
                "stock_movements": 1, "material_reservations": 1, "model_bom": 1, "waste_records": 1,
            },
        }
    chain(customer_pg_sessions)


@pytest.mark.parametrize(
    "refusal", ["inactive_target", "reservation_floor", "reserved_warehouse", "roll_lengths", "eco_return"],
)
def test_pg_batch_edit_refusals_leave_all_rows_and_audit_unchanged(customer_pg_sessions, refusal):
    ids = _seed(
        customer_pg_sessions,
        reservation_quantity=8 if refusal == "reservation_floor" else 2 if refusal == "reserved_warehouse" else None,
        roll_lengths=[2.0, 2.0] if refusal == "roll_lengths" else None,
        eco_return=refusal == "eco_return",
    )
    with customer_pg_sessions() as db:
        before = _snapshot(db, ids)
        if refusal == "inactive_target":
            patch, force = {"item_id": ids["inactive_item"], "piece_count": 4}, True
            expected = "Selected material is inactive"
        elif refusal == "reservation_floor":
            patch, force = {"quantity": 7}, False
            expected = "Quantity cannot be lower than reserved stock (8 kg)"
        elif refusal == "reserved_warehouse":
            patch, force = {"warehouse_id": ids["destination"]}, True
            expected = "Cannot change warehouse while stock is reserved"
        elif refusal == "roll_lengths":
            patch, force = {"piece_count": 3}, False
            expected = "Cannot change roll count after individual roll lengths have been recorded"
        else:
            patch, force = {"color": "changed"}, False
            expected = "Return outstanding fabric through the Eco Cotton register before changing this batch"
        with pytest.raises(HTTPException) as error:
            stock_service.update_batch(
                db, ids["batch"], StockBatchUpdate.model_validate(patch), _actor(db, ids["actor"]), force=force,
            )
        assert error.value.detail == expected
        db.rollback()
        assert _snapshot(db, ids) == before


@pytest.mark.parametrize("scenario", ["reserved_relink", "unreserved_transfer"])
def test_pg_audit_failure_rolls_back_all_batch_edit_participants_then_one_retry(
    customer_pg_sessions, monkeypatch, scenario,
):
    reserved = scenario == "reserved_relink"
    ids = _seed(customer_pg_sessions, reservation_quantity=2 if reserved else None)
    with customer_pg_sessions() as db:
        before = _snapshot(db, ids)
        real_log_action = stock_service.log_action
        calls = 0

        def fail_first_audit(session, *args, **kwargs):
            nonlocal calls
            assert session is db
            calls += 1
            if calls == 1:
                raise RuntimeError("injected audit failure")
            return real_log_action(session, *args, **kwargs)

        monkeypatch.setattr(stock_service, "log_action", fail_first_audit)
        patch = {"item_id": ids["new_item"], "quantity": 8}
        if not reserved:
            patch["warehouse_id"] = ids["destination"]
        payload = StockBatchUpdate.model_validate(patch)
        with pytest.raises(RuntimeError, match="injected audit failure"):
            stock_service.update_batch(db, ids["batch"], payload, _actor(db, ids["actor"]), force=True)
        db.rollback()
        assert _snapshot(db, ids) == before

        stock_service.update_batch(db, ids["batch"], payload, _actor(db, ids["actor"]), force=True)
        assert calls == 2
        after = _snapshot(db, ids)
        target_warehouse = ids["source"] if reserved else ids["destination"]
        assert after["batch"][0] == ids["new_item"] and after["batch"][1:3] == (8.0, target_warehouse)
        assert after["bom_item"] == after["waste_item"] == ids["new_item"]
        if reserved:
            assert after["reservation_item"] == ids["new_item"]
            expected_movements = [
                ("receive", 10.0, None, ids["source"]),
                ("issue", 2.0, ids["source"], None),
            ]
        else:
            assert after["reservation_item"] is None
            expected_movements = [
                ("receive", 10.0, None, ids["source"]),
                ("issue", 2.0, ids["source"], None),
                ("transfer", 8.0, ids["source"], ids["destination"]),
            ]
        assert sorted((row[2], row[3], row[4], row[5]) for row in after["movements"]) == sorted(expected_movements)
        assert after["audit_count"] == before["audit_count"] + 1
        audit = _batch_update_audit(db, ids)
        assert audit.old_value_json["item_id"] == ids["old_item"]
        assert audit.old_value_json["quantity"] == 10.0
        assert audit.old_value_json["warehouse_id"] == ids["source"]
        expected_new_value = {
            "item_id": ids["new_item"], "quantity": 8.0,
            "relinked_item_references": {
                "stock_movements": 1, "material_reservations": 1 if reserved else 0,
                "model_bom": 1, "waste_records": 1,
            },
        }
        if not reserved:
            expected_new_value["warehouse_id"] = ids["destination"]
        assert audit.new_value_json == expected_new_value
    chain(customer_pg_sessions)
