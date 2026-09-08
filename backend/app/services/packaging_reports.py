"""Read-only packaging reports. Packages, rather than capacity, own piece totals."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from io import BytesIO
import base64

from fastapi import HTTPException
from sqlalchemy.orm import lazyload, selectinload
from PIL import Image

from app.core.dt import as_utc
from app.models import (
    Brand,
    CuttingPassport,
    Department,
    Model,
    ModelImage,
    Package,
    ProductionBatch,
    ProductionOrder,
    WorkOrder,
)
from app.services.model_images import model_preview_image_url
from app.services.label_images import model_label_image_src


REPORT_TZ = timezone(timedelta(hours=5), "Asia/Tashkent")
MAX_REPORT_PACKAGES = 20000


def report_bounds(from_date: date, to_date: date):
    if from_date > to_date or to_date == date.max:
        raise HTTPException(400, "Invalid report date range")
    start = datetime.combine(from_date, time.min, REPORT_TZ).astimezone(timezone.utc)
    end = datetime.combine(to_date + timedelta(days=1), time.min, REPORT_TZ).astimezone(timezone.utc)
    return start, end


def _day(value: datetime) -> str:
    return as_utc(value).astimezone(REPORT_TZ).date().isoformat()


def _natural(value):
    import re

    return [(0, int(part)) if part.isdigit() else (1, part.casefold()) for part in re.split(r"(\d+)", str(value))]


def _identity(model):
    general = (model.details_json or {}).get("general") or {}
    model_no = general.get("model_no") or general.get("modelNo")
    variant = general.get("variant_no") or general.get("variantNo")
    if not model_no:
        # Match the catalogue's last-hyphen model/variant convention.
        parts = model.code.rsplit("-", 1)
        model_no, variant = (parts[0], parts[1]) if len(parts) == 2 else (model.code, "")
    return str(model_no), str(variant or "")


def build_packaging_report(
    db, department: str, from_date: date, to_date: date, *, include_images: bool = False
) -> dict:
    start, end = report_bounds(from_date, to_date)
    # Import timestamps describe historical stock import, never new packaging output.
    package_query = db.query(Package).filter(
        Package.packaging_department_code == department,
        Package.legacy_receipt_id.is_(None),
        Package.production_order_id.is_not(None),
    )
    packages = (
        package_query.options(
            lazyload("*"),
            selectinload(Package.items),
            selectinload(Package.batch_allocations),
        )
        .filter(Package.packed_at >= start, Package.packed_at < end)
        .order_by(
            Package.packed_at,
            Package.id,
        )
        .limit(MAX_REPORT_PACKAGES + 1)
        .all()
    )
    if len(packages) > MAX_REPORT_PACKAGES:
        raise HTTPException(413, "Report is too large. Select a shorter date range.")

    # Completion is an explicit Packaging workflow event, not an inferred quantity.
    completed = (
        db.query(WorkOrder)
        .join(Department)
        .options(lazyload("*"))
        .filter(
            Department.code == department,
            WorkOrder.operation == "packaging",
            WorkOrder.status == "completed",
            WorkOrder.end_time >= start,
            WorkOrder.end_time < end,
        )
        .order_by(WorkOrder.end_time, WorkOrder.id)
        .limit(MAX_REPORT_PACKAGES + 1)
        .all()
    )
    if len(completed) > MAX_REPORT_PACKAGES:
        raise HTTPException(413, "Report is too large. Select a shorter date range.")
    order_ids = {p.production_order_id for p in packages} | {w.production_order_id for w in completed}
    orders = (
        {
            o.id: o
            for o in db.query(ProductionOrder).options(lazyload("*")).filter(ProductionOrder.id.in_(order_ids)).all()
        }
        if order_ids
        else {}
    )
    model_ids = {p.model_id for p in packages} | {o.model_id for o in orders.values()}
    image_loader = selectinload(Model.images)
    if not include_images:
        image_loader = image_loader.defer(ModelImage.file_data)
    models = (
        {m.id: m for m in db.query(Model).options(lazyload("*"), image_loader).filter(Model.id.in_(model_ids)).all()}
        if model_ids
        else {}
    )
    pictures = {}
    if include_images:
        for model_id, model in models.items():
            source = model_label_image_src(model)
            if source and source.startswith("data:image/"):
                try:
                    with Image.open(BytesIO(base64.b64decode(source.split(",", 1)[1]))) as picture:
                        picture.thumbnail((120, 90))
                        output = BytesIO()
                        picture.convert("RGB").save(output, format="PNG")
                        pictures[model_id] = output.getvalue()
                except (ValueError, OSError):
                    # A missing/corrupt image does not suppress real production output.
                    continue
    brand_ids = (
        {p.brand_id for p in packages} | {o.brand_id for o in orders.values()} | {m.brand_id for m in models.values()}
    )
    brands = dict(db.query(Brand.id, Brand.name).filter(Brand.id.in_([b for b in brand_ids if b])).all())
    batches = (
        {
            b.id: b.batch_no
            for b in db.query(ProductionBatch.id, ProductionBatch.batch_no)
            .filter(ProductionBatch.production_order_id.in_(order_ids))
            .all()
        }
        if order_ids
        else {}
    )
    passports = defaultdict(set)
    if order_ids:
        for order_id, passport_no in (
            db.query(CuttingPassport.production_order_id, CuttingPassport.passport_no)
            .filter(CuttingPassport.production_order_id.in_(order_ids))
            .all()
        ):
            passports[order_id].add(passport_no)

    def identity(order_id, model_id, brand_id=None):
        order, model = orders[order_id], models[model_id]
        model_no, variant_no = _identity(model)
        return {
            "order_no": order.production_no,
            "passport": ", ".join(sorted(passports[order_id], key=_natural)),
            "brand": brands.get(brand_id or order.brand_id or model.brand_id, ""),
            "model_no": model_no,
            "variant_no": variant_no,
            "category": model.category or model.product_type or model.name,
            "image_url": model_preview_image_url(model),
        }

    grouped = {}
    for package in packages:
        batch_ids = tuple(sorted(a.production_batch_id for a in package.batch_allocations)) or (
            (package.production_batch_id,) if package.production_batch_id else ()
        )
        day = _day(package.packed_at)
        key = (day, package.production_order_id, package.model_id, package.brand_id, package.color, batch_ids)
        if key not in grouped:
            grouped[key] = {
                **identity(package.production_order_id, package.model_id, package.brand_id),
                "date": day,
                "batch": ", ".join(batches.get(b, "") for b in batch_ids),
                "color": package.color,
                "sizes": set(),
                "standards": set(),
                "package_count": 0,
                "quantity": 0,
                "two_piece_quantity": None,
                "first_sort": None,
                "second_sort": None,
                **({"_image": pictures.get(package.model_id)} if include_images else {}),
            }
        row = grouped[key]
        row["sizes"].update(i.size for i in package.items if i.quantity > 0)
        row["standards"].add(package.capacity)
        row["package_count"] += 1
        row["quantity"] += package.total_quantity
    entries = list(grouped.values())
    for row in entries:
        row["sizes"] = ", ".join(sorted(row["sizes"], key=_natural))
        row["standards"] = " / ".join(str(n) for n in sorted(row["standards"]))
    entries.sort(
        key=lambda r: (
            r["date"],
            _natural(r["model_no"]),
            _natural(r["variant_no"]),
            _natural(r["order_no"]),
            r["batch"],
            r["color"],
        )
    )
    daily = {}
    for row in entries:
        day = daily.setdefault(
            row["date"],
            {
                "date": row["date"],
                "package_count": 0,
                "quantity": 0,
                "two_piece_quantity": None,
                "first_sort": None,
                "second_sort": None,
                "cutting_defects": None,
            },
        )
        day["package_count"] += row["package_count"]
        day["quantity"] += row["quantity"]

    # Completed rows show the saved workflow output; these are lifetime job totals,
    # independent of packages created during the selected period.
    closed = [
        {
            **identity(w.production_order_id, orders[w.production_order_id].model_id),
            "date": _day(w.end_time),
            "batch": batches.get(w.production_batch_id, ""),
            "planned_quantity": w.planned_output_qty,
            "packed_quantity": w.passed_qty,
            "damaged_quantity": w.failed_qty,
            "first_sort": None,
            "second_sort": None,
            "shortage": None,
            "balance": w.passed_qty + w.failed_qty - w.planned_output_qty,
            "notes": w.notes or "",
        }
        for w in completed
    ]
    return {
        "from_date": from_date.isoformat(),
        "to_date": to_date.isoformat(),
        "packaging_department_code": department,
        "timezone": "Asia/Tashkent",
        "entries": entries,
        "completed": closed,
        "daily": list(daily.values()),
        "totals": {
            "package_count": sum(r["package_count"] for r in entries),
            "quantity": sum(r["quantity"] for r in entries),
        },
    }
