from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.libs.enums.turnstile import GateAction

class GateEnrollmentInput(BaseModel):
    expected_employee_no: str = Field(min_length=1, max_length=64)
    device_ids: list[int] = Field(min_length=1, max_length=32)
    photo_asset_id: int = Field(gt=0)
    reviewed_name: str | None = Field(default=None, min_length=1, max_length=255)
    manual_face_reviewed: bool
    action: GateAction = GateAction.ENROLL

    @field_validator("device_ids")
    @classmethod
    def validate_devices(cls, value: list[int]) -> list[int]:
        if any(i <= 0 for i in value) or len(set(value)) != len(value):
            raise ValueError("device IDs must be positive and unique")
        return value

    @field_validator("manual_face_reviewed")
    @classmethod
    def validate_review(cls, value: bool) -> bool:
        if not value:
            raise ValueError("manual face review is required")
        return value

    @field_validator("action")
    @classmethod
    def validate_action(cls, value: GateAction) -> GateAction:
        if value is not GateAction.ENROLL:
            raise ValueError("only enrollment is supported")
        return value


class GateEditTargetInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    device_id: int = Field(gt=0)
    expected_revision: int = Field(gt=0)
    expected_profile_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class GateEditInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_employee_no: str = Field(min_length=1, max_length=64)
    reviewed_name: str = Field(min_length=1, max_length=255)
    action: GateAction = GateAction.EDIT
    targets: list[GateEditTargetInput] = Field(min_length=1, max_length=32)

    @field_validator("reviewed_name", mode="before")
    @classmethod
    def trim_name(cls, value: str) -> str:
        return value.strip() if isinstance(value, str) else value

    @field_validator("action")
    @classmethod
    def validate_action(cls, value: GateAction) -> GateAction:
        if value is not GateAction.EDIT:
            raise ValueError("only edit is supported")
        return value

    @field_validator("targets")
    @classmethod
    def unique_devices(cls, value: list[GateEditTargetInput]) -> list[GateEditTargetInput]:
        if len({target.device_id for target in value}) != len(value):
            raise ValueError("device IDs must be unique")
        return value


class GatePhotoReplacementInput(BaseModel):
    """PHOTO shares the reviewed per-device baseline references used by EDIT."""
    model_config = ConfigDict(extra="forbid")
    expected_employee_no: str = Field(min_length=1, max_length=64)
    photo_asset_id: int = Field(gt=0)
    manual_face_reviewed: bool
    action: GateAction = GateAction.PHOTO
    targets: list[GateEditTargetInput] = Field(min_length=1, max_length=32)

    @field_validator("manual_face_reviewed")
    @classmethod
    def validate_review(cls, value: bool) -> bool:
        if not value:
            raise ValueError("manual face review is required")
        return value

    @field_validator("action")
    @classmethod
    def validate_action(cls, value: GateAction) -> GateAction:
        if value is not GateAction.PHOTO:
            raise ValueError("only photo replacement is supported")
        return value

    @field_validator("targets")
    @classmethod
    def unique_devices(cls, value: list[GateEditTargetInput]) -> list[GateEditTargetInput]:
        if len({target.device_id for target in value}) != len(value):
            raise ValueError("device IDs must be unique")
        return value


class GateRevokeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_employee_no: str = Field(min_length=1, max_length=64)
    action: GateAction = GateAction.REVOKE
    targets: list[GateEditTargetInput] = Field(min_length=1, max_length=32)

    @field_validator("action")
    @classmethod
    def validate_action(cls, value: GateAction) -> GateAction:
        if value is not GateAction.REVOKE:
            raise ValueError("only revoke is supported")
        return value

    @field_validator("targets")
    @classmethod
    def unique_devices(cls, value: list[GateEditTargetInput]) -> list[GateEditTargetInput]:
        if len({target.device_id for target in value}) != len(value):
            raise ValueError("device IDs must be unique")
        return value
