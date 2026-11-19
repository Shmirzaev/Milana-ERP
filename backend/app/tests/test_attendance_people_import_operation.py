"""Connector people-import bytes, authorization and source reconciliation baseline."""

import hashlib
import json
import re
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import attendance
from app.core.config import settings
from app.core.dt import as_utc
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.schemas import AttendanceDevice, AttendancePerson, AuditLog, Employee, SystemSetting
from app.tests.pg_approved_instance import (
    ApprovedInstanceUnavailable, create_target_database, finalize_target,
    load_approved_instance, require_or_skip, target_engine,
)

TOKEN = "test-attendance-token"
MANAGED_TOKEN = "test-managed-attendance-token"
NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)


@pytest.fixture(params=["sqlite", "postgres"])
def attendance_database(request):
    target = None
    if request.param == "sqlite":
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    else:
        try:
            instance = load_approved_instance()
        except ApprovedInstanceUnavailable as exc:
            require_or_skip(exc)
        target = create_target_database(instance)
        engine = target_engine(target, options="-ctimezone=UTC")
    try:
        Base.metadata.create_all(engine)
        yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    finally:
        if target is not None:
            finalize_target(target, engine)
        else:
            engine.dispose()


@pytest.fixture
def attendance_case(attendance_database, monkeypatch, tmp_path):
    factory = attendance_database

    def sessions():
        with factory() as db:
            yield db

    previous = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = sessions
    monkeypatch.setattr(settings, "ATTENDANCE_INTEGRATION_TOKEN", TOKEN)
    monkeypatch.setattr(settings, "ATTENDANCE_INTEGRATION_FACTORY_CODE", "MIL")
    monkeypatch.setattr(settings, "ATTENDANCE_PHOTOS_DIR", str(tmp_path / "photos"))
    monkeypatch.setattr(attendance, "utcnow", lambda: NOW)
    try:
        yield SimpleNamespace(factory=factory, client=TestClient(app), photos=tmp_path / "photos")
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous


def post_json(case, path, payload, token=TOKEN):
    body = json.dumps(payload, separators=(",", ":")).encode()
    response = case.client.post(path, content=body,
                                headers={"Content-Type": "application/json", "X-Attendance-Token": token})
    assert response.request.content == body
    return response


def assert_bytes(response, expected, status=200):
    assert response.status_code == status, response.text
    assert response.content == expected
    assert response.headers["content-type"] == "application/json"
    assert "content-length" not in response.headers
    assert response.headers["content-encoding"] == "gzip"
    assert response.headers["vary"] == "Origin, Accept-Encoding"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert re.fullmatch(r"app;dur=\d+\.\d", response.headers["server-timing"])


def assert_openapi(path, digest):
    api = app.openapi()
    root = api["paths"][path]["post"]
    schemas, pending = {}, [root]
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            ref = value.get("$ref", "")
            if ref.startswith("#/components/schemas/"):
                name = ref.rsplit("/", 1)[-1]
                if name not in schemas:
                    schemas[name] = api["components"]["schemas"][name]
                    pending.append(schemas[name])
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
    encoded = json.dumps({"operation": root, "schemas": schemas}, sort_keys=True, separators=(",", ":")).encode()
    assert hashlib.sha256(encoded).hexdigest() == digest


def roster(*people, source="2026-10-20T11:00:00+00:00", full=True, key="wire-reader"):
    payload = {"device": {"device_key": key, "name": "Wire reader", "reported_person_count": len(people)},
               "people": list(people), "full_snapshot": full}
    if source is not None:
        payload["source_snapshot_at"] = source
    return payload


def person(external_id, name):
    return {"external_person_id": external_id, "full_name": name, "user_type": "contractor"}


def managed(case, *, enabled=True, key="managed-reader"):
    with case.factory() as db:
        row = AttendanceDevice(factory_code="ECO", device_key=key, name="Managed reader",
                               connector_token_hash=attendance._connector_token_hash(MANAGED_TOKEN), sync_enabled=enabled)
        db.add(row)
        db.commit()
        return row.id


def test_people_connector_bytes_roster_reconciliation_and_hr_isolation(attendance_case):
    case = attendance_case
    payload = roster(person("001", " Worker One "), person("002", "Worker Two"))
    created = post_json(case, "/api/attendance/integration/people", payload)
    device_id = created.json()["device_id"]
    assert_bytes(created, f'{{"device_id":{device_id},"received":2,"created":2,"updated":0,"marked_absent":0,"reported_person_count":2,"ignored":false}}'.encode())
    updated = post_json(case, "/api/attendance/integration/people", roster(person("001", "Renamed"), source="2026-10-20T11:30:00Z"))
    assert_bytes(updated, f'{{"device_id":{device_id},"received":1,"created":0,"updated":1,"marked_absent":1,"reported_person_count":1,"ignored":false}}'.encode())
    with case.factory() as db:
        rows = db.query(AttendancePerson).order_by(AttendancePerson.external_person_id).all()
        assert [(row.external_person_id, row.full_name, row.present_on_device, row.user_type) for row in rows] == [
            ("001", "Renamed", True, "contractor"), ("002", "Worker Two", False, "contractor"),
        ]
        device = db.get(AttendanceDevice, device_id)
        assert (device.factory_code, device.read_only, device.reported_person_count) == ("MIL", True, 1)
        assert as_utc(device.last_people_sync_at) == NOW
        assert db.query(Employee).count() == db.query(AuditLog).count() == 0
    assert_openapi("/api/attendance/integration/people", "a3fef6fccfa76463fdbf4ab0f2e4b214fd8cfabf996d07475cd5bb95a0983591")


@pytest.mark.parametrize("source,reason", [("2026-10-20T10:00:00Z", "stale_source_version"), (None, "missing_source_version")])
def test_people_stale_and_unversioned_snapshot_bytes_preserve_new_roster(attendance_case, source, reason):
    case = attendance_case
    first = post_json(case, "/api/attendance/integration/people", roster(person("001", "Current")))
    device_id = first.json()["device_id"]
    ignored = post_json(case, "/api/attendance/integration/people", roster(person("002", "Stale"), source=source))
    assert_bytes(ignored, f'{{"device_id":{device_id},"received":1,"created":0,"updated":0,"marked_absent":0,"reported_person_count":1,"ignored":true,"ignored_reason":"{reason}"}}'.encode())
    with case.factory() as db:
        assert [(row.external_person_id, row.full_name, row.present_on_device) for row in db.query(AttendancePerson)] == [("001", "Current", True)]
        checkpoint = db.query(SystemSetting).one().value_json
        assert checkpoint["people_snapshot_at"] == "2026-10-20T11:00:00+00:00"


@pytest.mark.parametrize("token,disabled,expected,status", [
    ("wrong", False, b'{"detail":"Invalid attendance integration credentials"}', 401),
    (MANAGED_TOKEN, True, b'{"detail":"Attendance device synchronization is disabled"}', 403),
    (MANAGED_TOKEN, False, b'{"detail":"Connector token does not belong to this attendance device"}', 403),
])
def test_people_auth_error_bytes_and_no_mirrored_writes(attendance_case, token, disabled, expected, status):
    case = attendance_case
    managed(case, enabled=not disabled)
    result = post_json(case, "/api/attendance/integration/people", roster(person("001", "Refused")), token)
    assert_bytes(result, expected, status)
    with case.factory() as db:
        assert db.query(AttendancePerson).count() == db.query(SystemSetting).count() == 0
        assert db.query(AttendanceDevice).count() == 1


def test_people_managed_identity_factory_and_validation_precedence(attendance_case):
    case = attendance_case
    device_id = managed(case)
    good = post_json(case, "/api/attendance/integration/people", roster(person("001", "Managed"), key="managed-reader"), MANAGED_TOKEN)
    assert_bytes(good, f'{{"device_id":{device_id},"received":1,"created":1,"updated":0,"marked_absent":0,"reported_person_count":1,"ignored":false}}'.encode())
    duplicate = post_json(case, "/api/attendance/integration/people", roster(person("001", "A"), person("001", "B")), MANAGED_TOKEN)
    assert_bytes(duplicate, b'{"detail":"Duplicate person ID in snapshot: 001"}', 400)
    empty = roster();empty["device"]["reported_person_count"] = 1
    assert_bytes(post_json(case, "/api/attendance/integration/people", empty), b'{"detail":"Refusing an empty full snapshot for a non-empty device"}', 400)
    with case.factory() as db:
        assert db.query(AttendancePerson).one().factory_code == "ECO"
        assert db.query(AttendanceDevice).count() == 1


def test_people_commit_failure_rolls_back_device_roster_and_checkpoint(attendance_case):
    case = attendance_case

    def fail_commit(session):
        raise RuntimeError("Synthetic attendance people commit failure")

    event.listen(Session, "before_commit", fail_commit)
    try:
        with pytest.raises(RuntimeError, match="Synthetic attendance people commit failure"):
            post_json(case, "/api/attendance/integration/people", roster(person("001", "Rolled back")))
    finally:
        event.remove(Session, "before_commit", fail_commit)
    with case.factory() as db:
        assert db.query(AttendanceDevice).count() == db.query(AttendancePerson).count() == db.query(SystemSetting).count() == 0


def test_people_unconfigured_global_token_still_accepts_managed_identity(attendance_case, monkeypatch):
    case = attendance_case
    device_id = managed(case)
    monkeypatch.setattr(settings, "ATTENDANCE_INTEGRATION_TOKEN", "")
    assert_bytes(post_json(case, "/api/attendance/integration/people", roster(), "wrong"),
                 b'{"detail":"Attendance integration is not configured"}', 503)
    accepted = post_json(case, "/api/attendance/integration/people", roster(person("001", "Managed"), key="managed-reader"), MANAGED_TOKEN)
    assert_bytes(accepted, f'{{"device_id":{device_id},"received":1,"created":1,"updated":0,"marked_absent":0,"reported_person_count":1,"ignored":false}}'.encode())


def test_people_legacy_stale_receipt_omits_source_reason(attendance_case):
    case = attendance_case
    first = post_json(case, "/api/attendance/integration/people", roster(person("001", "Current"), source=None))
    device_id = first.json()["device_id"]
    stale = post_json(case, "/api/attendance/integration/people", roster(person("002", "Ignored"), source=None))
    assert_bytes(stale, f'{{"device_id":{device_id},"received":1,"created":0,"updated":0,"marked_absent":0,"reported_person_count":1,"ignored":true}}'.encode())
    with case.factory() as db:
        assert db.query(AttendancePerson).one().full_name == "Current"
        assert db.query(SystemSetting).count() == 0
