"""Stocktake vocabulary for new writes and supported request filters."""
from enum import Enum


class StocktakeCategory(str, Enum):
    EXPECTED = "expected"
    UNEXPECTED = "unexpected"
    UNKNOWN = "unknown"
    AMBIGUOUS = "ambiguous"


class StocktakeResult(str, Enum):
    FOUND = "found"
    MISSING = "missing"
    UNEXPECTED = "unexpected"
    UNKNOWN = "unknown"
    AMBIGUOUS = "ambiguous"


class StocktakeFilter(str, Enum):
    ALL = "all"
    SCANNED = "scanned"
    FOUND = "found"
    MISSING = "missing"
    UNKNOWN = "unknown"
    UNEXPECTED = "unexpected"
    AMBIGUOUS = "ambiguous"
    CHANGED = "changed"
