from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, Integer, JSON, String
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.db.base import Base
from app.libs.enums.ceo_dashboard import FactoryFilter


SNAPSHOT_VERSION = 1
_FACTORY_VALUES = ", ".join(repr(factory.value) for factory in FactoryFilter)


class CeoBalanceSnapshot(Base):
    __tablename__ = "ceo_balance_snapshots"
    __table_args__ = (
        CheckConstraint(f"factory IN ({_FACTORY_VALUES})", name="ck_ceo_snapshot_factory"),
        CheckConstraint("schema_version > 0", name="ck_ceo_snapshot_version"),
    )

    business_date: Mapped[date] = mapped_column(Date, primary_key=True)
    factory: Mapped[str] = mapped_column(String(3), primary_key=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)


def add_snapshot(
    db: Session, business_date: date, factory: FactoryFilter, captured_at: datetime, payload: dict,
) -> None:
    db.add(CeoBalanceSnapshot(
        business_date=business_date,
        factory=factory.value,
        captured_at=captured_at,
        schema_version=SNAPSHOT_VERSION,
        payload=payload,
    ))
