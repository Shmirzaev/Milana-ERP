"""Ready-stock sales: allocation of finished goods and branded stock.

Contract for `_reserve_branded_stock`:
* input: a sales order, the acting user and optionally the order lines
* output: the reservations taken and the shortage lines left over
* refusals: 400 when the order mixes first-grade and standard lines, 409 when
  the stock is already fully reserved or the shortage cannot be filled
* records: `finished_goods_stock` quantities, `stock_reservations` rows and the
  sales order status and notes
* lock order: package rows (key share) before the stock rows, the same order
  warehouse dispatch takes
* transaction owner: the calling sales operation
"""
from collections import defaultdict

from fastapi import HTTPException
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.models.finished_goods_service import repair_missing_brand_metadata
from app.models.ready_stock_sales_service import reserve_ready_packs
from app.models.workflow_service import notify_department
from app.schemas import (
    Customer, Department, FinishedGoodsStock, Model, Package, SalesOrder, SalesOrderItem,
    Shipment, ShipmentPackage, StockReservation, Task, User,
)

_SHIPMENT_READY_PACKAGE_STATUSES = ("received_in_storage", "reserved")
# Variants per stock round trip. Bounds the parameter list of the batched
# eligibility query without changing which rows are eligible.
_STOCK_VARIANT_QUERY_CHUNK_SIZE = 200


def _is_any_stock_token(value: str | None) -> bool:
    token = str(value or "").strip().lower()
    return token in {"", "*", "any", "mixed", "__any__", "pack60", "bag"}


def _stock_variant_key(model_id: int, color: str, size: str, brand_id: int | None) -> tuple[int, str, str, int | None]:
    return (int(model_id), str(color or "").strip(), str(size or "").strip(), brand_id)


def _stock_rows_by_variant(
    db: Session,
    variant_keys: list[tuple[int, str, str, int | None]],
    *,
    stock_kind: str = "standard",
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
            if not _is_any_stock_token(color):
                parts.append(FinishedGoodsStock.color == color)
            if not _is_any_stock_token(size):
                parts.append(FinishedGoodsStock.size == size)
            if brand_id is not None:
                parts.append(FinishedGoodsStock.brand_id == brand_id)
            variant_predicates.append(and_(*parts))

        qry = (
            db.query(FinishedGoodsStock)
            .outerjoin(Package, Package.id == FinishedGoodsStock.package_id)
            .filter(
                FinishedGoodsStock.status == "available",
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
            .filter(func.coalesce(Package.stock_kind, "standard") == stock_kind)
        )
        if db.bind and db.bind.dialect.name == "postgresql":
            # Keep the same package -> stock lock order as warehouse dispatch.
            package_ids = qry.with_entities(FinishedGoodsStock.package_id).filter(FinishedGoodsStock.package_id.isnot(None))
            db.query(Package).filter(Package.id.in_(package_ids)).order_by(Package.id).with_for_update(key_share=True, of=Package).all()
            qry = qry.with_for_update(key_share=True, of=FinishedGoodsStock)
        for row in qry.order_by(FinishedGoodsStock.id.asc()).all():
            for key in keys_by_model.get(int(row.model_id), ()):
                _model_id, color, size, brand_id = key
                if not _is_any_stock_token(color) and row.color != color:
                    continue
                if not _is_any_stock_token(size) and row.size != size:
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


def _notify_planning_shortage(
    db: Session,
    *,
    so: SalesOrder,
    current: User,
    shortages: list[dict],
) -> None:
    if not shortages:
        return
    planning_dept = db.query(Department).filter(Department.code == "PLN").first()
    planning_user = (
        db.query(User)
        .filter(User.is_active.is_(True), User.department_id == planning_dept.id if planning_dept else False)
        .order_by(User.id.asc())
        .first()
        if planning_dept
        else None
    )
    if planning_user:
        summary = ", ".join(f"M{r['model_id']} {r['color']}/{r['size']}: {r['shortage']}" for r in shortages[:6])
        if len(shortages) > 6:
            summary += f" (+{len(shortages) - 6} more)"
        db.add(
            Task(
                title=f"Stock shortage for {so.order_no}",
                description=f"Auto-created from reserve-stock. Resolve shortages: {summary}",
                assigned_to=planning_user.id,
                created_by=current.id,
                status="pending",
                priority="high",
                due_date=so.deadline,
            )
        )
    notify_department(
        db,
        department_code="PLN",
        title=f"Shortage detected for {so.order_no}",
        message=f"{len(shortages)} shortage line(s) were detected during reserve-stock.",
        link=f"/sales-orders/{so.id}",
        exclude_user_id=current.id,
    )


def _shipment_handoff_details(
    db: Session,
    *,
    so: SalesOrder,
    lines: list[SalesOrderItem],
) -> tuple[int, str]:
    model_ids = sorted({int(line.model_id) for line in lines if line.model_id})
    model_rows = db.query(Model.id, Model.code, Model.name).filter(Model.id.in_(model_ids)).all() if model_ids else []
    model_by_id = {
        int(model_id): str(code or name or f"Model {model_id}")
        for model_id, code, name in model_rows
    }
    item_parts: list[str] = []
    total_qty = 0
    for line in lines:
        quantity = max(0, int(line.quantity or 0))
        total_qty += quantity
        model_label = model_by_id.get(int(line.model_id), f"Model {line.model_id}")
        variant = " / ".join(part for part in (str(line.color or "").strip(), str(line.size or "").strip()) if part)
        item_parts.append(f"{model_label}{f' ({variant})' if variant else ''} x {quantity}")

    customer = db.get(Customer, so.customer_id) if so.customer_id else None
    destination = str(customer.address or "").strip() if customer else ""
    customer_name = str(customer.name or "").strip() if customer else ""
    item_summary = "; ".join(item_parts) if item_parts else "No item lines"
    destination_summary = destination or "Not specified"
    customer_summary = f" for {customer_name}" if customer_name else ""
    return total_qty, f"{item_summary}. Destination{customer_summary}: {destination_summary}."


def _reserve_branded_stock(
    db: Session,
    *,
    so: SalesOrder,
    current: User,
    lines: list[SalesOrderItem] | None = None,
    fail_on_shortage: bool = False,
    notify_shortage: bool = True,
    notify_storage_when_ready: bool = False,
) -> tuple[list[dict], list[dict]]:
    line_rows = lines if lines is not None else db.query(SalesOrderItem).filter(SalesOrderItem.sales_order_id == so.id).all()
    kinds = {line.source_type == "first_grade" for line in line_rows}
    if len(kinds) > 1:
        raise HTTPException(400, "FIRST_GRADE_SEPARATE_ORDER")
    stock_kind = "first_grade" if True in kinds else "standard"
    if any(line.requested_pack_count is not None for line in line_rows):
        reservations = reserve_ready_packs(db, so=so, lines=line_rows, user_id=current.id)
        if notify_storage_when_ready:
            _total_qty, handoff_message = _shipment_handoff_details(db, so=so, lines=line_rows)
            pack_count = sum(line.requested_pack_count for line in line_rows)
            notify_department(
                db, department_code="FGS", title=f"{so.order_no}: {pack_count} packs to prepare",
                message=handoff_message, link=f"/departments/FGS#shipping-order-{so.id}",
                exclude_user_id=current.id,
            )
        return reservations, []
    requested_by_variant: dict[tuple[int, str, str, int | None], int] = defaultdict(int)
    for line in line_rows:
        key = _stock_variant_key(line.model_id, line.color, line.size, line.brand_id)
        requested_by_variant[key] += int(line.quantity or 0)

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
        .filter(StockReservation.sales_order_id == so.id)
        .all()
    )

    outstanding_by_variant: dict[tuple[int, str, str, int | None], int] = {}
    for key, requested_qty in requested_by_variant.items():
        model_id, color, size, brand_id = key
        any_color = _is_any_stock_token(color)
        any_size = _is_any_stock_token(size)
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

    shortages_precheck: list[dict] = []
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

    reservations: list[dict] = []
    shortages: list[dict] = []
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
                s.available_qty = 0
                s.reserved_qty = int(s.reserved_qty or 0) + take
                s.status = "reserved"
                db.add(
                    StockReservation(
                        sales_order_id=so.id,
                        finished_goods_stock_id=s.id,
                        package_id=package.id,
                        quantity=take,
                        reserved_by=current.id,
                    )
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
            s.available_qty = int(s.available_qty or 0) - take
            s.reserved_qty = int(s.reserved_qty or 0) + take
            if int(s.available_qty or 0) == 0:
                s.status = "reserved"
            db.add(
                StockReservation(
                    sales_order_id=so.id,
                    finished_goods_stock_id=s.id,
                    package_id=s.package_id,
                    quantity=take,
                    reserved_by=current.id,
                )
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

    if reservations:
        is_complete = not shortages
        so.status = "ready" if is_complete else "reserved"
        auto_note = (
            "[Auto route] Branded stock reserved and sent to storage team for shipment prep."
            if is_complete
            else "[Auto route] Complete packages reserved; remaining quantity awaits another package."
        )
        so.notes = f"{so.notes}\n{auto_note}".strip() if so.notes else auto_note
        if notify_storage_when_ready:
            total_qty, handoff_message = _shipment_handoff_details(db, so=so, lines=line_rows)
            reserved_qty = sum(int(row.get("qty") or 0) for row in reservations)
            notify_department(
                db,
                department_code="FGS",
                title=(
                    f"{so.order_no}: {total_qty} pcs ready to ship"
                    if is_complete
                    else f"{so.order_no}: {reserved_qty}/{total_qty} pcs ready to ship"
                ),
                message=handoff_message,
                link=f"/departments/FGS#shipping-order-{so.id}",
                exclude_user_id=current.id,
            )

    if shortages and notify_shortage:
        _notify_planning_shortage(db, so=so, current=current, shortages=shortages)

    return reservations, shortages
