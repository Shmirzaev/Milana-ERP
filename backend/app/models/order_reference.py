from sqlalchemy import String, Integer, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PkMixin, TimestampMixin


class BusinessOrderAlias(Base, PkMixin, TimestampMixin):
    """Historical references resolve to existing records without changing their IDs."""
    __tablename__ = "business_order_aliases"
    __table_args__ = (
        UniqueConstraint("namespace", "reference", name="uq_business_order_alias_reference"),
        Index("ix_business_order_alias_entity", "namespace", "entity_id"),
    )
    namespace: Mapped[str] = mapped_column(String(16), nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    reference: Mapped[str] = mapped_column(String(128), nullable=False)
    canonical_reference: Mapped[str] = mapped_column(String(64), nullable=False)
