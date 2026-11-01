from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, field_validator, model_validator

from app.libs.dto.common import ORMModel
from app.libs.enums.work_management import TaskPriority, TaskStatus


def _reject_numeric_datetime(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        raise ValueError("date must be an ISO date or datetime")
    if isinstance(value, str):
        try:
            float(value.strip())
        except ValueError:
            pass
        else:
            raise ValueError("date must be an ISO date or datetime")
    return value


class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None
    assigned_to: Optional[int] = None
    status: TaskStatus = TaskStatus.PENDING
    priority: TaskPriority = TaskPriority.MEDIUM
    due_date: Optional[datetime] = None
    entity_type: Optional[str] = Field(default=None, min_length=1, max_length=64)
    entity_id: Optional[int] = Field(default=None, gt=0)

    @field_validator("title", "entity_type")
    @classmethod
    def nonblank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("field must not be blank")
        return value

    _validate_due_date = field_validator("due_date", mode="before")(_reject_numeric_datetime)

    @model_validator(mode="after")
    def reference_pair(self):
        if (self.entity_type is None) != (self.entity_id is None):
            raise ValueError("entity_type and entity_id must be provided together")
        return self


class TaskUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    assigned_to: Optional[int] = None
    status: Optional[TaskStatus] = None
    priority: Optional[TaskPriority] = None
    due_date: Optional[datetime] = None
    entity_type: Optional[str] = Field(default=None, min_length=1, max_length=64)
    entity_id: Optional[int] = Field(default=None, gt=0)

    @field_validator("title", "status", "priority", mode="before")
    @classmethod
    def required_when_sent(cls, value):
        if value is None:
            raise ValueError("field cannot be null when provided")
        return value

    @field_validator("title", "entity_type")
    @classmethod
    def nonblank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("field must not be blank")
        return value

    _validate_due_date = field_validator("due_date", mode="before")(_reject_numeric_datetime)


class TaskOut(ORMModel):
    id: int
    title: str
    description: Optional[str] = None
    assigned_to: Optional[int] = None
    created_by: Optional[int] = None
    status: str
    priority: str
    due_date: Optional[datetime] = None
    entity_type: Optional[str] = None
    entity_id: Optional[int] = None
    completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class NotificationOut(ORMModel):
    id: int
    user_id: int
    title: str
    message: Optional[str] = None
    link: Optional[str] = None
    is_read: bool
    created_at: datetime
