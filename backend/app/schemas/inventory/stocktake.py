from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, Query, Session, mapped_column

from app.db.base import Base, PkMixin, TimestampMixin


class WarehouseStocktake(Base, PkMixin, TimestampMixin):
    __tablename__ = "warehouse_stocktakes"

    request_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WarehouseStocktakeRow(Base, PkMixin):
    __tablename__ = "warehouse_stocktake_rows"
    __table_args__ = (UniqueConstraint("stocktake_id", "identity", name="uq_stocktake_identity"),)

    stocktake_id: Mapped[int] = mapped_column(ForeignKey("warehouse_stocktakes.id"), index=True)
    identity: Mapped[str] = mapped_column(String(80), nullable=False)
    # Snapshot references deliberately survive later package deletion.
    package_id: Mapped[int | None] = mapped_column(Integer, index=True)
    expected: Mapped[bool] = mapped_column(Boolean, nullable=False)
    category: Mapped[str] = mapped_column(String(24), nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    final_snapshot: Mapped[dict | None] = mapped_column(JSON)
    # First-scan evidence is independent of count-start and completion snapshots.
    scan_snapshot: Mapped[dict | None] = mapped_column(JSON)
    scan_code: Mapped[str | None] = mapped_column(String(512))
    scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scanned_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


def add_stocktake(db: Session, *, request_key: str, title: str, created_by: int) -> WarehouseStocktake:
    """Add the count to the caller's session; the service controls flushing."""
    count = WarehouseStocktake(request_key=request_key, title=title, created_by=created_by)
    db.add(count)
    return count


def add_expected_stocktake_row(db: Session, *, stocktake_id: int, package_id: int, snapshot: dict) -> None:
    """Record one count-start snapshot in the caller's session."""
    db.add(WarehouseStocktakeRow(
        stocktake_id=stocktake_id, identity=f"package:{package_id}",
        package_id=package_id, expected=True, category="expected", snapshot=snapshot,
    ))


def delete_stocktake(db: Session, count: WarehouseStocktake, rows: Query) -> None:
    """Delete a locked count and its rows in the caller's transaction."""
    rows.delete(synchronize_session=False)
    db.delete(count)


def freeze_stocktake_completion(
    db: Session, count: WarehouseStocktake, rows: list[WarehouseStocktakeRow],
    snapshots: dict, completed_at: datetime,
) -> None:
    """Apply completion evidence in the caller's existing transaction."""
    for row in rows:
        row.final_snapshot = snapshots.get(row.package_id, {})
    count.completed_at = completed_at


def remove_recorded_scan(db, row: WarehouseStocktakeRow) -> None:
    """Apply an already-authorized undo in the caller's transaction."""
    if row.expected:
        row.scan_code = row.scanned_at = row.scanned_by = None
        row.scan_snapshot = None
    else:
        db.delete(row)
