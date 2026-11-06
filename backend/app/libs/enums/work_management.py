"""Canonical task values and resolved reference kinds; storage stays unchanged."""
from enum import Enum


class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TaskPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class TaskReferenceKind(str, Enum):
    SALES_ORDER = "salesorder"
    PRODUCTION_ORDER = "productionorder"
    WORK_ORDER = "workorder"
    BUNDLE = "bundle"
    PACKAGE = "package"
    SHIPMENT = "shipment"
    INVOICE = "invoice"
