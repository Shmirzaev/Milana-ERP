"""Attendance business operations; writes share the supplied transaction."""
import hashlib
import secrets
from collections.abc import Callable

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.libs.dto.people.attendance import ManagedDeviceIn, ManagedDeviceUpdateIn
from app.models.factory_scope_service import selected_factory_code
from app.schemas import AttendanceDevice, User
from app.schemas.people.attendance_persistence import insert_managed_device, update_managed_device


def _connector_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _device_payload(device: AttendanceDevice) -> dict:
    return {
        "id": device.id,
        "device_key": device.device_key,
        "name": device.name,
        "vendor": device.vendor,
        "model": device.model,
        "serial_no": device.serial_no,
        "source_host": device.source_host,
        "certificate_sha256": device.certificate_sha256,
        "managed": bool(device.connector_token_hash),
        "sync_enabled": device.sync_enabled,
        "read_only": device.read_only,
        "reported_person_count": device.reported_person_count,
        "last_seen_at": device.last_seen_at,
        "last_people_sync_at": device.last_people_sync_at,
        "last_event_sync_at": device.last_event_sync_at,
    }


def create_managed_attendance_device(
    payload: ManagedDeviceIn, db: Session, current: User, *, audit: Callable,
):
    factory_code = selected_factory_code(current)
    existing = db.query(AttendanceDevice.id).filter(
        AttendanceDevice.factory_code == factory_code,
        AttendanceDevice.device_key == payload.device_key,
    ).first()
    if existing:
        raise HTTPException(400, "Attendance device key already exists in this factory")
    connector_token = secrets.token_urlsafe(48)
    device = insert_managed_device(db, values=dict(
        factory_code=factory_code,
        device_key=payload.device_key,
        name=payload.name.strip(),
        vendor=payload.vendor,
        source_host=payload.source_host,
        certificate_sha256=payload.certificate_sha256,
        connector_token_hash=_connector_token_hash(connector_token),
        sync_enabled=True,
        configured_by=current.id,
        read_only=True,
    ))
    db.flush()
    audit(
        db,
        current,
        "create",
        "AttendanceDeviceConfig",
        device.id,
        new_value={"factory_code": factory_code, "device_key": device.device_key, "vendor": device.vendor},
    )
    db.commit()
    result = _device_payload(device)
    # The plaintext token is intentionally returned once and never stored.
    result["connector_token"] = connector_token
    return result



def update_managed_attendance_device(device_id: int, payload: ManagedDeviceUpdateIn, db: Session, current: User, *, audit: Callable):
    device = db.query(AttendanceDevice).filter(
        AttendanceDevice.id == device_id,
        AttendanceDevice.factory_code == selected_factory_code(current),
    ).one_or_none()
    if not device:
        raise HTTPException(404, "Attendance device not found")
    changes = {}
    if payload.name is not None:
        changes["name"] = payload.name.strip()
    if payload.sync_enabled is not None:
        changes["sync_enabled"] = payload.sync_enabled
    update_managed_device(db, device=device, changes=changes)
    audit(
        db,
        current,
        "update",
        "AttendanceDeviceConfig",
        device.id,
        new_value={"name": device.name, "sync_enabled": device.sync_enabled},
    )
    db.commit()
    return _device_payload(device)
