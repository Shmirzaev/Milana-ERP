from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from time import monotonic, sleep
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.api.routes import cutting_passports as passport_routes
from app.api.routes import production as production_routes
from app.schemas import (
    AuditLog,
    Bundle,
    CuttingRecord,
    CuttingPassport,
    Department,
    Model,
    ProductionBatch,
    ProductionOrder,
    User,
    WorkOrder,
)
from app.tests.test_password_change_races import (
    password_change_postgres_sessions as password_change_postgres_sessions,
)


@pytest.mark.parametrize("has_operator", [False, True])
def test_postgres_linked_passport_edit_with_optional_operator(password_change_postgres_sessions, has_operator):
    sessions, engine = password_change_postgres_sessions
    marker = uuid4().hex
    with sessions() as db:
        actor = User(name="Passport editor", email=f"passport-{marker}@example.invalid",
                     password_hash="test-only", factory_code="MIL", extra_permissions=["admin.super"])
        model = Model(code=f"EDIT-{marker}", name="Passport edit regression")
        department = Department(name=f"Cutting {marker[:12]}", code=f"CUT-{marker[:8]}")
        db.add_all([actor, model, department])
        db.flush()
        order = ProductionOrder(production_no=f"EDIT-{marker}", production_type="branded_stock",
                                model_id=model.id, planned_quantity=300, status="cutting")
        db.add(order)
        db.flush()
        work = WorkOrder(production_order_id=order.id, department_id=department.id,
                         operation="cutting", status="in_progress", planned_input_qty=300, planned_output_qty=300)
        db.add(work)
        db.commit()
        payload = passport_routes.CuttingPassportIn(
            passport_no=marker[:20], date="2026-10-19T00:00:00Z", production_order_id=order.id,
            operator_id=actor.id if has_operator else None, pieces=300, total_layers=50,
            layer_weight_kg=1.1, planned_kg=51,
        )
        created = passport_routes.create_passport(payload, db, actor)
        actor_id, passport_id, batch_id = actor.id, created["id"], created["production_batch_id"]

    contender_pid = Queue()

    def edit():
        with sessions() as db:
            contender_pid.put(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
            return passport_routes.update_passport(
                passport_id, payload.model_copy(update={"beka_per_piece_kg": 0.005}), db, db.get(User, actor_id),
            )

    with sessions() as blocker, ThreadPoolExecutor(max_workers=1) as executor:
        blocker.query(CuttingPassport).filter_by(id=passport_id).with_for_update(of=CuttingPassport).one()
        future = executor.submit(edit)
        try:
            pid = contender_pid.get(timeout=10)
            deadline = monotonic() + 10
            with engine.connect() as observer:
                while monotonic() < deadline:
                    if observer.execute(text("SELECT cardinality(pg_blocking_pids(:pid))"), {"pid": pid}).scalar_one():
                        break
                    assert not future.done(), "Passport edit did not wait for its row lock"
                    sleep(0.02)
                else:
                    raise AssertionError("Passport edit never waited for its row lock")
        finally:
            blocker.rollback()
        updated = future.result(timeout=15)
    assert updated["actual_kg"] == 56.5
    assert updated["production_batch_id"] == batch_id
    with sessions() as db:
        saved = db.get(CuttingPassport, passport_id)
        assert float(saved.beka_per_piece_kg) == 0.005
        assert db.query(ProductionBatch).filter_by(cutting_passport_id=passport_id).count() == 1
        assert db.get(ProductionBatch, batch_id).passport_actual_quantity == 300
        assert db.query(CuttingRecord).filter_by(cutting_passport_id=passport_id).count() == 0
        assert db.query(Bundle).filter_by(production_batch_id=batch_id).count() == 0
        assert db.query(AuditLog).filter_by(entity_type="CuttingPassport", entity_id=passport_id, action="update").count() == 1


def _bundle_adjustment_fixture(sessions) -> tuple[int, int, int]:
    marker = uuid4().hex
    with sessions() as db:
        actor = User(
            name="Cutting reconciliation race",
            email=f"cutting-reconciliation-{marker}@example.invalid",
            password_hash="test-only",
            factory_code="MIL",
            extra_permissions=["admin.super"],
            is_active=True,
        )
        model = Model(code=f"P19-{marker}", name="Cutting reconciliation race")
        department = Department(name=f"Cutting {marker[:12]}", code="CUT")
        db.add_all([actor, model, department])
        db.flush()
        order = ProductionOrder(
            production_no=f"P19-{marker}",
            production_type="branded_stock",
            model_id=model.id,
            planned_quantity=10,
            status="cutting",
        )
        db.add(order)
        db.flush()
        batch = ProductionBatch(
            production_order_id=order.id,
            batch_no="P19-0001",
            batch_index=1,
            planned_quantity=10,
        )
        db.add(batch)
        db.flush()
        cutting = WorkOrder(
            production_order_id=order.id,
            production_batch_id=batch.id,
            department_id=department.id,
            operation="cutting",
            status="waiting",
            planned_input_qty=10,
            planned_output_qty=10,
            actual_input_qty=0,
            actual_output_qty=0,
            passed_qty=0,
            failed_qty=0,
            rework_qty=0,
        )
        packaging = WorkOrder(
            production_order_id=order.id,
            production_batch_id=batch.id,
            department_id=department.id,
            operation="packaging",
            status="waiting",
            planned_input_qty=10,
            planned_output_qty=10,
            actual_input_qty=0,
            actual_output_qty=0,
            passed_qty=0,
            failed_qty=0,
            rework_qty=0,
        )
        db.add_all([cutting, packaging])
        db.flush()
        record = CuttingRecord(
            work_order_id=cutting.id,
            production_batch_id=batch.id,
            input_quantity=1,
            input_unit="kg",
            cut_pieces=10,
            passed_pieces=10,
            defective_pieces=0,
            waste_quantity=0,
            waste_unit="kg",
            layer_material_kg=0,
            beika_kg=0,
            material_rolls_used=0,
            bundle_count=1,
            total_bundled_quantity=10,
            approval_status="approved",
        )
        db.add(record)
        db.flush()
        bundle = Bundle(
            bundle_no=f"P19-{marker}",
            barcode=f"P19-QR-{marker}",
            production_order_id=order.id,
            production_batch_id=batch.id,
            cutting_record_id=record.id,
            model_id=model.id,
            color="blue",
            size="M",
            quantity=10,
            status="created",
        )
        db.add(bundle)
        db.commit()
        return int(actor.id), int(record.id), int(bundle.id)


def test_postgres_bundle_adjustment_waits_for_lock_and_retries_after_rollback(
    password_change_postgres_sessions,
):
    sessions, engine = password_change_postgres_sessions
    actor_id, record_id, bundle_id = _bundle_adjustment_fixture(sessions)
    payload = production_routes.CuttingBundleQuantityUpdateIn(
        bundles=[{"id": bundle_id, "quantity": 11}],
    )
    contender_pid = Queue()

    def contender():
        with sessions() as db:
            contender_pid.put(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
            return production_routes.update_cutting_bundle_quantities(
                record_id,
                payload,
                db,
                db.get(User, actor_id),
            )

    with sessions() as blocker, ThreadPoolExecutor(max_workers=1) as executor:
        locked_bundle = (
            blocker.query(Bundle)
            .filter(Bundle.id == bundle_id)
            .with_for_update()
            .one()
        )
        locked_bundle.quantity = 99
        blocker.flush()
        future = executor.submit(contender)
        pid = contender_pid.get(timeout=10)
        deadline = monotonic() + 10
        with engine.connect() as observer:
            while monotonic() < deadline:
                blocked = observer.execute(
                    text("SELECT cardinality(pg_blocking_pids(:pid))"),
                    {"pid": pid},
                ).scalar_one()
                if blocked:
                    break
                assert not future.done(), "Bundle adjustment did not wait for the row lock"
                sleep(0.02)
            else:
                raise AssertionError("Bundle adjustment never waited for the row lock")
        blocker.rollback()
        result = future.result(timeout=15)

    assert result["total_bundled_quantity"] == 11
    with sessions() as db:
        assert int(db.get(Bundle, bundle_id).quantity) == 11
        record = db.get(CuttingRecord, record_id)
        assert int(record.passed_pieces) == 11
        assert int(record.total_bundled_quantity) == 11
        assert db.query(AuditLog).filter_by(
            entity_type="CuttingRecord",
            entity_id=record_id,
            action="adjust_cutting_bundle_quantity",
        ).count() == 1
