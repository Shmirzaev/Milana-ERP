"""Real PostgreSQL locking/recovery for two-source Packaging budgets."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

from fastapi import HTTPException
import pytest

from app.schemas import Department, FinishedGoodsStock, Model, Package, PackageBatchAllocation, PackagingRecord, ProductionBatch, ProductionOrder, WorkOrder
from app.models import packages_service as service
from app.tests.test_package_write_postgres import package_write_postgres_sessions as package_write_postgres_sessions


def seed(sessions):
    marker = uuid4().hex[:10]
    with sessions.begin() as db:
        department = Department(code=f"ECP-{marker}", name=f"Eco Packaging {marker}")
        model = Model(code=f"MULTI-PG-{marker}", name="Two Nastils")
        db.add_all([department, model])
        db.flush()
        order = ProductionOrder(production_no=f"MULTI-PG-{marker}", model_id=model.id,
                                production_type="branded_stock", planned_quantity=165)
        db.add(order)
        db.flush()
        work = WorkOrder(production_order_id=order.id, department_id=department.id, operation="packaging")
        db.add(work)
        db.flush()
        batches = []
        for index, quantity in enumerate([35, 40, 90], 1):
            batch = ProductionBatch(production_order_id=order.id, batch_no=f"PG-{marker}-{index}",
                                    batch_index=index, planned_quantity=quantity)
            db.add(batch)
            db.flush()
            batches.append(batch.id)
            db.add(PackagingRecord(work_order_id=work.id, production_batch_id=batch.id,
                                   input_qty=quantity, packed_qty=quantity))
        return order.id, model.id, batches


def kwargs(order_id, model_id, allocations):
    quantity = sum(qty for _, qty in allocations)
    return dict(production_order_id=order_id, model_id=model_id, color="White", capacity=60,
                packaging_department_code="ECP", _sync_production=False,
                items=[dict(model_id=model_id, color="White", size="M", quantity=quantity)],
                batch_allocations=[dict(production_batch_id=bid, quantity=qty) for bid, qty in allocations])


def stub_files(monkeypatch):
    monkeypatch.setattr(service, "save_qr_image", lambda *_args: "/test/qr.png")
    monkeypatch.setattr(service, "save_barcode_image", lambda *_args: None)
    monkeypatch.setattr(service, "notify_department", lambda *_args, **_kwargs: None)


def test_concurrent_two_nastil_creation_cannot_spend_same_sources(package_write_postgres_sessions, monkeypatch):
    sessions, _ = package_write_postgres_sessions
    stub_files(monkeypatch)
    order_id, model_id, (first, second, third) = seed(sessions)
    barrier = Barrier(2)

    def create():
        with sessions() as db:
            barrier.wait(timeout=10)
            try:
                service.create_package(db, **kwargs(order_id, model_id, [(first, 35), (second, 25)]))
                db.commit()
                return "created"
            except HTTPException as error:
                db.rollback()
                assert error.status_code == 400
                return "refused"

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(create) for _ in range(2)]
        assert sorted(future.result(timeout=25) for future in futures) == ["created", "refused"]
    with sessions.begin() as db:
        service.create_package(db, **kwargs(order_id, model_id, [(second, 15)]))
    with sessions() as db:
        allocations = db.query(PackageBatchAllocation).join(Package).filter(Package.production_order_id == order_id).all()
        assert {bid: sum(row.quantity for row in allocations if row.production_batch_id == bid)
                for bid in [first, second, third]} == {first: 35, second: 40, third: 0}
        assert db.query(Package).filter_by(production_order_id=order_id).count() == 2
        assert sum(row.quantity for row in db.query(FinishedGoodsStock).filter_by(production_order_id=order_id)) == 75


def test_two_nastil_transaction_rollback_restores_each_source(package_write_postgres_sessions, monkeypatch):
    sessions, _ = package_write_postgres_sessions
    stub_files(monkeypatch)
    order_id, model_id, (first, second, _) = seed(sessions)
    with sessions() as db:
        with pytest.raises(HTTPException):
            service.create_package(db, **kwargs(order_id, model_id, [(first, 35), (second, 25)]))
            service.create_package(db, **kwargs(order_id, model_id, [(second, 16)]))
        db.rollback()
        assert db.query(Package).filter_by(production_order_id=order_id).count() == 0
        assert db.query(FinishedGoodsStock).filter_by(production_order_id=order_id).count() == 0
    with sessions.begin() as db:
        service.create_package(db, **kwargs(order_id, model_id, [(first, 35), (second, 25)]))
        service.create_package(db, **kwargs(order_id, model_id, [(second, 15)]))
    with sessions() as db:
        assert sum(row.total_quantity for row in db.query(Package).filter_by(production_order_id=order_id)) == 75
