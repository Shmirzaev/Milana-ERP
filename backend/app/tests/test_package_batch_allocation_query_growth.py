from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from app.db.session import SessionLocal
from app.models import Model, Package, PackageBatchAllocation, ProductionBatch, ProductionOrder
from app.services import packages as package_service


def _batched_order(quantity: int) -> tuple[int, int, int]:
    marker = uuid4().hex[:8]
    with SessionLocal() as db:
        model = Model(code=f"PERF09-A-{marker}", name=f"PERF09 allocations {marker}", product_type="shirt")
        db.add(model)
        db.flush()
        order = ProductionOrder(
            production_no=f"PERF09-A-PO-{marker}", production_type="branded_stock",
            model_id=model.id, status="packaging", planned_quantity=quantity,
        )
        db.add(order)
        db.flush()
        batch = ProductionBatch(
            production_order_id=order.id, batch_no=f"PERF09-A-B-{marker}",
            batch_index=1, planned_quantity=quantity,
        )
        db.add(batch)
        db.commit()
        return int(order.id), int(model.id), int(batch.id)


def _production_batch_selects(bind, callback):
    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        normalized = " ".join(statement.lower().split())
        if normalized.startswith("select") and " from production_batches " in normalized:
            statements.append(normalized)

    event.listen(bind, "before_cursor_execute", capture)
    try:
        result = callback()
    finally:
        event.remove(bind, "before_cursor_execute", capture)
    return result, statements


@pytest.mark.parametrize("allocation_count", [1, 50, 401])
def test_create_package_reuses_duplicate_batch_existence_read(monkeypatch, allocation_count):
    order_id, model_id, batch_id = _batched_order(allocation_count)
    monkeypatch.setattr(package_service, "_enforce_packaged_quantity_available", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(package_service, "_compute_cost", lambda *_args, **_kwargs: 0.0)
    monkeypatch.setattr(package_service, "save_qr_image", lambda *_args, **_kwargs: "/test/qr.png")
    monkeypatch.setattr(package_service, "save_barcode_image", lambda *_args, **_kwargs: "/test/barcode.png")
    monkeypatch.setattr(package_service, "sync_production_order_status", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(package_service, "notify_department", lambda *_args, **_kwargs: None)

    with SessionLocal() as db:
        package, statements = _production_batch_selects(
            db.bind,
            lambda: package_service.create_package(
                db,
                production_order_id=order_id,
                model_id=model_id,
                color="navy",
                items=[{"model_id": model_id, "color": "navy", "size": "M", "quantity": allocation_count}],
                batch_allocations=[
                    {"production_batch_id": batch_id, "quantity": 1}
                    for _ in range(allocation_count)
                ],
                capacity=allocation_count,
                packaging_department_code="PKG",
            ),
        )
        allocations = db.query(PackageBatchAllocation).filter_by(package_id=package.id).all()

    assert len(statements) == 2
    assert len(allocations) == 1
    assert allocations[0].production_batch_id == batch_id
    assert allocations[0].quantity == allocation_count


def test_missing_first_batch_keeps_error_precedence_and_rolls_back(monkeypatch):
    order_id, model_id, _ = _batched_order(2)
    monkeypatch.setattr(package_service, "_enforce_packaged_quantity_available", lambda *_args, **_kwargs: None)

    with SessionLocal() as db:
        with pytest.raises(HTTPException) as exc_info:
            package_service.create_package(
                db,
                production_order_id=order_id,
                model_id=model_id,
                color="navy",
                items=[{"model_id": model_id, "color": "navy", "size": "M", "quantity": 2}],
                batch_allocations=[
                    {"production_batch_id": 2_147_483_647, "quantity": 1},
                    {"production_batch_id": "invalid", "quantity": 1},
                ],
                capacity=2,
                packaging_department_code="PKG",
            )
        assert exc_info.value.status_code == 404
        db.rollback()

    with SessionLocal() as db:
        assert db.query(Package).filter_by(production_order_id=order_id).count() == 0
