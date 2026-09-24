from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

from sqlalchemy import func
from sqlalchemy.orm import Session, load_only

from app.models import (
    Brand,
    Collection,
    FinishedGoodsStock,
    Item,
    Model,
    ModelBOM,
    ProductionOrder,
    ProductionOrderItem,
    SalesOrder,
    SalesOrderItem,
    StockBatch,
    StockMovement,
)
from app.services.inventory import available_stock_for_item, stock_summary


ACTIVE_PRODUCTION_STATUSES = (
    "new",
    "planning",
    "waiting_material",
    "cutting",
    "printing",
    "sewing",
    "packaging",
    "storage_transfer",
)

BRANDED_SALES_EXCLUDED_STATUSES = ("draft", "cancelled")
BRANDED_PRODUCTION_HISTORY_STATUSES = ("finished_storage", "closed", "delivered")

BrandedKey = tuple[int, int | None, int | None, str, str]
_REFERENCE_BATCH_SIZE = 400


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _confidence(order_count: int) -> str:
    if order_count >= 8:
        return "high"
    if order_count >= 3:
        return "medium"
    return "low"


def _reference_id_chunks(values: set[int]):
    ordered = sorted(values)
    for start in range(0, len(ordered), _REFERENCE_BATCH_SIZE):
        yield ordered[start:start + _REFERENCE_BATCH_SIZE]


def _branded_reference_maps(
    db: Session,
    keys: list[BrandedKey],
) -> tuple[
    dict[int, tuple[str | None, str | None]],
    dict[int, str | None],
    dict[int, str | None],
]:
    model_ids = {int(model_id) for model_id, _, _, _, _ in keys}
    brand_ids = {int(brand_id) for _, brand_id, _, _, _ in keys if brand_id is not None}
    collection_ids = {
        int(collection_id)
        for _, _, collection_id, _, _ in keys
        if collection_id is not None
    }

    model_labels: dict[int, tuple[str | None, str | None]] = {}
    for ids in _reference_id_chunks(model_ids):
        model_labels.update({
            int(model_id): (code, name)
            for model_id, code, name in db.query(Model.id, Model.code, Model.name).filter(
                Model.id.in_(ids)
            ).all()
        })

    brand_names: dict[int, str | None] = {}
    for ids in _reference_id_chunks(brand_ids):
        brand_names.update({
            int(brand_id): name
            for brand_id, name in db.query(Brand.id, Brand.name).filter(Brand.id.in_(ids)).all()
        })

    collection_names: dict[int, str | None] = {}
    for ids in _reference_id_chunks(collection_ids):
        collection_names.update({
            int(collection_id): name
            for collection_id, name in db.query(Collection.id, Collection.name).filter(
                Collection.id.in_(ids)
            ).all()
        })
    return model_labels, brand_names, collection_names


def _add_demand_event(
    groups: dict[BrandedKey, dict[str, Any]],
    *,
    key: BrandedKey,
    quantity: int,
    order_id: int,
    created_at: datetime | None,
    source: str,
) -> None:
    row = groups.setdefault(
        key,
        {
            "quantity": 0,
            "order_ids": set(),
            "first_at": created_at,
            "last_at": created_at,
            "events": [],
            "source": source,
        },
    )
    row["quantity"] += max(0, int(quantity or 0))
    row["order_ids"].add(int(order_id))
    row["events"].append((created_at, max(0, int(quantity or 0))))
    if created_at and (not row["first_at"] or created_at < row["first_at"]):
        row["first_at"] = created_at
    if created_at and (not row["last_at"] or created_at > row["last_at"]):
        row["last_at"] = created_at


def _branded_demand_groups(
    db: Session,
    *,
    factory_codes: Sequence[str] | None = None,
) -> dict[BrandedKey, dict[str, Any]]:
    sales_query = (
        db.query(SalesOrderItem, SalesOrder).options(
            load_only(
                SalesOrderItem.id,
                SalesOrderItem.model_id,
                SalesOrderItem.brand_id,
                SalesOrderItem.collection_id,
                SalesOrderItem.color,
                SalesOrderItem.size,
                SalesOrderItem.quantity,
            ),
            load_only(SalesOrder.id, SalesOrder.created_at),
        )
        .join(SalesOrder, SalesOrder.id == SalesOrderItem.sales_order_id)
        .filter(
            SalesOrder.order_type == "branded_stock_sale",
            SalesOrder.status.notin_(BRANDED_SALES_EXCLUDED_STATUSES),
        )
    )
    if factory_codes is not None:
        sales_model_id = func.coalesce(
            SalesOrderItem.model_id,
            FinishedGoodsStock.model_id,
        )
        sales_query = (
            sales_query.outerjoin(
                FinishedGoodsStock,
                FinishedGoodsStock.id == SalesOrderItem.finished_goods_stock_id,
            )
            .join(
                Model,
                Model.id == sales_model_id,
            )
            .filter(Model.factory_code.in_(factory_codes))
            .add_columns(sales_model_id.label("forecast_model_id"))
        )
    sales_rows = sales_query.order_by(SalesOrder.created_at.asc(), SalesOrderItem.id.asc()).all()
    sales_groups: dict[BrandedKey, dict[str, Any]] = {}
    for row in sales_rows:
        item, order = row[:2]
        model_id = row[2] if factory_codes is not None else item.model_id
        _add_demand_event(
            sales_groups,
            key=(
                int(model_id),
                int(item.brand_id) if item.brand_id else None,
                int(item.collection_id) if item.collection_id else None,
                str(item.color or ""),
                str(item.size or ""),
            ),
            quantity=int(item.quantity or 0),
            order_id=int(order.id),
            created_at=order.created_at,
            source="sales_orders",
        )

    production_query = (
        db.query(ProductionOrderItem, ProductionOrder).options(
            load_only(
                ProductionOrderItem.id,
                ProductionOrderItem.model_id,
                ProductionOrderItem.color,
                ProductionOrderItem.size,
                ProductionOrderItem.planned_quantity,
            ),
            load_only(
                ProductionOrder.id,
                ProductionOrder.created_at,
                ProductionOrder.brand_id,
                ProductionOrder.collection_id,
            ),
        )
        .join(ProductionOrder, ProductionOrder.id == ProductionOrderItem.production_order_id)
        .filter(
            ProductionOrder.production_type == "branded_stock",
            ProductionOrder.status.in_(BRANDED_PRODUCTION_HISTORY_STATUSES),
        )
    )
    if factory_codes is not None:
        production_query = production_query.join(
            Model, Model.id == ProductionOrderItem.model_id,
        ).filter(Model.factory_code.in_(factory_codes))
    production_rows = production_query.order_by(
        ProductionOrder.created_at.asc(), ProductionOrderItem.id.asc(),
    ).all()
    production_groups: dict[BrandedKey, dict[str, Any]] = {}
    for item, order in production_rows:
        _add_demand_event(
            production_groups,
            key=(
                int(item.model_id),
                int(order.brand_id) if order.brand_id else None,
                int(order.collection_id) if order.collection_id else None,
                str(item.color or ""),
                str(item.size or ""),
            ),
            quantity=int(item.planned_quantity or 0),
            order_id=int(order.id),
            created_at=order.created_at,
            source="branded_production_orders",
        )

    # Sales are the authoritative demand signal for a variant. Until Sales is
    # used for that variant, its branded planning/production history is a
    # conservative fallback so Forecasting is useful in the current workflow.
    groups = dict(production_groups)
    groups.update(sales_groups)
    return groups


def _branded_stock_analysis(
    db: Session,
    *,
    horizon_weeks: int = 4,
    groups: dict[BrandedKey, dict[str, Any]] | None = None,
    factory_codes: Sequence[str] | None = None,
) -> list[dict]:
    if groups is None:
        groups = (
            _branded_demand_groups(db)
            if factory_codes is None
            else _branded_demand_groups(db, factory_codes=factory_codes)
        )
    if not groups:
        return []
    model_labels, brand_names, collection_names = _branded_reference_maps(db, list(groups))

    effective_brand_id = func.coalesce(FinishedGoodsStock.brand_id, ProductionOrder.brand_id)
    effective_collection_id = func.coalesce(FinishedGoodsStock.collection_id, ProductionOrder.collection_id)
    effective_model_id = (
        func.coalesce(FinishedGoodsStock.model_id, ProductionOrder.model_id)
        if factory_codes is not None
        else FinishedGoodsStock.model_id
    )
    available_query = (
        db.query(
            effective_model_id,
            effective_brand_id,
            effective_collection_id,
            FinishedGoodsStock.color,
            FinishedGoodsStock.size,
            func.coalesce(func.sum(FinishedGoodsStock.available_qty), 0),
        )
        .outerjoin(ProductionOrder, ProductionOrder.id == FinishedGoodsStock.production_order_id)
    )
    if factory_codes is not None:
        available_query = available_query.join(
            Model, Model.id == effective_model_id,
        ).filter(Model.factory_code.in_(factory_codes))
    available_rows = available_query.group_by(
        effective_model_id,
        effective_brand_id,
        effective_collection_id,
        FinishedGoodsStock.color,
        FinishedGoodsStock.size,
    ).all()
    available: dict[BrandedKey, int] = {}
    for model_id, brand_id, collection_id, color, size, qty in available_rows:
        available[
            (
                int(model_id),
                int(brand_id) if brand_id else None,
                int(collection_id) if collection_id else None,
                str(color or ""),
                str(size or ""),
            )
        ] = int(qty or 0)

    pipeline_query = (
        db.query(
            ProductionOrderItem.model_id,
            ProductionOrderItem.color,
            ProductionOrderItem.size,
            ProductionOrderItem.planned_quantity,
            ProductionOrder.brand_id,
            ProductionOrder.collection_id,
        )
        .join(ProductionOrder, ProductionOrder.id == ProductionOrderItem.production_order_id)
        .filter(
            ProductionOrder.production_type == "branded_stock",
            ProductionOrder.status.in_(ACTIVE_PRODUCTION_STATUSES),
        )
    )
    if factory_codes is not None:
        pipeline_query = pipeline_query.join(
            Model, Model.id == ProductionOrderItem.model_id,
        ).filter(Model.factory_code.in_(factory_codes))
    pipeline_rows = pipeline_query.all()
    pipeline: dict[BrandedKey, int] = defaultdict(int)
    for model_id, color, size, planned_quantity, brand_id, collection_id in pipeline_rows:
        key = (
            int(model_id),
            int(brand_id) if brand_id else None,
            int(collection_id) if collection_id else None,
            str(color or ""),
            str(size or ""),
        )
        pipeline[key] += max(0, int(planned_quantity or 0))

    analysis: list[dict] = []
    for (model_id, brand_id, collection_id, color, size), row in groups.items():
        first_at = row["first_at"]
        last_at = row["last_at"]
        span_days = 7
        first_utc = _aware(first_at)
        last_utc = _aware(last_at)
        if first_utc and last_utc:
            span_days = max(7, (last_utc - first_utc).days + 1)
        observed_weeks = max(1.0, span_days / 7.0)
        total_qty = int(row["quantity"] or 0)
        avg_weekly = total_qty / observed_weeks
        projected = int(math.ceil(avg_weekly * max(1, horizon_weeks)))
        on_hand = int(available.get((model_id, brand_id, collection_id, color, size), 0))
        pipeline_qty = int(pipeline.get((model_id, brand_id, collection_id, color, size), 0))
        suggested = max(0, projected - on_hand - pipeline_qty)
        model_code, model_name = model_labels.get(model_id, (None, None))
        order_count = len(row["order_ids"])
        source_label = "branded-stock sale" if row["source"] == "sales_orders" else "branded production plan"
        analysis.append(
            {
                "recommendation_type": "branded_stock_production",
                "model_id": model_id,
                "model_code": model_code,
                "model_name": model_name,
                "brand_id": brand_id,
                "brand_name": brand_names.get(brand_id) if brand_id is not None else None,
                "collection_id": collection_id,
                "collection_name": collection_names.get(collection_id) if collection_id is not None else None,
                "color": color,
                "size": size,
                "historical_quantity": total_qty,
                "historical_order_count": order_count,
                "average_weekly_demand": round(avg_weekly, 2),
                "horizon_weeks": horizon_weeks,
                "projected_demand": projected,
                "available_quantity": on_hand,
                "pipeline_quantity": pipeline_qty,
                "suggested_quantity": suggested,
                "unit": "pcs",
                "confidence": _confidence(order_count),
                "demand_source": row["source"],
                "is_low_stock": on_hand < max(1, int(math.ceil(avg_weekly))),
                "reason": (
                    f"Projected {horizon_weeks}-week demand is {projected} pcs based on "
                    f"{order_count} {source_label}(s); available stock is {on_hand} pcs and "
                    f"active production is {pipeline_qty} pcs."
                ),
            }
        )
    return sorted(analysis, key=lambda r: (-(r["suggested_quantity"]), r.get("model_code") or "", r.get("color") or "", r.get("size") or ""))


def branded_stock_suggestions(
    db: Session,
    *,
    horizon_weeks: int = 4,
    factory_codes: Sequence[str] | None = None,
) -> list[dict]:
    return [
        row
        for row in _branded_stock_analysis(
            db,
            horizon_weeks=horizon_weeks,
            factory_codes=factory_codes,
        )
        if row["suggested_quantity"] > 0
    ]


def _planned_bom_demand(db: Session) -> dict[tuple[int, str], float]:
    active_pos = (
        db.query(
            ProductionOrder.id,
            ProductionOrder.model_id,
            ProductionOrder.planned_quantity,
        )
        .filter(ProductionOrder.status.in_(ACTIVE_PRODUCTION_STATUSES))
        .all()
    )
    if not active_pos:
        return {}
    po_ids = [int(po.id) for po in active_pos]
    items_by_po: dict[int, list[ProductionOrderItem]] = defaultdict(list)
    for ids in _reference_id_chunks(set(po_ids)):
        rows = db.query(
            ProductionOrderItem.production_order_id,
            ProductionOrderItem.model_id,
            ProductionOrderItem.color,
            ProductionOrderItem.size,
            ProductionOrderItem.planned_quantity,
        ).filter(ProductionOrderItem.production_order_id.in_(ids)).all()
        for row in rows:
            items_by_po[int(row.production_order_id)].append(row)

    model_ids = {int(po.model_id) for po in active_pos}
    for lines in items_by_po.values():
        model_ids.update(int(line.model_id) for line in lines if line.model_id)
    bom_by_model: dict[int, list] = defaultdict(list)
    bom_rows = []
    for ids in _reference_id_chunks(model_ids):
        bom_rows.extend(
            db.query(
                ModelBOM.model_id,
                ModelBOM.item_id,
                ModelBOM.stock_batch_id,
                ModelBOM.color,
                ModelBOM.size,
                ModelBOM.quantity_per_piece,
                ModelBOM.unit,
                ModelBOM.waste_percent,
            )
            .filter(ModelBOM.model_id.in_(ids))
            .all()
        )
    stock_batch_item_ids: dict[int, int] = {}
    stock_batch_ids = {int(bom.stock_batch_id) for bom in bom_rows if bom.stock_batch_id}
    for ids in _reference_id_chunks(stock_batch_ids):
        stock_batch_item_ids.update({
            int(batch_id): int(item_id)
            for batch_id, item_id in db.query(StockBatch.id, StockBatch.item_id)
            .filter(StockBatch.id.in_(ids))
            .all()
        })
    for bom in bom_rows:
        bom_by_model[int(bom.model_id)].append(bom)

    demand: dict[tuple[int, str], float] = defaultdict(float)

    def add_bom(bom, planned_qty: int, color: str | None = None, size: str | None = None) -> None:
        # Descriptive BOM rows are valid, but cannot identify inventory demand.
        item_id = bom.item_id or stock_batch_item_ids.get(int(bom.stock_batch_id or 0))
        if not item_id:
            return
        if bom.color and color and bom.color != color:
            return
        if bom.size and size and bom.size != size:
            return
        qty = float(bom.quantity_per_piece or 0) * max(0, int(planned_qty or 0))
        qty *= 1.0 + float(bom.waste_percent or 0) / 100.0
        if qty > 0:
            demand[(int(item_id), str(bom.unit or ""))] += qty

    for po in active_pos:
        lines = items_by_po.get(int(po.id), [])
        if lines:
            for line in lines:
                for bom in bom_by_model.get(int(line.model_id or po.model_id), []):
                    add_bom(bom, int(line.planned_quantity or 0), color=line.color, size=line.size)
        else:
            for bom in bom_by_model.get(int(po.model_id), []):
                add_bom(bom, int(po.planned_quantity or 0))
    return demand


def _recent_usage_by_item(db: Session, *, days: int = 90) -> dict[tuple[int, str], float]:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (
        db.query(StockMovement.item_id, StockMovement.unit, func.coalesce(func.sum(StockMovement.quantity), 0))
        .filter(
            StockMovement.movement_type.in_(("issue", "consume", "waste")),
            StockMovement.created_at >= since,
        )
        .group_by(StockMovement.item_id, StockMovement.unit)
        .all()
    )
    return {(int(item_id), str(unit or "")): float(qty or 0) for item_id, unit, qty in rows}


def item_reorder_suggestions(db: Session) -> list[dict]:
    item_rows = db.query(
        Item.id,
        Item.sku,
        Item.name,
        Item.category,
        Item.unit,
        Item.reorder_level,
    ).filter(Item.is_active.is_(True)).order_by(Item.sku.asc()).all()
    if not item_rows:
        return []
    stock_rows = {int(row["item_id"]): row for row in stock_summary(db)}
    planned_demand = _planned_bom_demand(db)
    recent_usage = _recent_usage_by_item(db)

    suggestions: list[dict] = []
    for item in item_rows:
        stock = stock_rows.get(int(item.id), {})
        available = float((stock["available_quantity"] if "available_quantity" in stock
                           else available_stock_for_item(db, int(item.id))) or 0)
        current = float(stock.get("quantity", 0) or 0)
        reserved = float(stock.get("reserved_quantity", 0) or 0)
        unit = str(item.unit or "")
        reorder_level = float(item.reorder_level or 0)
        bom_demand = float(planned_demand.get((int(item.id), unit), 0.0))
        recent_90 = float(recent_usage.get((int(item.id), unit), 0.0))
        recent_monthly = recent_90 / 3.0
        level_shortage = max(0.0, reorder_level - available)
        bom_shortage = max(0.0, bom_demand - available)
        usage_shortage = max(0.0, recent_monthly - available)
        suggested = max(level_shortage, bom_shortage, usage_shortage)
        if suggested <= 0:
            continue
        reason_parts = []
        if level_shortage > 0:
            reason_parts.append(f"available {available:g} {unit} is below reorder level {reorder_level:g}")
        if bom_shortage > 0:
            reason_parts.append(f"planned BOM demand is {bom_demand:g} {unit}")
        if recent_monthly > 0:
            reason_parts.append(f"recent usage averages {recent_monthly:g} {unit}/month")
        suggestions.append(
            {
                "recommendation_type": "item_reorder",
                "item_id": int(item.id),
                "item_sku": item.sku,
                "item_name": item.name,
                "category": item.category,
                "unit": unit,
                "current_quantity": current,
                "reserved_quantity": reserved,
                "available_quantity": available,
                "reorder_level": reorder_level,
                "planned_bom_demand": round(bom_demand, 4),
                "recent_usage_90d": round(recent_90, 4),
                "suggested_quantity": round(float(suggested), 4),
                "confidence": "medium" if recent_90 > 0 or bom_demand > 0 else "low",
                "reason": "; ".join(reason_parts) + ".",
            }
        )
    return sorted(suggestions, key=lambda r: (-(r["suggested_quantity"]), r["item_sku"]))


def demand_trend(
    db: Session,
    *,
    weeks: int = 8,
    groups: dict[BrandedKey, dict[str, Any]] | None = None,
    factory_codes: Sequence[str] | None = None,
) -> list[dict]:
    now = datetime.now(timezone.utc)
    weeks = max(1, weeks)
    current_week = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    start = current_week - timedelta(weeks=weeks - 1)
    buckets = {i: 0 for i in range(weeks)}
    if groups is None:
        groups = (
            _branded_demand_groups(db)
            if factory_codes is None
            else _branded_demand_groups(db, factory_codes=factory_codes)
        )
    for row in groups.values():
        for created_at, qty in row["events"]:
            created_utc = _aware(created_at)
            if not created_utc or created_utc < start or created_utc > now:
                continue
            idx = (created_utc - start).days // 7
            buckets[idx] += int(qty or 0)
    out = []
    for idx in range(weeks):
        week_start = (start + timedelta(days=7 * idx)).date().isoformat()
        out.append({"week_start": week_start, "quantity": buckets[idx]})
    return out


def forecasting_dashboard(
    db: Session,
    *,
    factory_codes: Sequence[str] | None = None,
) -> dict:
    branded_groups = (
        _branded_demand_groups(db)
        if factory_codes is None
        else _branded_demand_groups(db, factory_codes=factory_codes)
    )
    branded_analysis = _branded_stock_analysis(
        db,
        groups=branded_groups,
        factory_codes=factory_codes,
    )
    branded = [row for row in branded_analysis if row["suggested_quantity"] > 0]
    reorder = item_reorder_suggestions(db)
    low_stock_fg = sum(1 for row in branded_analysis if row["is_low_stock"])
    trend = demand_trend(db, groups=branded_groups)
    unlinked_bom_query = db.query(ModelBOM.id).filter(
        ModelBOM.item_id.is_(None),
        ModelBOM.stock_batch_id.is_(None),
        ModelBOM.model_id.in_(db.query(ProductionOrder.model_id).filter(
            ProductionOrder.status.in_(ACTIVE_PRODUCTION_STATUSES),
        ).union(db.query(ProductionOrderItem.model_id).join(
            ProductionOrder, ProductionOrder.id == ProductionOrderItem.production_order_id,
        ).filter(ProductionOrder.status.in_(ACTIVE_PRODUCTION_STATUSES)))),
    )
    if factory_codes is not None:
        unlinked_bom_query = unlinked_bom_query.join(
            Model, Model.id == ModelBOM.model_id,
        ).filter(Model.factory_code.in_(factory_codes))
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "unlinked_bom_count": unlinked_bom_query.count(),
        "cards": {
            "suggested_production_count": len(branded),
            "reorder_alert_count": len(reorder),
            "low_stock_finished_goods": low_stock_fg,
            "demand_trend_quantity": sum(int(row["quantity"] or 0) for row in trend),
        },
        "demand_trend": trend,
        "branded_stock_suggestions": branded,
        "item_reorder_suggestions": reorder,
    }
