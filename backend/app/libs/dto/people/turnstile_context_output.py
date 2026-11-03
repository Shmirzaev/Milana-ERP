from pydantic import BaseModel
from app.libs.dto.people.turnstile_output import GateOperationOutput
from app.libs.enums.turnstile import GateAction, GateBindingState

class GateDeviceContextOutput(BaseModel):
    id: int
    name: str
    device_key: str
    online: bool

class GateEditBaselineOutput(BaseModel):
    revision: int
    profile_hash: str
    full_name: str

class GateBindingContextOutput(BaseModel):
    device_id: int
    state: GateBindingState
    desired_revision: int
    edit_baseline: GateEditBaselineOutput | None = None

class GateEmployeeContextOutput(BaseModel):
    employee_id: int
    employee_no: str | None
    supported_actions: list[GateAction]
    simulator_enabled: bool
    devices: list[GateDeviceContextOutput]
    bindings: list[GateBindingContextOutput]
    operations: list[GateOperationOutput]
