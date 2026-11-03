"""Pack recipient policy and the explicit, scoped admin release operation."""
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.deps import is_admin
from app.libs.dto.fulfillment.package_customer_release import (
    PackageCustomerAccessOut, PackageCustomerReleaseIn, PackageCustomerReleaseOut,
)
from app.libs.enums.fulfillment import FinishedGoodsStatus, ShipmentStatus
from app.libs.enums.packaging import PackageStatus
from app.models.audit_service import log_action
from app.models.idempotency_service import replay_idempotent_response, store_idempotent_response
from app.models.packaging_scope_service import require_package_access
from app.schemas import (
    Customer, FinishedGoodsStock, Package, PackageCustomerRelease, ProductionOrder,
    SalesOrder, Shipment, ShipmentPackage, StockReservation, User, WarehousePackReservation,
)
from app.schemas.fulfillment.package_customer_release import save_customer_release


@dataclass(frozen=True)
class PackageCustomerPolicy:
    source_order_ids: tuple[int, ...]
    customers: tuple[tuple[int, str], ...]
    released: bool


def _remaining(package: Package) -> int:
    return int(package.total_quantity or 0) - int(package.dispatched_quantity or 0)


def package_customer_policies(db: Session, packages: list[Package], *,
                              stock_rows: list[FinishedGoodsStock] | None = None) -> dict[int, PackageCustomerPolicy]:
    """Bounded reads; production provenance survives partial-dispatch detachment."""
    if not packages:
        return {}
    production_ids = {p.production_order_id for p in packages if p.production_order_id}
    source_orders = dict(db.query(ProductionOrder.id, ProductionOrder.sales_order_id).filter(
        ProductionOrder.id.in_(production_ids)).all()) if production_ids else {}
    # Stock source attribution is retained even when a direct-order package's
    # production order has no sales link and partial dispatch detaches the pack.
    stock_orders: dict[int, set[int]] = {}
    stock_sources = ([(row.package_id, row.sales_order_id) for row in stock_rows if row.sales_order_id]
                     if stock_rows is not None else db.query(FinishedGoodsStock.package_id, FinishedGoodsStock.sales_order_id).filter(
                         FinishedGoodsStock.package_id.in_([p.id for p in packages]),
                         FinishedGoodsStock.sales_order_id.isnot(None)).distinct().all())
    for pid, oid in stock_sources:
        stock_orders.setdefault(pid, set()).add(oid)
    order_ids_by_package = {p.id: tuple(sorted({oid for oid in (
        source_orders.get(p.production_order_id), p.sales_order_id) if oid} | stock_orders.get(p.id, set()))) for p in packages}
    order_ids = {oid for values in order_ids_by_package.values() for oid in values}
    customers_by_order = {oid: (cid, name) for oid, cid, name in db.query(
        SalesOrder.id, Customer.id, Customer.name).join(Customer, Customer.id == SalesOrder.customer_id)
        .filter(SalesOrder.id.in_(order_ids)).all()} if order_ids else {}
    releases = {row.package_id: row for row in db.query(PackageCustomerRelease).filter(
        PackageCustomerRelease.package_id.in_([p.id for p in packages])).populate_existing().all()}
    return {
        p.id: PackageCustomerPolicy(
            order_ids_by_package[p.id],
            tuple(sorted({customers_by_order[oid] for oid in order_ids_by_package[p.id] if oid in customers_by_order})),
            bool((release := releases.get(p.id))
                 and tuple(release.source_order_ids) == order_ids_by_package[p.id]
                 and 0 < _remaining(p) <= release.released_quantity),
        ) for p in packages
    }


def shipment_customer_id(db: Session, shipment: Shipment) -> int | None:
    # A supplied shipment header must not override its order's selected customer.
    order_customer = db.query(SalesOrder.customer_id).filter_by(id=shipment.sales_order_id).scalar() if shipment.sales_order_id else None
    if order_customer and shipment.customer_id and shipment.customer_id != order_customer:
        raise HTTPException(409, "Shipment customer must match the sales order customer")
    return order_customer or shipment.customer_id


def customer_policy_error(package: Package, policy: PackageCustomerPolicy, customer_id: int | None) -> str | None:
    if not policy.released and any(cid != customer_id for cid, _ in policy.customers):
        names = ", ".join(name for _, name in policy.customers)
        return f"Package {package.package_no} is assigned to customer {names}. An admin must release it before shipping to another customer."
    return None


def package_customer_error(db: Session, shipment: Shipment, package: Package) -> str | None:
    return customer_policy_error(package, package_customer_policies(db, [package])[package.id],
                                 shipment_customer_id(db, shipment))


def package_reservation_error(db: Session, sales_order_id: int | None, package: Package) -> str | None:
    """A customer release never releases a subsequent stock reservation."""
    query = db.query(StockReservation.id).outerjoin(
        FinishedGoodsStock, FinishedGoodsStock.id == StockReservation.finished_goods_stock_id).filter(
            or_(StockReservation.package_id == package.id, FinishedGoodsStock.package_id == package.id),
            StockReservation.quantity > 0)
    if sales_order_id:
        query = query.filter(StockReservation.sales_order_id != sales_order_id)
    if query.first():
        return f"Package {package.package_no} is reserved for another order."
    return None


def assert_package_customer(db: Session, shipment: Shipment, package: Package) -> PackageCustomerPolicy:
    policy = package_customer_policies(db, [package])[package.id]
    error = customer_policy_error(package, policy, shipment_customer_id(db, shipment))
    if error:
        raise HTTPException(409, error)
    reservation_error = package_reservation_error(db, shipment.sales_order_id, package)
    if reservation_error:
        raise HTTPException(409, reservation_error)
    return policy


def assert_shipment_customers(db: Session, shipment: Shipment, packages: list[Package], *,
                              stock_rows: list[FinishedGoodsStock] | None = None) -> None:
    customer_id = shipment_customer_id(db, shipment)
    policies = package_customer_policies(db, packages, stock_rows=stock_rows)
    for package in packages:
        error = customer_policy_error(package, policies[package.id], customer_id)
        if error:
            raise HTTPException(409, error)


def package_customer_access(db: Session, current: User, package_id: int) -> PackageCustomerAccessOut:
    package = db.get(Package, package_id)
    if package is None:
        raise HTTPException(404, "Package not found")
    require_package_access(current, package)
    policy = package_customer_policies(db, [package])[package.id]
    release = db.get(PackageCustomerRelease, package.id)
    actor = db.get(User, release.released_by) if release else None
    released_at = release.released_at if release else None
    if released_at and released_at.tzinfo is None:
        released_at = released_at.replace(tzinfo=timezone.utc)
    return PackageCustomerAccessOut(
        customer_names=[name for _, name in policy.customers],
        released_for_any_customer=policy.released,
        released_at=released_at,
        released_by_name=actor.name if actor else None,
        release_reason=release.reason if release else None,
        released_quantity=release.released_quantity if release else None,
    )


def release_packages_for_any_customer(payload: PackageCustomerReleaseIn, db: Session, current: User,
                                      idempotency_key: str | None = None) -> PackageCustomerReleaseOut:
    if not is_admin(current):
        raise HTTPException(403, "Admin access required")
    fingerprint = payload.model_dump()
    replay = replay_idempotent_response(db, scope="packages.customer-release", key=idempotency_key, payload=fingerprint)
    if replay is not None:
        return PackageCustomerReleaseOut.model_validate(replay)
    ids = sorted(payload.package_ids)
    packages = db.query(Package).filter(Package.id.in_(ids)).order_by(Package.id).with_for_update(of=Package).populate_existing().all()
    if len(packages) != len(ids):
        raise HTTPException(404, "Package not found")
    for package in packages:
        require_package_access(current, package)
    stocks = db.query(FinishedGoodsStock).filter(FinishedGoodsStock.package_id.in_(ids)).order_by(
        FinishedGoodsStock.id).with_for_update(of=FinishedGoodsStock).populate_existing().all()
    stock_ids = [row.id for row in stocks]
    if (db.query(WarehousePackReservation.package_id).filter(WarehousePackReservation.package_id.in_(ids)).first()
            or db.query(StockReservation.id).filter(or_(StockReservation.package_id.in_(ids),
                StockReservation.finished_goods_stock_id.in_(stock_ids)), StockReservation.quantity > 0).first()
            or db.query(ShipmentPackage.id).join(Shipment, Shipment.id == ShipmentPackage.shipment_id).filter(
                ShipmentPackage.package_id.in_(ids), Shipment.status.in_((ShipmentStatus.DRAFT, ShipmentStatus.CREATED)),
                Shipment.deleted_at.is_(None)).first()):
        raise HTTPException(409, "Remove active reservations and open shipment allocations before releasing packs")
    policies = package_customer_policies(db, packages, stock_rows=stocks)
    for package in packages:
        rows = [row for row in stocks if row.package_id == package.id]
        if (package.status != PackageStatus.RECEIVED or _remaining(package) <= 0 or not rows
                or sum(row.quantity for row in rows) != package.total_quantity
                or sum(row.sold_qty for row in rows) != package.dispatched_quantity
                or sum(row.available_qty for row in rows) != _remaining(package)
                or any(row.reserved_qty or row.quantity != row.available_qty + row.sold_qty
                       or row.available_qty < 0 or row.sold_qty < 0
                       or row.status not in (FinishedGoodsStatus.AVAILABLE, FinishedGoodsStatus.SOLD) for row in rows)):
            raise HTTPException(409, f"Package {package.package_no} must have available, balanced warehouse stock")
    now = datetime.now(timezone.utc)
    for package in packages:
        policy = policies[package.id]
        if policy.released:
            continue
        if not policy.customers:
            # Ordinary unrestricted stock already has this eligibility.
            continue
        save_customer_release(db, package_id=package.id, source_order_ids=list(policy.source_order_ids),
                              quantity=_remaining(package), actor_id=current.id, released_at=now, reason=payload.reason)
        log_action(db, current, "release_for_any_customer", "Package", package.id,
                   old_value={"source_order_ids": list(policy.source_order_ids), "customer_names": [name for _, name in policy.customers]},
                   new_value={"reason": payload.reason, "released_quantity": _remaining(package)})
    result = PackageCustomerReleaseOut(package_ids=ids, released_count=len(ids))
    store_idempotent_response(db, scope="packages.customer-release", key=idempotency_key,
                             payload=fingerprint, response=result.model_dump(mode="json"), user=current)
    db.commit()
    return result
