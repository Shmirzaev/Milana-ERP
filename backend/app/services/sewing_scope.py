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
    band_id = getattr(current, "sewing_band_id", None)
    if band_id is not None and band_id != flow.id:
        raise HTTPException(403, "You cannot access another sewing band")
    target = sewing_line_factory_scope(current, getattr(flow, "factory_code", None))
    if target != getattr(flow, "factory_code", None):
        raise HTTPException(403, "You cannot access another sewing factory's line")
    return target


def band_report_scope(current, requested=None):
    band_id = getattr(current, "sewing_band_id", None)
    if band_id is not None:
        if requested is not None and requested != band_id:
            raise HTTPException(403, "You cannot access another sewing band")
        return band_id
    return requested


def enforce_band_request(user, request, db):
    """Fail closed for band accounts, including legacy/shared API routes.

    The dedicated workspace exposes only scoped operations. A role permission
    accidentally added later must not grant factory-wide reads or mutations.
    """
    if getattr(user, "sewing_band_id", None) is None:
        return
    from app.models import SewingFlow
    flow = db.get(SewingFlow, user.sewing_band_id)
    if not flow or not flow.is_active or flow.factory_code != "ECO":
        raise HTTPException(403, "Sewing band access is inactive")
    require_sewing_flow_access(user, flow)
    path = request.url.path.rstrip("/")
    if path in {"/api/auth/me", "/api/session/me"} and request.method == "GET":
        return
    if path in {"/api/auth/logout", "/api/session/logout", "/api/auth/change-password", "/api/session/change-password"} and request.method == "POST":
        return
    if path == "/api/sewing-bands" or path.startswith("/api/sewing-bands/"):
        return
    if path == "/api/sewing-daily-reports" or path.startswith("/api/sewing-daily-reports/"):
        return
    raise HTTPException(403, "This account can access only its sewing band workspace")
