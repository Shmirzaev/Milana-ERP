from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event, text

from app.api.routes import shipments as shipment_routes
from app.db.session import SessionLocal
from app.models import Model, Package, ProductionOrder, Shipment, ShipmentPackage, User


def _shipment(package_count: int, *, invalid_index: int | None = None) -> int:
    marker = uuid4().hex[:8]
    with SessionLocal() as db:
        model = Model(code=f"PERF27-M-{marker}", name=f"PERF27 model {marker}", product_type="shirt")
        db.add(model)
        db.flush()
        order = ProductionOrder(
            production_no=f"PERF27-PO-{marker}",
            production_type="branded_stock",
            model_id=model.id,
            status="packaging",
            planned_quantity=package_count,
        )
        db.add(order)
        db.flush()
        shipment = Shipment(
            shipment_no=f"PERF27-{marker}",
            status="created",
            dispatch_snapshot={},
        )
        db.add(shipment)
        db.flush()
        for index in range(package_count):
            package = Package(
                package_no=f"PERF27-PKG-{marker}-{index:04d}",
                barcode=f"PERF27-BC-{marker}-{index:04d}",
                production_order_id=order.id,
                model_id=model.id,
                color="navy",
                total_quantity=1,
                capacity=1,
                status="damaged" if index == invalid_index else "received_in_storage",
            )
            db.add(package)
            db.flush()
            db.add(ShipmentPackage(shipment_id=shipment.id, package_id=package.id, quantity=1))
        db.commit()
        return int(shipment.id)


def _package_selects(bind, callback):
    statements: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        normalized = " ".join(statement.lower().split())
        if normalized.startswith("select") and " from packages " in normalized:
            statements.append(normalized)

    event.listen(bind, "before_cursor_execute", capture)
    try:
        result = callback()
    finally:
        event.remove(bind, "before_cursor_execute", capture)
    return result, statements


@pytest.mark.parametrize("package_count", [1, 50, 401])
def test_ship_verified_packages_reuses_one_locked_package_read(monkeypatch, package_count):
    shipment_id = _shipment(package_count)
    shipped: list[tuple[int, int]] = []
    monkeypatch.setattr(
        shipment_routes,
        "_scan_progress",
        lambda _db, shipment: (
            package_count,
            package_count,
            0,
            True,
            {int(row.package_id) for row in shipment.packages},
            {int(row.package_id) for row in shipment.packages},
        ),
    )
    monkeypatch.setattr(
        shipment_routes,
        "_finished_goods_rows_for_package",
        lambda _db, _package_id: [SimpleNamespace(available_qty=1, reserved_qty=0, sold_qty=0, quantity=1)],
    )
    monkeypatch.setattr(
        shipment_routes,
        "_finished_goods_rows_for_packages",
        lambda _db, package_ids: {
            int(package_id): [SimpleNamespace(available_qty=1, reserved_qty=0, sold_qty=0, quantity=1)]
            for package_id in package_ids
        },
    )
    monkeypatch.setattr(shipment_routes, "freeze_dispatch_document", lambda _db, shipment: setattr(
        shipment, "dispatch_snapshot", {"document": {}}
    ))
    monkeypatch.setattr(
        shipment_routes,
        "ship_package",
        lambda _db, package, user_id: (shipped.append((int(package.id), int(user_id))), setattr(package, "status", "shipped")),
    )

    with SessionLocal() as db:
        shipment = db.get(Shipment, shipment_id)
        current = db.query(User).filter(User.email == "admin@example.com").one()
        (result, package_statements) = _package_selects(
            db.bind,
            lambda: shipment_routes._ship_verified_packages(db, shipment, current),
        )
        assert result == (package_count, package_count)
        assert shipment.status == "shipped"
        assert {db.get(Package, package_id).status for package_id, _ in shipped} == {"shipped"}

    assert len(package_statements) == 1
    assert len(shipped) == package_count
    assert [package_id for package_id, _ in shipped] == sorted(package_id for package_id, _ in shipped)


def test_ship_verified_packages_invalid_middle_preserves_all_packages(monkeypatch):
    shipment_id = _shipment(3, invalid_index=1)
    monkeypatch.setattr(
        shipment_routes,
        "_scan_progress",
        lambda _db, shipment: (
            3,
            3,
            0,
            True,
            {int(row.package_id) for row in shipment.packages},
            {int(row.package_id) for row in shipment.packages},
        ),
    )
    monkeypatch.setattr(
        shipment_routes,
        "_finished_goods_rows_for_package",
        lambda _db, _package_id: [SimpleNamespace(available_qty=1, reserved_qty=0, sold_qty=0, quantity=1)],
    )
    monkeypatch.setattr(
        shipment_routes,
        "_finished_goods_rows_for_packages",
        lambda _db, package_ids: {
            int(package_id): [SimpleNamespace(available_qty=1, reserved_qty=0, sold_qty=0, quantity=1)]
            for package_id in package_ids
        },
    )

    with SessionLocal() as db:
        shipment = db.get(Shipment, shipment_id)
        current = db.query(User).filter(User.email == "admin@example.com").one()
        package_ids = [int(row.package_id) for row in shipment.packages]
        with pytest.raises(HTTPException, match="no longer ready to ship"):
            shipment_routes._ship_verified_packages(db, shipment, current)
        db.rollback()

    with SessionLocal() as db:
        packages = db.query(Package).filter(Package.id.in_(package_ids)).order_by(Package.id).all()
        assert [package.status for package in packages] == ["received_in_storage", "damaged", "received_in_storage"]


def test_ship_verified_packages_refreshes_stale_locked_package_identity(monkeypatch):
    shipment_id = _shipment(1)
    monkeypatch.setattr(
        shipment_routes,
        "_scan_progress",
        lambda _db, shipment: (
            1,
            1,
            0,
            True,
            {int(row.package_id) for row in shipment.packages},
            {int(row.package_id) for row in shipment.packages},
        ),
    )

    with SessionLocal() as db:
        shipment = db.get(Shipment, shipment_id)
        current = db.query(User).filter(User.email == "admin@example.com").one()
        package_id = int(shipment.packages[0].package_id)
        stale_package = db.get(Package, package_id)
        assert stale_package.status == "received_in_storage"
        db.execute(
            text("UPDATE packages SET status = 'damaged' WHERE id = :package_id"),
            {"package_id": package_id},
        )
        assert stale_package.status == "received_in_storage"

        with pytest.raises(HTTPException, match="no longer ready to ship"):
            shipment_routes._ship_verified_packages(db, shipment, current)
        assert stale_package.status == "damaged"
        db.rollback()
