"""Brand creation persistence within the caller's transaction."""

from sqlalchemy.orm import Session

from app.schemas.catalog.catalog import Brand


def insert_brand(
    db: Session, *, name: str, description: str | None, logo_url: str | None, is_active: bool
) -> Brand:
    """Insert and flush for the generated ID; the caller owns commit and audit."""
    brand = Brand(name=name, description=description, logo_url=logo_url, is_active=is_active)
    db.add(brand)
    db.flush()
    return brand
