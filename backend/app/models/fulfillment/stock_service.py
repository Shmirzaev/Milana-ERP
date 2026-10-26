"""Fulfillment's approved piece/pack reservation operations.

Sales supplies the Session, scalar identities and typed demands. It owns its order
lock/replay guard and the outer transaction. This service owns physical eligibility,
selection, package/stock locks and schema-owned stock writes. No Sales mapped object
crosses the reservation boundary; no commit/rollback/begin/close is performed here.
"""
from collections import defaultdict

from fastapi import HTTPException
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.libs.enums.fulfillment import FinishedGoodsStatus
from app.libs.enums.packaging import PackageStockKind
from app.libs.types.stock_reservation import (
    PackDemand, PackReservationResult, PieceDemand, PieceReservationResult,
    ReservationSummary, StockShortage,
)
from app.models.finished_goods_service import repair_missing_brand_metadata
from app.schemas import FinishedGoodsStock, Model, Package, PackageItem, Shipment, ShipmentPackage, StockReservation
from app.schemas.fulfillment.stock_persistence import reserve_stock_row

_SHIPMENT_READY_PACKAGE_STATUSES = ("received_in_storage", "reserved")
_STOCK_VARIANT_QUERY_CHUNK_SIZE = 200
_PIECE_STOCK_KINDS = frozenset({PackageStockKind.STANDARD, PackageStockKind.FIRST_GRADE})


class _ShortagePrecheck(StockShortage):
    requested: int
    available: int


def is_any_stock_token(value: str | None) -> bool:
    """Existing stock wildcard predicate also used by Sales input guards."""
    token = str(value or "").strip().lower()
    return token in {"", "*", "any", "mixed", "__any__", "pack60", "bag"}


def _stock_variant_key(model_id: int, color: str, size: str, brand_id: int | None) -> tuple[int, str, str, int | None]:
    return (int(model_id), str(color or "").strip(), str(size or "").strip(), brand_id)


def has_order_reservations(db: Session, sales_order_id: int) -> bool:
    """Read the reservation existence used by Sales' pack replay guard."""
    return db.query(StockReservation.id).filter(StockReservation.sales_order_id == sales_order_id).first() is not None


def _validate_identity(sales_order_id: int, reserved_by: int | None) -> None:
    if type(sales_order_id) is not int or sales_order_id <= 0:
        raise ValueError("sales_order_id must be a positive integer")
    if reserved_by is not None and (type(reserved_by) is not int or reserved_by <= 0):
        raise ValueError("reserved_by must be a positive integer or None")


def _validate_model(model_id: int, brand_id: int | None) -> None:
    if type(model_id) is not int or model_id <= 0:
        raise ValueError("model_id must be a positive integer")
    if brand_id is not None and (type(brand_id) is not int or brand_id <= 0):
        raise ValueError("brand_id must be a positive integer or None")


def _validate_piece_demands(demands: tuple[PieceDemand, ...]) -> None:
    if type(demands) is not tuple or not demands:
        raise ValueError("At least one piece demand is required")
    variants: set[tuple[int, str, str, int | None]] = set()
    for demand in demands:
        if type(demand) is not PieceDemand:
            raise ValueError("Expected only PieceDemand objects")
        _validate_model(demand.model_id, demand.brand_id)
        if type(demand.quantity) is not int or demand.quantity < 0:
            raise ValueError("Piece quantity must be a nonnegative integer")
        if not isinstance(demand.color, str) or not isinstance(demand.size, str):
            raise ValueError("Piece color and size must be strings")
        key = _stock_variant_key(demand.model_id, demand.color, demand.size, demand.brand_id)
        if key in variants:
            raise ValueError("Piece demands must be aggregated by normalized variant")
        variants.add(key)


def _validate_pack_demands(demands: tuple[PackDemand, ...]) -> None:
    if type(demands) is not tuple or not demands:
        raise ValueError("At least one pack demand is required")
    keys: set[str] = set()
    models: set[int] = set()
    for demand in demands:
        if type(demand) is not PackDemand:
            raise ValueError("Expected only PackDemand objects")
        _validate_model(demand.model_id, demand.brand_id)
        if not isinstance(demand.demand_key, str) or not demand.demand_key or demand.demand_key in keys:
            raise ValueError("Demand keys must be nonempty and unique")
        if type(demand.pack_count) is not int or demand.pack_count <= 0:
            raise ValueError("Pack count must be a positive integer")
        if demand.model_id in models:
            raise ValueError("Use one pack-count demand per model variant")
        keys.add(demand.demand_key)
        models.add(demand.model_id)


def _stock_rows_by_variant(
    db: Session,
    variant_keys: list[tuple[int, str, str, int | None]],
    *,
    stock_kind: PackageStockKind = PackageStockKind.STANDARD,
) -> dict[tuple[int, str, str, int | None], list[FinishedGoodsStock]]:
    """Load the eligible stock for many requested variants in bounded batches.

    One reserved line per variant used to run its own `SELECT ... FOR UPDATE`
    and hydrate its own stock entities, so an order with many variants paid for
    the same shared rows once per variant. This loads a whole chunk of variants
    per round trip and splits the hydrated rows in Python.

    Eligibility is unchanged: the same filters run in SQL, and the per-variant
    colour/size/brand restrictions are re-applied in Python with the exact
    comparisons the SQL used, so a batched row is admitted to a variant only
    when the single-variant query would have returned it.

    Locking is unchanged too: within a chunk the eligible packages are locked
    first, ordered by package id, and the stock rows are locked only afterwards.
    Variants are processed in a fixed sorted order so two reservations that
    request the same variants in opposite line order take the same locks in the
    same sequence.
    """
    unique_keys = sorted(
        set(variant_keys),
        key=lambda key: (key[0], key[1], key[2], -1 if key[3] is None else key[3]),
    )
    rows_by_variant: dict[tuple[int, str, str, int | None], list[FinishedGoodsStock]] = {
        key: [] for key in unique_keys
    }
    for offset in range(0, len(unique_keys), _STOCK_VARIANT_QUERY_CHUNK_SIZE):
        chunk = unique_keys[offset:offset + _STOCK_VARIANT_QUERY_CHUNK_SIZE]
        keys_by_model: dict[int, list[tuple[int, str, str, int | None]]] = defaultdict(list)
        variant_predicates = []
        for key in chunk:
            model_id, color, size, brand_id = key
            keys_by_model[model_id].append(key)
            parts = [FinishedGoodsStock.model_id == model_id]
            if not is_any_stock_token(color):
                parts.append(FinishedGoodsStock.color == color)
            if not is_any_stock_token(size):
                parts.append(FinishedGoodsStock.size == size)
            if brand_id is not None:
                parts.append(FinishedGoodsStock.brand_id == brand_id)
            variant_predicates.append(and_(*parts))

        qry = (
            db.query(FinishedGoodsStock)
            .outerjoin(Package, Package.id == FinishedGoodsStock.package_id)
            .filter(
                FinishedGoodsStock.status == FinishedGoodsStatus.AVAILABLE.value,
                FinishedGoodsStock.available_qty > 0,
                or_(
                    FinishedGoodsStock.package_id.is_(None),
                    Package.status.in_(_SHIPMENT_READY_PACKAGE_STATUSES),
                ),
                ~db.query(ShipmentPackage.id).join(Shipment, Shipment.id == ShipmentPackage.shipment_id).filter(
                    ShipmentPackage.package_id == FinishedGoodsStock.package_id,
                    Shipment.status != "cancelled",
                ).exists(),
                or_(*variant_predicates),
            )
            .filter(func.coalesce(Package.stock_kind, "standard") == stock_kind.value)
        )
        if db.bind and db.bind.dialect.name == "postgresql":
            # Keep the same package -> stock lock order as warehouse dispatch.
            package_ids = qry.with_entities(FinishedGoodsStock.package_id).filter(FinishedGoodsStock.package_id.isnot(None))
            db.query(Package).filter(Package.id.in_(package_ids)).order_by(Package.id).with_for_update(key_share=True, of=Package).all()
            qry = qry.with_for_update(key_share=True, of=FinishedGoodsStock)
        for row in qry.order_by(FinishedGoodsStock.id.asc()).all():
            for key in keys_by_model.get(int(row.model_id), ()):
                _model_id, color, size, brand_id = key
                if not is_any_stock_token(color) and row.color != color:
                    continue
                if not is_any_stock_token(size) and row.size != size:
                    continue
                if brand_id is not None and row.brand_id != brand_id:
                    continue
                rows_by_variant[key].append(row)
    return rows_by_variant


def _package_allocation_candidates(
    db: Session,
    stock_rows: list[FinishedGoodsStock],
    *,
    package_cache: dict[int, Package] | None = None,
) -> tuple[dict[int, tuple[Package, list[FinishedGoodsStock]]], list[FinishedGoodsStock]]:
    """Split physical whole bags from legacy stock that permits piece allocation.

    `package_cache` reuses ``Package`` rows that a caller has already locked, so
    a package referenced by several variants is not read and locked again. Only
    the package identity is cached: the whole-bag eligibility tests below read
    the mutable stock quantities (`available_qty`, `reserved_qty`, `sold_qty`),
    so the groups are rebuilt from the current row state on every call and a
    package consumed by an earlier allocation cannot be handed out twice.
    """
    rows_by_package: dict[int, list[FinishedGoodsStock]] = defaultdict(list)
    for stock in stock_rows:
        if stock.package_id is not None:
            rows_by_package[int(stock.package_id)].append(stock)
    if not rows_by_package:
        return {}, [row for row in stock_rows if row.package_id is None]

    packages = package_cache if package_cache is not None else {}
    missing_package_ids = sorted(set(rows_by_package) - set(packages))
    if missing_package_ids:
        package_query = db.query(Package).filter(Package.id.in_(missing_package_ids))
        if db.bind and db.bind.dialect.name == "postgresql":
            package_query = package_query.with_for_update(key_share=True, of=Package)
        packages.update({
            int(package.id): package
            for package in package_query.order_by(Package.id).all()
        })

    partial_rows = [
        row
        for row in stock_rows
        if row.package_id is None
        or (
            int(row.package_id) in packages
            and packages[int(row.package_id)].legacy_receipt_id is not None
        )
    ]

    groups: dict[int, tuple[Package, list[FinishedGoodsStock]]] = {}
    for package_id, rows in rows_by_package.items():
        package = packages.get(package_id)
        if not package or package.status not in _SHIPMENT_READY_PACKAGE_STATUSES:
            continue
        if package.legacy_receipt_id is not None:
            continue
        package_qty = int(package.total_quantity or 0)
        if package_qty <= 0:
            continue
        if any(
            int(row.available_qty or 0) != int(row.quantity or 0)
            or int(row.reserved_qty or 0) != 0
            or int(row.sold_qty or 0) != 0
            for row in rows
        ):
            continue
        if sum(int(row.available_qty or 0) for row in rows) != package_qty:
            continue
        groups[package_id] = (package, rows)
    return groups, partial_rows


def _select_whole_packages(
    package_groups: dict[int, tuple[Package, list[FinishedGoodsStock]]],
    target_qty: int,
) -> list[int]:
    """Choose complete packages with the greatest total not exceeding target."""
    target = max(0, int(target_qty or 0))
    if target <= 0:
        return []

    candidates = sorted(
        (
            (package_id, int(package.total_quantity or 0))
            for package_id, (package, _rows) in package_groups.items()
            if 0 < int(package.total_quantity or 0) <= target
        ),
        key=lambda row: (-row[1], row[0]),
    )
    exact = next((package_id for package_id, quantity in candidates if quantity == target), None)
    if exact is not None:
        return [exact]
    if not candidates:
        return []

    # A bitset keeps subset selection bounded by the requested quantity while
    # predecessor entries allow reconstructing the best physical-package set.
    reachable = 1
    predecessor: dict[int, tuple[int, int]] = {}
    mask = (1 << (target + 1)) - 1
    for package_id, quantity in candidates:
        shifted = (reachable << quantity) & mask
        newly_reachable = shifted & ~reachable
        pending = newly_reachable
        while pending:
            bit = pending & -pending
            total = bit.bit_length() - 1
            predecessor[total] = (total - quantity, package_id)
            pending ^= bit
        reachable |= shifted

    best_total = reachable.bit_length() - 1
    selected: list[int] = []
    while best_total > 0:
        previous_total, package_id = predecessor[best_total]
        selected.append(package_id)
        best_total = previous_total
    return selected


def ready_pack_candidates(
    db: Session, *, model_ids: set[int] | None = None, lock: bool = False, stock_kind: PackageStockKind = PackageStockKind.STANDARD,
) -> list[tuple[Package, list[FinishedGoodsStock]]]:
    """Return intact received packages, never synthetic bags or remaining pieces.

    Compare every size/color stock row with package-item evidence. An intact
    12-piece bag counts as one pack just like a 78-piece bag.
    """
    package_query = db.query(Package).join(Model, Model.id == Package.model_id).filter(
        Package.status.in_(("received_in_storage", "reserved")),
        Package.total_quantity > 0,
        Package.stock_kind == stock_kind.value,
        Package.sales_order_id.is_(None),
        Model.catalog_scope == "standard",
        ~db.query(ShipmentPackage.id).join(Shipment, Shipment.id == ShipmentPackage.shipment_id).filter(
            ShipmentPackage.package_id == Package.id, Shipment.status != "cancelled",
        ).exists(),
        ~db.query(StockReservation.id).join(
            FinishedGoodsStock, FinishedGoodsStock.id == StockReservation.finished_goods_stock_id,
        ).filter(or_(StockReservation.package_id == Package.id, FinishedGoodsStock.package_id == Package.id)).exists(),
    )
    if model_ids is not None:
        package_query = package_query.filter(Package.model_id.in_(model_ids))
    # Shipment correction and dispatch use this same global lock order.
    # Exclude attached/reserved packages before locking, then recheck evidence.
    if lock and db.bind and db.bind.dialect.name == "postgresql":
        package_query = package_query.with_for_update(of=Package)
    packages = package_query.order_by(Package.id).all()
    package_ids = [package.id for package in packages]
    if not package_ids:
        return []
    stock_query = db.query(FinishedGoodsStock).filter(FinishedGoodsStock.package_id.in_(package_ids))
    if lock and db.bind and db.bind.dialect.name == "postgresql":
        stock_query = stock_query.with_for_update(of=FinishedGoodsStock)
    stocks = stock_query.order_by(FinishedGoodsStock.id).all()
    stock_groups = defaultdict(list)
    for stock in stocks:
        stock_groups[stock.package_id].append(stock)
    item_groups = defaultdict(list)
    for item in db.query(PackageItem).filter(PackageItem.package_id.in_(package_ids)).all():
        item_groups[item.package_id].append(item)
    reserved_rows = db.query(StockReservation.finished_goods_stock_id, StockReservation.package_id).filter(
        or_(StockReservation.package_id.in_(package_ids),
            StockReservation.finished_goods_stock_id.in_([s.id for s in stocks])),
    ).all()
    reserved_stock_ids = {row[0] for row in reserved_rows}
    reserved_ids = {row[1] for row in reserved_rows} | {
        stock.package_id for stock in stocks if stock.id in reserved_stock_ids
    }
    attached_ids = {
        row[0] for row in db.query(ShipmentPackage.package_id).join(
            Shipment, Shipment.id == ShipmentPackage.shipment_id,
        ).filter(ShipmentPackage.package_id.in_(package_ids), Shipment.status != "cancelled").all()
    }
    result = []
    for package in packages:
        rows = stock_groups[package.id]
        if package.id in reserved_ids or package.id in attached_ids or not rows:
            continue
        if not (package.production_order_id or package.legacy_receipt_id or getattr(package, "manual_receipt_id", None)):
            continue
        if any(
            row.status != FinishedGoodsStatus.AVAILABLE.value or row.quantity <= 0 or row.available_qty != row.quantity
            or row.reserved_qty or row.sold_qty or row.model_id != package.model_id
            or row.sales_order_id is not None
            for row in rows
        ):
            continue
        stock_contents = defaultdict(int)
        item_contents = defaultdict(int)
        for row in rows:
            stock_contents[(row.model_id, row.color, row.size)] += row.quantity
        for item in item_groups[package.id]:
            item_contents[(item.model_id, item.color, item.size)] += item.quantity
        if stock_contents != item_contents or sum(stock_contents.values()) != package.total_quantity:
            continue
        result.append((package, rows))
    return result


def reserve_pieces(
    db: Session, *, sales_order_id: int, reserved_by: int | None,
    stock_kind: PackageStockKind, demands: tuple[PieceDemand, ...], fail_on_shortage: bool,
) -> PieceReservationResult:
    """Reserve whole packages then legacy remainder, preserving existing order.

    Explicit runtime validation precedes all database access. The caller owns
    authorization and rollback if the operation refuses after metadata repair.
    """
    _validate_identity(sales_order_id, reserved_by)
    if not isinstance(stock_kind, PackageStockKind) or stock_kind not in _PIECE_STOCK_KINDS:
        raise ValueError("Piece Sales require standard or first-grade PackageStockKind")
    if type(fail_on_shortage) is not bool:
        raise ValueError("fail_on_shortage must be bool")
    _validate_piece_demands(demands)
    requested_by_variant = {
        _stock_variant_key(d.model_id, d.color, d.size, d.brand_id): d.quantity for d in demands
    }
    package_cache: dict[int, Package] = {}
    if db.bind and db.bind.dialect.name == "postgresql":
        # Lock across all lines before metadata repair or any stock lock, so
        # opposite model-line ordering cannot invert the package lock order.
        locked_packages = db.query(Package).filter(
            Package.model_id.in_({key[0] for key in requested_by_variant}),
            Package.status.in_(_SHIPMENT_READY_PACKAGE_STATUSES),
            ~db.query(ShipmentPackage.id).join(Shipment, Shipment.id == ShipmentPackage.shipment_id).filter(
                ShipmentPackage.package_id == Package.id, Shipment.status != "cancelled",
            ).exists(),
        ).order_by(Package.id).with_for_update(key_share=True, of=Package).all()
        package_cache.update({int(package.id): package for package in locked_packages})

    # Legacy rows need inferred metadata only when a requested brand must be
    # matched. Keep that repair scoped to the models in this order instead of
    # scanning the entire finished-goods warehouse on every submission.
    branded_model_ids = {
        int(model_id)
        for model_id, _color, _size, brand_id in requested_by_variant
        if brand_id is not None
    }
    if branded_model_ids:
        repair_missing_brand_metadata(db, model_ids=branded_model_ids)

    existing_rows = (
        db.query(StockReservation, FinishedGoodsStock)
        .join(FinishedGoodsStock, FinishedGoodsStock.id == StockReservation.finished_goods_stock_id)
        .filter(StockReservation.sales_order_id == sales_order_id)
        .all()
    )

    outstanding_by_variant: dict[tuple[int, str, str, int | None], int] = {}
    for key, requested_qty in requested_by_variant.items():
        model_id, color, size, brand_id = key
        any_color = is_any_stock_token(color)
        any_size = is_any_stock_token(size)
        already_reserved = 0
        for reservation, stock in existing_rows:
            if int(stock.model_id) != int(model_id):
                continue
            if not any_color and str(stock.color or "").strip() != color:
                continue
            if not any_size and str(stock.size or "").strip() != size:
                continue
            if brand_id is not None and int(stock.brand_id or 0) != int(brand_id):
                continue
            already_reserved += int(reservation.quantity or 0)
        outstanding_by_variant[key] = max(0, int(requested_qty) - already_reserved)

    if requested_by_variant and all(qty <= 0 for qty in outstanding_by_variant.values()):
        raise HTTPException(409, "Stock has already been fully reserved for this sales order")

    shortages_precheck: list[_ShortagePrecheck] = []
    stock_rows_by_variant = _stock_rows_by_variant(
        db,
        [key for key, requested_qty in outstanding_by_variant.items() if requested_qty > 0],
        stock_kind=stock_kind,
    )
    for key, requested_qty in outstanding_by_variant.items():
        if requested_qty <= 0:
            continue
        model_id, color, size, brand_id = key
        stock_rows = stock_rows_by_variant[key]
        package_groups, partial_stocks = _package_allocation_candidates(
            db,
            stock_rows,
            package_cache=package_cache,
        )
        available_qty = sum(
            int(package.total_quantity or 0)
            for package, _rows in package_groups.values()
        ) + sum(
            int(row.available_qty or 0)
            for row in partial_stocks
        )
        if available_qty < requested_qty:
            shortages_precheck.append(
                {
                    "model_id": model_id,
                    "brand_id": brand_id,
                    "color": color,
                    "size": size,
                    "requested": requested_qty,
                    "available": available_qty,
                    "shortage": requested_qty - available_qty,
                }
            )

    if fail_on_shortage and shortages_precheck:
        summary = "; ".join(
            f"M{s['model_id']} {s['color']}/{s['size']} need {s['requested']}, available {s['available']}"
            for s in shortages_precheck[:4]
        )
        if len(shortages_precheck) > 4:
            summary += f" (+{len(shortages_precheck) - 4} more)"
        raise HTTPException(409, f"Not enough branded stock to fulfill this order: {summary}")

    reservations: list[ReservationSummary] = []
    shortages: list[StockShortage] = []
    for key, requested_qty in outstanding_by_variant.items():
        if requested_qty <= 0:
            continue
        model_id, color, size, brand_id = key
        needed = int(requested_qty)
        stocks = stock_rows_by_variant[key]
        package_groups, partial_stocks = _package_allocation_candidates(
            db,
            stocks,
            package_cache=package_cache,
        )
        selected_package_ids = _select_whole_packages(package_groups, needed)
        for package_id in selected_package_ids:
            package, package_stocks = package_groups[package_id]
            for s in package_stocks:
                take = int(s.available_qty or 0)
                reserve_stock_row(
                    db, s, sales_order_id=sales_order_id, reserved_by=reserved_by,
                    quantity=take, package_id=package.id, available_quantity=0,
                    reserved_quantity=int(s.reserved_qty or 0) + take,
                    status=FinishedGoodsStatus.RESERVED,
                )
                reservations.append({"stock_id": s.id, "package_id": package.id, "qty": take})
                needed -= take

        # Legacy aggregate receipts and package-less rows retain their existing
        # piece-level sales behavior. Factory-produced bags remain indivisible.
        for s in partial_stocks:
            if needed <= 0:
                break
            take = min(needed, int(s.available_qty or 0))
            if take <= 0:
                continue
            remaining = int(s.available_qty or 0) - take
            reserve_stock_row(
                db, s, sales_order_id=sales_order_id, reserved_by=reserved_by,
                quantity=take, package_id=s.package_id, available_quantity=remaining,
                reserved_quantity=int(s.reserved_qty or 0) + take,
                status=FinishedGoodsStatus.RESERVED if remaining == 0 else FinishedGoodsStatus(s.status),
            )
            reservations.append({"stock_id": s.id, "package_id": None, "qty": take})
            needed -= take
        if needed > 0:
            shortages.append(
                {
                    "model_id": model_id,
                    "brand_id": brand_id,
                    "color": color,
                    "size": size,
                    "shortage": needed,
                }
            )

    return PieceReservationResult(tuple(reservations), tuple(shortages))


def reserve_packs(
    db: Session, *, sales_order_id: int, reserved_by: int | None,
    demands: tuple[PackDemand, ...],
) -> PackReservationResult:
    """Reserve intact standard packages; return quantities for Sales-owned lines.

    Sales takes its order lock and applies its replay refusal before this call.
    This operation then takes full Package -> FinishedGoodsStock locks and never
    changes a Sales row. Requested pack count is a strict positive integer.
    """
    _validate_identity(sales_order_id, reserved_by)
    _validate_pack_demands(demands)
    candidates = ready_pack_candidates(db, model_ids={d.model_id for d in demands}, lock=True,
                                      stock_kind=PackageStockKind.STANDARD)
    selected_by_demand: list[tuple[PackDemand, list[tuple[Package, list[FinishedGoodsStock]]]]] = []
    for demand in demands:
        matching = [
            (package, rows) for package, rows in candidates
            if package.model_id == demand.model_id
            and (demand.brand_id is None or all(row.brand_id == demand.brand_id for row in rows))
        ]
        if len(matching) < demand.pack_count:
            raise HTTPException(409, f"Not enough complete packs: requested {demand.pack_count}, available {len(matching)}")
        selected_by_demand.append((demand, matching[:demand.pack_count]))
    reservations: list[ReservationSummary] = []
    quantities: dict[str, int] = {}
    for demand, selected in selected_by_demand:
        quantities[demand.demand_key] = sum(package.total_quantity for package, _ in selected)
        for package, rows in selected:
            for stock in rows:
                quantity = stock.quantity
                reserve_stock_row(db, stock, sales_order_id=sales_order_id, reserved_by=reserved_by,
                                  quantity=quantity, package_id=package.id, available_quantity=0,
                                  reserved_quantity=quantity, status=FinishedGoodsStatus.RESERVED)
                reservations.append({"stock_id": stock.id, "package_id": package.id, "qty": quantity})
    return PackReservationResult(tuple(reservations), quantities)
