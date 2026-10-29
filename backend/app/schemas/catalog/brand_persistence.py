"""Brand persistence within the caller's transaction."""

from sqlalchemy.orm import Session

from app.libs.types.catalog import BrandUpdateCommand
from app.schemas.catalog.catalog import Brand


def insert_brand(
    db: Session, *, name: str, description: str | None, logo_url: str | None, is_active: bool
) -> Brand:
    """Insert and flush for the generated ID; the caller owns commit and audit."""
    brand = Brand(name=name, description=description, logo_url=logo_url, is_active=is_active)
    db.add(brand)
    db.flush()
    return brand


def apply_brand_update(db: Session, brand: Brand, fields: BrandUpdateCommand) -> None:
    """Apply the validated supplied fields; the caller owns audit and commit."""
    brand.name = fields["name"]
    if "description" in fields:
        brand.description = fields["description"]
    if "logo_url" in fields:
        brand.logo_url = fields["logo_url"]
    if "is_active" in fields:
        brand.is_active = fields["is_active"]
