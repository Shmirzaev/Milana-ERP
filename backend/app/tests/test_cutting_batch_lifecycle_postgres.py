from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.routes import cutting_passports, production
from app.schemas import CuttingRecord, Department, Model, ProductionBatch, ProductionOrder, SewingRecord, User, WorkOrder
from app.tests.test_password_change_races import password_change_postgres_sessions as password_change_postgres_sessions


def _fixture(sessions):
    marker = uuid4().hex
    with sessions.begin() as db:
        actor = User(name="Cutting test", email=f"{marker}@example.invalid", password_hash="unused",
                     factory_code="MIL", extra_permissions=["admin.super"])
        model = Model(code=marker, name="Isolated cutting test")
        department = db.query(Department).filter_by(code="CUT").first() or Department(code="CUT", name="Cutting")
        db.add_all([actor, model, department])
        db.flush()
        order = ProductionOrder(production_no=marker, model_id=model.id, production_type="branded_stock",
                                planned_quantity=10, status="cutting")
        db.add(order)
        db.flush()
        batch = ProductionBatch(production_order_id=order.id, batch_no="TEST-01", batch_index=1, planned_quantity=10)
        db.add(batch)
        db.flush()
        cutting = WorkOrder(production_order_id=order.id, department_id=department.id, operation="cutting",
                            status="in_progress", planned_input_qty=10, planned_output_qty=10)
        sewing = WorkOrder(production_order_id=order.id, department_id=department.id, operation="sewing",
                           status="in_progress", planned_input_qty=10, planned_output_qty=10)
        db.add_all([cutting, sewing])
        db.flush()
        return actor.id, cutting.id, sewing.id, batch.id


def test_postgres_delete_and_edit_reject_concurrent_then_committed_sewing(password_change_postgres_sessions):
    sessions, _ = password_change_postgres_sessions
    actor_id, cutting_id, sewing_id, batch_id = _fixture(sessions)
    with sessions() as sewing_writer:
        sewing_writer.query(WorkOrder).filter_by(id=sewing_id).with_for_update(of=WorkOrder).one()
        for edit in (False, True):
            with sessions() as db:
                with pytest.raises(HTTPException, match="Sewing is being updated") as caught:
                    if edit:
                        production.update_cutting_batch(cutting_id, batch_id,
                                                        production.CuttingBatchUpdateIn(name="stale"), db, db.get(User, actor_id))
                    else:
                        production.remove_cutting_batch(cutting_id, batch_id, db, db.get(User, actor_id))
                assert caught.value.status_code == 409
                db.rollback()
        sewing_writer.add(SewingRecord(work_order_id=sewing_id, production_batch_id=batch_id,
                                       input_qty=1, sewn_qty=1, passed_qty=1))
        sewing_writer.commit()
    with sessions() as db:
        with pytest.raises(HTTPException, match="Sewing output"):
            production.remove_cutting_batch(cutting_id, batch_id, db, db.get(User, actor_id))
        db.rollback()
        assert db.get(ProductionBatch, batch_id)
        assert not db.query(CuttingRecord).filter_by(production_batch_id=batch_id).count()


def test_factory_change_serializes_with_sewing_output(password_change_postgres_sessions):
    sessions, _ = password_change_postgres_sessions
    actor_id, cutting_id, sewing_id, batch_id = _fixture(sessions)
    with sessions() as writer:
        writer.query(WorkOrder).filter_by(id=sewing_id).with_for_update(of=WorkOrder).one()
        with sessions() as db:
            with pytest.raises(HTTPException, match="Sewing is being updated") as caught:
                production.update_cutting_sewing_factory(
                    cutting_id, production.CuttingSewingFactoryIn(sewing_factory_code="BST"),
                    db, db.get(User, actor_id),
                )
            assert caught.value.status_code == 409
        writer.add(SewingRecord(work_order_id=sewing_id, production_batch_id=batch_id,
                                input_qty=1, sewn_qty=1, passed_qty=1))
        writer.commit()
    with sessions() as db:
        with pytest.raises(HTTPException, match="Sewing output"):
            production.update_cutting_sewing_factory(
                cutting_id, production.CuttingSewingFactoryIn(sewing_factory_code="BST"),
                db, db.get(User, actor_id),
            )


@pytest.mark.parametrize("legacy", [False, True])
def test_postgres_progress_preserves_output_without_bundles(password_change_postgres_sessions, legacy):
    sessions, _ = password_change_postgres_sessions
    actor_id, cutting_id, sewing_id, batch_id = _fixture(sessions)
    with sessions.begin() as db:
        order_id = db.get(WorkOrder, cutting_id).production_order_id
        assert cutting_passports.material_defaults(order_id, db, db.get(User, actor_id))["can_add_material"] is True
        db.add(SewingRecord(
            work_order_id=sewing_id, production_batch_id=None if legacy else batch_id,
            input_qty=1, sewn_qty=1, passed_qty=1,
        ))
    with sessions() as db:
        result = production.cutting_batch_progress(cutting_id, db, db.get(User, actor_id))
        row = next(item for item in result["items"] if item["id"] == batch_id)
        assert row["bundle_count"] == 0
        assert row["sewing_output_recorded"] is True
        assert row["deletable"] is False
        assert cutting_passports.material_defaults(order_id, db, db.get(User, actor_id))["can_add_material"] is False


def test_postgres_delete_returns_consumption_once_with_audit(password_change_postgres_sessions):
    from app.schemas import AuditLog, CuttingMaterialUsage, Item, StockBatch, StockMovement, Warehouse
    sessions, _ = password_change_postgres_sessions
    actor_id, cutting_id, _, batch_id = _fixture(sessions)
    with sessions.begin() as db:
        work = db.get(WorkOrder, cutting_id)
        item = Item(sku=uuid4().hex, name="Fabric", category="fabric", unit="kg")
        warehouse = Warehouse(name="Isolated fabric", type="fabric_storage")
        db.add_all([item, warehouse])
        db.flush()
        stock = StockBatch(item_id=item.id, warehouse_id=warehouse.id, batch_no=uuid4().hex,
                           quantity=95, unit="kg", qc_status="passed")
        db.add(stock)
        db.flush()
        record = CuttingRecord(work_order_id=work.id, production_batch_id=batch_id,
                               fabric_batch_id=stock.id, input_quantity=5, input_unit="kg",
                               cut_pieces=10, passed_pieces=10)
        db.add(record)
        db.flush()
        db.add(CuttingMaterialUsage(cutting_record_id=record.id, stock_batch_id=stock.id,
                                   quantity=5, unit="kg", position=1))
        db.add(StockMovement(movement_type="consume", item_id=item.id, batch_id=stock.id,
                             from_warehouse_id=warehouse.id, quantity=5, unit="kg",
                             reference_type="CuttingRecord", reference_id=record.id))
        stock_id, record_id = stock.id, record.id
    with sessions() as db:
        result = production.remove_cutting_batch(cutting_id, batch_id, db, db.get(User, actor_id))
        assert result["deleted"]
    with sessions() as db:
        assert float(db.get(StockBatch, stock_id).quantity) == 100
        assert db.get(CuttingRecord, record_id) is None
        assert db.query(StockMovement).filter_by(reference_type="CuttingRecord", reference_id=record_id).count() == 1
        assert db.query(StockMovement).filter_by(reference_type="CuttingBatchDeletion", reference_id=batch_id).count() == 1
        audit = db.query(AuditLog).filter_by(action="delete_cutting_batch", entity_id=batch_id).one()
        assert audit.old_value_json["records"][0]["id"] == record_id
        with pytest.raises(HTTPException) as caught:
            production.remove_cutting_batch(cutting_id, batch_id, db, db.get(User, actor_id))
        assert caught.value.status_code == 404
        db.rollback()
        assert float(db.get(StockBatch, stock_id).quantity) == 100


def test_postgres_delete_does_not_wait_behind_order_writer(password_change_postgres_sessions):
    sessions, _ = password_change_postgres_sessions
    actor_id, cutting_id, _, batch_id = _fixture(sessions)
    with sessions() as writer:
        order_id = writer.get(WorkOrder, cutting_id).production_order_id
        writer.query(ProductionOrder).filter_by(id=order_id).with_for_update(of=ProductionOrder).one()
        with sessions() as db:
            with pytest.raises(HTTPException, match="production order is being updated") as caught:
                production.remove_cutting_batch(cutting_id, batch_id, db, db.get(User, actor_id))
            assert caught.value.status_code == 409
            db.rollback()
            assert db.get(ProductionBatch, batch_id)


@pytest.mark.parametrize("used", [False, True])
def test_postgres_retired_label_delete_preserves_sibling_and_history(password_change_postgres_sessions, used):
    from datetime import datetime, timezone
    from app.schemas import AuditLog, PayrollQrLabel
    sessions, _ = password_change_postgres_sessions
    actor_id, cutting_id, _, empty_id = _fixture(sessions)
    with sessions.begin() as db:
        cutting = db.get(WorkOrder, cutting_id)
        keep = ProductionBatch(production_order_id=cutting.production_order_id, batch_no="KEEP-01",
                               batch_index=2, planned_quantity=600, name="Nastil 1")
        db.add(keep)
        db.flush()
        record = CuttingRecord(work_order_id=cutting_id, production_batch_id=keep.id,
                               cut_pieces=600, passed_pieces=600, input_quantity=0)
        label = PayrollQrLabel(production_order_id=cutting.production_order_id, label_uid=uuid4().hex,
                               status="superseded", last_scanned_at=datetime.now(timezone.utc) if used else None)
        db.add_all([record, label])
        db.flush()
        cutting.actual_input_qty = cutting.actual_output_qty = cutting.passed_qty = 600
        cutting.planned_input_qty = cutting.planned_output_qty = 600
        keep_id, record_id, label_id = keep.id, record.id, label.id
    with sessions() as db:
        if used:
            with pytest.raises(HTTPException, match="Unallocated downstream history"):
                production.remove_cutting_batch(cutting_id, empty_id, db, db.get(User, actor_id))
            db.rollback()
        else:
            assert production.remove_cutting_batch(cutting_id, empty_id, db, db.get(User, actor_id))["deleted"]
    with sessions() as db:
        assert (db.get(ProductionBatch, empty_id) is not None) == used
        assert db.get(ProductionBatch, keep_id).planned_quantity == 600
        assert db.get(CuttingRecord, record_id).passed_pieces == 600
        assert db.get(PayrollQrLabel, label_id).status == "superseded"
        assert db.query(AuditLog).filter_by(action="delete_cutting_batch", entity_id=empty_id).count() == (0 if used else 1)
