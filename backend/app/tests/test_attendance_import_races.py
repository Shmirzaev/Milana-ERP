from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from functools import partial
from io import BytesIO
import os
from pathlib import Path
from queue import Queue
from threading import Barrier, BrokenBarrierError, Event, current_thread
from time import monotonic, sleep
from uuid import uuid4

import pytest
from PIL import Image
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.api.routes import attendance
from app.core.uploads import UploadCommitState, _run_upload_db_work
from app.db.base import Base
from app.models import AttendanceDevice, AttendanceEvent, AttendancePerson, SystemSetting


@pytest.fixture(scope="module")
def attendance_postgres_sessions():
    raw_url = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw_url:
        pytest.skip("Set STABILIZATION_POSTGRES_URL for real PostgreSQL attendance race coverage")
    url = make_url(raw_url)
    if url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"} or url.query:
        pytest.fail("Attendance race tests require a loopback PostgreSQL URL without connection overrides")
    schema = f"attendance_imports_{uuid4().hex}"
    engine = create_engine(
        url,
        connect_args={"options": f"-csearch_path={schema} -clock_timeout=15000 -cstatement_timeout=20000"},
        pool_size=4,
        max_overflow=0,
        isolation_level="READ COMMITTED",
    )
    assert engine.dialect.name == "postgresql"
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        Base.metadata.create_all(engine)
        yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False), engine
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()


def _device(device_key: str) -> dict:
    return {
        "device_key": device_key,
        "name": f"Synthetic {device_key}",
        "vendor": "Hikvision",
        "source_host": "127.0.0.1",
        "reported_person_count": 1,
    }


def _person(employee_no: str, name: str) -> dict:
    return {
        "external_person_id": employee_no,
        "full_name": name,
        "is_valid": True,
        "has_face": False,
        "card_count": 0,
        "fingerprint_count": 0,
    }


def _people_payload(
    device_key: str,
    employee_no: str,
    name: str,
    source_snapshot_at: datetime | None = None,
):
    return attendance.PeopleSnapshotIn(
        device=_device(device_key),
        people=[_person(employee_no, name)],
        full_snapshot=True,
        source_snapshot_at=source_snapshot_at,
    )


def _event_payload(
    device_key: str,
    event_uid: str,
    employee_no: str,
    source_snapshot_at: datetime | None = None,
):
    return attendance.EventBatchIn(
        device=_device(device_key),
        events=[{
            "event_uid": event_uid,
            "external_person_id": employee_no,
            "occurred_at": "2026-08-17T08:00:00+05:00",
            "result": "success",
        }],
        source_snapshot_at=source_snapshot_at,
    )


def _call(session_factory, function, payload):
    with session_factory() as db:
        try:
            return function(payload, db, identity=None)
        except Exception as exc:  # Returned so both concurrent outcomes remain observable.
            db.rollback()
            return exc


def _photo_bytes() -> bytes:
    stream = BytesIO()
    Image.new("RGB", (12, 12), (40, 50, 60)).save(stream, format="PNG")
    return stream.getvalue()


def test_postgres_concurrent_photo_retries_serialize_before_file_assignment(
    attendance_postgres_sessions, tmp_path
):
    sessions, engine = attendance_postgres_sessions
    device_key = f"photo-race-{uuid4().hex}"
    external_person_id = "photo-race-person"
    with sessions() as db:
        device = AttendanceDevice(
            factory_code="MIL",
            device_key=device_key,
            name="Photo race device",
            vendor="Hikvision",
        )
        db.add(device)
        db.flush()
        person = AttendancePerson(
            factory_code="MIL",
            device_id=device.id,
            external_person_id=external_person_id,
            full_name="Photo race person",
            last_synced_at=datetime.now(timezone.utc),
        )
        db.add(person)
        db.commit()
        device_id = int(device.id)
        person_id = int(person.id)

    lock_barrier = Barrier(2)
    lock_statements = []

    def align_person_locks(_connection, _cursor, statement, _parameters, _context, _many):
        normalized = " ".join(statement.upper().split())
        if "FROM ATTENDANCE_PEOPLE" not in normalized or "FOR UPDATE" not in normalized:
            return
        lock_statements.append(normalized)
        try:
            lock_barrier.wait(timeout=2)
        except BrokenBarrierError:
            pass

    event.listen(engine, "before_cursor_execute", align_person_locks)

    def worker():
        file_state = attendance._AttendancePhotoFileState()
        commit_state = UploadCommitState()
        try:
            return _run_upload_db_work(
                sessions,
                partial(
                    attendance._store_attendance_photo,
                    factory_code="MIL",
                    device_key=device_key,
                    external_person_id=external_person_id,
                    identity_device_id=device_id,
                    content=_photo_bytes(),
                    photo_root=tmp_path,
                    file_state=file_state,
                ),
                commit=True,
                commit_state=commit_state,
                failure_cleanup=partial(attendance._discard_attendance_photo, file_state),
            )
        except Exception as exc:
            return exc

    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = [future.result(timeout=10) for future in [
                workers.submit(worker),
                workers.submit(worker),
            ]]
    finally:
        event.remove(engine, "before_cursor_execute", align_person_locks)

    assert not [result for result in results if isinstance(result, Exception)], results
    assert sorted(result["updated"] for result in results) == [False, True]
    assert len(lock_statements) == 2
    stored_files = [path for path in Path(tmp_path).iterdir() if path.is_file()]
    assert len(stored_files) == 1
    with sessions() as db:
        person = db.get(AttendancePerson, person_id)
        assert person.photo_file_name == stored_files[0].name
        assert person.photo_sha256 == results[0]["photo_sha256"] == results[1]["photo_sha256"]


def _align_queries(engine, fragment: str):
    barrier = Barrier(2)

    def align(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT") and fragment in statement:
            try:
                barrier.wait(timeout=0.75)
            except BrokenBarrierError:
                pass

    event.listen(engine, "before_cursor_execute", align)
    return align


def test_postgres_concurrent_duplicate_event_batches_are_idempotent(attendance_postgres_sessions):
    sessions, _engine = attendance_postgres_sessions
    device_key = f"duplicate-events-{uuid4().hex}"
    assert not isinstance(_call(sessions, attendance.import_people_snapshot,
                                _people_payload(device_key, "880001", "Duplicate event")), Exception)
    payload = _event_payload(device_key, "same-event", "880001")
    ready = Queue()

    def worker():
        with sessions() as db:
            ready.put(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
            try:
                return attendance.import_events(payload, db, identity=None)
            except Exception as exc:
                db.rollback()
                return exc

    with sessions() as holder, ThreadPoolExecutor(max_workers=2) as workers:
        holder.execute(
            text("SELECT pg_advisory_xact_lock(:namespace, hashtext(:resource))"),
            {
                "namespace": attendance.ATTENDANCE_IMPORT_LOCK_NAMESPACE,
                "resource": f"MIL:{device_key}",
            },
        )
        futures = [workers.submit(worker) for _ in range(2)]
        try:
            worker_pids = [ready.get(timeout=10) for _ in futures]
            deadline = monotonic() + 10
            while monotonic() < deadline:
                blockers = [
                    holder.execute(text("SELECT pg_blocking_pids(:pid)"), {"pid": pid}).scalar_one()
                    for pid in worker_pids
                ]
                if all(blockers):
                    break
                sleep(0.02)
            else:
                pytest.fail("Both event imports must reach the device advisory-lock wait")
        finally:
            holder.rollback()
        responses = [future.result(timeout=10) for future in futures]

    assert not [response for response in responses if isinstance(response, Exception)]
    assert sorted((response["inserted"], response["duplicates"]) for response in responses) == [(0, 1), (1, 0)]
    with sessions() as db:
        assert db.query(AttendanceEvent).filter_by(event_uid="same-event").count() == 1


def test_postgres_concurrent_rosters_create_one_person(attendance_postgres_sessions):
    sessions, engine = attendance_postgres_sessions
    device_key = f"duplicate-people-{uuid4().hex}"
    assert not isinstance(_call(sessions, attendance.import_events,
                                attendance.EventBatchIn(device=_device(device_key), events=[])), Exception)
    payload = _people_payload(device_key, "880002", "Concurrent person")
    align = _align_queries(engine, "attendance_people.external_person_id")
    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            responses = list(
                workers.map(lambda _: _call(sessions, attendance.import_people_snapshot, payload), range(2))
            )
    finally:
        event.remove(engine, "before_cursor_execute", align)

    assert not [response for response in responses if isinstance(response, Exception)]
    assert sorted(response["created"] for response in responses) == [0, 1]
    with sessions() as db:
        device = db.query(AttendanceDevice).filter_by(device_key=device_key).one()
        assert db.query(AttendancePerson).filter_by(device_id=device.id, external_person_id="880002").count() == 1


def test_postgres_earlier_roster_cannot_overwrite_newer_snapshot(attendance_postgres_sessions, monkeypatch):
    sessions, _engine = attendance_postgres_sessions
    device_key = f"stale-roster-{uuid4().hex}"
    newer = datetime(2026, 8, 17, 12, tzinfo=timezone.utc)
    older = datetime(2026, 8, 17, 11, tzinfo=timezone.utc)

    monkeypatch.setattr(attendance, "utcnow", lambda: newer)
    latest = _call(
        sessions,
        attendance.import_people_snapshot,
        _people_payload(device_key, "880003", "Current profile"),
    )
    monkeypatch.setattr(attendance, "utcnow", lambda: older)
    stale = _call(
        sessions,
        attendance.import_people_snapshot,
        _people_payload(device_key, "880004", "Stale profile"),
    )

    assert latest["ignored"] is False
    assert stale == {
        "device_id": latest["device_id"],
        "received": 1,
        "created": 0,
        "updated": 0,
        "marked_absent": 0,
        "reported_person_count": 1,
        "ignored": True,
    }
    with sessions() as db:
        people = db.query(AttendancePerson).join(AttendanceDevice).filter(
            AttendanceDevice.device_key == device_key,
        ).all()
        assert [(person.external_person_id, person.full_name, person.present_on_device) for person in people] == [
            ("880003", "Current profile", True),
        ]


def test_postgres_older_blocked_roster_is_ignored_after_newer_commit(
    attendance_postgres_sessions,
    monkeypatch,
):
    sessions, _engine = attendance_postgres_sessions
    device_key = f"overtaken-roster-{uuid4().hex}"
    newer = datetime(2026, 8, 17, 12, tzinfo=timezone.utc)
    older = datetime(2026, 8, 17, 11, tzinfo=timezone.utc)
    older_waiting = Event()
    release_older = Event()
    original_lock = attendance._lock_attendance_import

    monkeypatch.setattr(
        attendance,
        "utcnow",
        lambda: older if current_thread().name.startswith("older-roster") else newer,
    )

    def pause_older_before_lock(db, factory_code, key):
        if current_thread().name.startswith("older-roster"):
            older_waiting.set()
            assert release_older.wait(10), "Older roster was not released"
        return original_lock(db, factory_code, key)

    monkeypatch.setattr(attendance, "_lock_attendance_import", pause_older_before_lock)
    older_payload = _people_payload(device_key, "880006", "Overtaken profile")
    newer_payload = _people_payload(device_key, "880007", "Winning profile")
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="older-roster") as worker:
        older_future = worker.submit(_call, sessions, attendance.import_people_snapshot, older_payload)
        assert older_waiting.wait(10), "Older roster did not reach the pre-lock pause"
        winning = _call(sessions, attendance.import_people_snapshot, newer_payload)
        release_older.set()
        overtaken = older_future.result(timeout=10)

    assert winning["ignored"] is False
    assert overtaken["ignored"] is True
    with sessions() as db:
        people = db.query(AttendancePerson).join(AttendanceDevice).filter(
            AttendanceDevice.device_key == device_key,
        ).all()
        assert [(person.external_person_id, person.full_name, person.present_on_device) for person in people] == [
            ("880007", "Winning profile", True),
        ]


def test_postgres_older_blocked_events_keep_newer_device_metadata(
    attendance_postgres_sessions,
    monkeypatch,
):
    sessions, _engine = attendance_postgres_sessions
    device_key = f"overtaken-events-{uuid4().hex}"
    newer = datetime(2026, 8, 17, 12, tzinfo=timezone.utc)
    older = datetime(2026, 8, 17, 11, tzinfo=timezone.utc)
    older_waiting = Event()
    release_older = Event()
    original_lock = attendance._lock_attendance_import

    monkeypatch.setattr(
        attendance,
        "utcnow",
        lambda: older if current_thread().name.startswith("older-events") else newer,
    )

    def pause_older_before_lock(db, factory_code, key):
        if current_thread().name.startswith("older-events"):
            older_waiting.set()
            assert release_older.wait(10), "Older event batch was not released"
        return original_lock(db, factory_code, key)

    monkeypatch.setattr(attendance, "_lock_attendance_import", pause_older_before_lock)
    older_payload = _event_payload(device_key, "older-event", "880008")
    older_payload.device.name = "Stale turnstile"
    older_payload.device.model = "DS-stale"
    older_payload.device.source_host = "10.100.50.11"
    newer_payload = _event_payload(device_key, "newer-event", "880008")
    newer_payload.device.name = "Current turnstile"
    newer_payload.device.model = "DS-current"
    newer_payload.device.source_host = "10.100.50.12"

    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="older-events") as worker:
        older_future = worker.submit(_call, sessions, attendance.import_events, older_payload)
        assert older_waiting.wait(10), "Older event batch did not reach the pre-lock pause"
        winning = _call(sessions, attendance.import_events, newer_payload)
        release_older.set()
        overtaken = older_future.result(timeout=10)

    assert winning["inserted"] == 1
    assert overtaken["inserted"] == 1
    with sessions() as db:
        device = db.query(AttendanceDevice).filter_by(device_key=device_key).one()
        assert (device.name, device.model, device.source_host) == (
            "Current turnstile",
            "DS-current",
            "10.100.50.12",
        )
        assert device.last_seen_at == newer
        assert device.last_event_sync_at == newer
        assert {
            event_uid
            for (event_uid,) in db.query(AttendanceEvent.event_uid).filter_by(device_id=device.id)
        } == {"newer-event", "older-event"}


def test_postgres_late_older_source_roster_cannot_regress_newer_snapshot(
    attendance_postgres_sessions,
    monkeypatch,
):
    sessions, _engine = attendance_postgres_sessions
    device_key = f"versioned-roster-{uuid4().hex}"
    older_waiting = Event()
    release_older = Event()
    original_lock = attendance._lock_attendance_import

    def pause_older_before_lock(db, factory_code, key):
        if current_thread().name.startswith("source-old-roster"):
            older_waiting.set()
            assert release_older.wait(10), "Older source roster was not released"
        return original_lock(db, factory_code, key)

    monkeypatch.setattr(attendance, "_lock_attendance_import", pause_older_before_lock)
    older_payload = _people_payload(
        device_key,
        "880009",
        "Old source profile",
        datetime(2026, 9, 20, 11, tzinfo=timezone.utc),
    )
    newer_payload = _people_payload(
        device_key,
        "880010",
        "Current source profile",
        datetime(2026, 9, 20, 12, tzinfo=timezone.utc),
    )
    older_payload.device.name = "Old source turnstile"
    newer_payload.device.name = "Current source turnstile"
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="source-old-roster") as worker:
        older_future = worker.submit(_call, sessions, attendance.import_people_snapshot, older_payload)
        assert older_waiting.wait(10), "Older source roster did not reach the pre-lock pause"
        winning = _call(sessions, attendance.import_people_snapshot, newer_payload)
        release_older.set()
        overtaken = older_future.result(timeout=10)

    assert not isinstance(winning, Exception)
    assert not isinstance(overtaken, Exception)
    assert winning["ignored"] is False
    assert overtaken["ignored_reason"] == "stale_source_version"
    with sessions() as db:
        device = db.query(AttendanceDevice).filter_by(device_key=device_key).one()
        people = db.query(AttendancePerson).filter_by(device_id=device.id).all()
        checkpoint = db.query(SystemSetting).filter_by(
            key=attendance._source_setting_key("MIL", device_key),
        ).one()

    assert device.name == "Current source turnstile"
    assert [(person.external_person_id, person.full_name) for person in people] == [
        ("880010", "Current source profile"),
    ]
    assert checkpoint.value_json["people_snapshot_at"] == "2026-09-20T12:00:00+00:00"


def test_postgres_late_older_source_events_insert_without_metadata_regression(
    attendance_postgres_sessions,
    monkeypatch,
):
    sessions, _engine = attendance_postgres_sessions
    device_key = f"versioned-events-{uuid4().hex}"
    older_waiting = Event()
    release_older = Event()
    original_lock = attendance._lock_attendance_import

    def pause_older_before_lock(db, factory_code, key):
        if current_thread().name.startswith("source-old-events"):
            older_waiting.set()
            assert release_older.wait(10), "Older source events were not released"
        return original_lock(db, factory_code, key)

    monkeypatch.setattr(attendance, "_lock_attendance_import", pause_older_before_lock)
    older_payload = _event_payload(
        device_key,
        "source-old-event",
        "880011",
        datetime(2026, 9, 20, 11, tzinfo=timezone.utc),
    )
    newer_payload = _event_payload(
        device_key,
        "source-new-event",
        "880011",
        datetime(2026, 9, 20, 12, tzinfo=timezone.utc),
    )
    older_payload.device.name = "Old event metadata"
    older_payload.device.source_host = "10.100.50.21"
    newer_payload.device.name = "Current event metadata"
    newer_payload.device.source_host = "10.100.50.22"
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="source-old-events") as worker:
        older_future = worker.submit(_call, sessions, attendance.import_events, older_payload)
        assert older_waiting.wait(10), "Older source events did not reach the pre-lock pause"
        winning = _call(sessions, attendance.import_events, newer_payload)
        release_older.set()
        overtaken = older_future.result(timeout=10)

    assert not isinstance(winning, Exception)
    assert not isinstance(overtaken, Exception)
    assert winning["inserted"] == 1
    assert overtaken["inserted"] == 1
    assert overtaken["metadata_ignored_reason"] == "stale_source_version"
    with sessions() as db:
        device = db.query(AttendanceDevice).filter_by(device_key=device_key).one()
        event_uids = {
            uid for (uid,) in db.query(AttendanceEvent.event_uid).filter_by(device_id=device.id)
        }
        checkpoint = db.query(SystemSetting).filter_by(
            key=attendance._source_setting_key("MIL", device_key),
        ).one()

    assert (device.name, device.source_host) == ("Current event metadata", "10.100.50.22")
    assert event_uids == {"source-old-event", "source-new-event"}
    assert checkpoint.value_json["metadata_snapshot_at"] == "2026-09-20T12:00:00+00:00"
    assert checkpoint.value_json["event_snapshot_at"] == "2026-09-20T12:00:00+00:00"


def test_postgres_concurrent_roster_and_events_create_one_device(attendance_postgres_sessions):
    sessions, engine = attendance_postgres_sessions
    device_key = f"new-device-{uuid4().hex}"
    people = _people_payload(device_key, "880005", "Roster and event")
    events = _event_payload(device_key, "roster-event", "880005")
    align = _align_queries(engine, "attendance_devices.device_key")
    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            people_future = workers.submit(_call, sessions, attendance.import_people_snapshot, people)
            events_future = workers.submit(_call, sessions, attendance.import_events, events)
            responses = [people_future.result(timeout=15), events_future.result(timeout=15)]
    finally:
        event.remove(engine, "before_cursor_execute", align)

    assert not [response for response in responses if isinstance(response, Exception)]
    with sessions() as db:
        devices = db.query(AttendanceDevice).filter_by(device_key=device_key).all()
        assert len(devices) == 1
        assert db.query(AttendancePerson).filter_by(device_id=devices[0].id).count() == 1
        assert db.query(AttendanceEvent).filter_by(device_id=devices[0].id).count() == 1
