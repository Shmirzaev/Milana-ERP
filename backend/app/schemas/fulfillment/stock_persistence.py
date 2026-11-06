"""Apply decided stock/reservation writes in the caller's existing transaction.

The owning business service validates eligibility, locks rows and computes the
new quantities/status. These schema operations never commit or manage sessions.
"""
from sqlalchemy.orm import Session

from app.libs.enums.fulfillment import FinishedGoodsStatus
from app.schemas.production.tracking import FinishedGoodsStock, StockReservation


def reserve_stock_row(
    db: Session, stock: FinishedGoodsStock, *, sales_order_id: int,
    reserved_by: int | None, quantity: int, package_id: int | None,
    available_quantity: int, reserved_quantity: int, status: FinishedGoodsStatus,
) -> None:
    stock.available_qty = available_quantity
    stock.reserved_qty = reserved_quantity
    stock.status = status.value
    db.add(StockReservation(
        sales_order_id=sales_order_id, finished_goods_stock_id=stock.id,
        package_id=package_id, quantity=quantity, reserved_by=reserved_by,
    ))


def set_stock_metadata(
    db: Session, stock: FinishedGoodsStock, *, brand_id: int | None, collection_id: int | None,
) -> None:
    stock.brand_id = brand_id
    stock.collection_id = collection_id
