"""Canonical fixed vocabularies owned by People and Payroll."""

from enum import Enum


class PayrollAdjustmentType(str, Enum):
    """Persisted payroll adjustment categories; values remain database/API strings."""

    BONUS = "bonus"
    DEDUCTION = "deduction"
