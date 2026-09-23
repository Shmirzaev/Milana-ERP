from datetime import datetime, timezone

import pytest

from app.services.payroll_reports import salary_report_days


def test_salary_report_days_uses_observed_bounds_not_row_order_or_duplicates():
    rows = [
        {"daily_amounts": {"2026-09-12": 2, "2026-09-10": 1}},
        {"daily_amounts": {"2026-09-11": 3, "2026-09-10": 4}},
    ]

    assert salary_report_days(rows, None, None) == [
        "2026-09-10",
        "2026-09-11",
        "2026-09-12",
    ]


def test_salary_report_days_preserves_explicit_bounds_and_empty_input():
    rows = [{"daily_amounts": {"2026-09-12": 2}}]
    date_from = datetime(2026, 9, 10, tzinfo=timezone.utc)
    date_to = datetime(2026, 9, 11, tzinfo=timezone.utc)

    assert salary_report_days(rows, date_from, date_to) == [
        "2026-09-10",
        "2026-09-11",
    ]
    assert salary_report_days([], None, None) == []


def test_salary_report_days_preserves_invalid_observed_date_error():
    with pytest.raises(ValueError):
        salary_report_days([{"daily_amounts": {"": 1}}], None, None)
