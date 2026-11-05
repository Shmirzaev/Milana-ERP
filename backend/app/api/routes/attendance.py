from __future__ import annotations

import hmac
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response

from app.core.config import settings
from app.core.deps import DbSession, require_permissions
from app.core.dt import utcnow
from app.schemas import AttendanceDevice, AttendancePerson, User
from app.models.factory_scope_service import selected_factory_code
from app.models.attendance_reports_service import ReportLanguage
from app.models.audit_service import log_action
from app.models.people import attendance_service
from app.models.people.attendance_service import (
    _integration_factory as _integration_factory,
    _lock_attendance_import as _lock_attendance_import,
    _source_setting_key as _source_setting_key,
    _source_checkpoint as _source_checkpoint,
    _source_state as _source_state,
    _store_source_state as _store_source_state,
    _source_snapshot_at as _source_snapshot_at,
    _advance_source_checkpoint as _advance_source_checkpoint,
    _upsert_device as _upsert_device,
    ATTENDANCE_IMPORT_LOCK_NAMESPACE as ATTENDANCE_IMPORT_LOCK_NAMESPACE,
    ATTENDANCE_SOURCE_SETTING_PREFIX as ATTENDANCE_SOURCE_SETTING_PREFIX,
)
from app.libs.dto.people.attendance import PersonIn as PersonIn, PeopleSnapshotIn, EventIn as EventIn, EventBatchIn
from app.libs.dto.people.attendance import DeviceIn as DeviceIn, ManagedDeviceIn as ManagedDeviceIn, ManagedDeviceUpdateIn as ManagedDeviceUpdateIn


_day_bounds = attendance_service._day_bounds
_attendance_people_query = attendance_service._attendance_people_query
_attendance_row_payload = attendance_service._attendance_row_payload

router = APIRouter(prefix="/attendance", tags=["attendance"])
TASHKENT = ZoneInfo("Asia/Tashkent")
secrets = attendance_service.secrets


_connector_token_hash = attendance_service._connector_token_hash


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


@router.post("/integration/people")
def import_people_snapshot(
    payload: PeopleSnapshotIn,
    db: DbSession,
    identity: AttendanceDevice | None = Depends(_require_integration_token),
):
    return attendance_service.import_people_snapshot(
        payload, db, identity, clock=utcnow, upsert_device=_upsert_device,
    )


@router.post("/integration/events")
def import_events(
    payload: EventBatchIn,
    db: DbSession,
    identity: AttendanceDevice | None = Depends(_require_integration_token),
):
    return attendance_service.import_events(
        payload, db, identity, clock=utcnow, upsert_device=_upsert_device,
    )


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
    return await attendance_service.import_person_photo(device_key, external_person_id, content, db, identity)


_device_payload = attendance_service._device_payload


@router.post("/devices", status_code=201)
def create_managed_attendance_device(
    payload: ManagedDeviceIn,
    db: DbSession,
    current: User = Depends(require_permissions("attendance.manage", "*")),
):
    return attendance_service.create_managed_attendance_device(payload, db, current, audit=log_action)

@router.patch("/devices/{device_id}")
def update_managed_attendance_device(
    device_id: int,
    payload: ManagedDeviceUpdateIn,
    db: DbSession,
    current: User = Depends(require_permissions("attendance.manage", "*")),
):
    return attendance_service.update_managed_attendance_device(device_id, payload, db, current, audit=log_action)

@router.post("/devices/{device_id}/rotate-token")
def rotate_attendance_device_token(
    device_id: int,
    db: DbSession,
    current: User = Depends(require_permissions("attendance.manage", "*")),
):
    return attendance_service.rotate_attendance_device_token(device_id, db, current, audit=log_action)

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
    return attendance_service.attendance_overview(db, current, day, query, usage, page, page_size)


@router.get("/reports/daily.xlsx")
def download_daily_attendance_report(
    db: DbSession,
    current: User = Depends(require_permissions("attendance.view", "attendance.manage", "*")),
    day: date = Query(default_factory=lambda: datetime.now(TASHKENT).date()),
    query: str = Query(default="", max_length=120),
    usage: str = Query(default="all", pattern="^(all|used|not_used)$"),
    lang: ReportLanguage = Query(default="uz"),
):
    content = attendance_service.daily_attendance_report(db, current, day, query, usage, lang, clock=utcnow)
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
