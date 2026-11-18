"""Run at 23:59 Asia/Tashkent to record an immutable closing balance sample."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models.ceo_dashboard_snapshot_service import capture_closing_balances


def main() -> None:
    if engine.dialect.name != "postgresql":
        raise RuntimeError("The balance capture job requires PostgreSQL")
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection:
        with Session(bind=connection, autoflush=False) as db, db.begin():
            captured_at = db.scalar(select(func.transaction_timestamp()))
            if captured_at is None:
                raise RuntimeError("Could not read the database transaction timestamp")
            captured = capture_closing_balances(db, captured_at)
    print("CEO balance snapshot recorded." if captured else "No CEO balance snapshot recorded.")


if __name__ == "__main__":
    main()
