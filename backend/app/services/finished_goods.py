from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, tuple_
from sqlalchemy.orm import Session, load_only

from app.models import Collection, CollectionModel, FinishedGoodsStock, Package, ProductionOrder, SalesOrderItem


@dataclass
class _SalesOrderMetadata:
    brand_id: int | None
    collection_id: int | None


# Resolved reference metadata, keyed by the lookup the resolver used.
_ReferenceMetadataCache = dict[tuple[str, int, int], _SalesOrderMetadata]
# Entities the resolver only reads a few columns from, keyed by (table, id).
# A cached ``None`` records a deliberate miss so the row is not read again.
_ReferenceEntityCache = dict[tuple[str, int], object | None]
_REFERENCE_QUERY_CHUNK_SIZE = 400


def _chunks(values: list, size: int = _REFERENCE_QUERY_CHUNK_SIZE):
    for offset in range(0, len(values), size):
        yield values[offset:offset + size]


def _cached_entity(db: Session, model, entity_id: int | None, cache: _ReferenceEntityCache | None):
    """`db.get` that reads each referenced entity at most once per batch."""
    if entity_id is None:
        return None
    normalized_id = int(entity_id)
    key = (model.__name__, normalized_id)
    if cache is not None and key in cache:
        return cache[key]
    row = db.get(model, normalized_id)
    if cache is not None:
        cache[key] = row
    return row


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
    reference_cache: _ReferenceMetadataCache | None = None,
    entity_cache: _ReferenceEntityCache | None = None,
) -> tuple[int | None, int | None]:
    """Resolve a stock row's brand/collection from its own references.

    The resolution order is unchanged. The two caches only skip repeated reads
    of references that several stock rows share; every value still comes from
    the same query the uncached path would have run.
    """
    resolved_brand_id = int(brand_id) if brand_id is not None else None
    resolved_collection_id = int(collection_id) if collection_id is not None else None
    resolved_sales_order_id = int(sales_order_id) if sales_order_id is not None else None
    resolved_production_order_id = int(production_order_id) if production_order_id is not None else None

    pkg = _cached_entity(db, Package, package_id, entity_cache)
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
        po = _cached_entity(db, ProductionOrder, resolved_production_order_id, entity_cache)
        if po and po.collection_id is not None:
            resolved_collection_id = int(po.collection_id)
        if po and resolved_sales_order_id is None and po.sales_order_id is not None:
            resolved_sales_order_id = int(po.sales_order_id)

    if resolved_brand_id is None and resolved_collection_id is not None:
        col = _cached_entity(db, Collection, resolved_collection_id, entity_cache)
        if col and col.brand_id is not None:
            resolved_brand_id = int(col.brand_id)

    if resolved_sales_order_id is not None and (resolved_brand_id is None or resolved_collection_id is None):
        so_meta = _reference_metadata(
            db,
            reference_cache,
            "sales_order",
            resolved_sales_order_id,
            model_id,
            lambda: _sales_order_metadata_for_model(
                db, sales_order_id=resolved_sales_order_id, model_id=model_id
            ),
        )
        if resolved_collection_id is None and so_meta.collection_id is not None:
            resolved_collection_id = so_meta.collection_id
        if resolved_brand_id is None and so_meta.brand_id is not None:
            resolved_brand_id = so_meta.brand_id

    if resolved_brand_id is None and resolved_collection_id is not None:
        col = _cached_entity(db, Collection, resolved_collection_id, entity_cache)
        if col and col.brand_id is not None:
            resolved_brand_id = int(col.brand_id)

    if resolved_brand_id is None or resolved_collection_id is None:
        model_meta = _reference_metadata(
            db,
            reference_cache,
            "model",
            model_id,
            0,
            lambda: _model_collection_metadata(db, model_id=model_id),
        )
        if resolved_collection_id is None and model_meta.collection_id is not None:
            resolved_collection_id = model_meta.collection_id
        if resolved_brand_id is None and model_meta.brand_id is not None:
            resolved_brand_id = model_meta.brand_id

    return resolved_brand_id, resolved_collection_id


def _reference_metadata(
    db: Session,
    cache: _ReferenceMetadataCache | None,
    scope: str,
    first_id: int,
    second_id: int,
    load,
) -> _SalesOrderMetadata:
    """Return cached reference metadata, filling the cache on first use."""
    if cache is None:
        return load()
    key = (scope, int(first_id), int(second_id))
    metadata = cache.get(key)
    if metadata is None:
        metadata = load()
        cache[key] = metadata
    return metadata


def _first_set(*values):
    """The first value that is not None, mirroring the resolver's own checks.

    Deliberately not `or`: the resolver tests `is None` throughout, and the two
    differ for a falsy-but-present value.
    """
    for value in values:
        if value is not None:
            return value
    return None


def _prefetch_reference_metadata(
    db: Session,
    rows: list[FinishedGoodsStock],
) -> tuple[_ReferenceMetadataCache, _ReferenceEntityCache]:
    """Read every reference the batch needs in a few bounded queries.

    Returns the caches `infer_brand_and_collection` consults. The queries replay
    the resolver's own reference precedence (row, then package, then production
    order) to decide which packages, production orders, collections, sales-order
    lines and model/collection rows can possibly be consulted, so no lookup the
    uncached path would have run is skipped.
    """
    reference_cache: _ReferenceMetadataCache = {}
    entity_cache: _ReferenceEntityCache = {}

    package_ids = sorted({int(row.package_id) for row in rows if row.package_id is not None})
    for package_id in package_ids:
        entity_cache[(Package.__name__, package_id)] = None
    for chunk in _chunks(package_ids):
        for package in db.query(Package).options(load_only(
            Package.id,
            Package.sales_order_id,
            Package.production_order_id,
            Package.brand_id,
            Package.collection_id,
        )).filter(Package.id.in_(chunk)).all():
            entity_cache[(Package.__name__, int(package.id))] = package

    def _package_for(row: FinishedGoodsStock):
        if row.package_id is None:
            return None
        return entity_cache.get((Package.__name__, int(row.package_id)))

    production_order_ids = {
        int(row.production_order_id)
        for row in rows
        if row.production_order_id is not None
    }
    for row in rows:
        package = _package_for(row)
        if package is not None and package.production_order_id is not None:
            production_order_ids.add(int(package.production_order_id))
    sorted_production_order_ids = sorted(production_order_ids)
    for production_order_id in sorted_production_order_ids:
        entity_cache[(ProductionOrder.__name__, production_order_id)] = None
    for chunk in _chunks(sorted_production_order_ids):
        for production_order in db.query(ProductionOrder).options(load_only(
            ProductionOrder.id,
            ProductionOrder.sales_order_id,
            ProductionOrder.collection_id,
        )).filter(ProductionOrder.id.in_(chunk)).all():
            entity_cache[(ProductionOrder.__name__, int(production_order.id))] = production_order

    def _production_order_for(row: FinishedGoodsStock, production_order_id):
        if production_order_id is None:
            return None
        return entity_cache.get((ProductionOrder.__name__, int(production_order_id)))

    # Which sales-order lines and collections the batch can reach.
    sales_order_pairs: set[tuple[int, int]] = set()
    collection_ids: set[int] = set()
    for row in rows:
        package = _package_for(row)
        production_order_id = _first_set(
            row.production_order_id,
            package.production_order_id if package is not None else None,
        )
        sales_order_id = _first_set(
            row.sales_order_id,
            package.sales_order_id if package is not None else None,
        )
        collection_id = _first_set(
            row.collection_id,
            package.collection_id if package is not None else None,
        )
        production_order = _production_order_for(row, production_order_id)
        if production_order is not None:
            sales_order_id = _first_set(sales_order_id, production_order.sales_order_id)
            collection_id = _first_set(collection_id, production_order.collection_id)
        if sales_order_id is not None:
            sales_order_pairs.add((int(sales_order_id), int(row.model_id)))
        if collection_id is not None:
            collection_ids.add(int(collection_id))

    sorted_pairs = sorted(sales_order_pairs)
    for sales_order_id, model_id in sorted_pairs:
        reference_cache[("sales_order", sales_order_id, model_id)] = _SalesOrderMetadata(None, None)
    sales_metadata_values: dict[tuple[int, int], tuple[set[int], set[int]]] = {
        pair: (set(), set()) for pair in sorted_pairs
    }
    for chunk in _chunks(sorted_pairs):
        for sales_order_id, model_id, brand_id, collection_id in db.query(
            SalesOrderItem.sales_order_id,
            SalesOrderItem.model_id,
            SalesOrderItem.brand_id,
            SalesOrderItem.collection_id,
        ).filter(tuple_(SalesOrderItem.sales_order_id, SalesOrderItem.model_id).in_(chunk)).all():
            brands, collections = sales_metadata_values[(int(sales_order_id), int(model_id))]
            if brand_id is not None:
                brands.add(int(brand_id))
            if collection_id is not None:
                collections.add(int(collection_id))
    for (sales_order_id, model_id), (brands, collections) in sales_metadata_values.items():
        metadata = _SalesOrderMetadata(
            brand_id=_unique_or_none(brands),
            collection_id=_unique_or_none(collections),
        )
        reference_cache[("sales_order", sales_order_id, model_id)] = metadata
        # The resolver re-reads the collection after this step, so a collection
        # discovered here has to be part of the batch below.
        if metadata.collection_id is not None:
            collection_ids.add(metadata.collection_id)

    sorted_collection_ids = sorted(collection_ids)
    for collection_id in sorted_collection_ids:
        entity_cache[(Collection.__name__, collection_id)] = None
    for chunk in _chunks(sorted_collection_ids):
        for collection in db.query(Collection).options(load_only(
            Collection.id,
            Collection.brand_id,
        )).filter(Collection.id.in_(chunk)).all():
            entity_cache[(Collection.__name__, int(collection.id))] = collection

    # Which models still need the model -> collection fallback, replaying the
    # resolver's steps 1 to 5 so exactly the rows the uncached path would have
    # fallen through on are prefetched.
    model_ids_needing_fallback: set[int] = set()
    for row in rows:
        package = _package_for(row)
        production_order_id = _first_set(
            row.production_order_id,
            package.production_order_id if package is not None else None,
        )
        sales_order_id = _first_set(
            row.sales_order_id,
            package.sales_order_id if package is not None else None,
        )
        brand_id = _first_set(row.brand_id, package.brand_id if package is not None else None)
        collection_id = _first_set(
            row.collection_id,
            package.collection_id if package is not None else None,
        )
        production_order = _production_order_for(row, production_order_id)
        if production_order is not None:
            sales_order_id = _first_set(sales_order_id, production_order.sales_order_id)
            collection_id = _first_set(collection_id, production_order.collection_id)
        if brand_id is None and collection_id is not None:
            collection = entity_cache.get((Collection.__name__, int(collection_id)))
            brand_id = collection.brand_id if collection is not None else None
        if sales_order_id is not None and (brand_id is None or collection_id is None):
            metadata = reference_cache[("sales_order", int(sales_order_id), int(row.model_id))]
            brand_id = _first_set(brand_id, metadata.brand_id)
            collection_id = _first_set(collection_id, metadata.collection_id)
        if brand_id is None and collection_id is not None:
            collection = entity_cache.get((Collection.__name__, int(collection_id)))
            brand_id = collection.brand_id if collection is not None else None
        if brand_id is None or collection_id is None:
            model_ids_needing_fallback.add(int(row.model_id))

    sorted_fallback_model_ids = sorted(model_ids_needing_fallback)
    for model_id in sorted_fallback_model_ids:
        reference_cache[("model", model_id, 0)] = _SalesOrderMetadata(None, None)
    for chunk in _chunks(sorted_fallback_model_ids):
        grouped_rows = db.query(
            CollectionModel.model_id,
            func.count(func.distinct(CollectionModel.collection_id)),
            func.min(CollectionModel.collection_id),
            func.count(func.distinct(Collection.brand_id)),
            func.min(Collection.brand_id),
        ).join(Collection, Collection.id == CollectionModel.collection_id).filter(
            CollectionModel.model_id.in_(chunk)
        ).group_by(CollectionModel.model_id).all()
        for model_id, collection_count, collection_id, brand_count, brand_id in grouped_rows:
            reference_cache[("model", int(model_id), 0)] = _SalesOrderMetadata(
                brand_id=int(brand_id) if brand_count == 1 and brand_id is not None else None,
                collection_id=(
                    int(collection_id)
                    if collection_count == 1 and collection_id is not None
                    else None
                ),
            )
    return reference_cache, entity_cache


def repair_missing_brand_metadata(db: Session, *, model_ids: set[int] | None = None) -> int:
    """Backfill brand/collection on legacy stock rows that are missing them.

    The rows are repaired in one pass. Their references are read up front in a
    few bounded queries instead of once per row, and the same rows are still the
    only ones written, so the batch never widens what gets repaired.
    """
    query = db.query(FinishedGoodsStock).filter(
        (FinishedGoodsStock.brand_id.is_(None)) | (FinishedGoodsStock.collection_id.is_(None))
    )
    if model_ids is not None:
        normalized_model_ids = {int(model_id) for model_id in model_ids}
        if not normalized_model_ids:
            return 0
        query = query.filter(FinishedGoodsStock.model_id.in_(normalized_model_ids))
    rows = query.all()
    if not rows:
        return 0

    reference_cache, entity_cache = _prefetch_reference_metadata(db, rows)

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
            reference_cache=reference_cache,
            entity_cache=entity_cache,
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
