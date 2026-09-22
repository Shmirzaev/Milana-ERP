from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.db.session import SessionLocal
from app.models import (
    AuditLog,
    Department,
    LegacyStockReceipt,
    Model,
    Notification,
    Package,
    PackageChangeRequest,
    PackageItem,
    PackagingRecord,
    ProductionOrder,
    WorkOrder,
)
from app.services.packages import create_package


def _package(*, status: str = "packed", package_type: str = "bag") -> int:
    with SessionLocal() as db:
        suffix = uuid4().hex[:8]
        model = db.query(Model).filter(Model.code == "T-SHIRT-001").one()
        receipt = LegacyStockReceipt(
            source_system="TEST",
            source_warehouse_id="package-type-validation",
            source_record_id=suffix,
            source_checksum="0" * 64,
            source_payload={"test": True},
        )
        db.add(receipt)
        db.flush()
        package = Package(
            package_no=f"TYPE-{suffix}",
            barcode=f"TYPE-{suffix}",
            legacy_receipt_id=receipt.id,
            model_id=model.id,
            color="white",
            package_type=package_type,
            total_quantity=2,
            capacity=60,
            status=status,
        )
        db.add(package)
        db.flush()
        db.add(PackageItem(
            package_id=package.id,
            model_id=model.id,
            color="white",
            size=model.sizes[0].size,
            quantity=2,
        ))
        db.commit()
        return int(package.id)


def _edit_request(package_type: str | None = None) -> dict:
    payload = {}
    if package_type is not None:
        payload["package_type"] = package_type
    return {"request_type": "edit", "reason": "Package type correction", "payload": payload}


def _production_package_context() -> dict:
    with SessionLocal() as db:
        suffix = uuid4().hex[:8]
        model = db.query(Model).filter(Model.code == "T-SHIRT-001").one()
        department_id = db.query(Department.id).filter(Department.code == "PKG").scalar()
        order = ProductionOrder(
            production_no=f"TYPE-PO-{suffix}",
            production_type="branded_stock",
            model_id=model.id,
            planned_quantity=20,
        )
        db.add(order)
        db.flush()
        work_order = WorkOrder(
            production_order_id=order.id,
            department_id=department_id,
            operation="packaging",
            planned_input_qty=20,
            planned_output_qty=20,
            passed_qty=20,
            status="in_progress",
        )
        db.add(work_order)
        db.flush()
        db.add(PackagingRecord(work_order_id=work_order.id, input_qty=20, packed_qty=20))
        db.commit()
        return {
            "production_order_id": int(order.id),
            "model_id": int(model.id),
            "items": [{
                "model_id": int(model.id),
                "color": "white",
                "size": model.sizes[0].size,
                "quantity": 2,
            }],
        }


@pytest.mark.parametrize(
    ("package_type", "expected"),
    [(None, "bag"), ("bag", "bag"), ("box", "box"), ("legacy_stock", "legacy_stock")],
)
def test_create_package_accepts_default_and_every_existing_type(package_type, expected):
    context = _production_package_context()
    kwargs = {
        **context,
        "color": "white",
        "packaging_department_code": "PKG",
        "_sync_production": False,
    }
    if package_type is not None:
        kwargs["package_type"] = package_type

    with SessionLocal() as db:
        package = create_package(db, **kwargs)

        assert package.package_type == expected
        assert db.query(PackageItem).filter_by(package_id=package.id).count() == 1


def test_create_package_invalid_type_has_no_package_item_or_audit_side_effects():
    context = _production_package_context()
    with SessionLocal() as db:
        before = (
            db.query(Package).count(),
            db.query(PackageItem).count(),
            db.query(AuditLog).count(),
        )

        with pytest.raises(HTTPException) as raised:
            create_package(
                db,
                **context,
                color="white",
                package_type="crate",
                packaging_department_code="PKG",
                _sync_production=False,
            )

        assert (raised.value.status_code, raised.value.detail) == (400, "Invalid package_type")
        assert (
            db.query(Package).count(),
            db.query(PackageItem).count(),
            db.query(AuditLog).count(),
        ) == before


@pytest.mark.parametrize("package_type", ["bag", "box", "legacy_stock"])
def test_package_edit_request_accepts_every_existing_package_type(client, auth_headers, package_type):
    package_id = _package()

    response = client.post(
        f"/api/packages/{package_id}/change-requests",
        headers=auth_headers,
        json=_edit_request(package_type),
    )

    assert response.status_code == 201, response.text
    assert response.json()["payload_json"]["package_type"] == package_type


def test_package_edit_request_keeps_omitted_type_compatibility(client, auth_headers):
    package_id = _package(package_type="box")

    response = client.post(
        f"/api/packages/{package_id}/change-requests",
        headers=auth_headers,
        json=_edit_request(),
    )

    assert response.status_code == 201, response.text
    assert response.json()["payload_json"]["package_type"] == "box"


def test_invalid_package_type_creates_no_request_audit_or_notification(client, auth_headers):
    package_id = _package()
    with SessionLocal() as db:
        before = (
            db.query(PackageChangeRequest).count(),
            db.query(AuditLog).count(),
            db.query(Notification).count(),
        )

    response = client.post(
        f"/api/packages/{package_id}/change-requests",
        headers=auth_headers,
        json=_edit_request("crate"),
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid package_type"}
    with SessionLocal() as db:
        assert (
            db.query(PackageChangeRequest).count(),
            db.query(AuditLog).count(),
            db.query(Notification).count(),
        ) == before
        assert db.get(Package, package_id).package_type == "bag"


def test_missing_package_precedes_package_type_validation(client, auth_headers):
    response = client.post(
        "/api/packages/2147483647/change-requests",
        headers=auth_headers,
        json=_edit_request("crate"),
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Package not found"}


def test_package_business_state_precedes_package_type_validation(client, auth_headers):
    package_id = _package(status="reserved")

    response = client.post(
        f"/api/packages/{package_id}/change-requests",
        headers=auth_headers,
        json=_edit_request("crate"),
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Package in status 'reserved' cannot be edited or deleted"}


def test_authentication_precedes_package_type_validation(client):
    response = client.post(
        "/api/packages/2147483647/change-requests",
        json=_edit_request("crate"),
    )

    assert response.status_code == 401


def test_permission_denial_precedes_package_type_validation(client):
    package_id = _package()
    login = client.post(
        "/api/auth/token",
        data={"username": "planning@example.com", "password": "demo12345"},
    )
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    response = client.post(
        f"/api/packages/{package_id}/change-requests",
        headers=headers,
        json=_edit_request("crate"),
    )

    assert response.status_code == 403
    with SessionLocal() as db:
        assert db.query(PackageChangeRequest).count() == 0
