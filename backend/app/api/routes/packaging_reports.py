from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from app.core.deps import DbSession, require_permissions
from app.services.factory_scope import require_operational_department_access
from app.services.packaging_scope import packaging_department_scope
from app.services.packaging_reports import build_packaging_report
from app.services.packaging_report_exports import export_packaging_report


router = APIRouter(prefix="/packaging/reports", tags=["packaging"])
report_user = require_permissions("packaging.records", "packaging.packages", "planning.production")


def _report(db, current, from_date, to_date, department, *, include_images=False):
    scope = packaging_department_scope(current, department)
    require_operational_department_access(current, scope)
    return build_packaging_report(db, scope, from_date, to_date, include_images=include_images)


@router.get("")
def get_report(
    db: DbSession,
    from_date: date,
    to_date: date,
    packaging_department_code: str | None = None,
    current=Depends(report_user),
):
    return _report(db, current, from_date, to_date, packaging_department_code)


@router.get("/export.xlsx")
def download_report(
    db: DbSession,
    from_date: date,
    to_date: date,
    packaging_department_code: str | None = None,
    lang: Literal["en", "ru", "uz"] = "uz",
    current=Depends(report_user),
):
    report = _report(db, current, from_date, to_date, packaging_department_code, include_images=True)
    content = export_packaging_report(report, lang)
    filename = f"packaging_{report['packaging_department_code']}_{from_date}_{to_date}.xlsx"
    return Response(
        content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"},
    )
