from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import joinedload

from app.core.deps import DbSession, require_permissions
from app.models import CuttingPassport, Model, SewingAssignment, SewingDailyReport, SewingFlow, User, WorkOrder, ProductionOrder, ProductionBatch
from app.schemas.sewing_daily_report import (
    SewingDailyLineContext,
    SewingDailyLineWorkOrder,
    SewingDailyModelInfo,
    SewingDailyReportCreate,
    SewingDailyReportListOut,
    SewingDailyReportOut,
    SewingDailyReportSummaryLine,
)
from app.services.audit import log_action
from app.services.model_images import material_preview_image_url, model_preview_image_url
from app.services.sewing_daily_report_exports import (
    ReportLanguage,
    build_sewing_daily_report_pdf,
    build_sewing_daily_report_xlsx,
)

router = APIRouter(prefix="/sewing-daily-reports", tags=["sewing-daily-reports"])

SECTIONED_LINE_CODES = {"SEW-01", "SEW-06", "SEW-07", "SEW-09"}

_ACTIVE_WO_STATUSES = ("waiting", "pending", "collected", "ready", "in_progress", "paused", "new", "planning")
_ACTIVE_ASSIGN_STATUSES = ("planned", "in_progress")
_ASSIGNMENT_MANAGED_STATUSES = ("planned", "in_progress", "completed")
_REPORT_READ_PERMS = ("sewing.workspace",)


def _model_code_parts(model: Model | None) -> tuple[str | None, str | None]:
    if not model:
        return None, None
    code = str(model.code or "").strip()
    code_model_no, separator, code_variant_no = code.rpartition("-")
    if not separator:
        code_model_no, code_variant_no = code, ""
    details = model.details_json if isinstance(model.details_json, dict) else {}
    general = details.get("general") if isinstance(details.get("general"), dict) else {}
    model_no = str(general.get("model_no") or general.get("modelNo") or code_model_no or "").strip()
    variant_no = str(general.get("variant_no") or general.get("variantNo") or code_variant_no or "").strip()
    return model_no or None, variant_no or None


def _model_info(model: Model | None) -> dict:
    model_no, variant_no = _model_code_parts(model)
    return {
        "model_id": int(model.id) if model else None,
        "model_code": model.code if model else None,
        "model_no": model_no,
        "variant_no": variant_no,
        "model_name": model.name if model else None,
        "model_image_url": model_preview_image_url(model),
        "fabric_image_url": material_preview_image_url(model),
    }


def _production_model_info(db, production_order: ProductionOrder | None, cache: dict[int, dict] | None = None) -> dict:
    if not production_order:
        return _model_info(None)
    production_id = int(production_order.id)
    if cache is not None and production_id in cache:
        return cache[production_id]
    model = db.get(Model, int(production_order.model_id)) if production_order.model_id else None
    payload = _model_info(model)
    if cache is not None:
        cache[production_id] = payload
    return payload


def _production_kroy_no(db, production_order_id: int | None, cache: dict[int, str | None] | None = None) -> str | None:
    if not production_order_id:
        return None
    production_id = int(production_order_id)
    if cache is not None and production_id in cache:
        return cache[production_id]
    value = (
        db.query(CuttingPassport.passport_no)
        .filter(CuttingPassport.production_order_id == production_id)
        .order_by(CuttingPassport.date.desc(), CuttingPassport.id.desc())
        .limit(1)
        .scalar()
    )
    result = str(value or "").strip() or None
    if cache is not None:
        cache[production_id] = result
    return result


def _report_model_info(
    db,
    report: SewingDailyReport,
    production_order: ProductionOrder | None,
    cache: dict[int, dict] | None = None,
) -> dict:
    payload = dict(_production_model_info(db, production_order, cache))
    manual_model_no = str(report.manual_model_no or "").strip()
    manual_variant_no = str(report.manual_variant_no or "").strip()
    if manual_model_no:
        payload["model_no"] = manual_model_no
    if manual_variant_no:
        payload["variant_no"] = manual_variant_no
    return payload


def _work_order_context(
    db,
    work_order: WorkOrder,
    *,
    sewing_assignment: SewingAssignment | None = None,
    kroy_cache: dict[int, str | None] | None = None,
) -> SewingDailyLineWorkOrder:
    batch_id = sewing_assignment.production_batch_id if sewing_assignment and sewing_assignment.production_batch_id else work_order.production_batch_id
    batch = db.get(ProductionBatch, int(batch_id)) if batch_id else None
    if sewing_assignment is not None:
        planned = int(sewing_assignment.quantity or 0)
        completed = int(sewing_assignment.completed_qty or 0)
        assignment_id = int(sewing_assignment.id)
    else:
        planned = max(int(work_order.planned_input_qty or 0), int(work_order.planned_output_qty or 0))
        completed = int(work_order.passed_qty or 0) + int(work_order.failed_qty or 0)
        assignment_id = None
    return SewingDailyLineWorkOrder(
        work_order_id=int(work_order.id),
        sewing_assignment_id=assignment_id,
        production_order_id=int(work_order.production_order_id),
        production_batch_id=batch_id,
        batch_no=batch.batch_no if batch else None,
        batch_name=batch.name if batch else None,
        batch_index=batch.batch_index if batch else None,
        order_no=work_order.order_no,
        production_no=work_order.production_no,
        sales_order_no=work_order.sales_order_no,
        status=work_order.status,
        planned_qty=planned,
        completed_qty=completed,
        remaining_qty=max(0, planned - completed),
        deadline=work_order.deadline,
        kroy_no=_production_kroy_no(db, work_order.production_order_id, kroy_cache),
        **_production_model_info(db, work_order.production_order),
    )


def _line_context(db, flow: SewingFlow) -> SewingDailyLineContext:
    kroy_cache: dict[int, str | None] = {}
    order_ref_load = joinedload(WorkOrder.production_order).joinedload(ProductionOrder.sales_order)
    assignment_order_ref_load = (
        joinedload(SewingAssignment.work_order)
        .joinedload(WorkOrder.production_order)
        .joinedload(ProductionOrder.sales_order)
    )
    split_assignments = (
        db.query(SewingAssignment)
        .options(assignment_order_ref_load)
        .join(WorkOrder, WorkOrder.id == SewingAssignment.work_order_id)
        .filter(SewingAssignment.sewing_flow_id == flow.id)
        .filter(SewingAssignment.status.in_(_ACTIVE_ASSIGN_STATUSES))
        .filter(SewingAssignment.completed_qty < SewingAssignment.quantity)
        .filter(WorkOrder.status.in_(_ACTIVE_WO_STATUSES))
        .order_by(SewingAssignment.status.desc(), SewingAssignment.updated_at.desc(), SewingAssignment.id.desc())
        .all()
    )
    active = [
        _work_order_context(db, assignment.work_order, sewing_assignment=assignment, kroy_cache=kroy_cache)
        for assignment in split_assignments
        if assignment.work_order is not None
    ]

    assignment_managed_wo_ids = {
        wid
        for (wid,) in db.query(SewingAssignment.work_order_id)
        .filter(SewingAssignment.status.in_(_ASSIGNMENT_MANAGED_STATUSES))
        .distinct()
        .all()
    }
    direct_rows = (
        db.query(WorkOrder)
        .options(order_ref_load)
        .filter(WorkOrder.sewing_flow_id == flow.id)
        .filter(WorkOrder.operation == "sewing")
        .filter(WorkOrder.status.in_(_ACTIVE_WO_STATUSES))
        .order_by(WorkOrder.status.desc(), WorkOrder.updated_at.desc(), WorkOrder.id.desc())
        .all()
    )
    for work_order in direct_rows:
        if work_order.id in assignment_managed_wo_ids:
            continue
        planned = max(int(work_order.planned_input_qty or 0), int(work_order.planned_output_qty or 0))
        completed = int(work_order.passed_qty or 0) + int(work_order.failed_qty or 0)
        if planned > 0 and completed >= planned:
            continue
        active.append(_work_order_context(db, work_order, kroy_cache=kroy_cache))

    active.sort(key=lambda row: (row.status != "in_progress", row.work_order_id))
    return SewingDailyLineContext(
        sewing_flow_id=int(flow.id),
        line_code=flow.code,
        line_name=flow.name,
        active_work_orders=active,
    )


@router.get("/line-context", response_model=SewingDailyLineContext)
def line_context(
    sewing_flow_id: int,
    db: DbSession,
    _: User = Depends(require_permissions(*_REPORT_READ_PERMS)),
):
    flow = db.get(SewingFlow, sewing_flow_id)
    if not flow:
        raise HTTPException(404, "Sewing line not found")
    if not flow.is_active:
        raise HTTPException(400, "Sewing line is inactive")
    return _line_context(db, flow)


@router.post("", response_model=SewingDailyReportOut, status_code=201)
def create_report(
    payload: SewingDailyReportCreate,
    db: DbSession,
    current: User = Depends(require_permissions("sewing.workspace")),
):
    flow = db.get(SewingFlow, payload.sewing_flow_id)
    if not flow:
        raise HTTPException(404, "Sewing line not found")
    if not flow.is_active:
        raise HTTPException(400, "Sewing line is inactive")
    work_order = None
    assignment = None
    if payload.work_order_id is not None:
        work_order = (
            db.query(WorkOrder)
            .options(joinedload(WorkOrder.production_order).joinedload(ProductionOrder.sales_order))
            .filter(WorkOrder.id == payload.work_order_id)
            .first()
        )
        if not work_order or work_order.operation != "sewing":
            raise HTTPException(404, "Sewing work order not found")
        if payload.sewing_assignment_id is not None:
            assignment = db.get(SewingAssignment, payload.sewing_assignment_id)
            if (
                not assignment
                or assignment.work_order_id != work_order.id
                or assignment.sewing_flow_id != flow.id
            ):
                raise HTTPException(400, "Selected assignment does not belong to this sewing line and order")
        elif work_order.sewing_flow_id != flow.id:
            raise HTTPException(400, "Selected work order is not assigned to this sewing line")

    report_batch_id = (
        assignment.production_batch_id
        if assignment and assignment.production_batch_id
        else work_order.production_batch_id if work_order else None
    )
    report = SewingDailyReport(
        report_date=payload.report_date,
        sewing_flow_id=flow.id,
        work_order_id=work_order.id if work_order else None,
        sewing_assignment_id=payload.sewing_assignment_id,
        production_order_id=work_order.production_order_id if work_order else None,
        production_batch_id=report_batch_id,
        line_code=flow.code,
        line_name=flow.name,
        order_no=work_order.order_no if work_order else None,
        production_no=work_order.production_no if work_order else None,
        sales_order_no=work_order.sales_order_no if work_order else None,
        manual_model_no=(payload.manual_model_no or "").strip() or None,
        manual_variant_no=(payload.manual_variant_no or "").strip() or None,
        kroy_no=(payload.kroy_no or "").strip() or _production_kroy_no(
            db,
            work_order.production_order_id if work_order else None,
        ),
        sewn_qty=payload.sewn_qty,
        section_quantities=(payload.section_quantities if flow.code in SECTIONED_LINE_CODES else None),
        section_no=(payload.section_no if flow.code in SECTIONED_LINE_CODES else None),
        section_name=(payload.section_name if flow.code in SECTIONED_LINE_CODES else None),
        top_qty=(payload.top_qty if flow.code in SECTIONED_LINE_CODES else None),
        bottom_qty=(payload.bottom_qty if flow.code in SECTIONED_LINE_CODES else None),
        defective_qty=payload.defective_qty,
        defect_reason=(payload.defect_reason or "").strip() or None,
        notes=(payload.notes or "").strip() or None,
        created_by=current.id,
    )
    db.add(report)
    db.flush()
    log_action(
        db,
        current,
        "create",
        "SewingDailyReport",
        report.id,
        new_value={
            "report_date": payload.report_date,
            "sewing_flow_id": flow.id,
            "work_order_id": work_order.id if work_order else None,
            "kroy_no": report.kroy_no,
            "sewn_qty": payload.sewn_qty,
            "section_quantities": payload.section_quantities if flow.code in SECTIONED_LINE_CODES else None,
            "section_no": payload.section_no if flow.code in SECTIONED_LINE_CODES else None,
            "section_name": payload.section_name if flow.code in SECTIONED_LINE_CODES else None,
            "top_qty": payload.top_qty if flow.code in SECTIONED_LINE_CODES else None,
            "bottom_qty": payload.bottom_qty if flow.code in SECTIONED_LINE_CODES else None,
            "defective_qty": payload.defective_qty,
        },
    )
    db.commit()
    db.refresh(report)
    response_payload = SewingDailyReportOut.model_validate(report).model_dump()
    response_payload.update(_report_model_info(db, report, work_order.production_order if work_order else None))
    return response_payload


def _report_date_range(
    report_date: date | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
) -> tuple[date, date]:
    if report_date is not None:
        from_date = report_date
        to_date = report_date
    if from_date is None and to_date is None:
        from_date = date.today()
        to_date = from_date
    elif from_date is None:
        from_date = to_date
    elif to_date is None:
        to_date = from_date
    if from_date is None or to_date is None:
        raise HTTPException(400, "Report date is required")
    if from_date > to_date:
        raise HTTPException(400, "from_date cannot be after to_date")
    return from_date, to_date


def _report_list(
    db,
    *,
    from_date: date,
    to_date: date,
    sewing_flow_id: int | None = None,
) -> SewingDailyReportListOut:
    qry = db.query(SewingDailyReport).filter(SewingDailyReport.report_date >= from_date, SewingDailyReport.report_date <= to_date)
    if sewing_flow_id:
        qry = qry.filter(SewingDailyReport.sewing_flow_id == sewing_flow_id)
    rows = qry.order_by(SewingDailyReport.report_date.desc(), SewingDailyReport.line_code.asc(), SewingDailyReport.created_at.desc()).all()

    production_ids = sorted({int(row.production_order_id) for row in rows if row.production_order_id})
    production_orders = (
        db.query(ProductionOrder)
        .filter(ProductionOrder.id.in_(production_ids))
        .all()
        if production_ids
        else []
    )
    production_by_id = {int(row.id): row for row in production_orders}
    model_cache: dict[int, dict] = {}
    row_payloads: list[dict] = []
    summary_map: dict[int, dict] = {}
    for row in rows:
        model_info = _report_model_info(
            db,
            row,
            production_by_id.get(int(row.production_order_id)) if row.production_order_id else None,
            model_cache,
        )
        row_payload = SewingDailyReportOut.model_validate(row).model_dump()
        row_payload.update(model_info)
        row_payloads.append(row_payload)
        bucket = summary_map.setdefault(
            int(row.sewing_flow_id),
            {
                "sewing_flow_id": int(row.sewing_flow_id),
                "line_code": row.line_code,
                "line_name": row.line_name,
                "total_sewn_qty": 0,
                "total_defective_qty": 0,
                "report_count": 0,
                "orders": set(),
                "models": {},
                "defect_reasons": set(),
                "kroy_nos": set(),
            },
        )
        bucket["total_sewn_qty"] += int(row.sewn_qty or 0)
        bucket["total_defective_qty"] += int(row.defective_qty or 0)
        bucket["report_count"] += 1
        if row.order_no:
            bucket["orders"].add(row.order_no)
        model_key = "|".join(
            str(value or "")
            for value in (model_info.get("model_id"), model_info.get("model_no"), model_info.get("variant_no"))
        )
        if model_key:
            bucket["models"][str(model_key)] = model_info
        if row.defect_reason:
            bucket["defect_reasons"].add(row.defect_reason)
        if row.kroy_no:
            bucket["kroy_nos"].add(row.kroy_no)

    summary = [
        SewingDailyReportSummaryLine(
            sewing_flow_id=bucket["sewing_flow_id"],
            line_code=bucket["line_code"],
            line_name=bucket["line_name"],
            total_sewn_qty=bucket["total_sewn_qty"],
            total_defective_qty=bucket["total_defective_qty"],
            report_count=bucket["report_count"],
            order_count=len(bucket["orders"]),
            orders=sorted(bucket["orders"]),
            models=[SewingDailyModelInfo(**model) for model in bucket["models"].values()],
            defect_reasons=sorted(bucket["defect_reasons"]),
            kroy_nos=sorted(bucket["kroy_nos"]),
        )
        for bucket in sorted(summary_map.values(), key=lambda item: item["line_code"])
    ]
    return SewingDailyReportListOut(
        from_date=from_date,
        to_date=to_date,
        rows=row_payloads,
        summary=summary,
        total_sewn_qty=sum(int(row.sewn_qty or 0) for row in rows),
        total_defective_qty=sum(int(row.defective_qty or 0) for row in rows),
    )


def _report_generated_labels() -> tuple[str, str]:
    timestamp = datetime.now(ZoneInfo("Asia/Tashkent"))
    return timestamp.strftime("%Y-%m-%d %H:%M"), timestamp.strftime("%Y%m%d_%H%M")


@router.get("/export.xlsx")
def download_report_excel(
    db: DbSession,
    report_date: date | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    sewing_flow_id: int | None = None,
    lang: ReportLanguage = "uz",
    _: User = Depends(require_permissions(*_REPORT_READ_PERMS)),
):
    resolved_from, resolved_to = _report_date_range(report_date, from_date, to_date)
    report = _report_list(
        db,
        from_date=resolved_from,
        to_date=resolved_to,
        sewing_flow_id=sewing_flow_id,
    )
    generated_label, filename_timestamp = _report_generated_labels()
    content = build_sewing_daily_report_xlsx(report, generated_label, lang)
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": (
                f'attachment; filename="daily_sewing_report_{resolved_from}_{resolved_to}_{filename_timestamp}.xlsx"'
            ),
        },
    )


@router.get("/export.pdf")
def download_report_pdf(
    db: DbSession,
    report_date: date | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    sewing_flow_id: int | None = None,
    lang: ReportLanguage = "uz",
    _: User = Depends(require_permissions(*_REPORT_READ_PERMS)),
):
    resolved_from, resolved_to = _report_date_range(report_date, from_date, to_date)
    report = _report_list(
        db,
        from_date=resolved_from,
        to_date=resolved_to,
        sewing_flow_id=sewing_flow_id,
    )
    generated_label, filename_timestamp = _report_generated_labels()
    content = build_sewing_daily_report_pdf(report, generated_label, lang)
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="daily_sewing_report_{resolved_from}_{resolved_to}_{filename_timestamp}.pdf"'
            ),
        },
    )


@router.get("", response_model=SewingDailyReportListOut)
def list_reports(
    db: DbSession,
    _: User = Depends(require_permissions(*_REPORT_READ_PERMS)),
    report_date: date | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    sewing_flow_id: int | None = None,
):
    resolved_from, resolved_to = _report_date_range(report_date, from_date, to_date)
    return _report_list(
        db,
        from_date=resolved_from,
        to_date=resolved_to,
        sewing_flow_id=sewing_flow_id,
    )
