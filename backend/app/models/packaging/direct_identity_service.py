"""Validate operator recipes without treating the plan as actual size output."""
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.libs.dto.packaging.tracking import PackageIn
from app.schemas import ProductionOrder, ProductionOrderItem


def validate_direct_identities(db: Session, order: ProductionOrder, packages: list[PackageIn]) -> None:
    variants = db.query(ProductionOrderItem).filter_by(production_order_id=order.id).all()
    allowed = {(str(row.color or "").strip().casefold(), str(row.size or "").strip()) for row in variants}
    if not allowed:
        raise HTTPException(409, "Order color and size evidence is required for direct packaging")
    for package in packages:
        color = package.color.strip().casefold()
        if any((item.color.strip().casefold(), item.size.strip()) not in allowed
               or item.color.strip().casefold() != color for item in package.items):
            raise HTTPException(409, "Package color and size must match the production order")
