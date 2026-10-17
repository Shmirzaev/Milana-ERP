from datetime import datetime, timezone

import pytest

from app.db.session import SessionLocal
from app.models import Customer, Package, Shipment, ShipmentPackage, ShipmentScanLog, User
from app.tests.test_manual_pack_dispatch import receive, shipment
from app.tests.test_package_workflows import warehouse, package_qr  # noqa: F401
from app.tests.test_shipment_review import dispatch  # noqa: F401


def scan(client, headers, sid, pid, **kwargs):
    response = client.post(f"/api/shipments/{sid}/scan-package", headers=headers,
                           json={"code": package_qr(pid)}, **kwargs)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("state", ["same", "other", "shipped", "delivered"])
def test_repeat_scan_reports_original_customer_actor_and_time(client, warehouse, auth_headers, state):
    run = receive(client, warehouse, (7,))
    pid = run["package_ids"][0]
    sid = shipment(client, warehouse)
    first = scan(client, warehouse, sid, pid)
    assert first["sign"] == "success" and first["previous_scan"] is None
    assert first["package_quantity"] == 7
    with SessionLocal() as db:
        original = db.query(ShipmentScanLog).filter_by(shipment_id=sid, scan_result="matched").one()
        original.scanned_at = datetime(2026, 10, 14, 3, 4, 5, tzinfo=timezone.utc)
        actor = db.get(User, original.scanned_by).name
        sh = db.get(Shipment, sid)
        expected_no = sh.shipment_no
        customer = db.get(Customer, sh.customer_id).name
        db.commit()
    target = sid if state == "same" else shipment(client, warehouse)
    if state in ("shipped", "delivered"):
        response = client.post(f"/api/shipments/{sid}/ship", headers=warehouse)
        assert response.status_code == 200, response.text
        if state == "delivered":
            assert client.post(f"/api/shipments/{sid}/deliver", headers=warehouse).status_code == 200
    # Another operator's rescan must still show the first operator/time.
    for _ in range(2):
        repeated = scan(client, auth_headers, target, pid)
        assert repeated["sign"] == ("warning" if state == "same" else "error")
        assert repeated["previous_scan"] == {
            "shipment_no": expected_no, "customer_name": customer,
            "scanned_by_name": actor, "scanned_at": "2026-10-14T03:04:05Z",
        }
        assert repeated["scanned_count"] == (1 if state == "same" else 0)
    with SessionLocal() as db:
        assert db.query(ShipmentPackage).filter_by(package_id=pid).count() == 1
        assert db.query(ShipmentScanLog).filter_by(package_id=pid, scan_result="matched").count() == 1


def test_detach_rescan_and_return_use_current_original_scan(client, warehouse):
    pid = receive(client, warehouse, (7,))["package_ids"][0]
    sid = shipment(client, warehouse)
    scan(client, warehouse, sid, pid)
    url = f"/api/shipments/{sid}"
    removed = client.post(url + f"/packages/{pid}/remove", headers=warehouse, json={"reason": "Reselect pack"})
    assert removed.status_code == 200, removed.text
    assert scan(client, warehouse, sid, pid)["previous_scan"] is None
    with SessionLocal() as db:
        latest = db.query(ShipmentScanLog).filter_by(shipment_id=sid, scan_result="matched").order_by(ShipmentScanLog.id.desc()).first()
        latest.scanned_at = datetime(2026, 10, 14, 5, 6, 7, tzinfo=timezone.utc)
        db.commit()
    shipped = client.post(url + "/ship", headers=warehouse)
    assert shipped.status_code == 200, shipped.text
    returned = client.post(url + "/reopen", headers=warehouse, json={
        "reason": "Returned packages", "packages_returned": True,
        "expected_shipped_at": shipped.json()["shipped_at"],
    })
    assert returned.status_code == 200, returned.text
    repeated = scan(client, warehouse, sid, pid)
    assert repeated["sign"] == "warning"
    assert repeated["previous_scan"]["scanned_at"] == "2026-10-14T05:06:07Z"


def test_sales_customer_fallback_missing_actor_and_scan_permissions(client, auth_headers, dispatch):
    sid, pid = dispatch["shipment"], dispatch["package"]
    with SessionLocal() as db:
        db.get(Shipment, sid).customer_id = None
        db.commit()
    result = scan(client, auth_headers, sid, pid)
    assert result["previous_scan"]["customer_name"] == "<script>alert(1)</script>"
    assert result["previous_scan"]["scanned_by_name"] is None
    url = f"/api/shipments/{sid}/scan-package"
    assert client.post(url, json={"code": package_qr(pid)}).status_code == 401
    token = client.post("/api/auth/token", data={"username": "planning@example.com", "password": "demo12345"})
    viewer = {"Authorization": "Bearer " + token.json()["access_token"]}
    assert client.post(url, headers=viewer, json={"code": package_qr(pid)}).status_code == 403


@pytest.mark.parametrize("invalid", ["detached", "cancelled", "deleted", "unlinked", "not_found"])
def test_obsolete_or_failed_history_is_not_reported(client, auth_headers, dispatch, invalid):
    sid, pid = dispatch["shipment"], dispatch["package"]
    with SessionLocal() as db:
        if invalid == "detached":
            db.add(ShipmentScanLog(shipment_id=sid, package_id=pid, scanned_code="old", scan_result="detached"))
        elif invalid == "cancelled":
            db.get(Shipment, sid).status = "cancelled"
        elif invalid == "deleted":
            db.get(Shipment, sid).deleted_at = datetime.now(timezone.utc)
        elif invalid == "unlinked":
            db.query(ShipmentPackage).filter_by(shipment_id=sid).delete()
        else:
            db.query(ShipmentScanLog).filter_by(shipment_id=sid).one().scan_result = "not_found"
        db.get(Package, pid).status = "shipped"
        db.commit()
    target = shipment(client, auth_headers)
    result = scan(client, auth_headers, target, pid)
    assert result["sign"] == "error" and result["previous_scan"] is None
