from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

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


def _model_label(db: Session, model_id: int | None) -> tuple[str | None, str | None]:
    model = db.get(Model, model_id) if model_id else None
    return (model.code if model else None, model.name if model else None)


def _brand_name(db: Session, brand_id: int | None) -> str | None:
    brand = db.get(Brand, brand_id) if brand_id else None
    return brand.name if brand else None


def _collection_name(db: Session, collection_id: int | None) -> str | None:
    collection = db.get(Collection, collection_id) if collection_id else None
    return collection.name if collection else None


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


def _branded_demand_groups(db: Session) -> dict[BrandedKey, dict[str, Any]]:
    sales_rows = (
        db.query(SalesOrderItem, SalesOrder)
        .join(SalesOrder, SalesOrder.id == SalesOrderItem.sales_order_id)
        .filter(
            SalesOrder.order_type == "branded_stock_sale",
            SalesOrder.status.notin_(BRANDED_SALES_EXCLUDED_STATUSES),
        )
        .order_by(SalesOrder.created_at.asc(), SalesOrderItem.id.asc())
        .all()
    )
    sales_groups: dict[BrandedKey, dict[str, Any]] = {}
    for item, order in sales_rows:
        _add_demand_event(
            sales_groups,
            key=(
                int(item.model_id),
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

    production_rows = (
        db.query(ProductionOrderItem, ProductionOrder)
        .join(ProductionOrder, ProductionOrder.id == ProductionOrderItem.production_order_id)
        .filter(
            ProductionOrder.production_type == "branded_stock",
            ProductionOrder.status.in_(BRANDED_PRODUCTION_HISTORY_STATUSES),
        )
        .order_by(ProductionOrder.created_at.asc(), ProductionOrderItem.id.asc())
        .all()
    )
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


def _branded_stock_analysis(db: Session, *, horizon_weeks: int = 4) -> list[dict]:
    groups = _branded_demand_groups(db)
    if not groups:
        return []

    effective_brand_id = func.coalesce(FinishedGoodsStock.brand_id, ProductionOrder.brand_id)
    effective_collection_id = func.coalesce(FinishedGoodsStock.collection_id, ProductionOrder.collection_id)
    available_rows = (
        db.query(
            FinishedGoodsStock.model_id,
            effective_brand_id,
            effective_collection_id,
            FinishedGoodsStock.color,
            FinishedGoodsStock.size,
            func.coalesce(func.sum(FinishedGoodsStock.available_qty), 0),
        )
        .outerjoin(ProductionOrder, ProductionOrder.id == FinishedGoodsStock.production_order_id)
        .group_by(
            FinishedGoodsStock.model_id,
            effective_brand_id,
            effective_collection_id,
            FinishedGoodsStock.color,
            FinishedGoodsStock.size,
        )
        .all()
    )
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

    pipeline_rows = (
        db.query(ProductionOrderItem, ProductionOrder)
        .join(ProductionOrder, ProductionOrder.id == ProductionOrderItem.production_order_id)
        .filter(
            ProductionOrder.production_type == "branded_stock",
            ProductionOrder.status.in_(ACTIVE_PRODUCTION_STATUSES),
        )
        .all()
    )
    pipeline: dict[BrandedKey, int] = defaultdict(int)
    for item, order in pipeline_rows:
        key = (
            int(item.model_id),
            int(order.brand_id) if order.brand_id else None,
            int(order.collection_id) if order.collection_id else None,
            str(item.color or ""),
            str(item.size or ""),
        )
        pipeline[key] += max(0, int(item.planned_quantity or 0))

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
        model_code, model_name = _model_label(db, model_id)
        order_count = len(row["order_ids"])
        source_label = "branded-stock sale" if row["source"] == "sales_orders" else "branded production plan"
        analysis.append(
            {
                "recommendation_type": "branded_stock_production",
                "model_id": model_id,
                "model_code": model_code,
                "model_name": model_name,
                "brand_id": brand_id,
                "brand_name": _brand_name(db, brand_id),
                "collection_id": collection_id,
                "collection_name": _collection_name(db, collection_id),
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


def branded_stock_suggestions(db: Session, *, horizon_weeks: int = 4) -> list[dict]:
    return [row for row in _branded_stock_analysis(db, horizon_weeks=horizon_weeks) if row["suggested_quantity"] > 0]


def _planned_bom_demand(db: Session) -> dict[tuple[int, str], float]:
    active_pos = (
        db.query(ProductionOrder)
        .filter(ProductionOrder.status.in_(ACTIVE_PRODUCTION_STATUSES))
        .all()
    )
    if not active_pos:
        return {}
    po_ids = [int(po.id) for po in active_pos]
    items_by_po: dict[int, list[ProductionOrderItem]] = defaultdict(list)
    for row in db.query(ProductionOrderItem).filter(ProductionOrderItem.production_order_id.in_(po_ids)).all():
        items_by_po[int(row.production_order_id)].append(row)

    model_ids = {int(po.model_id) for po in active_pos}
    for lines in items_by_po.values():
        model_ids.update(int(line.model_id) for line in lines if line.model_id)
    bom_by_model: dict[int, list[ModelBOM]] = defaultdict(list)
    for bom in db.query(ModelBOM).filter(ModelBOM.model_id.in_(model_ids)).all():
        bom_by_model[int(bom.model_id)].append(bom)

    demand: dict[tuple[int, str], float] = defaultdict(float)

    def add_bom(bom: ModelBOM, planned_qty: int, color: str | None = None, size: str | None = None) -> None:
        if bom.color and color and bom.color != color:
            return
        if bom.size and size and bom.size != size:
            return
        qty = float(bom.quantity_per_piece or 0) * max(0, int(planned_qty or 0))
        qty *= 1.0 + float(bom.waste_percent or 0) / 100.0
        if qty > 0:
            demand[(int(bom.item_id), str(bom.unit or ""))] += qty

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
    item_rows = db.query(Item).filter(Item.is_active.is_(True)).order_by(Item.sku.asc()).all()
    if not item_rows:
        return []
    stock_rows = {int(row["item_id"]): row for row in stock_summary(db)}
    planned_demand = _planned_bom_demand(db)
    recent_usage = _recent_usage_by_item(db)

    suggestions: list[dict] = []
    for item in item_rows:
        stock = stock_rows.get(int(item.id), {})
        available = float(stock.get("available_quantity", available_stock_for_item(db, int(item.id))) or 0)
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


def demand_trend(db: Session, *, weeks: int = 8) -> list[dict]:
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=7 * max(1, weeks - 1))
    buckets = {i: 0 for i in range(weeks)}
    for row in _branded_demand_groups(db).values():
        for created_at, qty in row["events"]:
            created_utc = _aware(created_at)
            if not created_utc or created_utc < start:
                continue
            days = max(0, (now - created_utc).days)
            idx = weeks - 1 - min(weeks - 1, days // 7)
            buckets[idx] += int(qty or 0)
    out = []
    for idx in range(weeks):
        week_start = (start + timedelta(days=7 * idx)).date().isoformat()
        out.append({"week_start": week_start, "quantity": buckets[idx]})
    return out


def forecasting_dashboard(db: Session) -> dict:
    branded_analysis = _branded_stock_analysis(db)
    branded = [row for row in branded_analysis if row["suggested_quantity"] > 0]
    reorder = item_reorder_suggestions(db)
    low_stock_fg = sum(1 for row in branded_analysis if row["is_low_stock"])
    trend = demand_trend(db)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
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
