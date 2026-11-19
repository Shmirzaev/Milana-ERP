"""Connector event-batch bytes, idempotency and source reconciliation baseline."""

from datetime import timedelta

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.api.routes import attendance
from app.core.dt import as_utc
from app.schemas import AttendanceDevice, AttendanceEvent, AttendancePerson, AuditLog, Employee, SystemSetting
from app.tests.test_attendance_people_import_operation import (
    MANAGED_TOKEN, NOW, assert_bytes, assert_openapi, attendance_case, attendance_database,  # noqa: F401
    managed, person, post_json, roster,
)


def batch(*events, source="2026-10-20T11:30:00Z", key="wire-reader", name="Wire reader"):
    payload = {"device": {"device_key": key, "name": name}, "events": list(events)}
    if source is not None:
        payload["source_snapshot_at"] = source
    return payload


def punch(uid, external_id, occurred="2026-10-20T08:00:00+05:00", direction="entry", result="success"):
    return {"event_uid": uid, "external_person_id": external_id, "occurred_at": occurred,
            "direction": direction, "verification_mode": "face", "result": result,
            "door_no": 1, "reader_no": 2, "serial_no": 3}


def test_event_connector_bytes_duplicates_out_of_order_and_unmatched_people(attendance_case):
    case = attendance_case
    seeded = post_json(case, "/api/attendance/integration/people", roster(person("001", "Mirrored person")))
    assert seeded.status_code == 200
    payload = batch(punch("late", "001", "2026-10-20T18:00:00+05:00", " EXIT "),
                    punch("early", "001", direction="unrecognized", result="denied"),
                    punch("unknown", "unregistered"), punch("no-person", None))
    first = post_json(case, "/api/attendance/integration/events", payload)
    assert_bytes(first, b'{"received":4,"inserted":4,"duplicates":0,"metadata_ignored":false}')
    repeated = post_json(case, "/api/attendance/integration/events", payload)
    assert_bytes(repeated, b'{"received":4,"inserted":0,"duplicates":4,"metadata_ignored":true,"metadata_ignored_reason":"stale_source_version"}')
    with case.factory() as db:
        person_id = db.query(AttendancePerson.id).scalar()
        rows = db.query(AttendanceEvent).order_by(AttendanceEvent.id).all()
        assert [(row.event_uid, row.external_person_id, row.person_id, row.direction, row.result) for row in rows] == [
            ("late", "001", person_id, "exit", "success"), ("early", "001", person_id, "unknown", "denied"),
            ("unknown", "unregistered", None, "entry", "success"), ("no-person", None, None, "entry", "success"),
        ]
        assert as_utc(rows[0].occurred_at) > as_utc(rows[1].occurred_at)
        assert all(as_utc(row.received_at) == NOW and row.factory_code == "MIL" for row in rows)
        assert db.query(Employee).count() == db.query(AuditLog).count() == 0
    assert_openapi("/api/attendance/integration/events", "0eee2c37af0c17fa33dfc0dc6847cc5a7e8491cee863cd4f0438269a52b31fb3")


@pytest.mark.parametrize("source,reason", [("2026-10-20T10:00:00Z", "stale_source_version"), (None, "missing_source_version")])
def test_event_history_imports_without_regressing_versioned_metadata(attendance_case, monkeypatch, source, reason):
    case = attendance_case
    first = post_json(case, "/api/attendance/integration/events", batch(punch("current", "unknown"), name="Current"))
    assert first.status_code == 200
    monkeypatch.setattr(attendance, "utcnow", lambda: NOW + timedelta(hours=1))
    older = post_json(case, "/api/attendance/integration/events", batch(punch("older", "unknown", "2026-10-19T08:00:00Z"), source=source, name="Stale"))
    assert_bytes(older, f'{{"received":1,"inserted":1,"duplicates":0,"metadata_ignored":true,"metadata_ignored_reason":"{reason}"}}'.encode())
    with case.factory() as db:
        device = db.query(AttendanceDevice).one()
        assert device.name == "Current"
        assert as_utc(device.last_event_sync_at) == NOW + timedelta(hours=1)
        checkpoint = db.query(SystemSetting).one().value_json
        assert checkpoint["metadata_snapshot_at"] == checkpoint["event_snapshot_at"] == "2026-10-20T11:30:00+00:00"
        assert db.query(AttendanceEvent).count() == 2


def test_event_empty_batch_auto_creates_global_device_without_people(attendance_case):
    case = attendance_case
    assert_bytes(post_json(case, "/api/attendance/integration/events", batch(source=None)),
                 b'{"received":0,"inserted":0,"duplicates":0,"metadata_ignored":false}')
    with case.factory() as db:
        assert db.query(AttendanceDevice).one().factory_code == "MIL"
        assert db.query(AttendancePerson).count() == db.query(AttendanceEvent).count() == 0


def test_event_duplicate_batch_rolls_back_new_device_and_identity_mismatch_wins(attendance_case):
    case = attendance_case
    payload = batch(punch("same", "001"), punch("same", "001"))
    assert_bytes(post_json(case, "/api/attendance/integration/events", payload), b'{"detail":"Duplicate event UID in batch"}', 400)
    with case.factory() as db:
        assert db.query(AttendanceDevice).count() == db.query(AttendanceEvent).count() == db.query(SystemSetting).count() == 0
    managed(case)
    assert_bytes(post_json(case, "/api/attendance/integration/events", payload, MANAGED_TOKEN),
                 b'{"detail":"Connector token does not belong to this attendance device"}', 403)


@pytest.mark.parametrize("token,disabled,expected,status", [
    ("wrong", False, b'{"detail":"Invalid attendance integration credentials"}', 401),
    (MANAGED_TOKEN, True, b'{"detail":"Attendance device synchronization is disabled"}', 403),
])
def test_event_auth_errors_preserve_exact_bytes_and_no_events(attendance_case, token, disabled, expected, status):
    case = attendance_case
    managed(case, enabled=not disabled)
    assert_bytes(post_json(case, "/api/attendance/integration/events", batch(punch("refused", None)), token), expected, status)
    with case.factory() as db:
        assert db.query(AttendanceEvent).count() == db.query(SystemSetting).count() == 0


def test_event_commit_failure_rolls_back_batch_device_and_checkpoint(attendance_case):
    case = attendance_case

    def fail_commit(session):
        raise RuntimeError("Synthetic attendance event commit failure")

    event.listen(Session, "before_commit", fail_commit)
    try:
        with pytest.raises(RuntimeError, match="Synthetic attendance event commit failure"):
            post_json(case, "/api/attendance/integration/events", batch(punch("rollback", None)))
    finally:
        event.remove(Session, "before_commit", fail_commit)
    with case.factory() as db:
        assert db.query(AttendanceDevice).count() == db.query(AttendanceEvent).count() == db.query(SystemSetting).count() == 0


def test_event_legacy_duplicate_receipt_includes_stale_receipt_reason(attendance_case):
    case = attendance_case
    payload = batch(punch("legacy", "unknown"), source=None)
    assert_bytes(post_json(case, "/api/attendance/integration/events", payload),
                 b'{"received":1,"inserted":1,"duplicates":0,"metadata_ignored":false}')
    assert_bytes(post_json(case, "/api/attendance/integration/events", payload),
                 b'{"received":1,"inserted":0,"duplicates":1,"metadata_ignored":true,"metadata_ignored_reason":"stale_receipt"}')
