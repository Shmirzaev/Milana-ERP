from fastapi import APIRouter, Depends, Header, Query
from app.core.deps import DbSession, require_permissions
from app.libs.dto.inventory.eco_accessory_input import EcoAccessoryPlanIn, EcoAccessoryDecisionIn, EcoAccessoryIssueIn
from app.libs.dto.inventory.eco_accessory_output import EcoAccessoryPlanOut, EcoAccessoryItemOut, EcoAccessoryOrderListOut
from app.models.inventory import eco_accessory_service as service
from app.schemas import User

router = APIRouter(prefix="/eco-accessories", tags=["eco_accessories"])
READ = ("eco_accessories.read", "eco_accessories.manage", "eco_accessories.approve", "eco_accessories.issue")


@router.get("", response_model=EcoAccessoryOrderListOut)
def orders(db: DbSession, current: User = Depends(require_permissions(*READ)), q: str = Query("", max_length=200),
           page: int = Query(1, ge=1), page_size: int = Query(30, ge=1, le=100)):
    return service.list_orders(db, current, q=q, page=page, page_size=page_size)


@router.get("/items/options", response_model=list[EcoAccessoryItemOut])
def items(db: DbSession, current: User = Depends(require_permissions(*READ))):
    return service.item_options(db, current)


@router.get("/{order_id}", response_model=EcoAccessoryPlanOut)
def detail(order_id: int, db: DbSession, current: User = Depends(require_permissions(*READ))):
    return service.get_plan(db, current, order_id)


@router.put("/{order_id}", response_model=EcoAccessoryPlanOut)
def save(order_id: int, payload: EcoAccessoryPlanIn, db: DbSession, current: User = Depends(require_permissions("eco_accessories.manage"))):
    return service.save_plan(db, current, order_id, payload)


@router.post("/{order_id}/submit", response_model=EcoAccessoryPlanOut)
def submit(order_id: int, payload: EcoAccessoryDecisionIn, db: DbSession, current: User = Depends(require_permissions("eco_accessories.manage"))):
    return service.submit_plan(db, current, order_id, payload)


@router.post("/{order_id}/approve", response_model=EcoAccessoryPlanOut)
def approve(order_id: int, payload: EcoAccessoryDecisionIn, db: DbSession, current: User = Depends(require_permissions("eco_accessories.approve"))):
    return service.approve_plan(db, current, order_id, payload)


@router.post("/{order_id}/reopen", response_model=EcoAccessoryPlanOut)
def reopen(order_id: int, payload: EcoAccessoryDecisionIn, db: DbSession, current: User = Depends(require_permissions("eco_accessories.approve"))):
    return service.reopen_plan(db, current, order_id, payload)


@router.post("/{order_id}/issue", response_model=EcoAccessoryPlanOut)
def issue(order_id: int, payload: EcoAccessoryIssueIn, db: DbSession,
          current: User = Depends(require_permissions("eco_accessories.issue")),
          idempotency_key: str = Header(min_length=1, max_length=128)):
    return service.issue_plan(db, current, order_id, payload, idempotency_key)
