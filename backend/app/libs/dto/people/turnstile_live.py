"""Physical worker contracts; device revisions are never simulator revisions."""
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator
from app.libs.enums.turnstile import DoubleLockCapability, GateBindingState, HikvisionUserType, LiveGateAction, LiveGateOutcome, LiveGateState, LiveWriteStep


class LiveModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LiveRightPlan(LiveModel):
    door_no: int = Field(ge=1, le=64)
    plan_template_no: str = Field(pattern=r"^[1-9][0-9]*(,[1-9][0-9]*)*$", max_length=128)


class LiveValidity(LiveModel):
    enabled: bool = True
    begin: datetime
    end: datetime

    @model_validator(mode="after")
    def valid_window(self):
        if self.begin.tzinfo is not None or self.end.tzinfo is not None or self.end <= self.begin:
            raise ValueError("An increasing device-local validity window without timezone is required")
        return self


class LiveAccessPolicy(LiveModel):
    validity: LiveValidity
    right_plans: list[LiveRightPlan] = Field(min_length=1, max_length=64)

    @field_validator("right_plans")
    @classmethod
    def unique_doors(cls, value):
        if len({p.door_no for p in value}) != len(value):
            raise ValueError("Door plans must be unique")
        return sorted(value, key=lambda p: p.door_no)


class LiveSecurityCapabilities(LiveModel):
    user_info_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    double_lock: DoubleLockCapability


class LiveSnapshot(LiveModel):
    external_person_id: str = Field(min_length=1, max_length=64)
    present: bool
    full_name: str | None = Field(default=None, max_length=255)
    user_type: HikvisionUserType | None = None
    policy: LiveAccessPolicy | None = None
    photo_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    face_count: int = Field(default=0, ge=0, le=1000)
    card_count: int = Field(default=0, ge=0, le=1000)
    fingerprint_count: int = Field(default=0, ge=0, le=1000)
    other_fields_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    local_ui_right: bool | None = None
    double_lock_right: bool | None = None
    security_capabilities: LiveSecurityCapabilities | None = None

    @model_validator(mode="after")
    def complete(self):
        if self.present:
            if not self.full_name or self.user_type is None or self.policy is None or self.other_fields_hash is None:
                raise ValueError("A complete physical profile is required")
            if self.face_count > 1 or (self.face_count == 1) != (self.photo_sha256 is not None):
                raise ValueError("A single face must have independently read photo evidence")
        elif self.model_dump(exclude={"external_person_id", "present"}) != {
            "full_name": None, "user_type": None, "policy": None, "photo_sha256": None,
            "face_count": 0, "card_count": 0, "fingerprint_count": 0, "other_fields_hash": None,
            "local_ui_right": None, "double_lock_right": None,
            "security_capabilities": None,
        }:
            raise ValueError("Absent profiles cannot carry present-profile evidence")
        return self


class LiveDeviceInput(LiveModel):
    enabled: bool = False
    writes_enabled: bool = False
    allowed_employee_numbers: list[str] = Field(default_factory=list, max_length=10000)
    access_policy: LiveAccessPolicy | None = None
    policy_reference: str | None = Field(default=None, min_length=1, max_length=255)
    handover_reference: str | None = Field(default=None, min_length=1, max_length=255)
    face_library_id: str = Field(pattern=r"^[1-9][0-9]*$", max_length=16)

    @field_validator("policy_reference", "handover_reference")
    @classmethod
    def reference(cls, value):
        if value is not None and (not value.strip() or value != value.strip()):
            raise ValueError("Approval references must be nonempty and trimmed")
        return value

    @field_validator("allowed_employee_numbers")
    @classmethod
    def numbers(cls, value):
        if any(not n or n != n.strip() or len(n) > 64 for n in value) or len(set(value)) != len(value):
            raise ValueError("Explicit unique stored employee numbers are required")
        return sorted(value)

    @model_validator(mode="after")
    def approved(self):
        if self.writes_enabled and (not self.enabled or not self.access_policy or not self.policy_reference or not self.handover_reference or not self.allowed_employee_numbers):
            raise ValueError("Writing needs enabled device, approved policy, handover and explicit employee allowlist")
        if self.access_policy and not self.access_policy.validity.enabled:
            raise ValueError("New enrollment requires a bounded enabled validity window")
        return self


class LiveRequestInput(LiveModel):
    expected_employee_no: str = Field(min_length=1, max_length=64)
    action: LiveGateAction
    device_id: int = Field(gt=0)
    expected_profile_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    reviewed_name: str | None = Field(default=None, min_length=1, max_length=255)
    photo_asset_id: int | None = Field(default=None, gt=0)
    manual_face_reviewed: bool = False
    delete_credentials_confirmed: bool = False

    @model_validator(mode="after")
    def action_fields(self):
        if self.action in (LiveGateAction.ENROLL, LiveGateAction.PHOTO):
            if not self.photo_asset_id or not self.manual_face_reviewed:
                raise ValueError("Validated photo and manual face review are required")
        elif self.photo_asset_id is not None or self.manual_face_reviewed:
            raise ValueError("This action cannot carry a photo")
        if self.action is LiveGateAction.EDIT and not (self.reviewed_name or "").strip():
            raise ValueError("A reviewed name is required")
        if self.reviewed_name is not None and self.action not in (LiveGateAction.ENROLL, LiveGateAction.EDIT):
            raise ValueError("This action cannot change the name")
        if self.action not in (LiveGateAction.OBSERVE, LiveGateAction.ENROLL) and not self.expected_profile_hash:
            raise ValueError("Review the physical baseline first")
        if self.action is LiveGateAction.DELETE and not self.delete_credentials_confirmed:
            raise ValueError("Explicit credential deletion confirmation is required")
        if self.delete_credentials_confirmed and self.action is not LiveGateAction.DELETE:
            raise ValueError("Deletion confirmation belongs only to Delete")
        return self


class LiveAdoptInput(LiveModel):
    expected_employee_no: str = Field(min_length=1, max_length=64)
    observation_job_id: int = Field(gt=0)
    expected_profile_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    identity_reviewed: bool


class LiveResultInput(LiveModel):
    lease_token: str = Field(min_length=32, max_length=128)
    outcome: LiveGateOutcome
    before: LiveSnapshot | None = None
    after: LiveSnapshot | None = None
    vendor_accepted: bool = False
    worker_quiescent: bool
    delete_completed: bool = False
    credentials_absent: bool = False


class LiveJobOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    employee_id: int
    device_id: int
    action: LiveGateAction
    state: LiveGateState
    created_at: datetime
    observation: LiveSnapshot | None = None
    profile_hash: str | None = None


class LiveClaimOutput(LiveModel):
    job_id: int
    device_key: str
    source_host: str
    certificate_sha256: str
    external_person_id: str
    action: LiveGateAction
    lease_token: str
    lease_expires_at: datetime
    face_library_id: str
    baseline: LiveSnapshot | None
    desired_name: str | None
    desired_policy: LiveAccessPolicy | None
    photo_asset_id: int | None
    photo_sha256: str | None


class LiveProfileOutput(LiveModel):
    device_id: int
    state: GateBindingState
    profile_hash: str | None
    snapshot: LiveSnapshot | None
    observed_at: datetime | None


class LiveDeviceOutput(LiveModel):
    id: int
    name: str
    writes_enabled: bool
    identity_allowed: bool


class LiveContextOutput(LiveModel):
    enabled: bool
    employee_no: str | None
    devices: list[LiveDeviceOutput]
    profiles: list[LiveProfileOutput]
    jobs: list[LiveJobOutput]


class LiveResolutionInput(LiveModel):
    worker_stopped_reference: str = Field(min_length=1, max_length=255)
    observation_job_id: int = Field(gt=0)

    @field_validator("worker_stopped_reference")
    @classmethod
    def reference(cls, value):
        if not value.strip() or value != value.strip():
            raise ValueError("A nonempty trimmed worker-stop reference is required")
        return value


class LiveDispatchInput(LiveModel):
    step: LiveWriteStep
