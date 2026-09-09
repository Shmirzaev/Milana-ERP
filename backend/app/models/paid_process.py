from sqlalchemy import String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PkMixin, TimestampMixin


class PaidProcess(Base, PkMixin, TimestampMixin):
    __tablename__ = "paid_processes"
    __table_args__ = (UniqueConstraint("factory_code", "normalized_key", "section", name="uq_paid_process_identity"),)
    factory_code: Mapped[str] = mapped_column(String(3), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_key: Mapped[str] = mapped_column(String(64), nullable=False)
    section: Mapped[str] = mapped_column(String(32), nullable=False)
