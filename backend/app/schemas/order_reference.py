from sqlalchemy import String, Integer, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, Session, mapped_column

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

    @classmethod
    def reserve_bundle_reference(cls, db: Session, reference: str) -> None:
        db.add(cls(namespace="BND", entity_id=0, reference=reference, canonical_reference=reference))
        db.flush()

    @classmethod
    def reserve_bundle_references(cls, db: Session, references: list[str]) -> None:
        db.add_all([
            cls(namespace="BND", entity_id=0, reference=reference, canonical_reference=reference)
            for reference in references
        ])
        db.flush()

    @classmethod
    def link_reserved_bundle_reference(cls, db: Session, reference: str, bundle_id: int) -> None:
        db.query(cls).filter(
            cls.namespace == "BND", cls.reference == reference, cls.entity_id == 0,
        ).update({cls.entity_id: bundle_id}, synchronize_session=False)
