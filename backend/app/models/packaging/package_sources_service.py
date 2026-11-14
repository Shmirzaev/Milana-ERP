"""Same-department saved Packaging output across sibling work orders."""
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.libs.dto.packaging.package_source_output import PackageSourceBalanceOut, PackageSourceOut, PackageSourcesOut
from app.libs.enums.packaging import PackagingDepartment
from app.models.packaging_scope_service import packaging_departments_for_order, require_packaging_work_order_access
from app.models.packages_service import packaged_quantity_balances_by_batch
from app.models.packaging.sewing_availability_service import direct_input_budgets
from app.models.packaging.allocation_items_service import source_size_state, size_balance_payload
from app.schemas import ProductionBatch, ProductionOrder, User, WorkOrder


def package_sources(db: Session, current: User, work_order_id: int) -> PackageSourcesOut:
    work_order = db.get(WorkOrder, work_order_id)
    if work_order is None:
        raise HTTPException(404, "Work order not found")
    if work_order.operation != "packaging":
        raise HTTPException(400, "Work order is not a packaging operation")
    owner = PackagingDepartment(require_packaging_work_order_access(current, db, work_order))
    source_type = db.query(ProductionOrder.source_type).filter_by(id=work_order.production_order_id).scalar()
    if source_type == "usluga":
        raise HTTPException(409, "Usluga does not enter warehouse receiving print runs")
    batches = db.query(ProductionBatch.id, ProductionBatch.batch_no, ProductionBatch.batch_index, ProductionBatch.name).filter_by(
        production_order_id=work_order.production_order_id,
    ).order_by(ProductionBatch.batch_index, ProductionBatch.id).all()
    owners = packaging_departments_for_order(db, work_order.production_order_id, {row.id for row in batches})
    packed, packaged = packaged_quantity_balances_by_batch(db, work_order.production_order_id)
    budgets = direct_input_budgets(db, work_order.production_order_id)
    sizes = source_size_state(db, db.get(ProductionOrder, work_order.production_order_id))

    def balance(batch_id: int | None) -> dict:
        budget = budgets.get(batch_id, {"sewing_output_qty": 0, "available_input_qty": 0})
        return {"packed_qty": max(0, packed.get(batch_id, 0)),
                "packaged_qty": max(0, packaged.get(batch_id, 0)),
                "available_to_package": max(0, packed.get(batch_id, 0) - packaged.get(batch_id, 0)) + budget["available_input_qty"],
                **budget, **size_balance_payload(sizes, batch_id)}
    return PackageSourcesOut(
        work_order_id=work_order.id, production_order_id=work_order.production_order_id,
        packaging_department=owner,
        items=[PackageSourceOut(
            id=row.id, batch_no=row.batch_no, batch_index=row.batch_index, name=row.name,
            **balance(row.id),
        ) for row in batches if PackagingDepartment(owners[row.id]) == owner],
        unbatched_source=PackageSourceBalanceOut(**balance(None)) if not batches else None,
    )
