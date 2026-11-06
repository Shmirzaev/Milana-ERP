"""Task vocabularies documented by the mapping and used by the task UI.

Adopted by the system stock-shortage write; general Task CRUD/input migration and
historical-value reconciliation remain separate work. No storage constraint added.
"""
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
