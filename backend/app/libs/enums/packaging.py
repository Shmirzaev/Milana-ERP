"""Canonical stored package classification; service actions use explicit subsets."""
from enum import Enum


class PackageStockKind(str, Enum):
    STANDARD = "standard"
    FIRST_GRADE = "first_grade"
    SECOND_GRADE = "second_grade"
