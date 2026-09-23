from uuid import uuid4

import pytest
from sqlalchemy import event

from app.db.session import SessionLocal
from app.models import Model, Package, ProductionOrder
from app.services import packages as package_service


def _bulk_order() -> tuple[int, int]:
    marker = uuid4().hex[:8]
    with SessionLocal() as db:
        model = Model(
            code=f"PERF09-LOCK-{marker}",
            name=f"PERF09 locked order {marker}",
            product_type="shirt",
        )
        db.add(model)
        db.flush()
        order = ProductionOrder(
            production_no=f"PERF09-LOCK-PO-{marker}",
            production_type="branded_stock",
            model_id=model.id,
            status="packaging",
            planned_quantity=500,
        )
        db.add(order)
        db.commit()
        return int(order.id), int(model.id)


@pytest.mark.parametrize("package_count", [1, 50, 401])
def test_bulk_package_creation_reuses_locked_production_order(monkeypatch, package_count):
    order_id, model_id = _bulk_order()
    monkeypatch.setattr(package_service, "_enforce_packaged_quantity_available", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(package_service, "save_qr_image", lambda _payload, package_no: f"/test/{package_no}.png")
    monkeypatch.setattr(package_service, "save_barcode_image", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(package_service, "sync_production_order_status", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(package_service, "notify_department", lambda *_args, **_kwargs: None)
    order_selects: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        normalized = " ".join(statement.lower().split())
        if normalized.startswith("select") and " from production_orders " in normalized:
            order_selects.append(normalized)

    with SessionLocal() as db:
        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            packages = package_service.create_packages_bulk(
                db,
                count=package_count,
                production_order_id=order_id,
                model_id=model_id,
                color="navy",
                items=[{"model_id": model_id, "color": "navy", "size": "M", "quantity": 1}],
                capacity=1,
                packaging_department_code="PKG",
            )
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

        persisted = db.query(Package).filter(Package.production_order_id == order_id).all()

    assert len(packages) == package_count
    assert len(persisted) == package_count
    assert all(package.status == "packed" for package in packages)
    assert len(order_selects) == 1
