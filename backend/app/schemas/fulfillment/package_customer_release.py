"""Explicit admin release; source order and package identities stay untouched."""
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, JSON, String, func
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.db.base import Base


class PackageCustomerRelease(Base):
    __tablename__ = "package_customer_releases"
    __table_args__ = (CheckConstraint("released_quantity > 0", name="ck_package_customer_release_quantity"),)

    package_id: Mapped[int] = mapped_column(ForeignKey("packages.id", ondelete="CASCADE"), primary_key=True)
    source_order_ids: Mapped[list[int]] = mapped_column(JSON, nullable=False)
    released_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    released_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    released_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)


def save_customer_release(db: Session, *, package_id: int, source_order_ids: list[int],
                          quantity: int, actor_id: int, released_at: datetime, reason: str) -> None:
    """Caller already holds the package lock; participate without committing."""
    row = db.get(PackageCustomerRelease, package_id)
    if row is None:
        row = PackageCustomerRelease(package_id=package_id)
        db.add(row)
    row.source_order_ids = source_order_ids
    row.released_quantity = quantity
    row.released_by = actor_id
    row.released_at = released_at
    row.reason = reason
