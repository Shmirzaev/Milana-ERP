from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select

from app.libs.dto.ceo_dashboard.report import BalanceValues, WarehouseBalance
from app.libs.enums.ceo_dashboard import BalanceStatus, FactoryFilter, ReportGrouping
from app.models import ceo_dashboard_service as reporting, ceo_dashboard_snapshot_service as recorder
from app.schemas.fulfillment.ceo_balance_snapshot import CeoBalanceSnapshot
from app.tests.conftest import TestSessionLocal


def utc(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "grouping,expected",
    [
        (ReportGrouping.WEEKLY, [(25, 25), (26, 1), (2, 4)]),
        (ReportGrouping.MONTHLY, [(25, 31), (1, 4)]),
    ],
)
def test_report_groups_clip_at_selected_dates_and_today(grouping, expected):
    now = utc("2026-11-04T07:30:00")
    window = reporting.report_window(
        date(2026, 10, 25), date(2026, 11, 4), grouping, FactoryFilter.ALL, now=now,
    )
    assert window.lower == utc("2026-10-24T19:00:00")
    assert window.upper == now
    assert [(point.start.day, point.end.day) for point in window.buckets] == expected


def test_tashkent_today_and_historical_exclusive_upper_bound():
    now = utc("2026-11-04T19:01:00")
    window = reporting.report_window(
        date(2026, 11, 4), date(2026, 11, 4), ReportGrouping.DAILY, FactoryFilter.ALL, now=now,
    )
    assert window.upper == utc("2026-11-04T19:00:00")
    with pytest.raises(ValueError, match="after today"):
        reporting.report_window(
            date(2026, 11, 6), date(2026, 11, 6), ReportGrouping.DAILY, FactoryFilter.ALL, now=now,
        )


def test_snapshot_only_uses_close_and_never_fills_missing_history(monkeypatch):
    def read_fixture(db, as_of, factory):
        pieces = 10 if factory == FactoryFilter.ECO else 30
        return BalanceValues(
            waiting=[], warehouse=WarehouseBalance(packs=1, pieces=pieces, available_pieces=pieces),
            materials=[], material_totals=[],
        )

    monkeypatch.setattr(recorder, "read_live_balances", read_fixture)
    monkeypatch.setattr(reporting, "read_live_balances", read_fixture)
    with TestSessionLocal() as db:
        assert not recorder.capture_closing_balances(db, utc("2026-11-04T18:58:59"))
        assert recorder.capture_closing_balances(db, utc("2026-11-04T18:59:05"))
        db.flush()
        assert not recorder.capture_closing_balances(db, utc("2026-11-04T18:59:57"))
        snapshots = list(db.scalars(select(CeoBalanceSnapshot)))
        assert len(snapshots) == 4
        window = reporting.report_window(
            date(2026, 11, 3), date(2026, 11, 5), ReportGrouping.DAILY, FactoryFilter.ECO,
            now=utc("2026-11-05T02:00:00"),
        )
        missing, recorded, live = reporting.balance_points(db, window)
        assert missing.status == BalanceStatus.UNAVAILABLE and missing.values is None
        assert recorded.status == BalanceStatus.SNAPSHOT and recorded.values.warehouse.pieces == 10
        assert recorded.as_of == utc("2026-11-04T18:59:05")
        assert live.status == BalanceStatus.CURRENT and live.as_of == window.as_of
        db.rollback()
