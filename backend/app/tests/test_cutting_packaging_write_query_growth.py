from collections import Counter
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from app.models import (
    Bundle,
    BundleScanLog,
    CuttingRecord,
    Department,
    Item,
    MaterialReservation,
    Model,
    ModelBOM,
    PackagingRecord,
    ProductionOrder,
    StockBatch,
    StockMovement,
    Warehouse,
    WorkOrder,
)
from app.tests.conftest import TestSessionLocal, test_engine
from app.services.inventory import consume_cutting_materials


def _cutting_work_order(bundle_count: int) -> int:
    marker = uuid4().hex[:8]
    with TestSessionLocal() as db:
        model = Model(
            code=f"PERF20-W-{marker}",
            name=f"Cutting write growth {marker}",
            product_type="shirt",
            status="approved",
        )
        db.add(model)
        db.flush()
        order = ProductionOrder(
            production_no=f"PERF20-W-PO-{marker}",
            production_type="branded_stock",
            model_id=model.id,
            planned_quantity=bundle_count,
            status="cutting",
        )
        db.add(order)
        db.flush()
        department_ids = {
            code: int(department_id)
            for department_id, code in db.query(Department.id, Department.code).filter(
                Department.code.in_(("CUT", "MIL", "PKG", "STR")),
            )
        }
        work_orders = [
            WorkOrder(
                production_order_id=order.id,
                department_id=department_ids[department_code],
                operation=operation,
                planned_input_qty=bundle_count,
                planned_output_qty=bundle_count,
                status="waiting",
            )
            for operation, department_code in (
                ("cutting", "CUT"),
                ("sewing", "MIL"),
                ("packaging", "PKG"),
                ("storage_transfer", "STR"),
            )
        ]
        db.add_all(work_orders)
        db.commit()
        return int(work_orders[0].id)


def _cutting_material_work_order(
    material_count: int,
    *,
    reservation_quantity: float = 0,
) -> tuple[int, list[int]]:
    work_order_id = _cutting_work_order(1)
    marker = uuid4().hex[:8]
    with TestSessionLocal() as db:
        work_order = db.get(WorkOrder, work_order_id)
        warehouse = Warehouse(name=f"PERF20 cutting materials {marker}", type="materials")
        items = [
            Item(
                sku=f"PERF20-CUT-{marker}-{index:04d}",
                name=f"Cutting material {index}",
                category="fabric",
                unit="kg",
            )
            for index in range(material_count)
        ]
        db.add_all([warehouse, *items])
        db.flush()
        batches = [
            StockBatch(
                item_id=item.id,
                warehouse_id=warehouse.id,
                batch_no=f"PERF20-CUT-BATCH-{marker}-{index:04d}",
                quantity=2,
                unit="kg",
                qc_status="passed",
            )
            for index, item in enumerate(items)
        ]
        db.add_all(batches)
        db.flush()
        if reservation_quantity > 0:
            db.add_all([
                MaterialReservation(
                    reservation_no=f"PERF20-GROWTH-{marker}-{index:04d}",
                    production_order_id=int(work_order.production_order_id),
                    item_id=int(item.id),
                    stock_batch_id=int(batch.id),
                    warehouse_id=int(warehouse.id),
                    reserved_quantity=reservation_quantity,
                    consumed_quantity=0,
                    released_quantity=0,
                    unit="kg",
                    status="reserved",
                    reservation_type="material",
                    source="manual",
                )
                for index, (item, batch) in enumerate(zip(items, batches, strict=True))
            ])
        db.commit()
        return work_order_id, [int(batch.id) for batch in batches]


def _packaging_work_order(bom_count: int) -> tuple[int, list[int]]:
    marker = uuid4().hex[:8]
    with TestSessionLocal() as db:
        model = Model(
            code=f"PERF20-P-{marker}",
            name=f"Packaging write growth {marker}",
            product_type="shirt",
            status="approved",
        )
        warehouse = Warehouse(name=f"PERF20 packaging materials {marker}", type="materials")
        items = [
            Item(
                sku=f"PERF20-PKG-{marker}-{index:04d}",
                name=f"Packaging material {index}",
                category="packaging",
                unit="pcs",
            )
            for index in range(bom_count)
        ]
        db.add_all([model, warehouse, *items])
        db.flush()
        db.add_all([
            ModelBOM(
                model_id=model.id,
                item_id=item.id,
                quantity_per_piece=1,
                unit="pcs",
                waste_percent=0,
            )
            for item in items
        ])
        stock_batches = [
            StockBatch(
                item_id=item.id,
                warehouse_id=warehouse.id,
                batch_no=f"PERF20-PKG-BATCH-{marker}-{index:04d}",
                quantity=2,
                unit="pcs",
                qc_status="passed",
            )
            for index, item in enumerate(items)
        ]
        db.add_all(stock_batches)
        order = ProductionOrder(
            production_no=f"PERF20-P-PO-{marker}",
            production_type="branded_stock",
            model_id=model.id,
            planned_quantity=1,
            status="packaging",
        )
        db.add(order)
        db.flush()
        department_ids = {
            code: int(department_id)
            for department_id, code in db.query(Department.id, Department.code).filter(
                Department.code.in_(("SEW", "PKG", "STR")),
            )
        }
        work_orders = [
            WorkOrder(
                production_order_id=order.id,
                department_id=department_ids[department_code],
                operation=operation,
                planned_input_qty=1,
                planned_output_qty=1,
                status="completed" if operation == "sewing" else "waiting",
            )
            for operation, department_code in (
                ("sewing", "SEW"),
                ("packaging", "PKG"),
                ("storage_transfer", "STR"),
            )
        ]
        db.add_all(work_orders)
        db.commit()
        return int(work_orders[1].id), [int(batch.id) for batch in stock_batches]


def _usluga_cutting_record(bundle_count: int) -> tuple[int, list[int]]:
    marker = uuid4().hex[:8]
    with TestSessionLocal() as db:
        model = Model(
            code=f"PERF20-U-{marker}",
            name=f"Usluga log growth {marker}",
            product_type="shirt",
            status="approved",
            catalog_scope="usluga",
            factory_code="ECO",
        )
        db.add(model)
        db.flush()
        order = ProductionOrder(
            production_no=f"PERF20-U-PO-{marker}",
            production_type="service_order",
            source_type="usluga",
            model_id=model.id,
            planned_quantity=bundle_count,
            status="cutting",
        )
        db.add(order)
        db.flush()
        cutting_department = db.query(Department).filter(Department.code == "ECT").one()
        work_order = WorkOrder(
            production_order_id=order.id,
            department_id=cutting_department.id,
            operation="cutting",
            planned_input_qty=bundle_count,
            planned_output_qty=bundle_count,
            status="waiting",
        )
        db.add(work_order)
        db.flush()
        record = CuttingRecord(
            work_order_id=work_order.id,
            cutting_batch_no=f"PERF20-U-CUT-{marker}",
            material_name_snapshot="Customer fabric",
            material_role="main",
            approval_status="pending",
            input_quantity=bundle_count,
            input_unit="kg",
            cut_pieces=bundle_count,
            passed_pieces=bundle_count,
            bundle_count=bundle_count,
            total_bundled_quantity=bundle_count,
        )
        db.add(record)
        db.flush()
        bundles = [
            Bundle(
                bundle_no=f"PERF20-U-BND-{marker}-{index:04d}",
                barcode=f"PERF20-U-BC-{marker}-{index:04d}",
                production_order_id=order.id,
                cutting_record_id=record.id,
                model_id=model.id,
                color="natural",
                size="M",
                quantity=1,
                current_department_id=cutting_department.id,
                next_department_id=cutting_department.id,
                sewing_factory_code="ECO",
                status="created",
            )
            for index in range(bundle_count)
        ]
        db.add_all(bundles)
        db.flush()
        db.add_all([
            BundleScanLog(
                bundle_id=bundle.id,
                scan_type="created",
                to_department_id=cutting_department.id,
            )
            for bundle in bundles
        ])
        db.commit()
        return int(record.id), [int(bundle.id) for bundle in bundles]


def _table_select_counts(statements: list[str]) -> Counter:
    names = (
        "business_order_aliases",
        "bundles",
        "bundle_scan_logs",
        "departments",
        "production_batches",
        "production_orders",
        "stock_batches",
        "items",
        "model_bom",
        "material_reservations",
        "system_settings",
    )
    return Counter({
        name: sum(f" {name} " in statement for statement in statements)
        for name in names
    })


@pytest.mark.parametrize("bundle_count", [1, 50, 401])
def test_cutting_record_complete_bundle_query_growth(
    client,
    auth_headers,
    monkeypatch,
    bundle_count,
):
    work_order_id = _cutting_work_order(bundle_count)
    monkeypatch.setattr("app.services.bundles.save_barcode_image", lambda *_args, **_kwargs: None)
    statements: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(" ".join(statement.lower().split()))

    event.listen(test_engine, "before_cursor_execute", capture)
    try:
        response = client.post(
            "/api/cutting/records",
            headers=auth_headers,
            json={
                "work_order_id": work_order_id,
                "input_quantity": 0,
                "input_unit": "kg",
                "cut_pieces": bundle_count,
                "passed_pieces": bundle_count,
                "defective_pieces": 0,
                "waste_quantity": 0,
                "waste_unit": "kg",
                "bundles": [
                    {
                        "color": "navy",
                        "size": "M",
                        "quantity": 1,
                        "count": bundle_count,
                        "sewing_factory": "MIL",
                    },
                ],
            },
        )
    finally:
        event.remove(test_engine, "before_cursor_execute", capture)

    assert response.status_code == 201, response.text
    bundles = response.json()["bundles"]
    assert len(bundles) == bundle_count
    assert [row["id"] for row in bundles] == sorted(row["id"] for row in bundles)
    assert len({row["bundle_no"] for row in bundles}) == bundle_count
    number_suffixes = [int(row["bundle_no"].rsplit("-", 1)[-1]) for row in bundles]
    assert number_suffixes == list(range(number_suffixes[0], number_suffixes[0] + bundle_count))
    counts = _table_select_counts(statements)
    assert len(statements) == 41
    assert counts["departments"] == 6
    assert counts["business_order_aliases"] == 1
    print(
        f"PERF20 cutting bundles={bundle_count}: total={len(statements)} "
        f"tables={dict(counts)}"
    )


@pytest.mark.parametrize("material_count", [1, 50, 401])
def test_cutting_record_complete_material_query_growth(
    client,
    auth_headers,
    material_count,
):
    work_order_id, batch_ids = _cutting_material_work_order(
        material_count,
        reservation_quantity=0.5,
    )
    statements: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(" ".join(statement.lower().split()))

    event.listen(test_engine, "before_cursor_execute", capture)
    try:
        response = client.post(
            "/api/cutting/records",
            headers=auth_headers,
            json={
                "work_order_id": work_order_id,
                "input_quantity": 0,
                "input_unit": "kg",
                "cut_pieces": 0,
                "passed_pieces": 0,
                "defective_pieces": 0,
                "waste_quantity": 0,
                "waste_unit": "kg",
                "materials": [
                    {"stock_batch_id": batch_id, "quantity": 1, "unit": "kg"}
                    for batch_id in batch_ids
                ],
                "bundles": [],
            },
        )
    finally:
        event.remove(test_engine, "before_cursor_execute", capture)

    assert response.status_code == 201, response.text
    assert [row["stock_batch_id"] for row in response.json()["materials"]] == batch_ids
    counts = _table_select_counts(statements)
    assert len(statements) == 30
    assert counts["material_reservations"] == 1
    assert counts["stock_batches"] == 2
    assert counts["items"] == 2
    assert counts["system_settings"] == 1
    with TestSessionLocal() as db:
        quantities = {
            int(batch.id): float(batch.quantity)
            for batch in db.query(StockBatch).filter(StockBatch.id.in_(batch_ids)).all()
        }
        movements = (
            db.query(StockMovement)
            .filter(StockMovement.batch_id.in_(batch_ids))
            .order_by(StockMovement.id)
            .all()
        )
    assert quantities == {batch_id: 1.0 for batch_id in batch_ids}
    assert [int(row.batch_id) for row in movements] == [
        batch_id
        for batch_id in batch_ids
        for _movement in range(2)
    ]
    assert [float(row.quantity) for row in movements] == [0.5] * (2 * material_count)
    print(
        f"PERF20 cutting materials={material_count}: total={len(statements)} "
        f"tables={dict(counts)}"
    )


@pytest.mark.parametrize("bom_count", [1, 50, 401])
def test_packaging_record_complete_bom_query_growth(
    client,
    auth_headers,
    bom_count,
):
    work_order_id, batch_ids = _packaging_work_order(bom_count)
    statements: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(" ".join(statement.lower().split()))

    event.listen(test_engine, "before_cursor_execute", capture)
    try:
        response = client.post(
            "/api/packaging/records",
            headers=auth_headers,
            json={
                "work_order_id": work_order_id,
                "input_qty": 1,
                "packed_qty": 1,
                "damaged_qty": 0,
            },
        )
    finally:
        event.remove(test_engine, "before_cursor_execute", capture)

    assert response.status_code == 201, response.text
    counts = _table_select_counts(statements)
    assert len(statements) == 30
    assert counts["model_bom"] == 1
    assert counts["stock_batches"] == 2
    assert counts["material_reservations"] == 3
    with TestSessionLocal() as db:
        quantities = {
            int(batch.id): float(batch.quantity)
            for batch in db.query(StockBatch).filter(StockBatch.id.in_(batch_ids)).all()
        }
        record_count = db.query(PackagingRecord).filter(
            PackagingRecord.work_order_id == work_order_id,
        ).count()
        movements = (
            db.query(StockMovement)
            .filter(StockMovement.batch_id.in_(batch_ids))
            .order_by(StockMovement.id)
            .all()
        )
    assert quantities == {batch_id: 1.0 for batch_id in batch_ids}
    assert record_count == 1
    assert [int(row.batch_id) for row in movements] == batch_ids
    print(
        f"PERF20 packaging bom={bom_count}: total={len(statements)} "
        f"tables={dict(counts)}"
    )


def test_cutting_material_failure_rolls_back_prior_consumption(client, auth_headers):
    work_order_id, batch_ids = _cutting_material_work_order(2)

    response = client.post(
        "/api/cutting/records",
        headers=auth_headers,
        json={
            "work_order_id": work_order_id,
            "input_quantity": 0,
            "input_unit": "kg",
            "cut_pieces": 0,
            "passed_pieces": 0,
            "defective_pieces": 0,
            "waste_quantity": 0,
            "waste_unit": "kg",
            "materials": [
                {"stock_batch_id": batch_ids[0], "quantity": 1, "unit": "kg"},
                {"stock_batch_id": batch_ids[1], "quantity": 3, "unit": "kg"},
            ],
            "bundles": [],
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"].startswith("Insufficient stock in batch")
    with TestSessionLocal() as db:
        quantities = {
            int(batch.id): float(batch.quantity)
            for batch in db.query(StockBatch).filter(StockBatch.id.in_(batch_ids)).all()
        }
        records = db.query(CuttingRecord).filter(CuttingRecord.work_order_id == work_order_id).count()
        movements = db.query(StockMovement).filter(StockMovement.batch_id.in_(batch_ids)).count()
    assert quantities == {batch_id: 2.0 for batch_id in batch_ids}
    assert records == 0
    assert movements == 0


def test_cutting_material_batching_preserves_reservation_and_input_movement_order(
    client,
    auth_headers,
):
    work_order_id, batch_ids = _cutting_material_work_order(2)
    with TestSessionLocal() as db:
        work_order = db.get(WorkOrder, work_order_id)
        batches = {
            int(batch.id): batch
            for batch in db.query(StockBatch).filter(StockBatch.id.in_(batch_ids)).all()
        }
        reservations = [
            MaterialReservation(
                reservation_no=f"PERF20-CONSUME-{uuid4().hex[:10]}",
                production_order_id=int(work_order.production_order_id),
                item_id=int(batches[batch_id].item_id),
                stock_batch_id=batch_id,
                warehouse_id=int(batches[batch_id].warehouse_id),
                reserved_quantity=quantity,
                consumed_quantity=0,
                released_quantity=0,
                unit="kg",
                status="reserved",
                reservation_type="material",
                source="manual",
            )
            for batch_id, quantity in (
                (batch_ids[0], 0.5),
                (batch_ids[0], 0.5),
                (batch_ids[1], 0.5),
            )
        ]
        db.add_all(reservations)
        db.commit()
        reservation_ids = [int(row.id) for row in reservations]

    response = client.post(
        "/api/cutting/records",
        headers=auth_headers,
        json={
            "work_order_id": work_order_id,
            "input_quantity": 0,
            "input_unit": "kg",
            "cut_pieces": 0,
            "passed_pieces": 0,
            "defective_pieces": 0,
            "waste_quantity": 0,
            "waste_unit": "kg",
            "materials": [
                {"stock_batch_id": batch_ids[1], "quantity": 1, "unit": "kg"},
                {"stock_batch_id": batch_ids[0], "quantity": 1.5, "unit": "kg"},
            ],
            "bundles": [],
        },
    )

    assert response.status_code == 201, response.text
    with TestSessionLocal() as db:
        movements = (
            db.query(StockMovement)
            .filter(StockMovement.batch_id.in_(batch_ids))
            .order_by(StockMovement.id)
            .all()
        )
        refreshed_reservations = (
            db.query(MaterialReservation)
            .filter(MaterialReservation.id.in_(reservation_ids))
            .order_by(MaterialReservation.id)
            .all()
        )
    assert [int(row.batch_id) for row in movements] == [
        batch_ids[1],
        batch_ids[1],
        batch_ids[0],
        batch_ids[0],
        batch_ids[0],
    ]
    assert [float(row.quantity) for row in movements] == [0.5, 0.5, 0.5, 0.5, 0.5]
    assert [row.status for row in refreshed_reservations] == ["consumed", "consumed", "consumed"]


def test_cutting_material_strict_reservation_counts_duplicate_batch_lines_cumulatively():
    work_order_id, batch_ids = _cutting_material_work_order(1, reservation_quantity=1.5)
    batch_id = batch_ids[0]

    with TestSessionLocal() as db:
        work_order = db.get(WorkOrder, work_order_id)
        with pytest.raises(HTTPException, match="Insufficient material reservation for cutting"):
            consume_cutting_materials(
                db,
                production_order_id=int(work_order.production_order_id),
                lines=[
                    {"stock_batch_id": batch_id, "quantity": 1.0, "unit": "kg"},
                    {"stock_batch_id": batch_id, "quantity": 1.0, "unit": "kg"},
                ],
                reference_type="CuttingRecord",
                reference_id=123,
                user_id=None,
                require_full=True,
            )
        db.rollback()

    with TestSessionLocal() as db:
        batch = db.get(StockBatch, batch_id)
        reservation = db.query(MaterialReservation).filter(
            MaterialReservation.stock_batch_id == batch_id,
        ).one()
        movements = db.query(StockMovement).filter(StockMovement.batch_id == batch_id).count()
    assert float(batch.quantity) == 2.0
    assert float(reservation.consumed_quantity) == 0.0
    assert reservation.status == "reserved"
    assert movements == 0


@pytest.mark.parametrize("bundle_count", [1, 50, 401])
def test_usluga_rejection_batches_complete_scan_log_reads(client, bundle_count):
    login = client.post(
        "/api/auth/login-json",
        json={
            "email": "admin@example.com",
            "password": "test-admin-password-123!",
            "factory_code": "ECO",
        },
    )
    assert login.status_code == 200, login.text
    record_id, bundle_ids = _usluga_cutting_record(bundle_count)
    statements: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(" ".join(statement.lower().split()))

    event.listen(test_engine, "before_cursor_execute", capture)
    try:
        response = client.post(
            f"/api/cutting/records/{record_id}/reject-usluga-batch",
            json={"reason": "Synthetic PERF20 rejection"},
        )
    finally:
        event.remove(test_engine, "before_cursor_execute", capture)

    assert response.status_code == 200, response.text
    assert response.json()["deleted_bundle_count"] == bundle_count
    assert len(statements) == 18
    scan_log_reads = [statement for statement in statements if "bundle_scan_logs" in statement]
    assert len(scan_log_reads) == 1
    with TestSessionLocal() as db:
        assert db.query(Bundle).filter(Bundle.id.in_(bundle_ids)).count() == 0
        assert db.query(BundleScanLog).filter(BundleScanLog.bundle_id.in_(bundle_ids)).count() == 0
    print(
        f"PERF20 rejection bundles={bundle_count}: total={len(statements)} "
        f"scan_log_reads={len(scan_log_reads)}"
    )
