"""Mapped writes for one shipment's claim; caller owns locks and transaction."""
from sqlalchemy.orm import Session

from app.schemas.sales.sales import Shipment, ShipmentPackage


def save_package_claim(db: Session, shipment: Shipment, package_id: int,
                       quantities: dict[str, int], link: ShipmentPackage | None) -> ShipmentPackage:
    selections = {**(shipment.dispatch_snapshot or {}).get("package_quantities", {}),
                  str(package_id): dict(quantities)}
    shipment.dispatch_snapshot = {**(shipment.dispatch_snapshot or {}), "package_quantities": selections}
    if link is None:
        link = ShipmentPackage(shipment_id=shipment.id, package_id=package_id, quantity=sum(quantities.values()))
        db.add(link)
    else:
        link.quantity = sum(quantities.values())
    db.flush()
    db.expire(shipment, ["packages"])
    return link


def replace_package_claim(db: Session, shipment: Shipment, link: ShipmentPackage,
                          package_id: int, quantities: dict[str, int]) -> ShipmentPackage:
    selections = dict((shipment.dispatch_snapshot or {}).get("package_quantities", {}))
    selections.pop(str(link.package_id), None)
    shipment.dispatch_snapshot = {**(shipment.dispatch_snapshot or {}), "package_quantities": selections}
    link.package_id = package_id
    return save_package_claim(db, shipment, package_id, quantities, link)
