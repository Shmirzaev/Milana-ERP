from fastapi import HTTPException


SEWING_LINE_FACTORY_CODES = {"MIL", "BST", "ECO"}


def normalize_sewing_line_factory_code(value: str | None, *, default: str = "MIL") -> str:
    code = str(value or default).strip().upper()
    if code not in SEWING_LINE_FACTORY_CODES:
        raise HTTPException(400, "Sewing factory must be MIL, BST, or ECO")
    return code


def sewing_line_factory_scope(current, requested: str | None = None) -> str:
    from app.services.factory_scope import sewing_department_scope
    return sewing_department_scope(current, requested)


def require_sewing_flow_access(current, flow) -> str:
    target = sewing_line_factory_scope(current, getattr(flow, "factory_code", None))
    if target != getattr(flow, "factory_code", None):
        raise HTTPException(403, "You cannot access another sewing factory's line")
    return target
