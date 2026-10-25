from datetime import date

from fastapi import APIRouter, Depends, File, Header, UploadFile

from app.core.deps import CurrentUser, DbSession, require_permissions
from app.libs.dto.sales.sales_order_input import SalesOrderIn
from app.libs.dto.sales.sales_order_output import SalesOrderDetail, SalesOrderOut
from app.libs.dto.sales.sales_order_update import SalesOrderUpdate
from app.models.finance.invoices_service import generate_order_invoice
from app.models.sales import history_service, orders_service
from app.schemas import User

router = APIRouter(prefix="/sales-orders", tags=["sales"])


@router.get("/first-grade-options")
def first_grade_options(db: DbSession, current: User = Depends(require_permissions("sales.orders", "storage.packages", "*"))):
    return orders_service.first_grade_options(db)


@router.get("/ready-stock-options")
def ready_stock_options(db: DbSession, _: User = Depends(require_permissions("sales.orders", "*"))):
    return orders_service.ready_stock_options(db)


@router.post("/printing-attachments/upload", status_code=201)
async def upload_printing_attachment(
    file: UploadFile = File(...),
    current: User = Depends(require_permissions("sales.orders", "*")),
):
    return await orders_service.upload_printing_attachment(file)


@router.get("")
def list_sales_orders(
    db: DbSession, _: CurrentUser,
    status: str | None = None, order_type: str | None = None,
    customer_id: int | None = None, q: str | None = None,
    created_from: date | None = None,
    created_to: date | None = None,
    page: int = 1, page_size: int = 50,
    include_total: bool = False,
):
    return orders_service.list_sales_orders(
        db,
        status=status, order_type=order_type, customer_id=customer_id, q=q,
        created_from=created_from, created_to=created_to,
        page=page, page_size=page_size, include_total=include_total,
    )


@router.get("/history")
def list_sales_order_history(
    db: DbSession,
    _: CurrentUser,
    status: str | None = None,
    order_type: str | None = None,
    customer_id: int | None = None,
    q: str | None = None,
    created_from: date | None = None,
    created_to: date | None = None,
    page: int = 1,
    page_size: int = 50,
    include_total: bool = False,
):
    return history_service.list_sales_order_history(
        db,
        status=status,
        order_type=order_type,
        customer_id=customer_id,
        q=q,
        created_from=created_from,
        created_to=created_to,
        page=page,
        page_size=page_size,
        include_total=include_total,
    )


@router.get("/history/production/{pid}")
def get_stock_production_history(pid: int, db: DbSession, _: CurrentUser):
    return history_service.get_stock_production_history(pid, db)


@router.get("/{sid}/history")
def get_sales_order_history(sid: int, db: DbSession, _: CurrentUser):
    return history_service.get_sales_order_history(sid, db)


@router.post("", response_model=SalesOrderDetail, status_code=201)
def create_sales_order(payload: SalesOrderIn, db: DbSession, current: User = Depends(require_permissions("sales.orders", "*"))):
    return orders_service.create_sales_order(payload, db, current)


@router.get("/{sid}", response_model=SalesOrderDetail)
def get_sales_order(sid: int, db: DbSession, _: CurrentUser):
    return orders_service.get_sales_order(sid, db)


@router.patch("/{sid}", response_model=SalesOrderOut)
def update_sales_order(sid: int, payload: SalesOrderUpdate, db: DbSession, current: User = Depends(require_permissions("sales.orders", "*"))):
    return orders_service.update_sales_order(sid, payload, db, current)


@router.post("/{sid}/confirm", response_model=SalesOrderOut)
def confirm_sales_order(sid: int, db: DbSession, current: User = Depends(require_permissions("sales.orders", "*"))):
    return orders_service.confirm_sales_order(sid, db, current)


@router.post("/{sid}/reserve-stock")
def reserve_stock(
    sid: int,
    db: DbSession,
    current: User = Depends(require_permissions("sales.orders", "*")),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """For branded_stock_sale: try to reserve from FinishedGoodsStock for each line."""
    return orders_service.reserve_stock(sid, db, current, idempotency_key)


@router.post("/{sid}/generate-invoice")
def generate_invoice_for_order(
    sid: int,
    db: DbSession,
    current: User = Depends(require_permissions("finance.invoice", "sales.orders", "*")),
):
    return generate_order_invoice(db, sid, current)


@router.delete("/{sid}", status_code=204)
def delete_sales_order(sid: int, db: DbSession, current: User = Depends(require_permissions("sales.orders", "*"))):
    return orders_service.delete_sales_order(sid, db, current)
