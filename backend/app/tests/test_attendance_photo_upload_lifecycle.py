import asyncio
import hashlib
import threading
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import HTTPException
from PIL import Image
from sqlalchemy import event

from app.api.routes import attendance
from app.models import AttendanceDevice, AttendancePerson
from app.services.image_storage import convert_image_to_webp
from app.tests.conftest import TestSessionLocal, test_engine
from app.tests.upload_test_support import failing_upload_session_factory


INTEGRATION_HEADERS = {"X-Attendance-Token": "test-attendance-token"}


class _RequestBody:
    def __init__(self, content: bytes):
        self._content = content
        self.headers = {"content-length": str(len(content))}

    async def stream(self):
        yield self._content


def _png_bytes() -> bytes:
    data = BytesIO()
    Image.new("RGB", (12, 12), (40, 50, 60)).save(data, format="PNG")
    return data.getvalue()


def _seed_person(client) -> tuple[int, int]:
    response = client.post(
        "/api/attendance/integration/people",
        headers=INTEGRATION_HEADERS,
        json={
            "device": {
                "device_key": "main-turnstile",
                "name": "Main Turnstile",
                "vendor": "Hikvision",
                "reported_person_count": 1,
            },
            "people": [{
                "external_person_id": "735",
                "full_name": "Photo lifecycle person",
                "is_valid": True,
                "has_face": True,
                "card_count": 0,
                "fingerprint_count": 0,
            }],
            "full_snapshot": True,
        },
    )
    assert response.status_code == 200, response.text
    with TestSessionLocal() as db:
        device_id = int(db.query(AttendanceDevice.id).filter_by(device_key="main-turnstile").one()[0])
        person_id = int(db.query(AttendancePerson.id).filter_by(
            device_id=device_id,
            external_person_id="735",
        ).one()[0])
    return device_id, person_id


def _photo_state(person_id: int) -> tuple[str | None, str | None]:
    with TestSessionLocal() as db:
        person = db.get(AttendancePerson, person_id)
        return person.photo_file_name, person.photo_sha256


def _stored_files(root: Path) -> set[Path]:
    return {path.relative_to(root) for path in root.rglob("*") if path.is_file()}


def test_attendance_photo_staging_cleanup_failure_does_not_orphan_linked_file(tmp_path, monkeypatch):
    destination = tmp_path / "person.webp"
    original_unlink = Path.unlink
    failed_once = False

    def fail_first_temporary_unlink(path, *args, **kwargs):
        nonlocal failed_once
        if path.suffix == ".tmp" and not failed_once:
            failed_once = True
            raise OSError("synthetic temporary cleanup failure")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_first_temporary_unlink)

    with pytest.raises(OSError, match="synthetic temporary cleanup failure"):
        attendance._write_new_attendance_photo(destination, b"synthetic photo")

    assert not destination.exists()
    assert _stored_files(tmp_path) == set()


def test_attendance_person_photo_read_projects_only_photo_fields(client, auth_headers, tmp_path, monkeypatch):
    _device_id, person_id = _seed_person(client)
    monkeypatch.setattr(attendance.settings, "ATTENDANCE_PHOTOS_DIR", str(tmp_path))
    filename = "stored-person-photo.webp"
    photo_bytes = b"photo bytes"
    (tmp_path / filename).write_bytes(photo_bytes)
    with TestSessionLocal() as db:
        person = db.get(AttendancePerson, person_id)
        person.photo_file_name = filename
        db.commit()

    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        normalized = " ".join(statement.lower().split())
        if normalized.startswith("select") and " from attendance_people " in normalized:
            statements.append(normalized)

    event.listen(test_engine, "before_cursor_execute", capture)
    try:
        response = client.get(f"/api/attendance/people/{person_id}/photo", headers=auth_headers)
    finally:
        event.remove(test_engine, "before_cursor_execute", capture)

    assert response.status_code == 200, response.text
    assert response.content == photo_bytes
    assert len(statements) == 1, statements
    assert "attendance_people.photo_file_name" in statements[0]
    assert "attendance_people.full_name" not in statements[0]
    assert "attendance_people.external_person_id" not in statements[0]


def test_attendance_photo_wrong_managed_device_is_rejected_before_body_read(
    client, tmp_path, monkeypatch
):
    _device_id, person_id = _seed_person(client)
    before = _photo_state(person_id)
    monkeypatch.setattr(attendance.settings, "ATTENDANCE_PHOTOS_DIR", str(tmp_path))

    class _UnreadRequest:
        headers = {}

        async def stream(self):
            pytest.fail("An unauthorized upload must not read its request body")
            yield b""

    with TestSessionLocal() as db:
        wrong_identity = AttendanceDevice(
            factory_code="MIL",
            device_key="other-managed-device",
            name="Other managed device",
            vendor="Hikvision",
        )
        db.add(wrong_identity)
        db.commit()
        db.refresh(wrong_identity)
        with pytest.raises(HTTPException) as raised:
            asyncio.run(attendance.import_person_photo(
                "main-turnstile",
                "735",
                _UnreadRequest(),
                db,
                wrong_identity,
            ))

    assert raised.value.status_code == 403
    assert _photo_state(person_id) == before
    assert _stored_files(tmp_path) == set()


def test_attendance_photo_commit_failure_removes_only_new_file(client, tmp_path, monkeypatch):
    device_id, person_id = _seed_person(client)
    before = _photo_state(person_id)
    existing = tmp_path / "existing-photo.webp"
    existing.write_bytes(b"keep existing photo")
    monkeypatch.setattr(attendance.settings, "ATTENDANCE_PHOTOS_DIR", str(tmp_path))

    with TestSessionLocal() as db:
        identity = db.get(AttendanceDevice, device_id)
        monkeypatch.setattr(
            attendance,
            "upload_session_factory",
            lambda _db: failing_upload_session_factory(
                db, "Synthetic attendance photo commit failure"
            ),
        )
        with pytest.raises(RuntimeError, match="Synthetic attendance photo commit failure"):
            asyncio.run(attendance.import_person_photo(
                "main-turnstile",
                "735",
                _RequestBody(_png_bytes()),
                db,
                identity,
            ))

    assert existing.read_bytes() == b"keep existing photo"
    assert _stored_files(tmp_path) == {Path(existing.name)}
    assert _photo_state(person_id) == before


def test_attendance_photo_worker_cancellation_removes_new_file_before_unlock(
    client, tmp_path, monkeypatch
):
    device_id, person_id = _seed_person(client)
    before = _photo_state(person_id)
    existing = tmp_path / "existing-photo.webp"
    existing.write_bytes(b"keep existing photo")
    monkeypatch.setattr(attendance.settings, "ATTENDANCE_PHOTOS_DIR", str(tmp_path))

    monkeypatch.setattr(
        attendance,
        "_set_attendance_photo",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(asyncio.CancelledError()),
    )
    with TestSessionLocal() as db:
        identity = db.get(AttendanceDevice, device_id)
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(attendance.import_person_photo(
                "main-turnstile",
                "735",
                _RequestBody(_png_bytes()),
                db,
                identity,
            ))

    assert existing.read_bytes() == b"keep existing photo"
    assert _stored_files(tmp_path) == {Path(existing.name)}
    assert _photo_state(person_id) == before


def test_attendance_photo_failed_commit_preserves_preexisting_digest_file(client, tmp_path, monkeypatch):
    device_id, person_id = _seed_person(client)
    before = _photo_state(person_id)
    content = _png_bytes()
    converted = convert_image_to_webp(content)
    digest = hashlib.sha256(converted.data).hexdigest()
    collision = tmp_path / f"{device_id}_{person_id}_{digest[:20]}.webp"
    collision.write_bytes(converted.data)
    monkeypatch.setattr(attendance.settings, "ATTENDANCE_PHOTOS_DIR", str(tmp_path))

    with TestSessionLocal() as db:
        identity = db.get(AttendanceDevice, device_id)
        monkeypatch.setattr(
            attendance,
            "upload_session_factory",
            lambda _db: failing_upload_session_factory(
                db, "Synthetic preexisting photo commit failure"
            ),
        )
        with pytest.raises(RuntimeError, match="Synthetic preexisting photo commit failure"):
            asyncio.run(attendance.import_person_photo(
                "main-turnstile",
                "735",
                _RequestBody(content),
                db,
                identity,
            ))

    assert collision.read_bytes() == converted.data
    assert _stored_files(tmp_path) == {Path(collision.name)}
    assert _photo_state(person_id) == before


def test_attendance_photo_upload_limiter_bounds_body_read_and_conversion(client, tmp_path, monkeypatch):
    device_id, _ = _seed_person(client)
    monkeypatch.setattr(attendance.settings, "ATTENDANCE_PHOTOS_DIR", str(tmp_path))
    content = _png_bytes()
    first_body_read = asyncio.Event()
    second_body_read = asyncio.Event()
    conversion_started = threading.Event()
    release_conversion = threading.Event()
    original_convert = attendance.convert_image_to_webp
    event_loop_thread = threading.get_ident()

    def block_conversion(data: bytes):
        assert threading.get_ident() != event_loop_thread
        conversion_started.set()
        if not release_conversion.wait(timeout=5):
            raise TimeoutError("Timed out waiting to release photo conversion")
        return original_convert(data)

    monkeypatch.setattr(attendance, "convert_image_to_webp", block_conversion)

    class _TrackedRequest(_RequestBody):
        def __init__(self, *, second: bool):
            super().__init__(content)
            self._read_event = second_body_read if second else first_body_read

        async def stream(self):
            self._read_event.set()
            yield self._content

    async def run_upload(request: _TrackedRequest):
        with TestSessionLocal() as db:
            identity = db.get(AttendanceDevice, device_id)
            return await attendance.import_person_photo(
                "main-turnstile", "735", request, db, identity
            )

    async def run_concurrent_uploads():
        first = asyncio.create_task(run_upload(_TrackedRequest(second=False)))
        await asyncio.wait_for(first_body_read.wait(), timeout=2)
        await asyncio.wait_for(asyncio.to_thread(conversion_started.wait, 2), timeout=3)
        second = asyncio.create_task(run_upload(_TrackedRequest(second=True)))
        try:
            await asyncio.sleep(0.05)
            assert not second_body_read.is_set()
        finally:
            release_conversion.set()
        results = await asyncio.gather(first, second)
        assert second_body_read.is_set()
        assert all(result["photo_sha256"] for result in results)

    asyncio.run(run_concurrent_uploads())


def test_attendance_photo_raw_task_cancellation_waits_for_worker_commit(
    client, tmp_path, monkeypatch
):
    device_id, person_id = _seed_person(client)
    monkeypatch.setattr(attendance.settings, "ATTENDANCE_PHOTOS_DIR", str(tmp_path))
    mutation_started = threading.Event()
    release_mutation = threading.Event()
    original_set_photo = attendance._set_attendance_photo

    def block_after_mutation(person, *, file_name: str, digest: str):
        original_set_photo(person, file_name=file_name, digest=digest)
        mutation_started.set()
        if not release_mutation.wait(timeout=5):
            raise TimeoutError("Timed out waiting to release attendance photo transaction")

    monkeypatch.setattr(attendance, "_set_attendance_photo", block_after_mutation)

    async def run():
        with TestSessionLocal() as db:
            identity = db.get(AttendanceDevice, device_id)
            task = asyncio.create_task(attendance.import_person_photo(
                "main-turnstile",
                "735",
                _RequestBody(_png_bytes()),
                db,
                identity,
            ))
            await asyncio.wait_for(asyncio.to_thread(mutation_started.wait, 2), timeout=3)
            task.cancel()
            release_mutation.set()
            with pytest.raises(asyncio.CancelledError):
                await task

    asyncio.run(run())

    file_name, digest = _photo_state(person_id)
    assert file_name is not None
    assert digest is not None
    stored = tmp_path / file_name
    assert stored.is_file()
    assert hashlib.sha256(stored.read_bytes()).hexdigest() == digest


def test_attendance_photo_rejects_oversize_stream_before_buffering_or_decoding(client, tmp_path, monkeypatch):
    device_id, person_id = _seed_person(client)
    before = _photo_state(person_id)
    monkeypatch.setattr(attendance.settings, "ATTENDANCE_PHOTOS_DIR", str(tmp_path))
    monkeypatch.setattr(attendance.settings, "ATTENDANCE_PHOTO_MAX_BYTES", 4)

    class _OversizedRequest:
        headers = {}

        def __init__(self):
            self.read_chunks = 0

        async def stream(self):
            for chunk in (b"1234", b"5", b"unread remainder"):
                self.read_chunks += 1
                yield chunk

        async def body(self):
            raise AssertionError("The upload route must consume the bounded stream")

    request = _OversizedRequest()
    monkeypatch.setattr(
        attendance,
        "convert_image_to_webp",
        lambda _: pytest.fail("Oversized uploads must not be decoded"),
    )

    with TestSessionLocal() as db:
        identity = db.get(AttendanceDevice, device_id)
        with pytest.raises(HTTPException) as raised:
            asyncio.run(attendance.import_person_photo(
                "main-turnstile", "735", request, db, identity
            ))

    assert getattr(raised.value, "status_code", None) == 413
    assert request.read_chunks == 2
    assert _photo_state(person_id) == before
    assert _stored_files(tmp_path) == set()
