from datetime import datetime, time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.libs.enums.ceo_dashboard import FactoryFilter
from app.models.ceo_dashboard_balance_service import read_live_balances
from app.models.ceo_dashboard_service import BUSINESS_ZONE
from app.schemas.fulfillment.ceo_balance_snapshot import CeoBalanceSnapshot, add_snapshot


def capture_closing_balances(db: Session, captured_at: datetime) -> bool:
    """Collect all four views together from the same database snapshot."""
    local = captured_at.astimezone(BUSINESS_ZONE)
    if local.time() < time(23, 59):
        return False
    business_date = local.date()
    existing = db.scalars(select(CeoBalanceSnapshot.factory).where(
        CeoBalanceSnapshot.business_date == business_date,
    )).all()
    if set(existing) == {factory.value for factory in FactoryFilter}:
        return False
    if existing:
        raise RuntimeError("Incomplete CEO balance history for the business day")
    for factory in FactoryFilter:
        balances = read_live_balances(db, captured_at, factory)
        add_snapshot(db, business_date, factory, captured_at, balances.model_dump(mode="json"))
    return True
