"""Apply a validated routing correction in the supplied outer transaction."""
from collections.abc import Sequence

from sqlalchemy.orm import Session

from app.schemas.production.production import WorkOrder


def set_cutting_work_order_department(
    db: Session, work_orders: Sequence[WorkOrder], department_id: int,
) -> None:
    for work_order in work_orders:
        work_order.department_id = department_id
    db.flush()
