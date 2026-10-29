from fastapi import APIRouter, Depends, Query

from app.core.deps import DbSession, require_permissions
from app.libs.dto.catalog.paid_process_input import PaidProcessIn
from app.libs.dto.catalog.paid_process_output import PaidProcessList, PaidProcessOut
from app.libs.enums.catalog import CatalogScope
from app.models.catalog import paid_processes_service
from app.schemas import User

router = APIRouter(prefix="/paid-processes", tags=["paid-processes"])


@router.get("", response_model=PaidProcessList)
def list_processes(db: DbSession, search: str = Query("", max_length=255),
                   catalog_scope: CatalogScope = CatalogScope.STANDARD,
                   current: User = Depends(require_permissions("payroll.manage", "modeling.models", "*"))) -> PaidProcessList:
    return paid_processes_service.list_processes(current, db, search, catalog_scope)


@router.post("", response_model=PaidProcessOut)
def create_process(payload: PaidProcessIn, db: DbSession,
                   catalog_scope: CatalogScope = CatalogScope.STANDARD,
                   current: User = Depends(require_permissions("payroll.manage", "modeling.models", "*"))) -> PaidProcessOut:
    return paid_processes_service.create_process(current, db, payload, catalog_scope)
