"""Capability omission is evidence of no advertisement, never a false right.

These server-side receipt checks use synthetic snapshots only. They do not
establish physical firmware support or permission to activate a device writer.
"""
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.libs.dto.people.turnstile_live import LiveResultInput, LiveSecurityCapabilities, LiveSnapshot
from app.libs.enums.turnstile import DoubleLockCapability, LiveGateAction
from app.models.people.turnstile_live_service import _matches


def profile(**changes):
    value = {
        "external_person_id": "SYNTHETIC-1", "present": True, "full_name": "Synthetic Person",
        "user_type": "normal", "policy": {
            "validity": {"begin": "2026-01-01T00:00:00", "end": "2027-01-01T00:00:00"},
            "right_plans": [{"door_no": 1, "plan_template_no": "1"}],
        },
        "photo_sha256": "a" * 64, "face_count": 1, "other_fields_hash": "b" * 64,
        "local_ui_right": False, "double_lock_right": False,
    }
    value.update(changes)
    return LiveSnapshot.model_validate(value)


def capabilities(state):
    return LiveSecurityCapabilities(user_info_sha256="c" * 64, double_lock=state)


def enroll_receipt(after):
    job = SimpleNamespace(
        action=LiveGateAction.ENROLL,
        request={"expected_employee_no": "SYNTHETIC-1", "reviewed_name": "Synthetic Person"},
        dispatched=True, dispatch_count=3, desired_policy=after.policy.model_dump(mode="json"),
        photo_sha256="a" * 64,
    )
    result = LiveResultInput(
        lease_token="x" * 48, outcome="readback", vendor_accepted=True, worker_quiescent=True,
        before=LiveSnapshot(external_person_id="SYNTHETIC-1", present=False), after=after,
    )
    return job, result


@pytest.mark.parametrize("state", [None, *DoubleLockCapability])
@pytest.mark.parametrize("double_lock", [None, False, True])
@pytest.mark.parametrize("local_ui", [None, False, True])
def test_enrollment_requires_capability_evidence_and_verified_local_ui(state, double_lock, local_ui):
    after = profile(local_ui_right=local_ui, double_lock_right=double_lock,
        security_capabilities=capabilities(state) if state is not None else None)
    expected = local_ui is False and (
        (state is DoubleLockCapability.ADVERTISED and double_lock is False)
        or (state is DoubleLockCapability.NOT_ADVERTISED and double_lock is not True)
    )
    assert _matches(*enroll_receipt(after)) is expected


@pytest.mark.parametrize("sha", ["", "a" * 63, "a" * 65, "A" * 64, "g" * 64, None, 123])
def test_security_capability_hash_requires_exact_lowercase_sha256(sha):
    with pytest.raises(ValidationError):
        LiveSecurityCapabilities(user_info_sha256=sha, double_lock=DoubleLockCapability.NOT_ADVERTISED)


@pytest.mark.parametrize("state", [None, "unsupported", "false", "", True])
def test_security_capability_vocabulary_rejects_unsupported_assumptions(state):
    with pytest.raises(ValidationError):
        LiveSecurityCapabilities(user_info_sha256="c" * 64, double_lock=state)


@pytest.mark.parametrize("field", ["user_info_sha256", "double_lock"])
def test_security_capability_evidence_requires_both_fields(field):
    value = {"user_info_sha256": "c" * 64, "double_lock": "not_advertised"}
    del value[field]
    with pytest.raises(ValidationError):
        LiveSecurityCapabilities.model_validate(value)


def test_absent_profile_cannot_carry_security_capability_evidence():
    with pytest.raises(ValidationError, match="Absent profiles"):
        LiveSnapshot(external_person_id="SYNTHETIC-1", present=False,
            security_capabilities=capabilities(DoubleLockCapability.NOT_ADVERTISED))


def test_legacy_present_snapshot_is_readable_but_not_enrollment_evidence():
    legacy = profile().model_dump(mode="json", exclude={"security_capabilities"})
    restored = LiveSnapshot.model_validate(legacy)
    assert restored.security_capabilities is None
    assert not _matches(*enroll_receipt(restored))


@pytest.mark.parametrize("change", ["hash", "state", "missing"])
def test_name_edit_cannot_change_capability_evidence_in_reviewed_baseline(change):
    before = profile(security_capabilities=capabilities(DoubleLockCapability.NOT_ADVERTISED), double_lock_right=None)
    baseline = before.model_dump(mode="json")
    job = SimpleNamespace(
        action=LiveGateAction.EDIT,
        request={"expected_employee_no": "SYNTHETIC-1", "reviewed_name": "Reviewed Name"},
        dispatched=True, dispatch_count=1, baseline=baseline,
    )
    after = {**baseline, "full_name": "Reviewed Name"}
    result = LiveResultInput(
        lease_token="x" * 48, outcome="readback", vendor_accepted=True, worker_quiescent=True,
        before=before, after=LiveSnapshot.model_validate(after),
    )
    assert _matches(job, result)
    if change == "missing":
        after["security_capabilities"] = None
    else:
        after["security_capabilities"] = {
            **after["security_capabilities"],
            **({"user_info_sha256": "d" * 64} if change == "hash" else {"double_lock": "unknown"}),
        }
    result.after = LiveSnapshot.model_validate(after)
    assert not _matches(job, result)
