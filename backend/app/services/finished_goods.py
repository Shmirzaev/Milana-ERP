from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import Collection, CollectionModel, FinishedGoodsStock, Package, ProductionOrder, SalesOrderItem


@dataclass
class _SalesOrderMetadata:
    brand_id: int | None
    collection_id: int | None


def _unique_or_none(values: set[int]) -> int | None:
    if len(values) == 1:
        return next(iter(values))
    return None


def _sales_order_metadata_for_model(
    db: Session,
    *,
    sales_order_id: int,
    model_id: int,
) -> _SalesOrderMetadata:
    rows = (
        db.query(SalesOrderItem.brand_id, SalesOrderItem.collection_id)
        .filter(
            SalesOrderItem.sales_order_id == sales_order_id,
            SalesOrderItem.model_id == model_id,
        )
        .all()
    )
    brand_ids = {int(row.brand_id) for row in rows if row.brand_id is not None}
    collection_ids = {int(row.collection_id) for row in rows if row.collection_id is not None}
    return _SalesOrderMetadata(
        brand_id=_unique_or_none(brand_ids),
        collection_id=_unique_or_none(collection_ids),
    )


def _model_collection_metadata(
    db: Session,
    *,
    model_id: int,
) -> _SalesOrderMetadata:
    rows = (
        db.query(CollectionModel.collection_id, Collection.brand_id)
        .join(Collection, Collection.id == CollectionModel.collection_id)
        .filter(CollectionModel.model_id == model_id)
        .all()
    )
    collection_ids = {int(row.collection_id) for row in rows if row.collection_id is not None}
    brand_ids = {int(row.brand_id) for row in rows if row.brand_id is not None}
    return _SalesOrderMetadata(
        brand_id=_unique_or_none(brand_ids),
        collection_id=_unique_or_none(collection_ids),
    )


def infer_brand_and_collection(
    db: Session,
    *,
    model_id: int,
    sales_order_id: int | None,
    production_order_id: int | None,
    package_id: int | None,
    brand_id: int | None,
    collection_id: int | None,
) -> tuple[int | None, int | None]:
    resolved_brand_id = int(brand_id) if brand_id is not None else None
    resolved_collection_id = int(collection_id) if collection_id is not None else None
    resolved_sales_order_id = int(sales_order_id) if sales_order_id is not None else None
    resolved_production_order_id = int(production_order_id) if production_order_id is not None else None

    pkg = db.get(Package, package_id) if package_id else None
    if pkg:
        if resolved_sales_order_id is None and pkg.sales_order_id is not None:
            resolved_sales_order_id = int(pkg.sales_order_id)
        if resolved_collection_id is None and pkg.collection_id is not None:
            resolved_collection_id = int(pkg.collection_id)
        if resolved_brand_id is None and pkg.brand_id is not None:
            resolved_brand_id = int(pkg.brand_id)
        if resolved_production_order_id is None and pkg.production_order_id is not None:
            resolved_production_order_id = int(pkg.production_order_id)

    if resolved_collection_id is None and resolved_production_order_id is not None:
        po = db.get(ProductionOrder, resolved_production_order_id)
        if po and po.collection_id is not None:
            resolved_collection_id = int(po.collection_id)
        if po and resolved_sales_order_id is None and po.sales_order_id is not None:
            resolved_sales_order_id = int(po.sales_order_id)

    if resolved_brand_id is None and resolved_collection_id is not None:
        col = db.get(Collection, resolved_collection_id)
        if col and col.brand_id is not None:
            resolved_brand_id = int(col.brand_id)

    if resolved_sales_order_id is not None and (resolved_brand_id is None or resolved_collection_id is None):
        so_meta = _sales_order_metadata_for_model(
            db,
            sales_order_id=resolved_sales_order_id,
            model_id=model_id,
        )
        if resolved_collection_id is None and so_meta.collection_id is not None:
            resolved_collection_id = so_meta.collection_id
        if resolved_brand_id is None and so_meta.brand_id is not None:
            resolved_brand_id = so_meta.brand_id

    if resolved_brand_id is None and resolved_collection_id is not None:
        col = db.get(Collection, resolved_collection_id)
        if col and col.brand_id is not None:
            resolved_brand_id = int(col.brand_id)

    if resolved_brand_id is None or resolved_collection_id is None:
        model_meta = _model_collection_metadata(db, model_id=model_id)
        if resolved_collection_id is None and model_meta.collection_id is not None:
            resolved_collection_id = model_meta.collection_id
        if resolved_brand_id is None and model_meta.brand_id is not None:
            resolved_brand_id = model_meta.brand_id

    return resolved_brand_id, resolved_collection_id


def repair_missing_brand_metadata(db: Session, *, model_ids: set[int] | None = None) -> int:
    query = db.query(FinishedGoodsStock).filter(
        (FinishedGoodsStock.brand_id.is_(None)) | (FinishedGoodsStock.collection_id.is_(None))
    )
    if model_ids is not None:
        normalized_model_ids = {int(model_id) for model_id in model_ids}
        if not normalized_model_ids:
            return 0
        query = query.filter(FinishedGoodsStock.model_id.in_(normalized_model_ids))
    rows = query.all()
    updated = 0
    for row in rows:
        next_brand_id, next_collection_id = infer_brand_and_collection(
            db,
            model_id=int(row.model_id),
            sales_order_id=row.sales_order_id,
            production_order_id=row.production_order_id,
            package_id=row.package_id,
            brand_id=row.brand_id,
            collection_id=row.collection_id,
        )
        changed = False
        if row.brand_id is None and next_brand_id is not None:
            row.brand_id = int(next_brand_id)
            changed = True
        if row.collection_id is None and next_collection_id is not None:
            row.collection_id = int(next_collection_id)
            changed = True
        if changed:
            updated += 1
    if updated:
        db.flush()
    return updated
