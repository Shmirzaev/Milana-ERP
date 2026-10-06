from uuid import uuid4

import pytest
from sqlalchemy import event

from app.db.session import SessionLocal
from app.models import (
    FinishedGoodsStock,
    Item,
    Model,
    ModelBOM,
    Package,
    PackageItem,
    ProductionBatch,
    ProductionOrder,
    StockBatch,
    Warehouse,
)
from app.services import packages as package_service


def _bulk_order() -> tuple[int, int, float]:
    marker = uuid4().hex[:8]
    with SessionLocal() as db:
        warehouse = db.query(Warehouse).first()
        model = Model(
            code=f"PERF09-BULK-{marker}",
            name=f"PERF09 bulk cost {marker}",
            product_type="shirt",
        )
        material = Item(
            sku=f"PERF09-BULK-I-{marker}",
            name=f"PERF09 bulk material {marker}",
            category="fabric",
            unit="kg",
        )
        db.add_all([model, material])
        db.flush()
        db.add_all(
            [
                StockBatch(
                    item_id=material.id,
                    batch_no=f"PERF09-BULK-OLD-{marker}",
                    quantity=1,
                    unit="kg",
                    warehouse_id=warehouse.id,
                    cost_per_unit=7,
                ),
                StockBatch(
                    item_id=material.id,
                    batch_no=f"PERF09-BULK-NEW-{marker}",
                    quantity=1,
                    unit="kg",
                    warehouse_id=warehouse.id,
                    cost_per_unit=12.5,
                ),
                ModelBOM(
                    model_id=model.id,
                    item_id=material.id,
                    quantity_per_piece=2,
                    unit="kg",
                    waste_percent=20,
                ),
            ]
        )
        order = ProductionOrder(
            production_no=f"PERF09-BULK-PO-{marker}",
            production_type="branded_stock",
            model_id=model.id,
            status="packaging",
            planned_quantity=500,
        )
        db.add(order)
        db.commit()
        return int(order.id), int(model.id), 30.0


def _stub_unrelated_bulk_work(monkeypatch, *, stub_sync: bool = True) -> None:
    monkeypatch.setattr(
        package_service,
        "_enforce_packaged_quantity_available",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        package_service,
        "save_qr_image",
        lambda _payload, package_no: f"/test/{package_no}.png",
    )
    monkeypatch.setattr(package_service, "save_barcode_image", lambda *_args, **_kwargs: None)
    if stub_sync:
        monkeypatch.setattr(package_service, "sync_production_order_status", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(package_service, "notify_department", lambda *_args, **_kwargs: None)


@pytest.mark.parametrize("package_count", [1, 50, 401])
def test_bulk_package_workflow_status_reads_are_constant(monkeypatch, package_count):
    order_id, model_id, _expected_cost = _bulk_order()
    _stub_unrelated_bulk_work(monkeypatch, stub_sync=False)
    work_order_selects: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        normalized = " ".join(statement.lower().split())
        if normalized.startswith("select") and " from work_orders " in normalized:
            work_order_selects.append(normalized)

    with SessionLocal() as db:
        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            packages = package_service.create_packages_bulk(
                db,
                count=package_count,
                production_order_id=order_id,
                model_id=model_id,
                color="navy",
                items=[
                    {
                        "model_id": model_id,
                        "color": "navy",
                        "size": "M",
                        "quantity": 1,
                    }
                ],
                capacity=1,
                packaging_department_code="PKG",
            )
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

        assert len(packages) == package_count
        assert [int(package.id) for package in packages] == sorted(int(package.id) for package in packages)
        assert {package.status for package in packages} == {"packed"}
        assert db.get(ProductionOrder, order_id).status == "planning"

    assert len(work_order_selects) == 1


@pytest.mark.parametrize("package_count", [1, 50, 401])
def test_bulk_package_cost_reads_are_bounded(monkeypatch, package_count):
    order_id, model_id, expected_cost = _bulk_order()
    _stub_unrelated_bulk_work(monkeypatch)
    cost_selects: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        normalized = " ".join(statement.lower().split())
        if normalized.startswith("select") and (
            " from model_bom " in normalized or " from stock_batches " in normalized
        ):
            cost_selects.append(normalized)

    with SessionLocal() as db:
        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            packages = package_service.create_packages_bulk(
                db,
                count=package_count,
                production_order_id=order_id,
                model_id=model_id,
                color="navy",
                items=[
                    {
                        "model_id": model_id,
                        "color": "navy",
                        "size": "M",
                        "quantity": 1,
                    }
                ],
                capacity=1,
                packaging_department_code="PKG",
            )
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

        stock = (
            db.query(FinishedGoodsStock)
            .filter(FinishedGoodsStock.package_id.in_([package.id for package in packages]))
            .order_by(FinishedGoodsStock.package_id)
            .all()
        )

    assert len(packages) == package_count
    assert len(cost_selects) == 2
    assert sum(" from model_bom " in statement for statement in cost_selects) == 1
    assert sum(" from stock_batches " in statement for statement in cost_selects) == 1
    assert [float(row.cost_per_piece) for row in stock] == [expected_cost] * package_count


@pytest.mark.parametrize("package_count", [1, 50, 401])
def test_bulk_package_batch_presence_read_is_reused(monkeypatch, package_count):
    order_id, model_id, _expected_cost = _bulk_order()
    _stub_unrelated_bulk_work(monkeypatch)
    batch_presence_selects: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        normalized = " ".join(statement.lower().split())
        if normalized.startswith("select") and " from production_batches " in normalized:
            batch_presence_selects.append(normalized)

    with SessionLocal() as db:
        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            packages = package_service.create_packages_bulk(
                db,
                count=package_count,
                production_order_id=order_id,
                model_id=model_id,
                color="navy",
                items=[
                    {
                        "model_id": model_id,
                        "color": "navy",
                        "size": "M",
                        "quantity": 1,
                    }
                ],
                capacity=1,
                packaging_department_code="PKG",
            )
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    assert len(packages) == package_count
    assert len(batch_presence_selects) == 1


@pytest.mark.parametrize("package_count", [1, 50, 401])
def test_bulk_batch_membership_read_is_reused(monkeypatch, package_count):
    order_id, model_id, _expected_cost = _bulk_order()
    with SessionLocal() as db:
        batch = ProductionBatch(
            production_order_id=order_id,
            batch_no=f"PERF09-BULK-B-{uuid4().hex[:8]}",
            batch_index=1,
            planned_quantity=package_count,
        )
        db.add(batch)
        db.commit()
        batch_id = int(batch.id)

    _stub_unrelated_bulk_work(monkeypatch)
    batch_selects: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        normalized = " ".join(statement.lower().split())
        if normalized.startswith("select") and " from production_batches " in normalized:
            batch_selects.append(normalized)

    with SessionLocal() as db:
        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            packages = package_service.create_packages_bulk(
                db,
                count=package_count,
                production_order_id=order_id,
                production_batch_id=batch_id,
                model_id=model_id,
                color="navy",
                items=[{"model_id": model_id, "color": "navy", "size": "M", "quantity": 1}],
                capacity=1,
                packaging_department_code="PKG",
            )
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    presence_reads = [
        statement
        for statement in batch_selects
        if "production_batches.production_order_id =" in statement
        and "production_batches.id in" not in statement
    ]
    membership_reads = [statement for statement in batch_selects if "production_batches.id in" in statement]
    assert len(packages) == package_count
    assert len(presence_reads) == 1
    assert len(membership_reads) == 1


def test_bulk_cost_reuse_preserves_order_weights_and_item_rows(monkeypatch):
    order_id, model_id, expected_cost = _bulk_order()
    _stub_unrelated_bulk_work(monkeypatch)

    with SessionLocal() as db:
        packages = package_service.create_packages_bulk(
            db,
            count=3,
            production_order_id=order_id,
            model_id=model_id,
            color="navy",
            items=[
                {
                    "model_id": model_id,
                    "color": "navy",
                    "size": "M",
                    "quantity": 1,
                }
            ],
            capacity=1,
            weight_kg_values=[1.1, 1.2, 1.3],
            packaging_department_code="PKG",
        )
        package_ids = [int(package.id) for package in packages]
        items = (
            db.query(PackageItem)
            .filter(PackageItem.package_id.in_(package_ids))
            .order_by(PackageItem.package_id)
            .all()
        )
        stock = (
            db.query(FinishedGoodsStock)
            .filter(FinishedGoodsStock.package_id.in_(package_ids))
            .order_by(FinishedGoodsStock.package_id)
            .all()
        )

    assert package_ids == sorted(package_ids)
    assert [float(package.weight_kg) for package in packages] == [1.1, 1.2, 1.3]
    assert [(row.color, row.size, row.quantity) for row in items] == [
        ("navy", "M", 1),
        ("navy", "M", 1),
        ("navy", "M", 1),
    ]
    assert [float(row.cost_per_piece) for row in stock] == [expected_cost] * 3


def test_bulk_creation_failure_rolls_back_cached_cost_work(monkeypatch):
    order_id, model_id, _expected_cost = _bulk_order()
    _stub_unrelated_bulk_work(monkeypatch, stub_sync=False)
    calls = 0

    def fail_second_qr(_payload, package_no):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("synthetic QR failure")
        return f"/test/{package_no}.png"

    monkeypatch.setattr(package_service, "save_qr_image", fail_second_qr)

    with SessionLocal() as db:
        with pytest.raises(RuntimeError, match="synthetic QR failure"):
            package_service.create_packages_bulk(
                db,
                count=3,
                production_order_id=order_id,
                model_id=model_id,
                color="navy",
                items=[
                    {
                        "model_id": model_id,
                        "color": "navy",
                        "size": "M",
                        "quantity": 1,
                    }
                ],
                capacity=1,
                packaging_department_code="PKG",
            )
        db.rollback()

    with SessionLocal() as db:
        assert db.get(ProductionOrder, order_id).status == "packaging"
        assert db.query(Package).filter(Package.production_order_id == order_id).count() == 0
        assert (
            db.query(FinishedGoodsStock)
            .filter(FinishedGoodsStock.production_order_id == order_id)
            .count()
            == 0
        )


def test_bulk_package_endpoint_still_requires_authentication(client):
    response = client.post(
        "/api/packages/bulk",
        json={
            "count": 1,
            "production_order_id": 1,
            "model_id": 1,
            "color": "navy",
            "items": [
                {
                    "model_id": 1,
                    "color": "navy",
                    "size": "M",
                    "quantity": 1,
                }
            ],
        },
    )

    assert response.status_code == 401
