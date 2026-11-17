from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from app.core.deps import DbSession, require_permissions
from app.models.factory_scope_service import require_operational_department_access
from app.models.packaging_scope_service import packaging_department_scope
from app.models.packaging_reports_service import build_packaging_report, build_packaging_report_page
from app.libs.dto.packaging.packaging_report_output import PackagingReportPage
from app.libs.enums.packaging import PackagingReportKind
from app.models.packaging_report_exports_service import export_packaging_report


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


@router.get("/page", response_model=PackagingReportPage, response_model_exclude_unset=True)
def get_report_page(
    db: DbSession,
    from_date: date,
    to_date: date,
    kind: PackagingReportKind,
    packaging_department_code: str | None = None,
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current=Depends(report_user),
):
    scope = packaging_department_scope(current, packaging_department_code)
    require_operational_department_access(current, scope)
    return build_packaging_report_page(db, scope, from_date, to_date, kind, offset, limit)


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
