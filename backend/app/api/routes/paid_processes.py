from typing import Literal

from fastapi import APIRouter, Depends, Query

from app.core.deps import DbSession, require_permissions
from app.libs.dto.catalog.paid_process_input import PaidProcessIn
from app.models.catalog import paid_processes_service
from app.schemas import User

router = APIRouter(prefix="/paid-processes", tags=["paid-processes"])


@router.get("")
def list_processes(db: DbSession, search: str = Query("", max_length=255),
                   catalog_scope: Literal["standard", "usluga"] = "standard",
                   current: User = Depends(require_permissions("payroll.manage", "modeling.models", "*"))):
    return paid_processes_service.list_processes(current, db, search, catalog_scope)


@router.post("")
def create_process(payload: PaidProcessIn, db: DbSession,
                   catalog_scope: Literal["standard", "usluga"] = "standard",
                   current: User = Depends(require_permissions("payroll.manage", "modeling.models", "*"))):
    return paid_processes_service.create_process(current, db, payload, catalog_scope)
