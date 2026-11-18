from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.dt import as_utc
from app.libs.dto.ceo_dashboard.report import BalancePoint, BalanceValues, DashboardReport, DateBucket, ReportWindow
from app.libs.enums.ceo_dashboard import BalanceStatus, FactoryFilter, ReportGrouping
from app.models.ceo_dashboard_activity_service import read_activity
from app.models.ceo_dashboard_balance_service import read_live_balances
from app.schemas.fulfillment.ceo_balance_snapshot import CeoBalanceSnapshot, SNAPSHOT_VERSION


BUSINESS_ZONE = ZoneInfo("Asia/Tashkent")
MAX_REPORT_DAYS = 366


def _bucket_end(day: date, grouping: ReportGrouping) -> date:
    if grouping == ReportGrouping.WEEKLY:
        return day + timedelta(days=6 - day.weekday())
    if grouping == ReportGrouping.MONTHLY:
        next_month = (day.replace(day=28) + timedelta(days=4)).replace(day=1)
        return next_month - timedelta(days=1)
    return day


def report_window(
    start: date,
    end: date,
    grouping: ReportGrouping,
    factory: FactoryFilter,
    *,
    now: datetime,
) -> ReportWindow:
    today = now.astimezone(BUSINESS_ZONE).date()
    if end < start or (end - start).days >= MAX_REPORT_DAYS:
        raise ValueError("Choose an ordered date range of at most 366 days.")
    if end > today:
        raise ValueError("The range cannot end after today in Asia/Tashkent.")
    buckets: list[DateBucket] = []
    day = start
    while day <= end:
        last = min(_bucket_end(day, grouping), end)
        buckets.append(DateBucket(start=day, end=last))
        day = last + timedelta(days=1)
    return ReportWindow(
        start=start,
        end=end,
        lower=datetime.combine(start, time.min, BUSINESS_ZONE).astimezone(timezone.utc),
        upper=min(now, datetime.combine(day, time.min, BUSINESS_ZONE).astimezone(timezone.utc)),
        as_of=now,
        factory=factory,
        grouping=grouping,
        buckets=tuple(buckets),
    )


def balance_points(db: Session, window: ReportWindow) -> list[BalancePoint]:
    today = window.as_of.astimezone(BUSINESS_ZONE).date()
    requested = [bucket.end for bucket in window.buckets if bucket.end < today]
    snapshots = {}
    if requested:
        statement = select(CeoBalanceSnapshot).where(
            CeoBalanceSnapshot.business_date.in_(requested),
            CeoBalanceSnapshot.factory == window.factory.value,
            CeoBalanceSnapshot.schema_version == SNAPSHOT_VERSION,
        )
        snapshots = {row.business_date: row for row in db.scalars(statement)}
    points: list[BalancePoint] = []
    for bucket in window.buckets:
        snapshot = snapshots.get(bucket.end)
        if bucket.end == today:
            point = BalancePoint(
                **bucket.model_dump(),
                status=BalanceStatus.CURRENT,
                as_of=window.as_of,
                values=read_live_balances(db, window.as_of, window.factory),
            )
        elif snapshot is not None:
            point = BalancePoint(
                **bucket.model_dump(),
                status=BalanceStatus.SNAPSHOT,
                as_of=as_utc(snapshot.captured_at),
                values=BalanceValues.model_validate(snapshot.payload),
            )
        else:
            point = BalancePoint(**bucket.model_dump(), status=BalanceStatus.UNAVAILABLE)
        points.append(point)
    return points


def read_dashboard(db: Session, window: ReportWindow) -> DashboardReport:
    return DashboardReport(
        start=window.start,
        end=window.end,
        grouping=window.grouping,
        factory=window.factory,
        timezone=BUSINESS_ZONE.key,
        updated_at=window.as_of,
        activity=read_activity(db, window),
        balances=balance_points(db, window),
    )


def read_dashboard_for_range(
    db: Session, start: date, end: date, grouping: ReportGrouping, factory: FactoryFilter,
) -> DashboardReport:
    now = (
        db.scalar(select(func.transaction_timestamp()))
        if db.get_bind().dialect.name == "postgresql"
        else datetime.now(timezone.utc)
    )
    return read_dashboard(db, report_window(start, end, grouping, factory, now=now))
