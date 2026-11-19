from fastapi import APIRouter, Depends
from app.core.deps import require_permissions
from app.db.session import SessionLocal
from app.models.people.turnstile_simulator_service import run_simulator_operation, reconnect_simulator_operation
from app.schemas import User
from app.libs.dto.people.turnstile_output import GateOperationOutput

router = APIRouter(prefix="/turnstile-access", tags=["turnstile-access"])

@router.post("/operations/{operation_id}/simulate", response_model=GateOperationOutput)
def simulate(operation_id: int, current: User = Depends(require_permissions("attendance.provision", "*"))) -> GateOperationOutput:
    return run_simulator_operation(SessionLocal, current, operation_id)

@router.post("/operations/{operation_id}/simulator-reconnect", response_model=GateOperationOutput)
def simulator_reconnect(operation_id: int, current: User = Depends(require_permissions("attendance.provision", "*"))) -> GateOperationOutput:
    return reconnect_simulator_operation(SessionLocal, current, operation_id)
