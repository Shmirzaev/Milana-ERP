from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.api.routes.packages import api_batch_receive_storage
from app.db.session import SessionLocal
from app.models import Department, FinishedGoodsStock, Package, PackageItem, PackageScanLog, ProductionOrder, User, WorkOrder
from app.schemas.tracking import PackageBatchReceiveStorageIn
from app.services.packages import receive_at_storage
from app.services.workflow import sync_storage_transfer_work_order


@pytest.mark.parametrize("mode", ["scalar", "batch"])
@pytest.mark.parametrize("already_started", [False, True])
def test_complete_intake_keeps_start_and_end_timestamps(mode, already_started):
    marker = uuid4().hex
    historical_start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    with SessionLocal() as db:
        order = ProductionOrder(production_no=f"TIME-{marker}", model_id=1, production_type="branded_stock",
                                planned_quantity=10, status="storage_transfer")
        db.add(order)
        db.flush()
        department_id = db.query(Department.id).filter(Department.code == "FGS").scalar()
        transfer = WorkOrder(production_order_id=order.id, operation="storage_transfer",
                             department_id=department_id, planned_input_qty=10, planned_output_qty=10,
                             status="in_progress" if already_started else "waiting",
                             start_time=historical_start if already_started else None)
        db.add(transfer)
        packages = []
        for index in range(2):
            package = Package(package_no=f"TIME-{marker}-{index}", barcode=f"TIME-{marker}-{index}",
                              production_order_id=order.id, model_id=1, color="white", total_quantity=5,
                              capacity=5, status="packed")
            db.add(package)
            db.flush()
            db.add(PackageItem(package_id=package.id, model_id=1, color="white", size="M", quantity=5))
            db.add(FinishedGoodsStock(package_id=package.id, model_id=1, color="white", size="M",
                                     quantity=5, available_qty=5))
            packages.append(package)
        db.commit()
        package_ids = [package.id for package in packages]
        order_id, work_order_id = order.id, transfer.id

    with SessionLocal() as db:
        current = db.query(User).filter(User.email == "admin@example.com").one()
        if mode == "batch":
            api_batch_receive_storage(PackageBatchReceiveStorageIn(package_ids=package_ids), db, current)
        else:
            for package_id in package_ids:
                receive_at_storage(db, db.get(Package, package_id), None, current.id)
            db.commit()
    with SessionLocal() as db:
        transfer = db.get(WorkOrder, work_order_id)
        assert transfer.status == "completed"
        assert transfer.passed_qty == 10
        assert transfer.start_time is not None
        assert transfer.end_time is not None
        assert transfer.start_time <= transfer.end_time
        if already_started:
            assert transfer.start_time.replace(tzinfo=timezone.utc) == historical_start
        timestamps = transfer.start_time, transfer.end_time
        sync_storage_transfer_work_order(db, order_id)
        db.flush()
        assert (transfer.start_time, transfer.end_time) == timestamps
        assert db.query(PackageScanLog).filter(PackageScanLog.package_id.in_(package_ids),
                                              PackageScanLog.scan_type == "received_storage").count() == 2
