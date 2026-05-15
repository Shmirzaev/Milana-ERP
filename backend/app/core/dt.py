"""Datetime helpers — most importantly, a tz coercion utility.

SQLite (used in tests) and some legacy Postgres data return tz-naive datetimes
even when the column is declared TIMESTAMPTZ. Comparing those against a
tz-aware `datetime.now(timezone.utc)` raises:

    TypeError: can't compare offset-naive and offset-aware datetimes

This module gives us one source of truth for normalising every datetime to
tz-aware UTC before any comparison or serialisation.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional


def as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Return a tz-aware UTC datetime, or None if input is None."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def utcnow() -> datetime:
    """Tz-aware current time in UTC."""
    return datetime.now(timezone.utc)
