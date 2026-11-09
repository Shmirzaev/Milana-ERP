"""A waiting user request must not overwrite a newer worker/job transition.

These deterministic interleavings use independent database sessions at the
configuration-lock boundary. PostgreSQL lock ordering is verified separately;
the assertions here specifically catch SQLAlchemy's retained identity-map state.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.libs.dto.people.turnstile_live import LiveResultInput, LiveSnapshot
from app.libs.enums.turnstile import LiveGateAction, LiveGateState
from app.models.people import turnstile_live_service as service
from app.schemas import AttendanceDevice, Employee, SystemSetting, User
from app.schemas.people.turnstile_live import GateLiveJob
from app.tests.conftest import TestSessionLocal
from app.tests.test_turnstile_live import PREFIX, snapshot
from app.tests.test_turnstile_live import live as live


def _observe(live_context, key, *, uncertain=False):
    client, employee_id, device_id, actor_headers, worker_headers = live_context
    submitted = client.post(
        f"{PREFIX}/employees/{employee_id}/jobs",
        headers={**actor_headers, "Idempotency-Key": key},
        json={"expected_employee_no": "LIVE-123", "device_id": device_id, "action": "observe"},
    )
    assert submitted.status_code == 202, submitted.text
    claimed = client.post(f"{PREFIX}/worker/claim", headers=worker_headers)
    assert claimed.status_code == 200, claimed.text
    claim = claimed.json()
    result = client.post(
        f"{PREFIX}/worker/jobs/{claim['job_id']}/result",
        headers=worker_headers,
        json={
            "lease_token": claim["lease_token"],
            "outcome": "unknown" if uncertain else "readback",
            "after": None if uncertain else snapshot(),
            "worker_quiescent": not uncertain,
        },
    )
    assert result.status_code == 200, result.text
    return claim, result.json()


def test_retry_refreshes_job_claimed_while_request_waited(live, monkeypatch):
    client, employee_id, device_id, actor_headers, worker_headers = live
    submitted = client.post(
        f"{PREFIX}/employees/{employee_id}/jobs",
        headers={**actor_headers, "Idempotency-Key": "unsent-failure"},
        json={"expected_employee_no": "LIVE-123", "device_id": device_id, "action": "observe"},
    )
    assert submitted.status_code == 202, submitted.text
    claim = client.post(f"{PREFIX}/worker/claim", headers=worker_headers).json()
    failure = client.post(
        f"{PREFIX}/worker/jobs/{claim['job_id']}/result",
        headers=worker_headers,
        json={"lease_token": claim["lease_token"], "outcome": "refused", "worker_quiescent": True},
    )
    assert failure.status_code == 200 and failure.json()["state"] == "failed", failure.text
    original_config = service._config
    interleavings = []

    def another_retry_and_claim(db, selected_device):
        assert selected_device == device_id
        assert db.get(GateLiveJob, claim["job_id"]).state is LiveGateState.FAILED
        # Represents another accepted retry followed by the worker's fresh claim
        # while this request is waiting for its serialized configuration lock.
        with TestSessionLocal() as concurrent:
            job = concurrent.get(GateLiveJob, claim["job_id"])
            job.state = LiveGateState.PROCESSING
            job.attempt_count = 2
            job.lease_token_hash = "f" * 64
            job.lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=2)
            job.result = None
            job.result_hash = None
            job.completed_at = None
            concurrent.commit()
        interleavings.append(True)
        return original_config(db, selected_device)

    monkeypatch.setattr(service, "_config", another_retry_and_claim)
    retried = client.post(f"{PREFIX}/jobs/{claim['job_id']}/retry-unsent", headers=actor_headers)
    assert retried.status_code == 409, retried.text
    assert interleavings == [True]
    with TestSessionLocal() as db:
        job = db.get(GateLiveJob, claim["job_id"])
        assert job.state is LiveGateState.PROCESSING
        assert job.lease_token_hash == "f" * 64
        assert job.attempt_count == 2
        assert job.result is None and job.result_history == []


def test_resolution_refreshes_job_already_resolved_while_request_waited(live, monkeypatch):
    client, _employee_id, device_id, actor_headers, _worker_headers = live
    claim, uncertain = _observe(live, "uncertain-observation", uncertain=True)
    assert uncertain["state"] == "uncertain"
    _later_claim, observation = _observe(live, "later-observation")
    assert observation["state"] == "succeeded"
    original_config = service._config
    interleavings = []

    def another_resolution(db, selected_device):
        assert selected_device == device_id
        assert db.get(GateLiveJob, claim["job_id"]).state is LiveGateState.UNCERTAIN
        with TestSessionLocal() as concurrent:
            concurrent.get(GateLiveJob, claim["job_id"]).state = LiveGateState.CONFLICT
            concurrent.commit()
        interleavings.append(True)
        return original_config(db, selected_device)

    monkeypatch.setattr(service, "_config", another_resolution)
    resolved = client.post(
        f"{PREFIX}/jobs/{claim['job_id']}/resolve",
        headers=actor_headers,
        json={"worker_stopped_reference": "SYNTHETIC-QUIESCENT", "observation_job_id": observation["id"]},
    )
    assert resolved.status_code == 409, resolved.text
    assert interleavings == [True]
    with TestSessionLocal() as db:
        assert db.get(GateLiveJob, claim["job_id"]).state is LiveGateState.CONFLICT


@pytest.mark.parametrize("delete_completed,credentials_absent", [(False, False), (True, False), (False, True), (True, True)])
def test_delete_requires_completed_vendor_process_and_absent_credentials(delete_completed, credentials_absent):
    before = LiveSnapshot.model_validate(snapshot(user_type="blackList"))
    job = SimpleNamespace(
        action=LiveGateAction.DELETE,
        request={"expected_employee_no": "LIVE-123"},
        dispatched=True,
        dispatch_count=1,
        baseline=before.model_dump(mode="json"),
    )
    result = LiveResultInput(
        lease_token="x" * 48,
        outcome="readback",
        before=before,
        after=LiveSnapshot(external_person_id="LIVE-123", present=False),
        vendor_accepted=True,
        worker_quiescent=True,
        delete_completed=delete_completed,
        credentials_absent=credentials_absent,
    )
    assert service._matches(job, result) is (delete_completed and credentials_absent)


def _writable_profile(live_context):
    client, employee_id, device_id, actor_headers, _worker_headers = live_context
    configured = client.put(
        f"{PREFIX}/devices/{device_id}",
        headers=actor_headers,
        json={
            "enabled": True,
            "writes_enabled": True,
            "allowed_employee_numbers": ["LIVE-123"],
            "face_library_id": "1",
            "access_policy": snapshot()["policy"],
            "policy_reference": "SYNTHETIC-BOUNDED-POLICY",
            "handover_reference": "SYNTHETIC-ISOLATED-HANDOVER",
        },
    )
    assert configured.status_code == 200, configured.text
    worker_headers = {"X-Turnstile-Worker-Token": configured.json()["worker_token"]}
    live_context = (client, employee_id, device_id, actor_headers, worker_headers)
    claim, observation = _observe(live_context, "adoption-observation")
    adopted = client.post(
        f"{PREFIX}/employees/{employee_id}/adopt",
        headers=actor_headers,
        json={"expected_employee_no": "LIVE-123", "observation_job_id": claim["job_id"],
              "expected_profile_hash": observation["profile_hash"], "identity_reviewed": True},
    )
    assert adopted.status_code == 200, adopted.text
    submitted = client.post(
        f"{PREFIX}/employees/{employee_id}/jobs",
        headers={**actor_headers, "Idempotency-Key": "reviewed-name-change"},
        json={"expected_employee_no": "LIVE-123", "device_id": device_id, "action": "edit",
              "reviewed_name": "Reviewed synthetic name", "expected_profile_hash": observation["profile_hash"]},
    )
    assert submitted.status_code == 202, submitted.text
    return live_context, submitted.json()["id"]


def test_write_permit_is_single_use(live):
    live_context, job_id = _writable_profile(live)
    client, _employee_id, _device_id, _actor_headers, worker_headers = live_context
    claim = client.post(f"{PREFIX}/worker/claim", headers=worker_headers).json()
    headers = {**worker_headers, "X-Turnstile-Lease": claim["lease_token"]}
    first = client.post(f"{PREFIX}/worker/jobs/{job_id}/dispatch", headers=headers, json={"step": "modify_profile"})
    assert first.status_code == 200 and first.json() == {"permitted": True}, first.text
    repeated = client.post(f"{PREFIX}/worker/jobs/{job_id}/dispatch", headers=headers, json={"step": "modify_profile"})
    assert repeated.status_code == 409, repeated.text
    with TestSessionLocal() as db:
        job = db.get(GateLiveJob, job_id)
        assert job.dispatch_count == 1 and job.dispatched


@pytest.mark.parametrize("phase", ["claim", "dispatch"])
@pytest.mark.parametrize("change,status", [
    ("inactive_actor", 401), ("revoked_permissions", 403), ("archived_employee", 409),
    ("reserved_alias", 409), ("source_host", 409), ("certificate_pin", 409),
])
def test_queued_write_rechecks_scope_before_claim_and_dispatch(live, phase, change, status):
    live_context, job_id = _writable_profile(live)
    client, employee_id, device_id, _actor_headers, worker_headers = live_context
    claim = client.post(f"{PREFIX}/worker/claim", headers=worker_headers).json() if phase == "dispatch" else None
    with TestSessionLocal() as db:
        job = db.get(GateLiveJob, job_id)
        if change == "inactive_actor":
            db.get(User, job.requested_by).is_active = False
        elif change == "revoked_permissions":
            actor = db.get(User, job.requested_by)
            actor.role_id = None
            actor.extra_permissions = []
            actor.access_policy = None
        elif change == "archived_employee":
            db.get(Employee, employee_id).status = "archived"
        elif change == "reserved_alias":
            db.add(SystemSetting(key="employee_merge_aliases:MIL", value_json={"ids": {str(employee_id): "reserved"}}))
        elif change == "source_host":
            db.get(AttendanceDevice, device_id).source_host = "127.0.0.2"
        else:
            db.get(AttendanceDevice, device_id).certificate_sha256 = "d" * 64
        db.commit()
    if phase == "claim":
        response = client.post(f"{PREFIX}/worker/claim", headers=worker_headers)
        assert response.status_code == 200 and response.json() is None, response.text
    else:
        response = client.post(
            f"{PREFIX}/worker/jobs/{job_id}/dispatch",
            headers={**worker_headers, "X-Turnstile-Lease": claim["lease_token"]},
            json={"step": "modify_profile"},
        )
        assert response.status_code == status, response.text
    with TestSessionLocal() as db:
        job = db.get(GateLiveJob, job_id)
        assert not job.dispatched and job.dispatch_count == 0
        if phase == "claim":
            assert job.state is LiveGateState.CONFLICT


def test_unsent_retry_retains_receipts_and_stops_after_three_attempts(live):
    client, employee_id, device_id, actor_headers, worker_headers = live
    submitted = client.post(
        f"{PREFIX}/employees/{employee_id}/jobs",
        headers={**actor_headers, "Idempotency-Key": "bounded-unsent-retry"},
        json={"expected_employee_no": "LIVE-123", "device_id": device_id, "action": "observe"},
    )
    assert submitted.status_code == 202, submitted.text
    job_id = submitted.json()["id"]
    for attempt in range(1, 4):
        claim = client.post(f"{PREFIX}/worker/claim", headers=worker_headers).json()
        assert claim["job_id"] == job_id
        result = client.post(
            f"{PREFIX}/worker/jobs/{job_id}/result",
            headers=worker_headers,
            json={"lease_token": claim["lease_token"], "outcome": "refused", "worker_quiescent": True},
        )
        assert result.status_code == 200 and result.json()["state"] == "failed", result.text
        retried = client.post(f"{PREFIX}/jobs/{job_id}/retry-unsent", headers=actor_headers)
        assert retried.status_code == (200 if attempt < 3 else 409), retried.text
    with TestSessionLocal() as db:
        job = db.get(GateLiveJob, job_id)
        assert job.state is LiveGateState.FAILED and job.attempt_count == 3
        assert [receipt["attempt"] for receipt in job.result_history] == [1, 2]
        assert not job.dispatched and job.dispatch_count == 0
