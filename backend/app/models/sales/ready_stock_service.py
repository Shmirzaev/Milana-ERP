"""Ready-stock sales: allocation of finished goods and branded stock.

Contract for `_reserve_branded_stock`:
* input: a sales order, the acting user and optionally the order lines
* output: the reservations taken and the shortage lines left over
* refusals: 400 when the order mixes first-grade and standard lines, 409 when
  the stock is already fully reserved or the shortage cannot be filled
* records: `finished_goods_stock` quantities, `stock_reservations` rows and the
  sales order status and notes
* lock order: package rows (FOR NO KEY UPDATE) before the stock rows, the same order
  warehouse dispatch takes
* transaction owner: the calling sales operation
"""
from collections import defaultdict

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.libs.enums.sales import SalesOrderItemSourceType, SalesOrderStatus
from app.models.ready_stock_sales_service import reserve_ready_packs
from app.models.fulfillment.stock_service import reserve_pieces
from app.libs.enums.packaging import PackageStockKind
from app.libs.types.stock_reservation import PieceDemand, ReservationSummary, StockShortage
from app.models.workflow_service import notify_department
from app.models.work_management.tasks_service import create_stock_shortage_task
from app.schemas import (
    Customer, Department, Model, SalesOrder, SalesOrderItem, User,
)
from app.schemas.sales.sales_order_persistence import (
    append_sales_order_note,
    set_sales_order_status,
)

def _notify_planning_shortage(
    db: Session,
    *,
    so: SalesOrder,
    current: User,
    shortages: list[StockShortage],
) -> None:
    if not shortages:
        return
    planning_dept = db.query(Department).filter(Department.code == "PLN").first()
    planning_user = (
        db.query(User)
        .filter(User.is_active.is_(True), User.department_id == planning_dept.id if planning_dept else False)
        .order_by(User.id.asc())
        .first()
        if planning_dept
        else None
    )
    if planning_user:
        summary = ", ".join(f"M{r['model_id']} {r['color']}/{r['size']}: {r['shortage']}" for r in shortages[:6])
        if len(shortages) > 6:
            summary += f" (+{len(shortages) - 6} more)"
        create_stock_shortage_task(
            db,
            title=f"Stock shortage for {so.order_no}",
            description=f"Auto-created from reserve-stock. Resolve shortages: {summary}",
            assigned_to=planning_user.id,
            created_by=current.id,
            due_date=so.deadline,
        )
    notify_department(
        db,
        department_code="PLN",
        title=f"Shortage detected for {so.order_no}",
        message=f"{len(shortages)} shortage line(s) were detected during reserve-stock.",
        link=f"/sales-orders/{so.id}",
        exclude_user_id=current.id,
    )


def _shipment_handoff_details(
    db: Session,
    *,
    so: SalesOrder,
    lines: list[SalesOrderItem],
) -> tuple[int, str]:
    model_ids = sorted({int(line.model_id) for line in lines if line.model_id})
    model_rows = db.query(Model.id, Model.code, Model.name).filter(Model.id.in_(model_ids)).all() if model_ids else []
    model_by_id = {
        int(model_id): str(code or name or f"Model {model_id}")
        for model_id, code, name in model_rows
    }
    item_parts: list[str] = []
    total_qty = 0
    for line in lines:
        quantity = max(0, int(line.quantity or 0))
        total_qty += quantity
        model_label = model_by_id.get(int(line.model_id), f"Model {line.model_id}")
        variant = " / ".join(part for part in (str(line.color or "").strip(), str(line.size or "").strip()) if part)
        item_parts.append(f"{model_label}{f' ({variant})' if variant else ''} x {quantity}")

    customer = db.get(Customer, so.customer_id) if so.customer_id else None
    destination = str(customer.address or "").strip() if customer else ""
    customer_name = str(customer.name or "").strip() if customer else ""
    item_summary = "; ".join(item_parts) if item_parts else "No item lines"
    destination_summary = destination or "Not specified"
    customer_summary = f" for {customer_name}" if customer_name else ""
    return total_qty, f"{item_summary}. Destination{customer_summary}: {destination_summary}."


def _reserve_branded_stock(
    db: Session,
    *,
    so: SalesOrder,
    current: User,
    lines: list[SalesOrderItem] | None = None,
    fail_on_shortage: bool = False,
    notify_shortage: bool = True,
    notify_storage_when_ready: bool = False,
) -> tuple[list[ReservationSummary], list[StockShortage]]:
    line_rows = lines if lines is not None else db.query(SalesOrderItem).filter(SalesOrderItem.sales_order_id == so.id).all()
    if not line_rows:
        return [], []
    kinds = {line.source_type == SalesOrderItemSourceType.FIRST_GRADE.value for line in line_rows}
    if len(kinds) > 1:
        raise HTTPException(400, "FIRST_GRADE_SEPARATE_ORDER")
    stock_kind = PackageStockKind.FIRST_GRADE if True in kinds else PackageStockKind.STANDARD
    if any(line.requested_pack_count is not None for line in line_rows):
        reservations = reserve_ready_packs(db, so=so, lines=line_rows, user_id=current.id)
        if notify_storage_when_ready:
            _total_qty, handoff_message = _shipment_handoff_details(db, so=so, lines=line_rows)
            pack_count = sum(line.requested_pack_count for line in line_rows)
            notify_department(
                db, department_code="FGS", title=f"{so.order_no}: {pack_count} packs to prepare",
                message=handoff_message, link=f"/departments/FGS#shipping-order-{so.id}",
                exclude_user_id=current.id,
            )
        return reservations, []
    requested_by_variant: dict[tuple[int, str, str, int | None], int] = defaultdict(int)
    for line in line_rows:
        key = (int(line.model_id), str(line.color or "").strip(), str(line.size or "").strip(), line.brand_id)
        requested_by_variant[key] += int(line.quantity or 0)

    result = reserve_pieces(
        db, sales_order_id=so.id, reserved_by=current.id, stock_kind=stock_kind,
        demands=tuple(PieceDemand(key[0], key[3], key[1], key[2], quantity)
                      for key, quantity in requested_by_variant.items()),
        fail_on_shortage=fail_on_shortage,
    )
    reservations = list(result.reservations)
    shortages = list(result.shortages)

    if reservations:
        is_complete = not shortages
        set_sales_order_status(
            db,
            so,
            SalesOrderStatus.READY if is_complete else SalesOrderStatus.RESERVED,
        )
        auto_note = (
            "[Auto route] Branded stock reserved and sent to storage team for shipment prep."
            if is_complete
            else "[Auto route] Complete packages reserved; remaining quantity awaits another package."
        )
        append_sales_order_note(db, so, auto_note)
        if notify_storage_when_ready:
            total_qty, handoff_message = _shipment_handoff_details(db, so=so, lines=line_rows)
            reserved_qty = sum(int(row.get("qty") or 0) for row in reservations)
            notify_department(
                db,
                department_code="FGS",
                title=(
                    f"{so.order_no}: {total_qty} pcs ready to ship"
                    if is_complete
                    else f"{so.order_no}: {reserved_qty}/{total_qty} pcs ready to ship"
                ),
                message=handoff_message,
                link=f"/departments/FGS#shipping-order-{so.id}",
                exclude_user_id=current.id,
            )

    if shortages and notify_shortage:
        _notify_planning_shortage(db, so=so, current=current, shortages=shortages)

    return reservations, shortages
