"""Read-only full-history print-run search, scoped before paging/hydration."""
from datetime import date, datetime, time, timedelta, timezone
import re

from fastapi import HTTPException
from sqlalchemy import Integer, cast, func, or_, select

from app.core.deps import user_permissions
from app.libs.enums.packaging import PrintRunReceiptStatus
from app.models.package_workflows_service import run_list_payload
from app.models.packaging_scope_service import packaging_department_scope
from app.schemas import Model, Package, PackageItem, PackagePrintRun, PackagePrintRunMember

TASHKENT = timezone(timedelta(hours=5), "Asia/Tashkent")


def list_print_runs(db, current, *, production_order_id: int | None = None,
                    page: int | None = None, page_size: int = 50, q: str = "",
                    receipt_status: PrintRunReceiptStatus | None = None,
                    created_from: date | None = None, created_to: date | None = None):
    if created_from and created_to and created_from > created_to:
        raise HTTPException(400, "Start date must not be after end date")
    query = db.query(PackagePrintRun).filter(
        PackagePrintRun.deleted_at.is_(None), PackagePrintRun.returned_at.is_(None),
        PackagePrintRun.superseded_at.is_(None),
    )
    if production_order_id:
        query = query.filter(PackagePrintRun.id.in_(db.query(PackagePrintRunMember.run_id).join(
            Package, Package.id == PackagePrintRunMember.package_id,
        ).filter(Package.production_order_id == production_order_id)))
    if not set(user_permissions(current)).intersection({"storage.packages", "storage.shipment", "*"}):
        query = query.filter(PackagePrintRun.packaging_department_code == packaging_department_scope(current))
    if receipt_status is not None:
        query = query.filter(PackagePrintRun.received_at.is_not(None) if receipt_status == PrintRunReceiptStatus.RECEIVED
                             else PackagePrintRun.received_at.is_(None))
    # UTC binds also work with SQLite's naive UTC test timestamps. Day boundaries
    # are Tashkent calendar days, matching the warehouse clock and displayed dates.
    if created_from:
        start = datetime.combine(created_from, time.min, TASHKENT).astimezone(timezone.utc)
        query = query.filter(PackagePrintRun.created_at >= start)
    if created_to:
        end = datetime.combine(created_to, time.max, TASHKENT).astimezone(timezone.utc)
        query = query.filter(PackagePrintRun.created_at <= end)
    term = q.strip()
    if term:
        # UI formats OLD-6316 as OLD-V-6316; both spellings must find the same model.
        model_term = re.sub(r"-V-", "-", term.upper())
        if re.fullmatch(r"V-\d+", model_term):
            model_term = model_term[2:]
        model_ids = db.query(Model.id).filter(or_(
            func.replace(func.upper(Model.code), "-V-", "-").contains(model_term, autoescape=True),
            Model.name.icontains(term, autoescape=True),
        ))
        package_ids = db.query(Package.id).filter(or_(
            Package.package_no.icontains(term, autoescape=True), Package.barcode.icontains(term, autoescape=True),
            Package.model_id.in_(model_ids),
            Package.id.in_(db.query(PackageItem.package_id).filter(PackageItem.model_id.in_(model_ids))),
        ))
        # A shipped pack may be retained after deletion for accounting history.
        # Search the same active membership that run_list_payload displays.
        deleted = (func.json_array_elements_text(PackagePrintRun.deleted_package_ids).table_valued("value").render_derived()
                   if db.bind.dialect.name == "postgresql"
                   else func.json_each(PackagePrintRun.deleted_package_ids).table_valued("value"))
        deleted_member = select(1).select_from(deleted).where(
            cast(deleted.c.value, Integer) == PackagePrintRunMember.package_id,
        ).correlate(PackagePrintRun, PackagePrintRunMember).exists()
        matching_runs = db.query(PackagePrintRunMember.run_id).join(
            PackagePrintRun, PackagePrintRun.id == PackagePrintRunMember.run_id,
        ).filter(PackagePrintRunMember.package_id.in_(package_ids), ~deleted_member)
        query = query.filter(or_(
            PackagePrintRun.run_no.icontains(term, autoescape=True),
            PackagePrintRun.code.icontains(term, autoescape=True),
            PackagePrintRun.id.in_(matching_runs),
        ))
    if page is None:
        return run_list_payload(db, query.order_by(PackagePrintRun.id.desc()).limit(100).all())
    total = query.count()
    runs = query.order_by(PackagePrintRun.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {"rows": run_list_payload(db, runs), "total": total, "page": page,
            "page_size": page_size, "has_more": page * page_size < total}
