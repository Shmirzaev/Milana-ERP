"""Warehouse dispatch selections are shared; manufacturing package access is scoped."""
import pytest
from fastapi import HTTPException

from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.models.packaging_scope_service import require_package_access
from app.schemas import (
    AuditLog, Department, FinishedGoodsStock, Package, PackageItem, Role,
    Shipment, ShipmentPackage, ShipmentScanLog, User,
)
from app.tests.test_open_shipment_allocations import choose, new_shipment, open_pack  # noqa: F401
from app.tests.test_shipment_review import dispatch  # noqa: F401


def actor_headers(factory, permissions, *, super_admin=False):
    with SessionLocal() as db:
        role = Role(name="Quantity scope QA", permissions=permissions)
        db.add(role)
        db.flush()
        department = db.query(Department).filter_by(code="PKG").one()
        user = User(
            name="Quantity scope QA", email="quantity-scope@qa.local", password_hash="unused",
            role_id=role.id, department_id=department.id, factory_code="MIL",
            extra_permissions=[] if super_admin else [f"factory:{factory}:{p}" for p in permissions],
        )
        db.add(user)
        db.commit()
        token = create_access_token(user.id, extra={"factory_code": factory})
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.parametrize("factory", ["MIL", "BST", "ECO"])
@pytest.mark.parametrize("owner", ["PKG", "BPK", "ECP"])
@pytest.mark.parametrize("super_admin", [False, True])
def test_quantity_selection_uses_shipment_permission_across_factories(client, open_pack, factory, owner, super_admin):
    permissions = ["*", "admin.super"] if super_admin else ["storage.shipment"]
    headers = actor_headers(factory, permissions, super_admin=super_admin)
    with SessionLocal() as db:
        db.get(Package, open_pack["package"]).packaging_department_code = owner
        db.commit()

    response = choose(client, headers, open_pack, open_pack["shipment"], 1, 60)
    assert response.status_code == 200, response.text
    assert response.json()["review"]["quantity"] == 2
    reopened = client.get(f'/api/shipments/{open_pack["shipment"]}/preparation', headers=headers)
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["review"]["quantity"] == 2
    with SessionLocal() as db:
        package = db.get(Package, open_pack["package"])
        assert package.packaging_department_code == owner
        assert package.total_quantity == 60 and package.dispatched_quantity == 0
        assert [db.get(PackageItem, iid).quantity for iid in open_pack["items"]] == [30, 30]
        link = db.query(ShipmentPackage).filter_by(shipment_id=open_pack["shipment"]).one()
        assert link.quantity == 2
        assert db.get(Shipment, open_pack["shipment"]).dispatch_snapshot["package_quantities"] == {
            str(package.id): {str(iid): 1 for iid in open_pack["items"]},
        }
        stocks = db.query(FinishedGoodsStock).filter_by(package_id=package.id).all()
        assert sum(row.quantity for row in stocks) == 60
        assert sum(row.available_qty for row in stocks) == 60
        assert sum(row.reserved_qty + row.sold_qty for row in stocks) == 0
        assert db.query(AuditLog).filter_by(action="select_shipment_package_quantity", entity_id=open_pack["shipment"]).count() == 1


@pytest.mark.parametrize("permissions", [[], ["storage.packages"], ["packaging.packages"]])
def test_quantity_selection_requires_shipment_permission_without_writes(client, open_pack, permissions):
    headers = actor_headers("MIL", permissions)
    with SessionLocal() as db:
        before_audits = db.query(AuditLog).count()
    response = choose(client, headers, open_pack, open_pack["shipment"], 1, 60)
    assert response.status_code == 403, response.text
    with SessionLocal() as db:
        assert db.query(ShipmentPackage).filter_by(shipment_id=open_pack["shipment"]).one().quantity == 60
        assert db.get(Shipment, open_pack["shipment"]).dispatch_snapshot is None
        assert db.query(AuditLog).count() == before_audits


def test_cross_factory_selection_still_requires_scan(client, open_pack):
    headers = actor_headers("MIL", ["storage.shipment"])
    with SessionLocal() as db:
        db.get(Package, open_pack["package"]).packaging_department_code = "BPK"
        db.query(ShipmentScanLog).filter_by(shipment_id=open_pack["shipment"]).delete()
        db.commit()
    response = choose(client, headers, open_pack, open_pack["shipment"], 1, 60)
    assert response.status_code == 409, response.text
    with SessionLocal() as db:
        assert db.query(ShipmentPackage).filter_by(shipment_id=open_pack["shipment"]).one().quantity == 60


def test_cross_factory_split_dispatch_preserves_stock_and_packaging_scope(client, open_pack):
    headers = actor_headers("MIL", ["*", "admin.super"], super_admin=True)
    with SessionLocal() as db:
        package = db.get(Package, open_pack["package"])
        package.packaging_department_code = "BPK"
        db.commit()
        actor = db.query(User).filter_by(email="quantity-scope@qa.local").one()
        actor.session_factory_code = "MIL"
        with pytest.raises(HTTPException) as rejected:
            require_package_access(actor, package)
        assert rejected.value.status_code == 403
    assert choose(client, headers, open_pack, open_pack["shipment"], 1, 60).status_code == 200
    second = new_shipment(client, headers)
    scan = client.post(f"/api/shipments/{second}/scan-package", headers=headers, json={"code": "REVIEW-QR"})
    assert scan.status_code == 200 and scan.json()["ok"], scan.text
    assert scan.json()["package_quantity"] == 58
    for sid, quantity in [(open_pack["shipment"], 2), (second, 58)]:
        shipped = client.post(f"/api/shipments/{sid}/ship", headers=headers)
        assert shipped.status_code == 200, shipped.text
        invoice = client.get(f"/api/shipments/{sid}/invoice", headers=headers)
        assert invoice.status_code == 200, invoice.text
        assert invoice.json()["quantity"] == quantity
    with SessionLocal() as db:
        package = db.get(Package, open_pack["package"])
        assert package.total_quantity == package.dispatched_quantity == 60
        assert package.packaging_department_code == "BPK"
        stocks = db.query(FinishedGoodsStock).filter_by(package_id=package.id).all()
        assert sum(row.sold_qty for row in stocks) == 60
        assert sum(row.available_qty + row.reserved_qty for row in stocks) == 0
