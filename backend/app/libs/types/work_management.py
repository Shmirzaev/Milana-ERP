"""Internal task command contracts shared by Work Management layers."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app.libs.enums.work_management import TaskPriority, TaskStatus


TaskUpdateField = Literal[
    "title",
    "description",
    "assigned_to",
    "status",
    "priority",
    "due_date",
    "entity_type",
    "entity_id",
]


@dataclass(frozen=True)
class TaskUpdateCommand:
    """Typed PATCH values plus explicit presence, preserving omitted/null."""

    present_fields: frozenset[TaskUpdateField]
    title: str | None
    description: str | None
    assigned_to: int | None
    status: TaskStatus | None
    priority: TaskPriority | None
    due_date: datetime | None
    entity_type: str | None
    entity_id: int | None


@dataclass(frozen=True)
class TaskCompletionTimestampChange:
    """Whether Task PATCH changes completed_at, and its nullable target."""

    should_write: bool
    value: datetime | None = None
