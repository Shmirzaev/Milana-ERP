from fastapi import APIRouter, Depends

from app.core.deps import DbSession, require_permissions
from app.libs.dto.catalog.process_qr_sizes_input import ProcessQrSizesIn
from app.models.catalog import models_service
from app.schemas import User

router = APIRouter(tags=["catalog"])


@router.post("/models/{mid}/process-qr-sizes", status_code=201)
def add_process_qr_model_sizes(
    mid: int,
    payload: ProcessQrSizesIn,
    db: DbSession,
    current: User = Depends(require_permissions("payroll.manage", "modeling.models", "*")),
):
    return models_service.add_process_qr_model_sizes(current, db, mid, payload)
