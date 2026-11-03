from typing import Annotated
from fastapi import APIRouter, Header
from app.core.deps import CurrentUser, DbSession
from app.libs.dto.people.turnstile_input import GateEnrollmentInput, GateEditInput, GatePhotoReplacementInput
from app.libs.dto.people.turnstile_output import GateOperationOutput
from app.libs.dto.people.turnstile_context_output import GateEmployeeContextOutput
from app.libs.enums.turnstile import GateAction
from app.models.people.turnstile_access_service import replace_gate_photo, edit_gate_employee, enroll_gate_employee, get_gate_context, get_gate_operation, get_gate_request

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

@router.post("/employees/{employee_id}/photo", status_code=202, response_model=GateOperationOutput)
def photo(employee_id: int, payload: GatePhotoReplacementInput, db: DbSession, actor: CurrentUser,
          idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None):
    return replace_gate_photo(db, actor, employee_id, payload, idempotency_key)

@router.get("/operations/{operation_id}", response_model=GateOperationOutput)
def operation(operation_id: int, db: DbSession, actor: CurrentUser):
    return get_gate_operation(db, actor, operation_id)


@router.get("/employees/{employee_id}/requests/{action}", response_model=GateOperationOutput | None)
def request_receipt(employee_id: int, action: GateAction, db: DbSession, actor: CurrentUser,
                    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None):
    return get_gate_request(db, actor, employee_id, action, idempotency_key)
