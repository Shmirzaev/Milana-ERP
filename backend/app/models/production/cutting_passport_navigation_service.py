"""Read-only passport links to the real Cutting work order, without per-row queries."""
from app.schemas import Department, WorkOrder
from app.models.factory_scope_service import cutting_department_scope


def passport_cutting_work_orders(db, passports, batch_map, current) -> dict[int, int]:
    order_ids = {p.production_order_id for p in passports if p.production_order_id}
    if not order_ids:
        return {}
    department = cutting_department_scope(current, None)
    rows = db.query(WorkOrder.id, WorkOrder.production_order_id, WorkOrder.production_batch_id).join(
        Department, Department.id == WorkOrder.department_id,
    ).filter(WorkOrder.production_order_id.in_(order_ids), WorkOrder.operation == "cutting",
             Department.code == department).order_by(WorkOrder.id).all()
    by_order = {}
    for row in rows:
        by_order.setdefault(row.production_order_id, []).append(row)
    links = {}
    for passport in passports:
        candidates = by_order.get(passport.production_order_id, [])
        batch_id = batch_map.get(passport.id, {}).get("production_batch_id")
        exact = [row for row in candidates if batch_id is not None and row.production_batch_id == batch_id]
        parents = [row for row in candidates if row.production_batch_id is None]
        # Never link a passport to another Nastil merely because it sorts first.
        matches = exact or parents
        if len(matches) == 1:
            links[passport.id] = matches[0].id
    return links
