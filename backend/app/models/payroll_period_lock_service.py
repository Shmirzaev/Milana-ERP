"""Shared lock for period schedule changes and date-bound payroll corrections."""
from sqlalchemy import text
from sqlalchemy.orm import Session


def lock_period_schedule(db: Session, factory_code: str) -> None:
    # Empty date ranges need the same advisory lock as period create/update.
    # Always acquire before any period, label or record row locks.
    if db.get_bind().dialect.name == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(1297107635, hashtext(:resource))"),
            {"resource": f"payroll-periods:{factory_code}"},
        )
