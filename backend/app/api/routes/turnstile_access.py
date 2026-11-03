from typing import Annotated
from fastapi import APIRouter, Header
from app.core.deps import CurrentUser, DbSession
from app.libs.dto.people.turnstile_input import GateEnrollmentInput, GateEditInput
from app.libs.dto.people.turnstile_output import GateOperationOutput
from app.libs.dto.people.turnstile_context_output import GateEmployeeContextOutput
from app.models.people.turnstile_access_service import edit_gate_employee, enroll_gate_employee, get_gate_context, get_gate_operation

router = APIRouter(prefix="/turnstile-access", tags=["turnstile-access"])

@router.get("/employees/{employee_id}", response_model=GateEmployeeContextOutput)
def employee_context(employee_id: int, db: DbSession, actor: CurrentUser):
    return get_gate_context(db, actor, employee_id)

@router.post("/employees/{employee_id}/enroll", status_code=202, response_model=GateOperationOutput)
def enroll(employee_id: int, payload: GateEnrollmentInput, db: DbSession, actor: CurrentUser,
           idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None):
    return enroll_gate_employee(db, actor, employee_id, payload, idempotency_key)

@router.post("/employees/{employee_id}/edit", status_code=202, response_model=GateOperationOutput)
def edit(employee_id: int, payload: GateEditInput, db: DbSession, actor: CurrentUser,
         idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None):
    return edit_gate_employee(db, actor, employee_id, payload, idempotency_key)

@router.get("/operations/{operation_id}", response_model=GateOperationOutput)
def operation(operation_id: int, db: DbSession, actor: CurrentUser):
    return get_gate_operation(db, actor, operation_id)
