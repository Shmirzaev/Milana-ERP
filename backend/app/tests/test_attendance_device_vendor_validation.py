import hashlib
from uuid import uuid4

import pytest

from app.db.session import SessionLocal
from app.models import AttendanceDevice, AttendanceEvent, AttendancePerson


INTEGRATION_HEADERS = {"X-Attendance-Token": "test-attendance-token"}


def _snapshot(*, vendor: str | None = None, device_key: str | None = None, people: list | None = None) -> dict:
    device = {
        "device_key": device_key or f"vendor-{uuid4().hex[:8]}",
        "name": "Vendor validation device",
        "reported_person_count": len(people or []),
    }
    if vendor is not None:
        device["vendor"] = vendor
    return {"device": device, "people": people or [], "full_snapshot": True}


@pytest.mark.parametrize("vendor", ["Hikvision", "Dahua"])
def test_attendance_import_accepts_every_device_vendor(client, vendor):
    payload = _snapshot(vendor=vendor)

    response = client.post(
        "/api/attendance/integration/people",
        headers=INTEGRATION_HEADERS,
        json=payload,
    )

    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        device = db.query(AttendanceDevice).filter_by(device_key=payload["device"]["device_key"]).one()
        assert device.vendor == vendor


def test_attendance_import_keeps_omitted_vendor_compatibility(client):
    payload = _snapshot()

    response = client.post(
        "/api/attendance/integration/people",
        headers=INTEGRATION_HEADERS,
        json=payload,
    )

    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        device = db.query(AttendanceDevice).filter_by(device_key=payload["device"]["device_key"]).one()
        assert device.vendor == "Hikvision"


def test_invalid_attendance_vendor_creates_no_device_person_or_event(client):
    with SessionLocal() as db:
        before = (
            db.query(AttendanceDevice).count(),
            db.query(AttendancePerson).count(),
            db.query(AttendanceEvent).count(),
        )

    response = client.post(
        "/api/attendance/integration/people",
        headers=INTEGRATION_HEADERS,
        json=_snapshot(vendor="UnknownVendor"),
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid attendance device vendor"}
    with SessionLocal() as db:
        assert (
            db.query(AttendanceDevice).count(),
            db.query(AttendancePerson).count(),
            db.query(AttendanceEvent).count(),
        ) == before


def test_integration_authentication_precedes_vendor_validation(client):
    response = client.post(
        "/api/attendance/integration/people",
        headers={"X-Attendance-Token": "invalid-token"},
        json=_snapshot(vendor="UnknownVendor"),
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid attendance integration credentials"}


def test_connector_device_identity_precedes_vendor_validation(client):
    token = f"connector-{uuid4().hex}"
    with SessionLocal() as db:
        device = AttendanceDevice(
            factory_code="MIL",
            device_key="registered-device",
            name="Registered device",
            vendor="Hikvision",
            connector_token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
            sync_enabled=True,
        )
        db.add(device)
        db.commit()

    response = client.post(
        "/api/attendance/integration/people",
        headers={"X-Attendance-Token": token},
        json=_snapshot(vendor="UnknownVendor", device_key="different-device"),
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Connector token does not belong to this attendance device"}


def test_snapshot_business_validation_precedes_vendor_validation(client):
    duplicated_person = {"external_person_id": "100", "full_name": "Duplicate Person"}
    payload = _snapshot(vendor="UnknownVendor", people=[duplicated_person, duplicated_person])

    response = client.post(
        "/api/attendance/integration/people",
        headers=INTEGRATION_HEADERS,
        json=payload,
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Duplicate person ID in snapshot: 100"}
    with SessionLocal() as db:
        assert db.query(AttendanceDevice).count() == 0
