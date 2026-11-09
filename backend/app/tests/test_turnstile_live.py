from datetime import datetime, timedelta, timezone
import hashlib
import pytest
from app.core.config import settings
from app.libs.enums.turnstile import GateMode, LiveGateState
from app.schemas import AttendanceDevice, AttendanceEvent, AttendancePerson, Employee, User
from app.schemas.people.turnstile import GateEmployeeDevice, GatePhotoAsset
from app.schemas.people.turnstile_live import GateLiveDevice, GateLiveJob, GateLiveProfile
from app.tests.conftest import TestSessionLocal

PREFIX = "/api/turnstile-live"


def snapshot(number="LIVE-123", **changes):
    value = {"external_person_id": number, "present": True, "full_name": "Synthetic Person",
        "user_type": "normal", "policy": {"validity": {"begin": "2026-01-01T00:00:00", "end": "2027-01-01T00:00:00"},
        "right_plans": [{"door_no": 1, "plan_template_no": "1"}]},
        "photo_sha256": "a"*64, "face_count": 1, "card_count": 0, "fingerprint_count": 0,
        "other_fields_hash": "b"*64}
    value.update(changes); return value


@pytest.fixture
def live(client, admin_token, monkeypatch):
    monkeypatch.setattr(settings, "TURNSTILE_PROVISIONING_MODE", GateMode.HIKVISION)
    with TestSessionLocal() as db:
        person = Employee(factory_code="MIL", employee_no="LIVE-123", full_name="Synthetic Person", status="active")
        gate = AttendanceDevice(factory_code="MIL", device_key="synthetic-live", name="Synthetic live gate",
            source_host="127.0.0.1", certificate_sha256="c"*64, sync_enabled=True, read_only=True)
        db.add_all([person, gate]); db.commit(); person_id, device_id = person.id, gate.id
    auth = {"Authorization": f"Bearer {admin_token}"}
    config = {"enabled": True, "writes_enabled": False, "allowed_employee_numbers": ["LIVE-123"], "face_library_id": "1"}
    response = client.put(f"{PREFIX}/devices/{device_id}", headers=auth, json=config)
    assert response.status_code == 200, response.text
    worker = {"X-Turnstile-Worker-Token": response.json()["worker_token"]}
    return client, person_id, device_id, auth, worker


def observe(live):
    client, person, device, auth, worker = live
    r = client.post(f"{PREFIX}/employees/{person}/jobs", headers={**auth, "Idempotency-Key": "observe-one"},
        json={"expected_employee_no": "LIVE-123", "device_id": device, "action": "observe"})
    assert r.status_code == 202, r.text
    claim = client.post(f"{PREFIX}/worker/claim", headers=worker)
    assert claim.status_code == 200, claim.text
    job = claim.json(); assert job["job_id"] == r.json()["id"]
    result = client.post(f"{PREFIX}/worker/jobs/{job['job_id']}/result", headers=worker,
        json={"lease_token": job["lease_token"], "outcome": "readback", "after": snapshot(), "worker_quiescent": True})
    assert result.status_code == 200, result.text
    assert result.json()["state"] == "succeeded"
    return job, result.json()


def test_observe_and_explicit_adopt_preserve_business_data(live):
    client, person, device, auth, worker = live
    claim, observed = observe(live)
    body = {"expected_employee_no": "LIVE-123", "observation_job_id": claim["job_id"],
        "expected_profile_hash": observed["profile_hash"], "identity_reviewed": True}
    result = client.post(f"{PREFIX}/employees/{person}/adopt", headers=auth, json=body)
    assert result.status_code == 200, result.text
    again = client.post(f"{PREFIX}/employees/{person}/adopt", headers=auth, json=body)
    assert again.json() == result.json()
    with TestSessionLocal() as db:
        assert db.query(AttendancePerson).count() == db.query(AttendanceEvent).count() == 0
        assert db.get(Employee, person).full_name == "Synthetic Person"
        binding = db.query(GateEmployeeDevice).one()
        assert binding.mode is GateMode.HIKVISION
        assert db.query(GateLiveProfile).one().adopted
        assert db.query(GateLiveJob).one().dispatched is False
    permit = client.post(f"{PREFIX}/worker/jobs/{claim['job_id']}/dispatch", headers={**worker, "X-Turnstile-Lease": claim["lease_token"]}, json={"step": "modify_profile"})
    assert permit.status_code == 409


@pytest.mark.parametrize("change", ["not_reviewed", "wrong_hash", "wrong_number", "stale", "cross_employee"])
def test_adoption_refusals_are_atomic(live, change):
    client, person, device, auth, worker = live
    claim, observed = observe(live)
    payload = {"expected_employee_no": "LIVE-123", "observation_job_id": claim["job_id"],
        "expected_profile_hash": observed["profile_hash"], "identity_reviewed": True}
    if change == "not_reviewed": payload["identity_reviewed"] = False
    if change == "wrong_hash": payload["expected_profile_hash"] = "e"*64
    if change == "wrong_number": payload["expected_employee_no"] = "ANOTHER"
    if change in ("stale", "cross_employee"):
        with TestSessionLocal() as db:
            row = db.get(GateLiveJob, claim["job_id"])
            if change == "stale": row.completed_at = datetime.now(timezone.utc)-timedelta(minutes=6)
            else:
                other = Employee(factory_code="MIL", employee_no="OTHER", full_name="Other", status="active")
                db.add(other); db.flush(); person = other.id; payload["expected_employee_no"] = "OTHER"
            db.commit()
    r = client.post(f"{PREFIX}/employees/{person}/adopt", headers=auth, json=payload)
    assert r.status_code == 409
    with TestSessionLocal() as db:
        assert db.query(GateEmployeeDevice).count() == db.query(GateLiveProfile).count() == 0


@pytest.mark.parametrize("headers", [{}, {"X-Attendance-Token": "test-attendance-token"}, {"X-Turnstile-Worker-Token": "test-attendance-token"}])
def test_worker_boundary_refuses_reader_or_missing_token(live, headers):
    client, *_ = live
    assert client.post(f"{PREFIX}/worker/claim", headers=headers).status_code == 401


def test_wrong_device_token_and_stale_lease_cannot_submit(live):
    client, person, device, auth, worker = live
    claim, result = observe(live)
    body = {"lease_token": "x"*48, "outcome": "readback", "after": snapshot(), "worker_quiescent": True}
    assert client.post(f"{PREFIX}/worker/jobs/{claim['job_id']}/result", headers=worker, json=body).status_code == 404
    with TestSessionLocal() as db:
        other = GateLiveDevice(device_id=device+999, factory_code="MIL", worker_token_hash="0"*64, config_revision=1,
            configuration={}, enabled=True, writes_enabled=False, source_host="127.0.0.1", certificate_sha256="c"*64)
        # FK refusal is separately exercised by PostgreSQL; use a real second device here.
        gate = AttendanceDevice(factory_code="MIL", device_key="other-live", name="Other", read_only=True, sync_enabled=True)
        db.add(gate); db.flush(); other.device_id = gate.id; other.worker_token_hash = hashlib.sha256(b"other-worker").hexdigest(); db.add(other); db.commit()
    body["lease_token"] = claim["lease_token"]
    assert client.post(f"{PREFIX}/worker/jobs/{claim['job_id']}/result", headers={"X-Turnstile-Worker-Token": "other-worker"}, json=body).status_code == 404


def test_duplicate_result_is_idempotent_and_different_result_refused(live):
    client, *_rest, worker = live
    claim, original = observe(live)
    body = {"lease_token": claim["lease_token"], "outcome": "readback", "after": snapshot(), "worker_quiescent": True}
    assert client.post(f"{PREFIX}/worker/jobs/{claim['job_id']}/result", headers=worker, json=body).json() == original
    body["after"]["full_name"] = "Changed"
    assert client.post(f"{PREFIX}/worker/jobs/{claim['job_id']}/result", headers=worker, json=body).status_code == 409


def test_observe_unknown_never_becomes_profile_adoption(live):
    client, person, device, auth, worker = live
    client.post(f"{PREFIX}/employees/{person}/jobs", headers={**auth, "Idempotency-Key": "offline"},
        json={"expected_employee_no": "LIVE-123", "device_id": device, "action": "observe"})
    job = client.post(f"{PREFIX}/worker/claim", headers=worker).json()
    r = client.post(f"{PREFIX}/worker/jobs/{job['job_id']}/result", headers=worker,
        json={"lease_token": job["lease_token"], "outcome": "unknown", "worker_quiescent": True})
    assert r.json()["state"] == "failed"
    with TestSessionLocal() as db: assert db.query(GateEmployeeDevice).count() == 0


def test_expired_claim_is_not_automatically_replayed(live):
    client, person, device, auth, worker = live
    client.post(f"{PREFIX}/employees/{person}/jobs", headers={**auth, "Idempotency-Key": "expire"},
        json={"expected_employee_no": "LIVE-123", "device_id": device, "action": "observe"})
    job = client.post(f"{PREFIX}/worker/claim", headers=worker).json()
    with TestSessionLocal() as db:
        db.get(GateLiveJob, job["job_id"]).lease_expires_at = datetime.now(timezone.utc)-timedelta(seconds=1); db.commit()
    assert client.post(f"{PREFIX}/worker/claim", headers=worker).json() is None
    with TestSessionLocal() as db: assert db.get(GateLiveJob, job["job_id"]).state is LiveGateState.UNCERTAIN


def test_live_defaults_do_not_enable_device_writes(live):
    client, person, device, auth, worker = live
    r = client.post(f"{PREFIX}/employees/{person}/jobs", headers={**auth, "Idempotency-Key": "blocked-write"},
        json={"expected_employee_no": "LIVE-123", "device_id": device, "action": "revoke", "expected_profile_hash": "a"*64})
    assert r.status_code == 403
    with TestSessionLocal() as db: assert db.query(GateLiveJob).count() == 0


def test_exact_accepted_receipt_replays_after_employee_number_changes(live):
    client, person, device, auth, worker = live
    body={"expected_employee_no":"LIVE-123","device_id":device,"action":"observe"}
    headers={**auth,"Idempotency-Key":"receipt-before-identity-change"}
    accepted=client.post(f"{PREFIX}/employees/{person}/jobs",headers=headers,json=body)
    assert accepted.status_code==202
    with TestSessionLocal() as db:
        db.get(Employee,person).employee_no="CHANGED-IDENTITY";db.commit()
    replay=client.post(f"{PREFIX}/employees/{person}/jobs",headers=headers,json=body)
    assert replay.status_code==202 and replay.json()==accepted.json()
    assert client.post(f"{PREFIX}/worker/claim",headers=worker).json() is None
    with TestSessionLocal() as db:
        assert db.query(GateLiveJob).count()==1
        assert db.get(GateLiveJob,accepted.json()["id"]).state is LiveGateState.CONFLICT


@pytest.mark.parametrize("ever_dispatched", [False, True])
def test_new_explicit_enroll_reuses_only_never_written_reservation(live, ever_dispatched):
    client, person, device, auth, _ = live
    config={"enabled":True,"writes_enabled":True,"allowed_employee_numbers":["LIVE-123"],"face_library_id":"1",
        "access_policy":snapshot()["policy"],"policy_reference":"SYNTHETIC-POLICY","handover_reference":"SYNTHETIC-HANDOVER"}
    response=client.put(f"{PREFIX}/devices/{device}",headers=auth,json=config)
    worker={"X-Turnstile-Worker-Token":response.json()["worker_token"]}
    with TestSessionLocal() as db:
        asset=GatePhotoAsset(employee_id=person,factory_code="MIL",created_by=db.query(User).filter_by(email="admin@example.com").one().id,
            stored_name="synthetic-reserved.jpg",sha256="a"*64,width=30,height=40,content_type="image/jpeg")
        db.add(asset);db.commit();asset_id=asset.id
    body={"expected_employee_no":"LIVE-123","device_id":device,"action":"enroll","reviewed_name":"Synthetic Person",
        "photo_asset_id":asset_id,"manual_face_reviewed":True}
    first=client.post(f"{PREFIX}/employees/{person}/jobs",headers={**auth,"Idempotency-Key":"first-reservation"},json=body)
    assert first.status_code==202,first.text
    claim=client.post(f"{PREFIX}/worker/claim",headers=worker).json()
    failed=client.post(f"{PREFIX}/worker/jobs/{claim['job_id']}/result",headers=worker,json={
        "lease_token":claim["lease_token"],"outcome":"refused","worker_quiescent":True})
    assert failed.json()["state"]=="failed"
    if ever_dispatched:
        with TestSessionLocal() as db:
            db.get(GateLiveJob,first.json()["id"]).dispatched=True;db.commit()
    # Policy rotation no longer strands an identity that was never written.
    assert client.put(f"{PREFIX}/devices/{device}",headers=auth,json=config).status_code==200
    second=client.post(f"{PREFIX}/employees/{person}/jobs",headers={**auth,"Idempotency-Key":"new-reviewed-reservation"},json=body)
    assert second.status_code==(409 if ever_dispatched else 202),second.text
    with TestSessionLocal() as db:
        assert db.query(GateEmployeeDevice).count()==1
        assert db.query(GateLiveJob).count()==(1 if ever_dispatched else 2)
        assert db.get(GateLiveJob,first.json()["id"]).state is LiveGateState.FAILED
