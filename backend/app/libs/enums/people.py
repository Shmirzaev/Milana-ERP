"""Stored People vocabularies already bounded by database CHECK constraints."""

from enum import Enum


class PayrollPeriodStatus(str, Enum):
    DRAFT = "draft"
    OPEN = "open"
    LOCKED = "locked"
    APPROVED = "approved"
    PAID = "paid"
    CANCELLED = "cancelled"


class PayrollRecordStatus(str, Enum):
    RECORDED = "recorded"
    VOIDED = "voided"
    APPROVED = "approved"
    PAID = "paid"


class PayrollQrLabelStatus(str, Enum):
    AVAILABLE = "available"
    SCANNED = "scanned"
    SUPERSEDED = "superseded"
    CLOSED = "closed"


class PayrollAdjustmentType(str, Enum):
    BONUS = "bonus"
    DEDUCTION = "deduction"
