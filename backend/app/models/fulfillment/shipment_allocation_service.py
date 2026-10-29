"""Per-item claims on one physical package, including existing open shipments.

Writers lock their own Shipment then sorted Package rows. Never lock another
Shipment here: its owner may be waiting for the Package lock we already hold.
"""
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.libs.enums.fulfillment import ShipmentStatus
from app.schemas import Package, PackageItem, Shipment, ShipmentPackage
from app.schemas.fulfillment.shipment_allocation import save_package_claim, replace_package_claim

OPEN_STATUSES = (ShipmentStatus.DRAFT, ShipmentStatus.CREATED)


def available_claims(db: Session, packages: list[Package], shipment_id: int | None = None,
                     items: list[PackageItem] | None = None) -> dict[int, dict[str, int]]:
    """Physical remaining less OTHER open claims; reads are batched, never locked."""
    if not packages:
        return {}
    by_id = {p.id: p for p in packages}
    if items is None:
        items = db.query(PackageItem).filter(PackageItem.package_id.in_(by_id)).all()
    remaining: dict[int, dict[str, int]] = {pid: {} for pid in by_id}
    for item in items:
        package = by_id[item.package_id]
        remaining[package.id][str(item.id)] = item.quantity - (package.dispatched_quantities or {}).get(str(item.id), 0)
    result = {pid: dict(values) for pid, values in remaining.items()}
    query = db.query(ShipmentPackage.package_id, ShipmentPackage.quantity, Shipment.dispatch_snapshot).join(
        Shipment, Shipment.id == ShipmentPackage.shipment_id).filter(
            ShipmentPackage.package_id.in_(by_id), Shipment.status.in_(OPEN_STATUSES), Shipment.deleted_at.is_(None))
    if shipment_id is not None:
        query = query.filter(Shipment.id != shipment_id)
    for pid, quantity, snapshot in query.all():
        values = (snapshot or {}).get("package_quantities", {}).get(str(pid))
        if values is None:
            # Legacy whole-pack links have an unambiguous per-size meaning.
            # Never guess which sizes an old unfrozen partial quantity claimed.
            if quantity != sum(remaining[pid].values()):
                raise HTTPException(409, "Existing shipment allocation needs review before sharing this package")
            values = remaining[pid]
        if (not isinstance(values, dict) or set(values) != set(remaining[pid])
                or any(type(qty) is not int or qty < 0 for qty in values.values())
                or sum(values.values()) != quantity):
            raise HTTPException(409, "Existing shipment allocation does not balance")
        for key, qty in values.items():
            result[pid][key] -= qty
    if any(qty < 0 for values in result.values() for qty in values.values()):
        raise HTTPException(409, "Open shipment allocations exceed remaining package contents")
    return result


def validate_claim(db: Session, shipment: Shipment, package: Package, quantities: dict[str, int],
                   items: list[PackageItem] | None = None) -> None:
    available = available_claims(db, [package], shipment.id, items)[package.id]
    validate_available_claim(quantities, available)


def validate_available_claim(quantities: dict[str, int], available: dict[str, int]) -> None:
    if (set(quantities) != set(available) or sum(quantities.values()) <= 0
            or any(type(qty) is not int or qty < 0 or qty > available[key] for key, qty in quantities.items())):
        raise HTTPException(409, "Selected pieces exceed the remainder not allocated to other open shipments")


def attach_package_claim(db: Session, shipment: Shipment, package: Package) -> ShipmentPackage:
    if shipment.status not in OPEN_STATUSES or shipment.deleted_at:
        raise HTTPException(409, "Packages can only be added before shipment")
    package = db.query(Package).filter_by(id=package.id).with_for_update().populate_existing().one()
    if package.status not in {'received_in_storage', 'reserved'}:
        raise HTTPException(409, 'Package is no longer ready for shipment')
    if package.sales_order_id and package.sales_order_id != shipment.sales_order_id:
        raise HTTPException(409, 'Package belongs to another sales order')
    link = db.query(ShipmentPackage).filter_by(shipment_id=shipment.id, package_id=package.id).first()
    if link is not None:
        return link
    quantities = available_claims(db, [package], shipment.id)[package.id]
    if sum(quantities.values()) <= 0:
        raise HTTPException(409, "No unallocated pieces remain in this package")
    return save_package_claim(db, shipment, package.id, quantities, None)


def claimed_quantity(db: Session, shipment: Shipment, package: Package) -> int:
    link = db.query(ShipmentPackage.quantity).filter_by(shipment_id=shipment.id, package_id=package.id).first()
    return link[0] if link else sum(available_claims(db, [package], shipment.id)[package.id].values())


def replace_claim(db: Session, shipment: Shipment, link: ShipmentPackage, package: Package) -> None:
    quantities = available_claims(db, [package], shipment.id)[package.id]
    if not sum(quantities.values()):
        raise HTTPException(409, "No unallocated pieces remain in this package")
    replace_package_claim(db, shipment, link, package.id, quantities)
