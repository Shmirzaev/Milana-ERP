"""Read-only packaging reports. Packages, rather than capacity, own piece totals."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from io import BytesIO
import base64

from fastapi import HTTPException
from sqlalchemy.orm import lazyload, selectinload, load_only
from PIL import Image

from app.core.dt import as_utc
from app.schemas import (
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
from app.models.model_images_service import model_preview_image_url
from app.models.label_images_service import model_label_image_src


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


def build_packaging_report_page(db, department, from_date, to_date, kind, offset, limit):
    """Aggregate compact group identities before hydrating only the requested rows."""
    import hashlib
    from sqlalchemy import text, func
    from app.libs.enums.packaging import PackagingReportKind

    start, end = report_bounds(from_date, to_date)
    package_filter = (Package.packaging_department_code == department, Package.legacy_receipt_id.is_(None),
                      Package.production_order_id.is_not(None), Package.packed_at >= start, Package.packed_at < end)
    work_filter = (Department.code == department, WorkOrder.operation == "packaging", WorkOrder.status == "completed",
                   WorkOrder.end_time >= start, WorkOrder.end_time < end)
    if (db.query(func.count(Package.id)).filter(*package_filter).scalar() > MAX_REPORT_PACKAGES or
        db.query(func.count(WorkOrder.id)).join(Department).filter(*work_filter).scalar() > MAX_REPORT_PACKAGES):
        raise HTTPException(413, "Report is too large. Select a shorter date range.")

    # The sorted allocation tuple takes precedence over the legacy single batch.
    base = """
      WITH package_facts AS (
        SELECT p.id, p.packed_at, p.production_order_id, p.model_id, p.brand_id, p.color,
               p.total_quantity, p.capacity, CAST(timezone('Asia/Tashkent', p.packed_at) AS date) AS day,
               COALESCE((SELECT array_agg(a.production_batch_id ORDER BY a.production_batch_id)
                         FROM package_batch_allocations a WHERE a.package_id = p.id),
                        CASE WHEN p.production_batch_id IS NULL THEN ARRAY[]::integer[]
                             ELSE ARRAY[p.production_batch_id] END) AS batch_ids
        FROM packages p
        WHERE p.packaging_department_code = :department AND p.legacy_receipt_id IS NULL
          AND p.production_order_id IS NOT NULL AND p.packed_at >= :start AND p.packed_at < :end
      ), keyed AS (
        SELECT *, CAST(jsonb_build_array(day, production_order_id, model_id, brand_id, color, batch_ids) AS text) AS identity
        FROM package_facts
      )
    """
    args = {"department": department, "start": start, "end": end}
    if kind == PackagingReportKind.DAILY:
        day_rows = db.execute(text(base + """
          SELECT day, count(*) AS package_count, sum(total_quantity) AS quantity
          FROM keyed GROUP BY day ORDER BY day
        """), args).mappings().all()
        rows = [{"row_key": "day:" + r["day"].isoformat(), "date": r["day"].isoformat(),
                 "package_count": r["package_count"], "quantity": r["quantity"]} for r in day_rows]
        summary = {field: sum(row[field] for row in rows) if rows else None for field in ("package_count", "quantity")}
        return {"rows": rows[offset:offset + limit], "total": len(rows), "offset": offset, "limit": limit,
                "has_more": offset + limit < len(rows), "summary": summary}

    if kind == PackagingReportKind.COMPLETED:
        summary_row = db.query(func.count(WorkOrder.id), func.sum(WorkOrder.planned_output_qty),
                               func.sum(WorkOrder.passed_qty), func.sum(WorkOrder.failed_qty),
                               func.sum(WorkOrder.passed_qty + WorkOrder.failed_qty - WorkOrder.planned_output_qty)
                              ).join(Department).filter(*work_filter).one()
        completed_total = summary_row[0]
        completed = db.query(WorkOrder).join(Department).options(lazyload("*")).filter(*work_filter).order_by(
            WorkOrder.end_time, WorkOrder.id).offset(offset).limit(limit).all()
        groups = []
    else:
        completed = []
        groups = db.execute(text(base + """
          SELECT identity, day, production_order_id, model_id, brand_id, color, batch_ids,
                 count(*) AS package_count, sum(total_quantity) AS quantity,
                 (array_agg(id ORDER BY packed_at, id))[1] AS first_id,
                 min(packed_at) AS first_at
          FROM keyed GROUP BY identity, day, production_order_id, model_id, brand_id, color, batch_ids
          ORDER BY min(packed_at), (array_agg(id ORDER BY packed_at, id))[1]
        """), args).mappings().all()
    # Compact sort metadata covers all entry groups; full related details cover only the page.
    if kind == PackagingReportKind.ENTRIES:
        sort_order_ids = {g["production_order_id"] for g in groups}
        sort_model_ids = {g["model_id"] for g in groups}
        sort_orders = {o.id: o for o in db.query(ProductionOrder).options(load_only(ProductionOrder.id, ProductionOrder.production_no)).filter(ProductionOrder.id.in_(sort_order_ids)).all()}
        sort_models = {m.id: m for m in db.query(Model).options(load_only(Model.id, Model.code, Model.details_json)).filter(Model.id.in_(sort_model_ids)).all()}
        sort_batches = dict(db.query(ProductionBatch.id, ProductionBatch.batch_no).filter(ProductionBatch.production_order_id.in_(sort_order_ids)).all())
        decorated = [(g, _identity(sort_models[g["model_id"]]), ", ".join(sort_batches.get(b, "") for b in g["batch_ids"])) for g in groups]
        decorated.sort(key=lambda item: (item[0]["day"], _natural(item[1][0]), _natural(item[1][1]),
                                         _natural(sort_orders[item[0]["production_order_id"]].production_no), item[2], item[0]["color"]))
        selected = decorated[offset:offset + limit]
        order_ids = {g["production_order_id"] for g, _, _ in selected}
        model_ids = {g["model_id"] for g, _, _ in selected}
    else:
        order_ids = {w.production_order_id for w in completed}
        model_ids = set()
    orders = {o.id: o for o in db.query(ProductionOrder).options(lazyload("*")).filter(ProductionOrder.id.in_(order_ids)).all()}
    model_ids |= {o.model_id for o in orders.values()}
    models = {m.id: m for m in db.query(Model).options(lazyload("*"), selectinload(Model.images).defer(ModelImage.file_data)).filter(Model.id.in_(model_ids)).all()}
    brand_ids = {g["brand_id"] for g, _, _ in selected} if kind == PackagingReportKind.ENTRIES else set()
    brand_ids = brand_ids | {o.brand_id for o in orders.values()} | {m.brand_id for m in models.values()}
    brands = dict(db.query(Brand.id, Brand.name).filter(Brand.id.in_([b for b in brand_ids if b])).all())
    batches = dict(db.query(ProductionBatch.id, ProductionBatch.batch_no).filter(ProductionBatch.production_order_id.in_(order_ids)).all())
    passports = defaultdict(set)
    for order_id, passport_no in db.query(CuttingPassport.production_order_id, CuttingPassport.passport_no).filter(CuttingPassport.production_order_id.in_(order_ids)).all():
        passports[order_id].add(passport_no)

    def identity(order_id, model_id, brand_id=None):
        order, model = orders[order_id], models[model_id]
        model_no, variant_no = _identity(model)
        return {"order_no": order.production_no, "passport": ", ".join(sorted(passports[order_id], key=_natural)),
                "brand": brands.get(brand_id or order.brand_id or model.brand_id, ""), "model_no": model_no,
                "variant_no": variant_no, "category": model.category or model.product_type or model.name,
                "image_url": model_preview_image_url(model)}

    def row_key(value):
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    total_packages = sum(g["package_count"] for g in groups)
    total_quantity = sum(g["quantity"] for g in groups)
    if kind == PackagingReportKind.COMPLETED:
        rows = [{**identity(w.production_order_id, orders[w.production_order_id].model_id),
                 "row_key": f"work:{w.id}", "date": _day(w.end_time), "batch": batches.get(w.production_batch_id, ""),
                 "planned_quantity": w.planned_output_qty, "packed_quantity": w.passed_qty, "damaged_quantity": w.failed_qty,
                 "balance": w.passed_qty + w.failed_qty - w.planned_output_qty, "notes": w.notes or ""} for w in completed]
        summary = dict(zip(("planned_quantity", "packed_quantity", "damaged_quantity", "balance"), summary_row[1:]))
        return {"rows": rows, "total": completed_total, "offset": offset, "limit": limit,
                "has_more": offset + limit < completed_total, "summary": summary}
    else:
        keys = [g["identity"] for g, _, _ in selected]
        page_details = db.execute(text(base + """
          SELECT keyed.identity,
                 array_agg(DISTINCT keyed.capacity) AS standards,
                 array_agg(DISTINCT i.size) FILTER (WHERE i.quantity > 0) AS sizes
          FROM keyed LEFT JOIN package_items i ON i.package_id = keyed.id
          WHERE keyed.identity = ANY(:keys)
          GROUP BY keyed.identity
        """), {**args, "keys": keys}).mappings().all() if keys else []
        details_by_key = {r["identity"]: r for r in page_details}
        rows = []
        for g, _, batch in selected:
            details = identity(g["production_order_id"], g["model_id"], g["brand_id"])
            day = g["day"].isoformat()
            extra = details_by_key[g["identity"]]
            rows.append({**details, "row_key": "entry:" + row_key(g["identity"]), "date": day, "batch": batch,
                         "color": g["color"], "sizes": ", ".join(sorted(extra["sizes"] or [], key=_natural)),
                         "standards": " / ".join(str(n) for n in sorted(extra["standards"])),
                         "package_count": g["package_count"], "quantity": g["quantity"]})
        summary = {"package_count": total_packages if groups else None, "quantity": total_quantity if groups else None}
        return {"rows": rows, "total": len(groups), "offset": offset, "limit": limit,
                "has_more": offset + limit < len(groups), "summary": summary}
