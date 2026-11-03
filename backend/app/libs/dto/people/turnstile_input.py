from pydantic import BaseModel, Field, field_validator
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
