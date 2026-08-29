from fastapi import HTTPException

from app.models import Department, WorkOrder


PACKAGING_DEPARTMENT_CODES = {"PKG", "BPK", "ECP"}


def normalize_packaging_department_code(value: str | None, *, default: str = "PKG") -> str:
    code = str(value or default).strip().upper()
    if code not in PACKAGING_DEPARTMENT_CODES:
        raise HTTPException(400, "Packaging department must be PKG, BPK, or ECP")
    return code


def packaging_department_scope(current, requested: str | None = None) -> str:
    from app.services.factory_scope import factory_for_department, packaging_department_for_factory, selected_factory_code, user_is_super_admin
    department = getattr(current, "department", None)
    user_department = str(getattr(department, "code", "") or "").strip().upper()
    if factory_for_department(user_department) or user_is_super_admin(current):
        expected = packaging_department_for_factory(selected_factory_code(current))
        target = normalize_packaging_department_code(requested, default=expected)
        if target != expected:
            raise HTTPException(403, "Log in to the matching factory to access this packaging data")
        return expected
    return normalize_packaging_department_code(requested)


def packaging_work_order_department_code(db, work_order: WorkOrder) -> str:
    department_code = db.query(Department.code).filter(Department.id == work_order.department_id).scalar()
    return normalize_packaging_department_code(department_code)


def packaging_department_for_order(
    db,
    production_order_id: int,
    production_batch_id: int | None = None,
) -> str:
    query = (
        db.query(WorkOrder)
        .join(Department, Department.id == WorkOrder.department_id)
        .filter(
            WorkOrder.production_order_id == production_order_id,
            WorkOrder.operation == "packaging",
            Department.code.in_(PACKAGING_DEPARTMENT_CODES),
        )
    )
    work_order = None
    if production_batch_id is not None:
        work_order = query.filter(WorkOrder.production_batch_id == production_batch_id).order_by(WorkOrder.id.desc()).first()
    if not work_order:
        work_order = query.filter(WorkOrder.production_batch_id.is_(None)).order_by(WorkOrder.id.desc()).first()
    if not work_order:
        work_order = query.order_by(WorkOrder.id.desc()).first()
    if not work_order:
        raise HTTPException(404, "Packaging work order not found for this production order")
    return packaging_work_order_department_code(db, work_order)


def require_packaging_work_order_access(current, db, work_order: WorkOrder, requested: str | None = None) -> str:
    owner = packaging_work_order_department_code(db, work_order)
    target = packaging_department_scope(current, requested or owner)
    if target != owner:
        raise HTTPException(403, "This work order belongs to another packaging department")
    return owner


def require_package_access(current, package) -> str:
    from app.services.factory_scope import factory_for_department, user_is_super_admin
    owner = normalize_packaging_department_code(getattr(package, "packaging_department_code", None))
    department = getattr(current, "department", None)
    user_department = str(getattr(department, "code", "") or "").strip().upper()
    if not factory_for_department(user_department) and not user_is_super_admin(current):
        return owner
    target = packaging_department_scope(current, owner)
    if target != owner:
        raise HTTPException(403, "This package belongs to another packaging department")
    return owner
