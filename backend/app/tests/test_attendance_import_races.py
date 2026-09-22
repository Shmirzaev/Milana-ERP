from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import os
from queue import Queue
from threading import Barrier, BrokenBarrierError, Event, current_thread
from time import monotonic, sleep
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.api.routes import attendance
from app.db.base import Base
from app.models import AttendanceDevice, AttendanceEvent, AttendancePerson


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


def _people_payload(device_key: str, employee_no: str, name: str):
    return attendance.PeopleSnapshotIn(
        device=_device(device_key),
        people=[_person(employee_no, name)],
        full_snapshot=True,
    )


def _event_payload(device_key: str, event_uid: str, employee_no: str):
    return attendance.EventBatchIn(
        device=_device(device_key),
        events=[{
            "event_uid": event_uid,
            "external_person_id": employee_no,
            "occurred_at": "2026-08-17T08:00:00+05:00",
            "result": "success",
        }],
    )


def _call(session_factory, function, payload):
    with session_factory() as db:
        try:
            return function(payload, db, identity=None)
        except Exception as exc:  # Returned so both concurrent outcomes remain observable.
            db.rollback()
            return exc


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
