from copy import deepcopy
from datetime import datetime, timezone

import pytest

from app.api.routes import attendance
from app.core.dt import as_utc
from app.models import AuditLog, AttendanceDevice, AttendanceEvent, AttendancePerson, SystemSetting
from app.tests.conftest import TestSessionLocal


INTEGRATION_HEADERS = {"X-Attendance-Token": "test-attendance-token"}


def _device(device_key: str, name: str, host: str) -> dict:
    return {
        "device_key": device_key,
        "name": name,
        "vendor": "Hikvision",
        "model": f"model-{name}",
        "serial_no": f"serial-{name}",
        "source_host": host,
        "reported_person_count": 1,
    }


def _roster(device_key: str, name: str, person_id: str, source_snapshot_at: str | None) -> dict:
    payload = {
        "device": _device(device_key, name, f"10.0.0.{person_id[-1]}"),
        "people": [{
            "external_person_id": person_id,
            "full_name": name,
            "is_valid": True,
        }],
        "full_snapshot": True,
    }
    if source_snapshot_at is not None:
        payload["source_snapshot_at"] = source_snapshot_at
    return payload


def _events(
    device_key: str,
    name: str,
    event_uid: str,
    source_snapshot_at: str | None,
) -> dict:
    payload = {
        "device": _device(device_key, name, f"10.0.1.{event_uid[-1]}"),
        "events": [{
            "event_uid": event_uid,
            "external_person_id": "735",
            "occurred_at": "2026-09-20T08:00:00Z",
        }],
    }
    if source_snapshot_at is not None:
        payload["source_snapshot_at"] = source_snapshot_at
    return payload


def _set_received_at(monkeypatch, value: str) -> None:
    received_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    monkeypatch.setattr(attendance, "utcnow", lambda: received_at)


def _deep_json_value(levels: int) -> object:
    value: object = "leaf"
    for _ in range(levels):
        value = [value]
    return value


def test_versioned_roster_rejects_late_older_and_unversioned_snapshots(client, monkeypatch):
    device_key = "versioned-roster"
    _set_received_at(monkeypatch, "2026-09-20T10:01:00Z")
    first = client.post(
        "/api/attendance/integration/people",
        headers=INTEGRATION_HEADERS,
        json=_roster(device_key, "First profile", "735", "2026-09-20T10:00:00Z"),
    )
    _set_received_at(monkeypatch, "2026-09-20T12:01:00Z")
    newest = client.post(
        "/api/attendance/integration/people",
        headers=INTEGRATION_HEADERS,
        json=_roster(device_key, "Current profile", "736", "2026-09-20T12:00:00Z"),
    )
    _set_received_at(monkeypatch, "2026-09-20T13:00:00Z")
    stale = client.post(
        "/api/attendance/integration/people",
        headers=INTEGRATION_HEADERS,
        json=_roster(device_key, "Stale profile", "737", "2026-09-20T11:00:00Z"),
    )
    _set_received_at(monkeypatch, "2026-09-20T14:00:00Z")
    unversioned = client.post(
        "/api/attendance/integration/people",
        headers=INTEGRATION_HEADERS,
        json=_roster(device_key, "Unversioned profile", "738", None),
    )

    assert first.status_code == newest.status_code == stale.status_code == unversioned.status_code == 200
    assert first.json()["ignored"] is False
    assert newest.json()["ignored"] is False
    assert stale.json()["ignored_reason"] == "stale_source_version"
    assert unversioned.json()["ignored_reason"] == "missing_source_version"
    with TestSessionLocal() as db:
        device = db.query(AttendanceDevice).filter_by(device_key=device_key).one()
        people = db.query(AttendancePerson).filter_by(device_id=device.id).order_by(AttendancePerson.external_person_id).all()
        checkpoint = db.query(SystemSetting).filter_by(
            key=attendance._source_setting_key("MIL", device_key),
        ).one()

    assert (device.name, device.source_host, device.reported_person_count) == (
        "Current profile",
        "10.0.0.6",
        1,
    )
    assert [(person.external_person_id, person.full_name, person.present_on_device) for person in people] == [
        ("735", "First profile", False),
        ("736", "Current profile", True),
    ]
    assert checkpoint.value_json["people_snapshot_at"] == "2026-09-20T12:00:00+00:00"
    assert checkpoint.value_json["metadata_snapshot_at"] == "2026-09-20T12:00:00+00:00"


def test_old_and_unversioned_events_keep_history_but_not_device_metadata(client, monkeypatch):
    device_key = "versioned-events"
    _set_received_at(monkeypatch, "2026-09-20T12:01:00Z")
    current = client.post(
        "/api/attendance/integration/events",
        headers=INTEGRATION_HEADERS,
        json=_events(device_key, "Current device", "event-1", "2026-09-20T12:00:00Z"),
    )
    _set_received_at(monkeypatch, "2026-09-20T13:00:00Z")
    stale = client.post(
        "/api/attendance/integration/events",
        headers=INTEGRATION_HEADERS,
        json=_events(device_key, "Stale device", "event-2", "2026-09-20T11:00:00Z"),
    )
    _set_received_at(monkeypatch, "2026-09-20T14:00:00Z")
    unversioned = client.post(
        "/api/attendance/integration/events",
        headers=INTEGRATION_HEADERS,
        json=_events(device_key, "Unversioned device", "event-3", None),
    )
    unversioned_roster = client.post(
        "/api/attendance/integration/people",
        headers=INTEGRATION_HEADERS,
        json=_roster(device_key, "Unversioned roster", "735", None),
    )

    assert current.status_code == stale.status_code == unversioned.status_code == unversioned_roster.status_code == 200
    assert current.json()["metadata_ignored"] is False
    assert stale.json() == {
        "received": 1,
        "inserted": 1,
        "duplicates": 0,
        "metadata_ignored": True,
        "metadata_ignored_reason": "stale_source_version",
    }
    assert unversioned.json()["inserted"] == 1
    assert unversioned.json()["metadata_ignored_reason"] == "missing_source_version"
    assert unversioned_roster.json()["ignored_reason"] == "missing_source_version"
    with TestSessionLocal() as db:
        device = db.query(AttendanceDevice).filter_by(device_key=device_key).one()
        event_uids = {
            uid for (uid,) in db.query(AttendanceEvent.event_uid).filter_by(device_id=device.id)
        }
        person_count = db.query(AttendancePerson).filter_by(device_id=device.id).count()

    assert (device.name, device.model, device.source_host) == (
        "Current device",
        "model-Current device",
        "10.0.1.1",
    )
    assert event_uids == {"event-1", "event-2", "event-3"}
    assert person_count == 0
    assert as_utc(device.last_seen_at) == datetime(2026, 9, 20, 14, tzinfo=timezone.utc)
    assert as_utc(device.last_event_sync_at) == datetime(2026, 9, 20, 14, tzinfo=timezone.utc)


def test_first_versioned_snapshot_older_than_legacy_receipt_cannot_overwrite(client, monkeypatch):
    device_key = "legacy-transition"
    _set_received_at(monkeypatch, "2026-09-20T12:00:00Z")
    legacy = client.post(
        "/api/attendance/integration/people",
        headers=INTEGRATION_HEADERS,
        json=_roster(device_key, "Legacy current", "735", None),
    )
    _set_received_at(monkeypatch, "2026-09-20T13:00:00Z")
    stale = client.post(
        "/api/attendance/integration/people",
        headers=INTEGRATION_HEADERS,
        json=_roster(device_key, "Late old", "736", "2026-09-20T11:00:00Z"),
    )
    _set_received_at(monkeypatch, "2026-09-20T14:00:00Z")
    fresh = client.post(
        "/api/attendance/integration/people",
        headers=INTEGRATION_HEADERS,
        json=_roster(device_key, "Versioned current", "737", "2026-09-20T13:30:00Z"),
    )

    assert legacy.status_code == stale.status_code == fresh.status_code == 200
    assert stale.json()["ignored_reason"] == "stale_source_version"
    assert fresh.json()["ignored"] is False
    with TestSessionLocal() as db:
        device = db.query(AttendanceDevice).filter_by(device_key=device_key).one()
        present = db.query(AttendancePerson).filter_by(device_id=device.id, present_on_device=True).one()

    assert (device.name, present.external_person_id, present.full_name) == (
        "Versioned current",
        "737",
        "Versioned current",
    )


@pytest.mark.parametrize(
    ("legacy_extension", "message"),
    [
        ("Ж" * 9_000, "UTF-8 bytes"),
        (_deep_json_value(17), "nested container levels"),
    ],
    ids=["oversized", "deep"],
)
def test_changed_oversized_legacy_checkpoint_rejects_roster_without_writes(
    client, monkeypatch, legacy_extension, message,
):
    device_key = "oversized-checkpoint"
    _set_received_at(monkeypatch, "2026-09-20T12:01:00Z")
    initial = client.post(
        "/api/attendance/integration/people",
        headers=INTEGRATION_HEADERS,
        json=_roster(device_key, "Before", "735", "2026-09-20T12:00:00Z"),
    )
    assert initial.status_code == 200, initial.text
    checkpoint_key = attendance._source_setting_key("MIL", device_key)
    with TestSessionLocal() as db:
        checkpoint = db.query(SystemSetting).filter_by(key=checkpoint_key).one()
        checkpoint.value_json = {**checkpoint.value_json, "legacy_extension": legacy_extension}
        db.commit()
        before_checkpoint = deepcopy(checkpoint.value_json)
        before_device = db.query(AttendanceDevice).filter_by(device_key=device_key).one()
        before_device_state = (before_device.name, before_device.last_seen_at, before_device.last_people_sync_at)
        before = (
            db.query(AttendanceDevice.id).count(),
            db.query(AttendancePerson.id).count(),
            db.query(AttendanceEvent.id).count(),
            db.query(AuditLog.id).count(),
        )

    _set_received_at(monkeypatch, "2026-09-20T13:01:00Z")
    response = client.post(
        "/api/attendance/integration/people",
        headers=INTEGRATION_HEADERS,
        json=_roster(device_key, "Should not save", "736", "2026-09-20T13:00:00Z"),
    )

    assert response.status_code == 422, response.text
    assert message in response.text
    with TestSessionLocal() as db:
        checkpoint = db.query(SystemSetting).filter_by(key=checkpoint_key).one()
        device = db.query(AttendanceDevice).filter_by(device_key=device_key).one()
        assert checkpoint.value_json == before_checkpoint
        assert (device.name, device.last_seen_at, device.last_people_sync_at) == before_device_state
        assert (
            db.query(AttendanceDevice.id).count(),
            db.query(AttendancePerson.id).count(),
            db.query(AttendanceEvent.id).count(),
            db.query(AuditLog.id).count(),
        ) == before


@pytest.mark.parametrize(
    "legacy_extension",
    ["Ж" * 9_000, _deep_json_value(17)],
    ids=["oversized", "deep"],
)
def test_stale_import_passes_through_exact_oversized_legacy_checkpoint(
    client, monkeypatch, legacy_extension,
):
    device_key = "unchanged-oversized-checkpoint"
    _set_received_at(monkeypatch, "2026-09-20T12:01:00Z")
    initial = client.post(
        "/api/attendance/integration/people",
        headers=INTEGRATION_HEADERS,
        json=_roster(device_key, "Current", "735", "2026-09-20T12:00:00Z"),
    )
    assert initial.status_code == 200, initial.text
    checkpoint_key = attendance._source_setting_key("MIL", device_key)
    with TestSessionLocal() as db:
        checkpoint = db.query(SystemSetting).filter_by(key=checkpoint_key).one()
        checkpoint.value_json = {**checkpoint.value_json, "legacy_extension": legacy_extension}
        db.commit()
        before = deepcopy(checkpoint.value_json)

    _set_received_at(monkeypatch, "2026-09-20T13:01:00Z")
    stale = client.post(
        "/api/attendance/integration/people",
        headers=INTEGRATION_HEADERS,
        json=_roster(device_key, "Stale", "736", "2026-09-20T11:00:00Z"),
    )

    assert stale.status_code == 200, stale.text
    assert stale.json()["ignored_reason"] == "stale_source_version"
    with TestSessionLocal() as db:
        checkpoint = db.query(SystemSetting).filter_by(key=checkpoint_key).one()
        assert checkpoint.value_json == before


@pytest.mark.parametrize("source_snapshot_at", ["2026-09-20T12:00:00", "2026-09-20T12:06:01Z"])
def test_invalid_source_timestamp_is_rejected_before_writes(client, monkeypatch, source_snapshot_at):
    _set_received_at(monkeypatch, "2026-09-20T12:00:00Z")
    response = client.post(
        "/api/attendance/integration/people",
        headers=INTEGRATION_HEADERS,
        json=_roster("invalid-version", "Invalid", "735", source_snapshot_at),
    )

    assert response.status_code in {400, 422}
    with TestSessionLocal() as db:
        assert db.query(AttendanceDevice).filter_by(device_key="invalid-version").count() == 0
        assert db.query(SystemSetting).filter_by(
            key=attendance._source_setting_key("MIL", "invalid-version"),
        ).count() == 0


def test_source_checkpoint_rolls_back_with_failed_roster_import(monkeypatch):
    payload = attendance.PeopleSnapshotIn.model_validate(
        _roster("rollback-version", "Rollback", "735", "2026-09-20T12:00:00Z"),
    )
    _set_received_at(monkeypatch, "2026-09-20T12:01:00Z")
    with TestSessionLocal() as db:
        db.commit = lambda: (_ for _ in ()).throw(RuntimeError("synthetic commit failure"))
        with pytest.raises(RuntimeError, match="synthetic commit failure"):
            attendance.import_people_snapshot(payload, db, identity=None)
        db.rollback()

    with TestSessionLocal() as db:
        assert db.query(AttendanceDevice).filter_by(device_key="rollback-version").count() == 0
        assert db.query(SystemSetting).filter_by(
            key=attendance._source_setting_key("MIL", "rollback-version"),
        ).count() == 0

    with TestSessionLocal() as db:
        result = attendance.import_people_snapshot(payload, db, identity=None)
    assert result["ignored"] is False
    assert result["created"] == 1
