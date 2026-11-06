from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, JSON, Text, event, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PkMixin


class PackageQuantityAdjustment(Base, PkMixin):
    __tablename__ = "package_quantity_adjustments"
    __table_args__ = (CheckConstraint("extra_receipt_quantity >= 0", name="ck_package_quantity_extra_receipt_nonnegative"),)
    package_id: Mapped[int] = mapped_column(ForeignKey("packages.id"), nullable=False, index=True)
    shipment_id: Mapped[int] = mapped_column(ForeignKey("shipments.id"), nullable=False, index=True)
    delta: Mapped[int] = mapped_column(Integer, nullable=False)
    before_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    after_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    extra_receipt_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


@event.listens_for(PackageQuantityAdjustment, "before_update")
@event.listens_for(PackageQuantityAdjustment, "before_delete")
def immutable_quantity_evidence(mapper, connection, target):
    raise ValueError("Package quantity adjustment evidence is immutable")
