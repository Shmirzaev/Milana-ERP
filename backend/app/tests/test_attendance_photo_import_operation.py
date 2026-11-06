"""Connector raw-photo bytes, identity checks and file/database rollback baseline."""

import asyncio
import hashlib
from io import BytesIO

import pytest
from anyio import CancelScope
from PIL import Image
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.api.routes import attendance
from app.core.config import settings
from app.models.image_storage_service import convert_image_to_webp
from app.schemas import AttendanceDevice, AttendancePerson, AuditLog, Employee
from app.tests.test_attendance_people_import_operation import (
    MANAGED_TOKEN, TOKEN, assert_bytes, assert_openapi, attendance_case, attendance_database,  # noqa: F401
    managed, person, post_json, roster,
)


class PhotoBody:
    def __init__(self, data):
        self.data = data
        self.headers = {"content-length": str(len(data))}

    async def body(self):
        return self.data


def png():
    buffer = BytesIO()
    Image.new("RGB", (12, 12), (40, 50, 60)).save(buffer, format="PNG")
    return buffer.getvalue()


def seed_person(case):
    result = post_json(case, "/api/attendance/integration/people", roster(person("001", "Photo person")))
    assert result.status_code == 200
    with case.factory() as db:
        row = db.query(AttendancePerson).one()
        return row.device_id, row.id


def upload(case, data, *, key="wire-reader", external_id="001", token=TOKEN, length=None):
    headers = {"Content-Type": "image/png", "X-Attendance-Token": token}
    if length is not None:
        headers["Content-Length"] = str(length)
    response = case.client.post(f"/api/attendance/integration/photos/{key}/{external_id}", content=data, headers=headers)
    assert response.request.content == data
    return response


def test_photo_connector_bytes_digest_storage_and_identical_no_commit(attendance_case):
    case = attendance_case
    device_id, person_id = seed_person(case)
    data = png()
    commits = []
    def committed(session):
        commits.append(True)

    event.listen(Session, "after_commit", committed)
    try:
        first = upload(case, data)
        digest = first.json()["photo_sha256"]
        assert_bytes(first, f'{{"updated":true,"photo_sha256":"{digest}"}}'.encode())
        same = upload(case, data)
        assert_bytes(same, f'{{"updated":false,"photo_sha256":"{digest}"}}'.encode())
        assert commits == [True]
    finally:
        event.remove(Session, "after_commit", committed)
    file_name = f"{device_id}_{person_id}_{digest[:20]}.webp"
    stored = case.photos / file_name
    assert hashlib.sha256(stored.read_bytes()).hexdigest() == digest
    with case.factory() as db:
        row = db.get(AttendancePerson, person_id)
        assert (row.photo_file_name, row.photo_sha256) == (file_name, digest)
        assert db.query(Employee).count() == db.query(AuditLog).count() == 0
    assert_openapi("/api/attendance/integration/photos/{device_key}/{external_person_id}", "1b9e9917b91b3cdbefe3cd33daeb3b327b930538bbeed462ef288dd3c91e2a18")


@pytest.mark.parametrize("existing", [False, True])
def test_photo_commit_failure_removes_only_new_digest_file(attendance_case, existing):
    case = attendance_case
    device_id, person_id = seed_person(case)
    data = png()
    converted = convert_image_to_webp(data)
    digest = hashlib.sha256(converted.data).hexdigest()
    collision = case.photos / f"{device_id}_{person_id}_{digest[:20]}.webp"
    case.photos.mkdir(exist_ok=True)
    unrelated = case.photos / "keep-existing.webp"
    unrelated.write_bytes(b"existing unrelated photo")
    if existing:
        collision.write_bytes(converted.data)

    def fail_commit(session):
        raise RuntimeError("Synthetic attendance photo commit failure")

    event.listen(Session, "before_commit", fail_commit)
    try:
        with pytest.raises(RuntimeError, match="Synthetic attendance photo commit failure"):
            upload(case, data)
    finally:
        event.remove(Session, "before_commit", fail_commit)
    assert unrelated.read_bytes() == b"existing unrelated photo"
    assert collision.exists() is existing
    if existing:
        assert collision.read_bytes() == converted.data
    assert {p.name for p in case.photos.iterdir()} == ({unrelated.name, collision.name} if existing else {unrelated.name})
    with case.factory() as db:
        row = db.get(AttendancePerson, person_id)
        assert row.photo_file_name is row.photo_sha256 is None


def test_photo_cancellation_shields_cleanup_on_both_databases(attendance_case, monkeypatch):
    case = attendance_case
    _, person_id = seed_person(case)

    async def run():
        with case.factory() as db:
            with CancelScope() as scope:
                def cancel_commit():
                    scope.cancel()
                    raise asyncio.CancelledError

                monkeypatch.setattr(db, "commit", cancel_commit)
                with pytest.raises(asyncio.CancelledError):
                    await attendance.import_person_photo("wire-reader", "001", PhotoBody(png()), db, None)
                assert scope.cancel_called

    asyncio.run(run())
    assert not list(case.photos.glob("*.webp"))
    with case.factory() as db:
        row = db.get(AttendancePerson, person_id)
        assert row.photo_file_name is row.photo_sha256 is None


@pytest.mark.parametrize("token,disabled,expected,status", [
    ("wrong", False, b'{"detail":"Invalid attendance integration credentials"}', 401),
    (MANAGED_TOKEN, True, b'{"detail":"Attendance device synchronization is disabled"}', 403),
])
def test_photo_auth_error_bytes_before_body_processing(attendance_case, token, disabled, expected, status):
    case = attendance_case
    managed(case, enabled=not disabled)
    assert_bytes(upload(case, b"", token=token), expected, status)
    assert not case.photos.exists()


def test_photo_body_identity_and_missing_row_error_precedence(attendance_case, monkeypatch):
    case = attendance_case
    assert_bytes(upload(case, b"", key="missing"), b'{"detail":"Photo body is empty"}', 400)
    assert_bytes(upload(case, b"data", key="missing", length=settings.ATTENDANCE_PHOTO_MAX_BYTES + 1), b'{"detail":"Photo is too large"}', 413)
    assert_bytes(upload(case, b"data", key="missing"), b'{"detail":"Attendance device not found"}', 404)
    managed(case)
    with case.factory() as db:
        db.add(AttendanceDevice(factory_code="ECO", device_key="other-reader", name="Other reader"))
        db.commit()
    assert_bytes(upload(case, b"data", key="other-reader", token=MANAGED_TOKEN), b'{"detail":"Connector token does not belong to this attendance device"}', 403)
    assert_bytes(upload(case, b"data", key="managed-reader", token=MANAGED_TOKEN), b'{"detail":"Attendance person not found"}', 404)
    monkeypatch.setattr(settings, "ATTENDANCE_PHOTO_MAX_BYTES", 3)
    assert_bytes(upload(case, b"data", key="missing", length=0), b'{"detail":"Photo is too large"}', 413)
