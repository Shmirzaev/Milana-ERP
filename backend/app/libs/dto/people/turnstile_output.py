from datetime import datetime
from pydantic import BaseModel, ConfigDict
from app.libs.enums.turnstile import GateAction, GateMode, GateTargetState, GateErrorCode, GatePhotoValidation

class GatePhotoOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    employee_id: int
    factory_code: str
    sha256: str
    width: int
    height: int
    content_type: str
    validation: GatePhotoValidation
    created_at: datetime

class GateTargetOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    device_id: int
    device_name: str
    state: GateTargetState
    attempts: int
    error_code: GateErrorCode | None

class GateOperationOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    employee_id: int
    factory_code: str
    action: GateAction
    mode: GateMode
    revision: int
    full_name: str
    photo_asset_id: int
    external_person_id: str
    created_at: datetime
    targets: list[GateTargetOutput]
