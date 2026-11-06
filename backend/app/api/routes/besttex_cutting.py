from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse

from app.core.deps import CurrentUser, DbSession
from app.libs.dto.production.besttex_cutting_output import BesttexCuttingPageOut
from app.models.production.besttex_cutting_service import besttex_cutting_sheet, list_besttex_cutting

router = APIRouter(prefix="/besttex/cutting-orders", tags=["besttex"])


@router.get("", response_model=BesttexCuttingPageOut)
def cutting_orders(db: DbSession, current: CurrentUser, page: int = Query(1, ge=1),
                   page_size: int = Query(30, ge=1, le=100), q: str = Query("", max_length=120)) -> BesttexCuttingPageOut:
    return list_besttex_cutting(db, current, page=page, page_size=page_size, search=q)


@router.get("/{record_id}/sheet", response_class=HTMLResponse)
def cutting_sheet(record_id: int, db: DbSession, current: CurrentUser) -> str:
    return besttex_cutting_sheet(db, current, record_id)
