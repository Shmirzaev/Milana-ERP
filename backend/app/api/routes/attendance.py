from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import DbSession, require_permissions
from app.core.dt import as_utc, utcnow
from app.models import AttendanceDevice, AttendanceEvent, AttendancePerson, User
from app.services.factory_scope import normalize_factory_code, selected_factory_code
from app.services.image_storage import convert_image_to_webp
from app.services.attendance_reports import ReportLanguage, build_daily_attendance_xlsx
from app.services.audit import log_action


router = APIRouter(prefix="/attendance", tags=["attendance"])
TASHKENT = ZoneInfo("Asia/Tashkent")


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


class EventIn(BaseModel):
    event_uid: str = Field(min_length=1, max_length=160)
    external_person_id: str | None = Field(default=None, max_length=64)
    occurred_at: datetime
    direction: str = Field(default="unknown", max_length=16)
    verification_mode: str | None = Field(default=None, max_length=64)
    result: str | None = Field(default=None, max_length=32)
    door_no: int | None = Field(default=None, ge=0, le=10_000)
    reader_no: int | None = Field(default=None, ge=0, le=10_000)
    serial_no: int | None = Field(default=None, ge=0)

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


def _upsert_device(
    db: Session,
    payload: DeviceIn,
    identity: AttendanceDevice | None,
    *,
    people_sync: bool = False,
    event_sync: bool = False,
) -> AttendanceDevice:
    if identity is not None:
        if identity.device_key != payload.device_key:
            raise HTTPException(403, "Connector token does not belong to this attendance device")
        factory_code = identity.factory_code
        device = identity
    else:
        factory_code = _integration_factory()
        device = db.query(AttendanceDevice).filter(
            AttendanceDevice.factory_code == factory_code,
            AttendanceDevice.device_key == payload.device_key,
        ).one_or_none()
    now = utcnow()
    if device is None:
        device = AttendanceDevice(
            factory_code=factory_code,
            device_key=payload.device_key,
            name=payload.name,
            vendor=payload.vendor,
            read_only=True,
        )
        db.add(device)
        db.flush()
    device.name = payload.name
    device.vendor = payload.vendor
    device.model = payload.model
    device.serial_no = payload.serial_no
    device.source_host = payload.source_host
    device.reported_person_count = payload.reported_person_count
    device.read_only = True
    device.last_seen_at = now
    if people_sync:
        device.last_people_sync_at = now
    if event_sync:
        device.last_event_sync_at = now
    return device


@router.post("/integration/people")
def import_people_snapshot(
    payload: PeopleSnapshotIn,
    db: DbSession,
    identity: AttendanceDevice | None = Depends(_require_integration_token),
):
    device = _upsert_device(db, payload.device, identity, people_sync=True)
    now = utcnow()
    seen: set[str] = set()
    created = 0
    updated = 0
    for incoming in payload.people:
        external_id = incoming.external_person_id
        if external_id in seen:
            raise HTTPException(400, f"Duplicate person ID in snapshot: {external_id}")
        seen.add(external_id)
        person = db.query(AttendancePerson).filter(
            AttendancePerson.device_id == device.id,
            AttendancePerson.external_person_id == external_id,
        ).one_or_none()
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
        if not seen and (payload.device.reported_person_count or 0) != 0:
            raise HTTPException(400, "Refusing an empty full snapshot for a non-empty device")
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
    }


@router.post("/integration/events")
def import_events(
    payload: EventBatchIn,
    db: DbSession,
    identity: AttendanceDevice | None = Depends(_require_integration_token),
):
    device = _upsert_device(db, payload.device, identity, event_sync=True)
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
    return {"received": len(payload.events), "inserted": inserted, "duplicates": len(payload.events) - inserted}


@router.post("/integration/photos/{device_key}/{external_person_id}")
async def import_person_photo(
    device_key: str,
    external_person_id: str,
    request: Request,
    db: DbSession,
    identity: AttendanceDevice | None = Depends(_require_integration_token),
):
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > settings.ATTENDANCE_PHOTO_MAX_BYTES:
        raise HTTPException(413, "Photo is too large")
    content = await request.body()
    if not content:
        raise HTTPException(400, "Photo body is empty")
    if len(content) > settings.ATTENDANCE_PHOTO_MAX_BYTES:
        raise HTTPException(413, "Photo is too large")
    device = db.query(AttendanceDevice).filter(
        AttendanceDevice.factory_code == (identity.factory_code if identity else _integration_factory()),
        AttendanceDevice.device_key == device_key,
    ).one_or_none()
    if not device:
        raise HTTPException(404, "Attendance device not found")
    if identity is not None and device.id != identity.id:
        raise HTTPException(403, "Connector token does not belong to this attendance device")
    person = db.query(AttendancePerson).filter(
        AttendancePerson.device_id == device.id,
        AttendancePerson.external_person_id == external_person_id,
    ).one_or_none()
    if not person:
        raise HTTPException(404, "Attendance person not found")
    converted = convert_image_to_webp(content)
    digest = hashlib.sha256(converted.data).hexdigest()
    if person.photo_sha256 == digest and person.photo_file_name:
        return {"updated": False, "photo_sha256": digest}
    root = Path(settings.ATTENDANCE_PHOTOS_DIR)
    root.mkdir(parents=True, exist_ok=True)
    file_name = f"{device.id}_{person.id}_{digest[:20]}.webp"
    destination = root / file_name
    if not destination.exists():
        with NamedTemporaryFile(prefix=".attendance_", suffix=".tmp", dir=root, delete=False) as temporary:
            temporary.write(converted.data)
            temporary_path = Path(temporary.name)
        try:
            os.replace(temporary_path, destination)
        finally:
            temporary_path.unlink(missing_ok=True)
    person.photo_file_name = file_name
    person.photo_sha256 = digest
    db.commit()
    return {"updated": True, "photo_sha256": digest}


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
    ).group_by(AttendanceEvent.external_person_id).subquery()

    # Hikvision commonly replicates the same employee profile to every lane.
    # Keep the device-specific copies for traceability, but choose one stable
    # representative per employee ID for the combined attendance view.
    representative_people = db.query(
        AttendancePerson.external_person_id.label("external_person_id"),
        func.min(AttendancePerson.id).label("person_id"),
    ).filter(
        AttendancePerson.factory_code == factory_code,
        AttendancePerson.present_on_device.is_(True),
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
        AttendancePerson.present_on_device.is_(True),
    )
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

    total_people = db.query(func.count(func.distinct(AttendancePerson.external_person_id))).filter(
        AttendancePerson.factory_code == factory_code,
        AttendancePerson.present_on_device.is_(True),
    ).scalar() or 0
    used_today = db.query(func.count(func.distinct(AttendanceEvent.external_person_id))).filter(
        AttendanceEvent.factory_code == factory_code,
        AttendanceEvent.occurred_at >= start,
        AttendanceEvent.occurred_at <= end,
        AttendanceEvent.external_person_id.is_not(None),
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
    devices = db.query(AttendanceDevice).filter(AttendanceDevice.factory_code == factory_code).order_by(AttendanceDevice.name).all()
    return {
        "date": day.isoformat(),
        "summary": {
            "total_people": total_people,
            "used_today": used_today,
            "not_used_today": max(total_people - used_today, 0),
            "events_today": events_today,
            "unmatched_events": unmatched_events,
        },
        "devices": [_device_payload(device) for device in devices],
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
):
    factory_code = selected_factory_code(current)
    start, end = _day_bounds(day)
    records = _attendance_people_query(
        db,
        factory_code=factory_code,
        start=start,
        end=end,
        query=query,
        usage=usage,
    ).order_by(AttendancePerson.full_name.asc(), AttendancePerson.external_person_id.asc()).all()
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
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="attendance_daily_{day.isoformat()}.xlsx"'},
    )


@router.get("/people/{person_id}/photo")
def attendance_person_photo(
    person_id: int,
    db: DbSession,
    current: User = Depends(require_permissions("attendance.view", "attendance.manage", "*")),
):
    person = db.query(AttendancePerson).filter(
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
