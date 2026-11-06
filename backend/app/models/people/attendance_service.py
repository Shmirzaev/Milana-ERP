"""Attendance business operations; writes share the supplied transaction."""
import hashlib
import secrets
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.dt import as_utc, utcnow

from app.libs.dto.people.attendance import DeviceIn, ManagedDeviceIn, ManagedDeviceUpdateIn, PeopleSnapshotIn
from app.models.factory_scope_service import normalize_factory_code, selected_factory_code
from app.schemas import AttendanceDevice, AttendancePerson, SystemSetting, User
from app.schemas.people.attendance_persistence import (
    insert_managed_device, update_managed_device, insert_attendance_person,
    update_attendance_person, mark_other_people_absent, insert_source_checkpoint,
    update_source_checkpoint,
)


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


def rotate_attendance_device_token(device_id: int, db: Session, current: User, *, audit: Callable):
    device = db.query(AttendanceDevice).filter(
        AttendanceDevice.id == device_id,
        AttendanceDevice.factory_code == selected_factory_code(current),
    ).one_or_none()
    if not device:
        raise HTTPException(404, "Attendance device not found")
    connector_token = secrets.token_urlsafe(48)
    update_managed_device(db, device=device, changes={"connector_token_hash": _connector_token_hash(connector_token), "configured_by": current.id})
    audit(db, current, "rotate_connector_token", "AttendanceDeviceConfig", device.id)
    db.commit()
    result = _device_payload(device)
    result["connector_token"] = connector_token
    return result


ATTENDANCE_IMPORT_LOCK_NAMESPACE = 1096043342
ATTENDANCE_SOURCE_SETTING_PREFIX = "att_src:"


def _integration_factory() -> str:
    return normalize_factory_code(settings.ATTENDANCE_INTEGRATION_FACTORY_CODE, default="MIL")


def _lock_attendance_import(db: Session, factory_code: str, device_key: str) -> None:
    if db.get_bind().dialect.name == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(:namespace, hashtext(:resource))"),
            {
                "namespace": ATTENDANCE_IMPORT_LOCK_NAMESPACE,
                "resource": f"{factory_code}:{device_key}",
            },
        )


def _source_setting_key(factory_code: str, device_key: str) -> str:
    identity = f"{factory_code}:{device_key}".encode("utf-8")
    return ATTENDANCE_SOURCE_SETTING_PREFIX + hashlib.sha256(identity).hexdigest()[:56]


def _source_checkpoint(value: object, field: str) -> datetime | None:
    if not isinstance(value, dict) or not value.get(field):
        return None
    try:
        parsed = datetime.fromisoformat(str(value[field]).replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeError(f"Invalid attendance source checkpoint: {field}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RuntimeError(f"Attendance source checkpoint lacks timezone: {field}")
    return parsed.astimezone(timezone.utc)


def _source_state(
    db: Session,
    factory_code: str,
    device_key: str,
) -> tuple[SystemSetting | None, dict[str, object]]:
    query = db.query(SystemSetting).filter(
        SystemSetting.key == _source_setting_key(factory_code, device_key),
    )
    if db.get_bind().dialect.name == "postgresql":
        query = query.with_for_update(of=SystemSetting)
    row = query.one_or_none()
    if row is None:
        return None, {"factory_code": factory_code, "device_key": device_key}
    state = dict(row.value_json) if isinstance(row.value_json, dict) else {}
    if state.get("factory_code") not in {None, factory_code} or state.get("device_key") not in {None, device_key}:
        raise RuntimeError("Attendance source checkpoint identity mismatch")
    state.update(factory_code=factory_code, device_key=device_key)
    return row, state


def _store_source_state(
    db: Session,
    row: SystemSetting | None,
    state: dict[str, object],
) -> None:
    if row is None:
        insert_source_checkpoint(db, key=_source_setting_key(str(state["factory_code"]), str(state["device_key"])), state=state)
    else:
        update_source_checkpoint(db, row=row, state=state)


def _source_snapshot_at(
    source_snapshot_at: datetime | None,
    sync_started_at: datetime,
) -> datetime | None:
    if source_snapshot_at is None:
        return None
    normalized = as_utc(source_snapshot_at)
    if normalized is None:
        raise HTTPException(400, "source_snapshot_at must include a timezone offset")
    maximum = sync_started_at + timedelta(seconds=settings.ATTENDANCE_SOURCE_MAX_FUTURE_SECONDS)
    if normalized > maximum:
        raise HTTPException(400, "source_snapshot_at is too far in the future")
    return normalized


def _advance_source_checkpoint(
    state: dict[str, object],
    field: str,
    source_snapshot_at: datetime,
    legacy_checkpoint: datetime | None,
) -> tuple[bool, datetime | None]:
    checkpoint = _source_checkpoint(state, field)
    baseline = checkpoint if checkpoint is not None else as_utc(legacy_checkpoint)
    if baseline is not None and source_snapshot_at <= baseline:
        state[field] = baseline.isoformat()
        return False, baseline
    state[field] = source_snapshot_at.isoformat()
    return True, baseline


def _upsert_device(
    db: Session,
    payload: DeviceIn,
    identity: AttendanceDevice | None,
    *,
    sync_started_at: datetime,
    source_snapshot_at: datetime | None = None,
    people_sync: bool = False,
    event_sync: bool = False,
) -> tuple[AttendanceDevice, str | None, str | None]:
    if identity is not None:
        if identity.device_key != payload.device_key:
            raise HTTPException(403, "Connector token does not belong to this attendance device")
        factory_code = identity.factory_code
    else:
        factory_code = _integration_factory()
    _lock_attendance_import(db, factory_code, payload.device_key)
    device_query = db.query(AttendanceDevice).filter(
        AttendanceDevice.factory_code == factory_code,
        AttendanceDevice.device_key == payload.device_key,
    ).populate_existing()
    if db.get_bind().dialect.name == "postgresql":
        device_query = device_query.with_for_update(of=AttendanceDevice)
    device = device_query.one_or_none()
    if identity is not None and device is None:
        raise HTTPException(404, "Attendance device not found")
    source_snapshot_at = _source_snapshot_at(source_snapshot_at, sync_started_at)
    source_row, source_state = _source_state(db, factory_code, payload.device_key)

    if people_sync and device is not None:
        source_people_checkpoint = _source_checkpoint(source_state, "people_snapshot_at")
        source_metadata_checkpoint = _source_checkpoint(source_state, "metadata_snapshot_at")
        if source_snapshot_at is None and (
            source_people_checkpoint is not None or source_metadata_checkpoint is not None
        ):
            return device, "missing_source_version", "missing_source_version"
        if source_snapshot_at is not None:
            people_is_newer, _baseline = _advance_source_checkpoint(
                source_state,
                "people_snapshot_at",
                source_snapshot_at,
                device.last_people_sync_at,
            )
            if not people_is_newer:
                if (
                    _source_checkpoint(source_state, "metadata_snapshot_at") is None
                    and as_utc(device.last_seen_at) is not None
                ):
                    source_state["metadata_snapshot_at"] = as_utc(device.last_seen_at).isoformat()
                _store_source_state(db, source_row, source_state)
                return device, "stale_source_version", "stale_source_version"
        else:
            previous_people_sync = as_utc(device.last_people_sync_at)
            if previous_people_sync is not None and previous_people_sync >= sync_started_at:
                return device, "stale_receipt", "stale_receipt"

    vendor = payload.vendor
    if device is None:
        device = insert_managed_device(db, values={
            "factory_code": factory_code, "device_key": payload.device_key,
            "name": payload.name, "vendor": vendor, "read_only": True,
        })
        db.flush()
        if people_sync and source_snapshot_at is not None:
            source_state["people_snapshot_at"] = source_snapshot_at.isoformat()

    metadata_ignored_reason = None
    previous_seen = as_utc(device.last_seen_at)
    if source_snapshot_at is not None:
        metadata_is_newer, _baseline = _advance_source_checkpoint(
            source_state,
            "metadata_snapshot_at",
            source_snapshot_at,
            previous_seen,
        )
        if not metadata_is_newer:
            metadata_ignored_reason = "stale_source_version"
    elif _source_checkpoint(source_state, "metadata_snapshot_at") is not None:
        metadata_is_newer = False
        metadata_ignored_reason = "missing_source_version"
    else:
        metadata_is_newer = previous_seen is None or sync_started_at > previous_seen
        if not metadata_is_newer:
            metadata_ignored_reason = "stale_receipt"

    if metadata_is_newer:
        update_managed_device(db, device=device, changes={
            "name": payload.name, "vendor": vendor, "model": payload.model,
            "serial_no": payload.serial_no, "source_host": payload.source_host,
            "reported_person_count": payload.reported_person_count, "read_only": True,
        })
    if previous_seen is None or sync_started_at > previous_seen:
        update_managed_device(db, device=device, changes={"last_seen_at": sync_started_at})
    if people_sync:
        update_managed_device(db, device=device, changes={"last_people_sync_at": sync_started_at})
    if event_sync:
        previous_event_sync = as_utc(device.last_event_sync_at)
        if previous_event_sync is None or sync_started_at > previous_event_sync:
            update_managed_device(db, device=device, changes={"last_event_sync_at": sync_started_at})
    if source_snapshot_at is not None:
        if event_sync:
            _advance_source_checkpoint(
                source_state,
                "event_snapshot_at",
                source_snapshot_at,
                None,
            )
        _store_source_state(db, source_row, source_state)
    return device, None, metadata_ignored_reason


def import_people_snapshot(
    payload: PeopleSnapshotIn, db: Session, identity: AttendanceDevice | None, *,
    clock: Callable = utcnow, upsert_device: Callable = _upsert_device,
):
    seen: set[str] = set()
    for incoming in payload.people:
        external_id = incoming.external_person_id
        if external_id in seen:
            raise HTTPException(400, f"Duplicate person ID in snapshot: {external_id}")
        seen.add(external_id)
    if payload.full_snapshot and not seen and (payload.device.reported_person_count or 0) != 0:
        raise HTTPException(400, "Refusing an empty full snapshot for a non-empty device")

    sync_started_at = clock()
    device, ignored_reason, _metadata_ignored_reason = upsert_device(
        db,
        payload.device,
        identity,
        sync_started_at=sync_started_at,
        source_snapshot_at=payload.source_snapshot_at,
        people_sync=True,
    )
    if ignored_reason is not None:
        device_id = device.id
        db.commit()
        response = {
            "device_id": device_id,
            "received": len(payload.people),
            "created": 0,
            "updated": 0,
            "marked_absent": 0,
            "reported_person_count": payload.device.reported_person_count,
            "ignored": True,
        }
        if ignored_reason != "stale_receipt":
            response["ignored_reason"] = ignored_reason
        return response
    now = sync_started_at
    created = 0
    updated = 0

    # AT06 acquires the device import lock and rejects stale snapshots above.
    # Read the roster only after that gate, refreshing any preloaded ORM rows.
    existing_people = {}
    incoming_ids = sorted(seen)
    for offset in range(0, len(incoming_ids), 400):
        rows = db.query(AttendancePerson).filter(
            AttendancePerson.device_id == device.id,
            AttendancePerson.external_person_id.in_(incoming_ids[offset:offset + 400]),
        ).populate_existing().all()
        existing_people.update({person.external_person_id: person for person in rows})

    for incoming in payload.people:
        external_id = incoming.external_person_id
        person = existing_people.get(external_id)
        if person is None:
            person = insert_attendance_person(db, values={
                "factory_code": device.factory_code, "device_id": device.id,
                "external_person_id": external_id, "full_name": incoming.full_name,
                "last_synced_at": now,
            })
            created += 1
        else:
            updated += 1
        update_attendance_person(db, person=person, changes={
            "factory_code": device.factory_code, "full_name": incoming.full_name,
            "user_type": incoming.user_type, "valid_from": as_utc(incoming.valid_from),
            "valid_to": as_utc(incoming.valid_to), "is_valid": incoming.is_valid,
            "has_face": incoming.has_face, "card_count": incoming.card_count,
            "fingerprint_count": incoming.fingerprint_count, "present_on_device": True,
            "last_synced_at": now,
        })

    marked_absent = 0
    if payload.full_snapshot:
        marked_absent = mark_other_people_absent(db, device_id=device.id, seen=seen)
    db.commit()
    return {
        "device_id": device.id,
        "received": len(payload.people),
        "created": created,
        "updated": updated,
        "marked_absent": marked_absent,
        "reported_person_count": payload.device.reported_person_count,
        "ignored": False,
    }
