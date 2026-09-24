from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from functools import partial
from pathlib import Path
from tempfile import NamedTemporaryFile
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import case, func, or_, text
from sqlalchemy.orm import Session, load_only

from app.core.config import settings
from app.core.deps import DbSession, require_permissions
from app.core.dt import as_utc, utcnow
from app.core.uploads import (
    UploadCommitState,
    run_upload_db_work,
    upload_processing_slot,
    upload_session_factory,
)
from app.models import AttendanceDevice, AttendanceEvent, AttendancePerson, SystemSetting, User
from app.services.attendance_event_policy import accepted_attendance_result
from app.services.factory_scope import normalize_factory_code, selected_factory_code
from app.services.image_storage import convert_image_to_webp
from app.services.attendance_reports import ReportLanguage, build_daily_attendance_xlsx
from app.services.audit import log_action


router = APIRouter(prefix="/attendance", tags=["attendance"])
TASHKENT = ZoneInfo("Asia/Tashkent")
ATTENDANCE_IMPORT_LOCK_NAMESPACE = 1096043342
ATTENDANCE_DEVICE_VENDORS = frozenset({"Hikvision", "Dahua"})
ATTENDANCE_SOURCE_SETTING_PREFIX = "att_src:"


def _validate_device_vendor(value: str) -> str:
    if value not in ATTENDANCE_DEVICE_VENDORS:
        raise HTTPException(400, "Invalid attendance device vendor")
    return value


class DeviceIn(BaseModel):
    device_key: str = Field(min_length=1, max_length=64)
    name: str = Field(default="Main turnstile", min_length=1, max_length=128)
    vendor: str = Field(default="Hikvision", min_length=1, max_length=64)
    model: str | None = Field(default=None, max_length=128)
    serial_no: str | None = Field(default=None, max_length=128)
    source_host: str | None = Field(default=None, max_length=255)
    reported_person_count: int | None = Field(default=None, ge=0, le=100_000)

    @field_validator("device_key")
    @classmethod
    def validate_device_key(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized.replace("-", "").replace("_", "").isalnum():
            raise ValueError("device_key may contain only letters, numbers, hyphens, and underscores")
        return normalized


class PersonIn(BaseModel):
    external_person_id: str = Field(min_length=1, max_length=64)
    full_name: str = Field(min_length=1, max_length=255)
    user_type: str | None = Field(default=None, max_length=32)
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    is_valid: bool = True
    has_face: bool = False
    card_count: int = Field(default=0, ge=0, le=100)
    fingerprint_count: int = Field(default=0, ge=0, le=100)

    @field_validator("external_person_id", "full_name")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        return value.strip()


class PeopleSnapshotIn(BaseModel):
    device: DeviceIn
    people: list[PersonIn] = Field(max_length=5_000)
    full_snapshot: bool = True
    source_snapshot_at: datetime | None = None

    @field_validator("source_snapshot_at")
    @classmethod
    def validate_source_snapshot_at(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("source_snapshot_at must include a timezone offset")
        return value.astimezone(timezone.utc) if value is not None else None


class EventIn(BaseModel):
    event_uid: str = Field(min_length=1, max_length=160)
    external_person_id: str | None = Field(default=None, max_length=64)
    occurred_at: datetime
    direction: str = Field(default="unknown", max_length=16)
    verification_mode: str | None = Field(default=None, max_length=64)
    result: str | None = Field(default=None, max_length=32)
    door_no: int | None = Field(default=None, ge=0, le=10_000)
    reader_no: int | None = Field(default=None, ge=0, le=10_000)
    serial_no: int | None = Field(default=None, ge=0, le=2_147_483_647)

    @field_validator("event_uid")
    @classmethod
    def strip_event_uid(cls, value: str) -> str:
        return value.strip()

    @field_validator("direction")
    @classmethod
    def normalize_direction(cls, value: str) -> str:
        normalized = value.strip().lower()
        return normalized if normalized in {"entry", "exit"} else "unknown"


class EventBatchIn(BaseModel):
    device: DeviceIn
    events: list[EventIn] = Field(max_length=2_000)
    source_snapshot_at: datetime | None = None

    @field_validator("source_snapshot_at")
    @classmethod
    def validate_source_snapshot_at(cls, value: datetime | None) -> datetime | None:
        return PeopleSnapshotIn.validate_source_snapshot_at(value)


class ManagedDeviceIn(BaseModel):
    device_key: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    vendor: str = Field(pattern="^(Hikvision|Dahua)$")
    source_host: str = Field(min_length=8, max_length=255)
    certificate_sha256: str = Field(min_length=64, max_length=64)

    @field_validator("device_key")
    @classmethod
    def validate_managed_device_key(cls, value: str) -> str:
        return DeviceIn.validate_device_key(value)

    @field_validator("source_host")
    @classmethod
    def validate_source_host(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        if not normalized.lower().startswith("https://"):
            raise ValueError("Attendance device URL must use HTTPS")
        return normalized

    @field_validator("certificate_sha256")
    @classmethod
    def validate_certificate_sha256(cls, value: str) -> str:
        normalized = "".join(character for character in value.lower() if character in "0123456789abcdef")
        if len(normalized) != 64:
            raise ValueError("Certificate SHA-256 must contain 64 hexadecimal characters")
        return normalized


class ManagedDeviceUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    sync_enabled: bool | None = None


def _connector_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _require_integration_token(
    db: DbSession,
    x_attendance_token: str | None = Header(default=None, alias="X-Attendance-Token"),
) -> AttendanceDevice | None:
    supplied = str(x_attendance_token or "")
    if supplied:
        managed = db.query(AttendanceDevice).filter(
            AttendanceDevice.connector_token_hash == _connector_token_hash(supplied),
        ).one_or_none()
        if managed:
            if not managed.sync_enabled:
                raise HTTPException(403, "Attendance device synchronization is disabled")
            return managed
    expected = settings.ATTENDANCE_INTEGRATION_TOKEN.strip()
    if not expected:
        raise HTTPException(503, "Attendance integration is not configured")
    if not hmac.compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(401, "Invalid attendance integration credentials")
    return None


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
        db.add(SystemSetting(
            key=_source_setting_key(str(state["factory_code"]), str(state["device_key"])),
            value_json=state,
        ))
    else:
        row.value_json = state


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

    vendor = _validate_device_vendor(payload.vendor)
    if device is None:
        device = AttendanceDevice(
            factory_code=factory_code,
            device_key=payload.device_key,
            name=payload.name,
            vendor=vendor,
            read_only=True,
        )
        db.add(device)
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
        device.name = payload.name
        device.vendor = vendor
        device.model = payload.model
        device.serial_no = payload.serial_no
        device.source_host = payload.source_host
        device.reported_person_count = payload.reported_person_count
        device.read_only = True
    if previous_seen is None or sync_started_at > previous_seen:
        device.last_seen_at = sync_started_at
    if people_sync:
        device.last_people_sync_at = sync_started_at
    if event_sync:
        previous_event_sync = as_utc(device.last_event_sync_at)
        if previous_event_sync is None or sync_started_at > previous_event_sync:
            device.last_event_sync_at = sync_started_at
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


@router.post("/integration/people")
def import_people_snapshot(
    payload: PeopleSnapshotIn,
    db: DbSession,
    identity: AttendanceDevice | None = Depends(_require_integration_token),
):
    seen: set[str] = set()
    for incoming in payload.people:
        external_id = incoming.external_person_id
        if external_id in seen:
            raise HTTPException(400, f"Duplicate person ID in snapshot: {external_id}")
        seen.add(external_id)
    if payload.full_snapshot and not seen and (payload.device.reported_person_count or 0) != 0:
        raise HTTPException(400, "Refusing an empty full snapshot for a non-empty device")

    sync_started_at = utcnow()
    device, ignored_reason, _metadata_ignored_reason = _upsert_device(
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

    existing_people = {}
    incoming_ids = list(seen)
    for offset in range(0, len(incoming_ids), 400):
        existing_people.update({
            person.external_person_id: person
            for person in db.query(AttendancePerson).filter(
                AttendancePerson.device_id == device.id,
                AttendancePerson.external_person_id.in_(incoming_ids[offset:offset + 400]),
            ).all()
        })
    for incoming in payload.people:
        external_id = incoming.external_person_id
        person = existing_people.get(external_id)
        if person is None:
            person = AttendancePerson(
                factory_code=device.factory_code,
                device_id=device.id,
                external_person_id=external_id,
                full_name=incoming.full_name,
                last_synced_at=now,
            )
            db.add(person)
            created += 1
        else:
            updated += 1
        person.factory_code = device.factory_code
        person.full_name = incoming.full_name
        person.user_type = incoming.user_type
        person.valid_from = as_utc(incoming.valid_from)
        person.valid_to = as_utc(incoming.valid_to)
        person.is_valid = incoming.is_valid
        person.has_face = incoming.has_face
        person.card_count = incoming.card_count
        person.fingerprint_count = incoming.fingerprint_count
        person.present_on_device = True
        person.last_synced_at = now

    marked_absent = 0
    if payload.full_snapshot:
        absent_query = db.query(AttendancePerson).filter(
            AttendancePerson.device_id == device.id,
            AttendancePerson.present_on_device.is_(True),
        )
        if seen:
            absent_query = absent_query.filter(AttendancePerson.external_person_id.notin_(seen))
        marked_absent = absent_query.update({AttendancePerson.present_on_device: False}, synchronize_session=False)
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


@router.post("/integration/events")
def import_events(
    payload: EventBatchIn,
    db: DbSession,
    identity: AttendanceDevice | None = Depends(_require_integration_token),
):
    sync_started_at = utcnow()
    device, _ignored_reason, metadata_ignored_reason = _upsert_device(
        db,
        payload.device,
        identity,
        sync_started_at=sync_started_at,
        source_snapshot_at=payload.source_snapshot_at,
        event_sync=True,
    )
    incoming_uids = [event.event_uid for event in payload.events]
    if len(incoming_uids) != len(set(incoming_uids)):
        raise HTTPException(400, "Duplicate event UID in batch")
    existing = set()
    if incoming_uids:
        existing = {
            value for (value,) in db.query(AttendanceEvent.event_uid).filter(
                AttendanceEvent.device_id == device.id,
                AttendanceEvent.event_uid.in_(incoming_uids),
            ).all()
        }
    person_ids = {event.external_person_id for event in payload.events if event.external_person_id}
    people = {}
    if person_ids:
        people = {
            person.external_person_id: person.id
            for person in db.query(AttendancePerson).filter(
                AttendancePerson.device_id == device.id,
                AttendancePerson.external_person_id.in_(person_ids),
            ).all()
        }
    inserted = 0
    received_at = utcnow()
    for incoming in payload.events:
        if incoming.event_uid in existing:
            continue
        external_id = (incoming.external_person_id or "").strip() or None
        db.add(AttendanceEvent(
            factory_code=device.factory_code,
            device_id=device.id,
            person_id=people.get(external_id),
            event_uid=incoming.event_uid,
            external_person_id=external_id,
            occurred_at=as_utc(incoming.occurred_at),
            received_at=received_at,
            direction=incoming.direction,
            verification_mode=incoming.verification_mode,
            result=incoming.result,
            door_no=incoming.door_no,
            reader_no=incoming.reader_no,
            serial_no=incoming.serial_no,
        ))
        inserted += 1
    db.commit()
    response = {
        "received": len(payload.events),
        "inserted": inserted,
        "duplicates": len(payload.events) - inserted,
        "metadata_ignored": metadata_ignored_reason is not None,
    }
    if metadata_ignored_reason is not None:
        response["metadata_ignored_reason"] = metadata_ignored_reason
    return response


def _write_new_attendance_photo(destination: Path, content: bytes) -> bool:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(
            prefix=".attendance_",
            suffix=".tmp",
            dir=destination.parent,
            delete=False,
        ) as stream:
            stream.write(content)
            temporary_path = Path(stream.name)
        os.link(temporary_path, destination)
    except FileExistsError:
        return False
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return True


@dataclass
class _AttendancePhotoFileState:
    created_path: Path | None = None


def _discard_attendance_photo(state: _AttendancePhotoFileState) -> None:
    if state.created_path is None:
        return
    state.created_path.unlink(missing_ok=True)
    state.created_path = None


def _attendance_photo_target(
    db: Session,
    *,
    factory_code: str,
    device_key: str,
    external_person_id: str,
    identity_device_id: int | None,
    lock: bool,
) -> tuple[AttendanceDevice, AttendancePerson]:
    device_query = db.query(AttendanceDevice).filter(
        AttendanceDevice.factory_code == factory_code,
        AttendanceDevice.device_key == device_key,
    )
    device = device_query.one_or_none()
    if not device:
        raise HTTPException(404, "Attendance device not found")
    if identity_device_id is not None and device.id != identity_device_id:
        raise HTTPException(403, "Connector token does not belong to this attendance device")
    person_query = db.query(AttendancePerson).filter(
        AttendancePerson.device_id == device.id,
        AttendancePerson.external_person_id == external_person_id,
    )
    if lock:
        person_query = person_query.with_for_update()
    person = person_query.one_or_none()
    if not person:
        raise HTTPException(404, "Attendance person not found")
    return device, person


def _set_attendance_photo(
    person: AttendancePerson,
    *,
    file_name: str,
    digest: str,
) -> None:
    person.photo_file_name = file_name
    person.photo_sha256 = digest


def _store_attendance_photo(
    db: Session,
    *,
    factory_code: str,
    device_key: str,
    external_person_id: str,
    identity_device_id: int | None,
    content: bytes,
    photo_root: Path,
    file_state: _AttendancePhotoFileState,
) -> dict[str, bool | str]:
    converted = convert_image_to_webp(content)
    digest = hashlib.sha256(converted.data).hexdigest()
    device, person = _attendance_photo_target(
        db,
        factory_code=factory_code,
        device_key=device_key,
        external_person_id=external_person_id,
        identity_device_id=identity_device_id,
        lock=True,
    )
    if person.photo_sha256 == digest and person.photo_file_name:
        return {"updated": False, "photo_sha256": digest}
    file_name = f"{device.id}_{person.id}_{digest[:20]}.webp"
    destination = photo_root / file_name
    if _write_new_attendance_photo(destination, converted.data):
        file_state.created_path = destination
    _set_attendance_photo(person, file_name=file_name, digest=digest)
    return {"updated": True, "photo_sha256": digest}


async def _read_bounded_attendance_photo(request: Request, max_bytes: int) -> bytes:
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > max_bytes:
            raise HTTPException(413, "Photo is too large")
        content.extend(chunk)
    return bytes(content)


@router.post("/integration/photos/{device_key}/{external_person_id}")
async def import_person_photo(
    device_key: str,
    external_person_id: str,
    request: Request,
    db: DbSession,
    identity: AttendanceDevice | None = Depends(_require_integration_token),
):
    identity_device_id = int(identity.id) if identity is not None else None
    factory_code = identity.factory_code if identity is not None else _integration_factory()
    worker_sessions = upload_session_factory(db)
    target = partial(
        _attendance_photo_target,
        factory_code=factory_code,
        device_key=device_key,
        external_person_id=external_person_id,
        identity_device_id=identity_device_id,
    )
    await run_upload_db_work(worker_sessions, partial(target, lock=False))
    async with upload_processing_slot():
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > settings.ATTENDANCE_PHOTO_MAX_BYTES:
            raise HTTPException(413, "Photo is too large")
        content = await _read_bounded_attendance_photo(request, settings.ATTENDANCE_PHOTO_MAX_BYTES)
        if not content:
            raise HTTPException(400, "Photo body is empty")
        file_state = _AttendancePhotoFileState()
        commit_state = UploadCommitState()
        return await run_upload_db_work(
            worker_sessions,
            partial(
                _store_attendance_photo,
                factory_code=factory_code,
                device_key=device_key,
                external_person_id=external_person_id,
                identity_device_id=identity_device_id,
                content=content,
                photo_root=Path(settings.ATTENDANCE_PHOTOS_DIR),
                file_state=file_state,
            ),
            commit=True,
            commit_state=commit_state,
            failure_cleanup=partial(_discard_attendance_photo, file_state),
        )


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    start_local = datetime.combine(day, time.min, tzinfo=TASHKENT)
    end_local = datetime.combine(day, time.max, tzinfo=TASHKENT)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def _attendance_people_query(
    db: Session,
    *,
    factory_code: str,
    start: datetime,
    end: datetime,
    query: str,
    usage: str,
):
    event_rollup = db.query(
        AttendanceEvent.external_person_id.label("external_person_id"),
        func.count(AttendanceEvent.id).label("event_count"),
        func.min(AttendanceEvent.occurred_at).label("first_seen_at"),
        func.max(AttendanceEvent.occurred_at).label("last_seen_at"),
    ).filter(
        AttendanceEvent.factory_code == factory_code,
        AttendanceEvent.occurred_at >= start,
        AttendanceEvent.occurred_at <= end,
        AttendanceEvent.external_person_id.is_not(None),
        accepted_attendance_result(AttendanceEvent.result),
    ).group_by(AttendanceEvent.external_person_id).subquery()

    # Hikvision commonly replicates the same employee profile to every lane.
    # Keep the device-specific copies for traceability, but choose one stable
    # representative per employee ID for the combined attendance view.
    representative_people = db.query(
        AttendancePerson.external_person_id.label("external_person_id"),
        func.coalesce(
            func.min(case((AttendancePerson.present_on_device.is_(True), AttendancePerson.id))),
            func.min(AttendancePerson.id),
        ).label("person_id"),
    ).outerjoin(
        event_rollup,
        event_rollup.c.external_person_id == AttendancePerson.external_person_id,
    ).filter(
        AttendancePerson.factory_code == factory_code,
        or_(AttendancePerson.present_on_device.is_(True), event_rollup.c.event_count.is_not(None)),
    ).group_by(AttendancePerson.external_person_id).subquery()

    base = db.query(
        AttendancePerson,
        event_rollup.c.event_count,
        event_rollup.c.first_seen_at,
        event_rollup.c.last_seen_at,
    ).outerjoin(
        event_rollup,
        event_rollup.c.external_person_id == AttendancePerson.external_person_id,
    ).join(
        representative_people,
        representative_people.c.person_id == AttendancePerson.id,
    ).filter(
        AttendancePerson.factory_code == factory_code,
    ).options(load_only(
        AttendancePerson.id,
        AttendancePerson.external_person_id,
        AttendancePerson.full_name,
        AttendancePerson.user_type,
        AttendancePerson.is_valid,
        AttendancePerson.has_face,
        AttendancePerson.photo_file_name,
    ))
    search = query.strip()
    if search:
        like = f"%{search}%"
        base = base.filter(or_(AttendancePerson.full_name.ilike(like), AttendancePerson.external_person_id.ilike(like)))
    if usage == "used":
        base = base.filter(event_rollup.c.event_count.is_not(None))
    elif usage == "not_used":
        base = base.filter(event_rollup.c.event_count.is_(None))
    return base


def _attendance_row_payload(
    person: AttendancePerson,
    event_count: int | None,
    first_seen_at: datetime | None,
    last_seen_at: datetime | None,
) -> dict:
    count = int(event_count or 0)
    arrival_at = as_utc(first_seen_at) if count else None
    final_seen_at = as_utc(last_seen_at) if count else None
    departure_at = (
        final_seen_at
        if (
            count > 1
            and arrival_at is not None
            and final_seen_at is not None
            and final_seen_at - arrival_at >= timedelta(minutes=1)
        )
        else None
    )
    attendance_status = "complete" if departure_at is not None else ("single_scan" if arrival_at is not None else "absent")
    worked_minutes = (
        int((departure_at - arrival_at).total_seconds() // 60)
        if departure_at is not None and arrival_at is not None
        else None
    )
    return {
        "id": person.id,
        "external_person_id": person.external_person_id,
        "full_name": person.full_name,
        "user_type": person.user_type,
        "is_valid": person.is_valid,
        "has_face": person.has_face,
        "has_photo": bool(person.photo_file_name),
        "event_count": count,
        "arrival_at": arrival_at,
        "departure_at": departure_at,
        "worked_minutes": worked_minutes,
        "attendance_status": attendance_status,
        # Kept for compatibility with the first attendance UI/API version.
        "first_seen_at": arrival_at,
        "last_seen_at": final_seen_at,
    }


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


@router.post("/devices", status_code=201)
def create_managed_attendance_device(
    payload: ManagedDeviceIn,
    db: DbSession,
    current: User = Depends(require_permissions("attendance.manage", "*")),
):
    factory_code = selected_factory_code(current)
    existing = db.query(AttendanceDevice.id).filter(
        AttendanceDevice.factory_code == factory_code,
        AttendanceDevice.device_key == payload.device_key,
    ).first()
    if existing:
        raise HTTPException(400, "Attendance device key already exists in this factory")
    connector_token = secrets.token_urlsafe(48)
    device = AttendanceDevice(
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
    )
    db.add(device)
    db.flush()
    log_action(
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


@router.patch("/devices/{device_id}")
def update_managed_attendance_device(
    device_id: int,
    payload: ManagedDeviceUpdateIn,
    db: DbSession,
    current: User = Depends(require_permissions("attendance.manage", "*")),
):
    device = db.query(AttendanceDevice).filter(
        AttendanceDevice.id == device_id,
        AttendanceDevice.factory_code == selected_factory_code(current),
    ).one_or_none()
    if not device:
        raise HTTPException(404, "Attendance device not found")
    if payload.name is not None:
        device.name = payload.name.strip()
    if payload.sync_enabled is not None:
        device.sync_enabled = payload.sync_enabled
    log_action(
        db,
        current,
        "update",
        "AttendanceDeviceConfig",
        device.id,
        new_value={"name": device.name, "sync_enabled": device.sync_enabled},
    )
    db.commit()
    return _device_payload(device)


@router.post("/devices/{device_id}/rotate-token")
def rotate_attendance_device_token(
    device_id: int,
    db: DbSession,
    current: User = Depends(require_permissions("attendance.manage", "*")),
):
    device = db.query(AttendanceDevice).filter(
        AttendanceDevice.id == device_id,
        AttendanceDevice.factory_code == selected_factory_code(current),
    ).one_or_none()
    if not device:
        raise HTTPException(404, "Attendance device not found")
    connector_token = secrets.token_urlsafe(48)
    device.connector_token_hash = _connector_token_hash(connector_token)
    device.configured_by = current.id
    log_action(db, current, "rotate_connector_token", "AttendanceDeviceConfig", device.id)
    db.commit()
    result = _device_payload(device)
    result["connector_token"] = connector_token
    return result


@router.get("/overview")
def attendance_overview(
    db: DbSession,
    current: User = Depends(require_permissions("attendance.view", "attendance.manage", "*")),
    day: date = Query(default_factory=lambda: datetime.now(TASHKENT).date()),
    query: str = Query(default="", max_length=120),
    usage: str = Query(default="all", pattern="^(all|used|not_used)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=10, le=200),
):
    factory_code = selected_factory_code(current)
    start, end = _day_bounds(day)
    base = _attendance_people_query(
        db,
        factory_code=factory_code,
        start=start,
        end=end,
        query=query,
        usage=usage,
    )
    total_filtered = base.count()
    rows = base.order_by(AttendancePerson.full_name.asc(), AttendancePerson.external_person_id.asc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    total_people = _attendance_people_query(
        db, factory_code=factory_code, start=start, end=end, query="", usage="all",
    ).count()
    used_today = db.query(func.count(func.distinct(AttendanceEvent.external_person_id))).filter(
        AttendanceEvent.factory_code == factory_code,
        AttendanceEvent.occurred_at >= start,
        AttendanceEvent.occurred_at <= end,
        AttendanceEvent.external_person_id.is_not(None),
        accepted_attendance_result(AttendanceEvent.result),
    ).scalar() or 0
    events_today = db.query(func.count(AttendanceEvent.id)).filter(
        AttendanceEvent.factory_code == factory_code,
        AttendanceEvent.occurred_at >= start,
        AttendanceEvent.occurred_at <= end,
    ).scalar() or 0
    unmatched_events = db.query(func.count(AttendanceEvent.id)).filter(
        AttendanceEvent.factory_code == factory_code,
        AttendanceEvent.occurred_at >= start,
        AttendanceEvent.occurred_at <= end,
        AttendanceEvent.external_person_id.is_(None),
    ).scalar() or 0
    devices = db.query(
        AttendanceDevice.id,
        AttendanceDevice.device_key,
        AttendanceDevice.name,
        AttendanceDevice.vendor,
        AttendanceDevice.model,
        AttendanceDevice.serial_no,
        AttendanceDevice.source_host,
        AttendanceDevice.certificate_sha256,
        AttendanceDevice.connector_token_hash.is_not(None).label("managed"),
        AttendanceDevice.sync_enabled,
        AttendanceDevice.read_only,
        AttendanceDevice.reported_person_count,
        AttendanceDevice.last_seen_at,
        AttendanceDevice.last_people_sync_at,
        AttendanceDevice.last_event_sync_at,
    ).filter(
        AttendanceDevice.factory_code == factory_code,
    ).order_by(AttendanceDevice.name).all()
    return {
        "date": day.isoformat(),
        "summary": {
            "total_people": total_people,
            "used_today": used_today,
            "not_used_today": max(total_people - used_today, 0),
            "events_today": events_today,
            "unmatched_events": unmatched_events,
        },
        "devices": [
            {
                "id": device.id,
                "device_key": device.device_key,
                "name": device.name,
                "vendor": device.vendor,
                "model": device.model,
                "serial_no": device.serial_no,
                "source_host": device.source_host,
                "certificate_sha256": device.certificate_sha256,
                "managed": bool(device.managed),
                "sync_enabled": device.sync_enabled,
                "read_only": device.read_only,
                "reported_person_count": device.reported_person_count,
                "last_seen_at": device.last_seen_at,
                "last_people_sync_at": device.last_people_sync_at,
                "last_event_sync_at": device.last_event_sync_at,
            }
            for device in devices
        ],
        "people": [
            _attendance_row_payload(person, event_count, first_seen_at, last_seen_at)
            for person, event_count, first_seen_at, last_seen_at in rows
        ],
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total_filtered,
            "pages": max((total_filtered + page_size - 1) // page_size, 1),
        },
    }


@router.get("/reports/daily.xlsx")
def download_daily_attendance_report(
    db: DbSession,
    current: User = Depends(require_permissions("attendance.view", "attendance.manage", "*")),
    day: date = Query(default_factory=lambda: datetime.now(TASHKENT).date()),
    query: str = Query(default="", max_length=120),
    usage: str = Query(default="all", pattern="^(all|used|not_used)$"),
    lang: ReportLanguage = Query(default="uz"),
    page: int | None = Query(default=None, ge=1),
    page_size: int | None = Query(default=None, ge=1, le=500),
):
    factory_code = selected_factory_code(current)
    start, end = _day_bounds(day)
    records_query = _attendance_people_query(
        db,
        factory_code=factory_code,
        start=start,
        end=end,
        query=query,
        usage=usage,
    ).order_by(
        AttendancePerson.full_name.asc(),
        AttendancePerson.external_person_id.asc(),
    )
    total = None
    if page is not None or page_size is not None:
        page = page or 1
        page_size = page_size or 100
        total = records_query.order_by(None).count()
        records_query = records_query.offset((page - 1) * page_size).limit(page_size)
    records = records_query.all()
    rows = [
        _attendance_row_payload(person, event_count, first_seen_at, last_seen_at)
        for person, event_count, first_seen_at, last_seen_at in records
    ]
    content = build_daily_attendance_xlsx(
        day=day,
        rows=rows,
        generated_at=utcnow(),
        lang=lang,
    )
    headers = {"Content-Disposition": f'attachment; filename="attendance_daily_{day.isoformat()}.xlsx"'}
    if total is not None:
        headers.update({
            "X-Total-Count": str(total),
            "X-Page": str(page),
            "X-Page-Size": str(page_size),
            "X-Has-More": "true" if page * page_size < total else "false",
        })
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )


@router.get("/people/{person_id}/photo")
def attendance_person_photo(
    person_id: int,
    db: DbSession,
    current: User = Depends(require_permissions("attendance.view", "attendance.manage", "*")),
):
    person = db.query(AttendancePerson).options(
        load_only(AttendancePerson.id, AttendancePerson.photo_file_name),
    ).filter(
        AttendancePerson.id == person_id,
        AttendancePerson.factory_code == selected_factory_code(current),
        AttendancePerson.present_on_device.is_(True),
    ).one_or_none()
    if not person or not person.photo_file_name:
        raise HTTPException(404, "Attendance photo not found")
    root = Path(settings.ATTENDANCE_PHOTOS_DIR).resolve()
    path = (root / person.photo_file_name).resolve()
    if path.parent != root or not path.is_file():
        raise HTTPException(404, "Attendance photo not found")
    return FileResponse(path, media_type="image/webp", headers={"Cache-Control": "private, max-age=300"})
