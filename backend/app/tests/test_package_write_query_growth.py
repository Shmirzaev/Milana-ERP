from math import ceil
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from app.db.session import SessionLocal
from app.models import (
    Department,
    FinishedGoodsStock,
    ManualPackageReceipt,
    Model,
    Notification,
    Package,
    PackageItem,
    PackagePrintRunMember,
    PackagingRecord,
    ProductionBatch,
    ProductionOrder,
    User,
    WorkOrder,
)
from app.services import package_workflows, packages as package_service
from app.services.packaging_scope import packaging_departments_for_order


def _packaged_order(quantity: int) -> tuple[int, int]:
    marker = uuid4().hex[:10]
    with SessionLocal() as db:
        model = Model(
            code=f"PERF09-W-{marker}",
            name=f"PERF09 write context {marker}",
            product_type="shirt",
        )
        db.add(model)
        db.flush()
        order = ProductionOrder(
            production_no=f"PERF09-W-PO-{marker}",
            production_type="branded_stock",
            model_id=model.id,
            status="packaging",
            planned_quantity=quantity,
        )
        db.add(order)
        db.flush()
        work_order = WorkOrder(
            production_order_id=order.id,
            department_id=db.query(Department.id).filter_by(code="PKG").scalar(),
            operation="packaging",
            status="completed",
            planned_input_qty=quantity,
            planned_output_qty=quantity,
            actual_input_qty=quantity,
            actual_output_qty=quantity,
            passed_qty=quantity,
        )
        db.add(work_order)
        db.flush()
        db.add(PackagingRecord(
            work_order_id=work_order.id,
            input_qty=quantity,
            packed_qty=quantity,
            package_count=quantity,
            total_packed_quantity=quantity,
        ))
        db.commit()
        return int(order.id), int(model.id)


def _stub_package_artifacts(monkeypatch) -> None:
    monkeypatch.setattr(
        package_service,
        "save_qr_image",
        lambda _payload, package_no: f"/test/{package_no}.png",
    )
    monkeypatch.setattr(package_service, "save_barcode_image", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(package_service, "sync_production_order_status", lambda *_args, **_kwargs: None)


@pytest.mark.parametrize("batch_count", [1, 50, 401])
def test_packaging_owner_resolution_is_one_read(batch_count):
    marker = uuid4().hex[:10]
    with SessionLocal() as db:
        model = Model(
            code=f"PERF09-O-{marker}",
            name=f"PERF09 owners {marker}",
            product_type="shirt",
        )
        db.add(model)
        db.flush()
        order = ProductionOrder(
            production_no=f"PERF09-O-PO-{marker}",
            production_type="branded_stock",
            model_id=model.id,
            status="packaging",
            planned_quantity=batch_count,
        )
        db.add(order)
        db.flush()
        batches = [
            ProductionBatch(
                production_order_id=order.id,
                batch_no=f"PERF09-O-B-{marker}-{index}",
                batch_index=index,
                planned_quantity=1,
            )
            for index in range(1, batch_count + 1)
        ]
        db.add_all(batches)
        db.flush()
        packaging_id = db.query(Department.id).filter_by(code="PKG").scalar()
        branded_packaging_id = db.query(Department.id).filter_by(code="BPK").scalar()
        db.add(WorkOrder(
            production_order_id=order.id,
            department_id=branded_packaging_id,
            operation="packaging",
        ))
        db.add_all([
            WorkOrder(
                production_order_id=order.id,
                production_batch_id=batch.id,
                department_id=packaging_id,
                operation="packaging",
            )
            for batch in batches
        ])
        db.commit()
        batch_ids = [int(batch.id) for batch in batches]
        requested_ids = set(batch_ids) | {None}
        statements: list[str] = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            normalized = " ".join(statement.lower().split())
            if normalized.startswith("select") and " from work_orders " in normalized:
                statements.append(normalized)

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            owners = packaging_departments_for_order(db, int(order.id), requested_ids)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    assert len(statements) == 1
    assert owners[None] == "BPK"
    assert {owners[batch_id] for batch_id in batch_ids} == {"PKG"}


@pytest.mark.parametrize("package_count", [1, 50, 401])
def test_bulk_package_write_reads_are_bounded_and_results_match(monkeypatch, package_count):
    order_id, model_id = _packaged_order(package_count)
    _stub_package_artifacts(monkeypatch)
    statements: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(" ".join(statement.lower().split()))

    with SessionLocal() as db:
        expected_recipients = db.query(User.id).join(
            Department,
            Department.id == User.department_id,
        ).filter(Department.code == "FGS", User.is_active.is_(True)).count()
        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            packages = package_service.create_packages_bulk(
                db,
                count=package_count,
                production_order_id=order_id,
                model_id=model_id,
                color="navy",
                items=[{
                    "model_id": model_id,
                    "color": "navy",
                    "size": "M",
                    "quantity": 1,
                }],
                capacity=1,
                packaging_department_code="PKG",
            )
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

        package_ids = [int(package.id) for package in packages]
        db.flush()
        persisted_items = db.query(PackageItem).filter(
            PackageItem.package_id.in_(package_ids),
        ).count()
        notifications = db.query(Notification).filter(
            Notification.title == "New package packed",
        ).count()

    availability_reads = [
        statement
        for statement in statements
        if " from packaging_records " in statement
        or " from package_batch_allocations " in statement
        or (
            " from packages " in statement
            and "sum(packages.total_quantity + packages.quantity_shortfall)" in statement
        )
    ]
    package_number_reads = [
        statement
        for statement in statements
        if " from packages " in statement and "packages.package_no" in statement
    ]
    retired_number_reads = [
        statement
        for statement in statements
        if " from system_settings " in statement and "system_settings.value_json" in statement
    ]
    notification_directory_reads = [
        statement
        for statement in statements
        if " from departments " in statement or " from users " in statement
    ]
    assert len(packages) == package_count
    assert package_ids == sorted(package_ids)
    assert [package.total_quantity for package in packages] == [1] * package_count
    assert persisted_items == package_count
    assert notifications == expected_recipients * package_count
    assert len(availability_reads) == 3
    assert len(package_number_reads) == 1
    assert len(retired_number_reads) == 1
    assert len(notification_directory_reads) == 2


def test_bulk_package_availability_failure_rolls_back_all_writes(monkeypatch):
    order_id, model_id = _packaged_order(2)
    _stub_package_artifacts(monkeypatch)
    issued_numbers: list[str] = []

    def save_qr(payload, package_no):
        issued_numbers.append(payload.split("|", 1)[0].split(":", 1)[1])
        return f"/test/{package_no}.png"

    monkeypatch.setattr(package_service, "save_qr_image", save_qr)

    with SessionLocal() as db:
        with pytest.raises(HTTPException) as exc_info:
            package_service.create_packages_bulk(
                db,
                count=3,
                production_order_id=order_id,
                model_id=model_id,
                color="navy",
                items=[{
                    "model_id": model_id,
                    "color": "navy",
                    "size": "M",
                    "quantity": 1,
                }],
                capacity=1,
                packaging_department_code="PKG",
            )
        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == (
            "Package quantity 1 exceeds available packed quantity 0 for this production order"
        )
        db.rollback()

    with SessionLocal() as db:
        assert db.query(Package).filter_by(production_order_id=order_id).count() == 0
        assert db.query(FinishedGoodsStock).filter_by(production_order_id=order_id).count() == 0
        retried = package_service.create_packages_bulk(
            db,
            count=1,
            production_order_id=order_id,
            model_id=model_id,
            color="navy",
            items=[{
                "model_id": model_id,
                "color": "navy",
                "size": "M",
                "quantity": 1,
            }],
            capacity=1,
            packaging_department_code="PKG",
        )
        assert retried[0].package_no == issued_numbers[0]
        db.rollback()


def _manual_packages(package_count: int):
    marker = uuid4().hex[:10]
    with SessionLocal() as db:
        actor = db.query(User).order_by(User.id).first()
        model = Model(
            code=f"PERF09-R-{marker}",
            name=f"PERF09 run snapshot {marker}",
            product_type="shirt",
        )
        receipt = ManualPackageReceipt(
            receipt_no=f"PERF09-R-{marker}",
            created_by=actor.id,
            evidence={"source": "query-growth"},
            evidence_hash="a" * 64,
        )
        db.add_all([model, receipt])
        db.flush()
        packages = []
        for index in range(package_count):
            package = Package(
                package_no=f"PERF09-R-PKG-{marker}-{index:04d}",
                barcode=f"PERF09-R-BC-{marker}-{index:04d}",
                manual_receipt_id=receipt.id,
                model_id=model.id,
                color="navy",
                total_quantity=1,
                capacity=1,
                status="received_in_storage",
                packaging_department_code="PKG",
            )
            package.items = [
                PackageItem(model_id=model.id, color="navy", size="M", quantity=1)
            ]
            db.add(package)
            packages.append(package)
        db.commit()
        return int(actor.id), [int(package.id) for package in packages]


@pytest.mark.parametrize("package_count", [1, 50, 401])
def test_print_run_snapshot_hydration_is_chunk_bounded(package_count):
    actor_id, package_ids = _manual_packages(package_count)
    statements: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(" ".join(statement.lower().split()))

    with SessionLocal() as db:
        actor = db.get(User, actor_id)
        packages = db.query(Package).filter(Package.id.in_(package_ids)).order_by(Package.id).all()
        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            run = package_workflows.create_run(db, actor, packages, received=True)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)
        snapshots = [
            member.snapshot
            for member in db.query(PackagePrintRunMember)
            .filter_by(run_id=run.id)
            .order_by(PackagePrintRunMember.id)
            .all()
        ]

    item_reads = [statement for statement in statements if " from package_items " in statement]
    allocation_reads = [
        statement for statement in statements if " from package_batch_allocations " in statement
    ]
    expected_chunks = ceil(package_count / 400)
    assert len(item_reads) == expected_chunks
    assert len(allocation_reads) == expected_chunks
    assert len(snapshots) == package_count
    assert all(snapshot["quantity"] == 1 for snapshot in snapshots)
    assert all(snapshot["items"] == [{
        "model_id": snapshots[0]["model_id"],
        "color": "navy",
        "size": "M",
        "quantity": 1,
    }] for snapshot in snapshots)
