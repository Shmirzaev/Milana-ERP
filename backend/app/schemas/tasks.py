from datetime import datetime
import re
from typing import Annotated, Literal, Optional
from pydantic import AfterValidator, BaseModel, Field, field_validator, model_validator

from app.schemas.common import ORMModel


TaskStatus = Literal["pending", "in_progress", "completed", "cancelled"]
TaskPriority = Literal["low", "medium", "high", "urgent"]
_TASK_ENTITY_TYPES = (
    "salesorder", "productionorder", "workorder", "bundle", "package", "shipment", "invoice",
)

_TASK_ENTITY_TYPE_ALIASES = {
    **{value: value for value in _TASK_ENTITY_TYPES},
    "salesorders": "salesorder",
    "productionorders": "productionorder",
    "workorders": "workorder",
    "bundles": "bundle",
    "packages": "package",
    "shipments": "shipment",
    "invoices": "invoice",
}


def normalize_task_entity_type(value: str) -> str:
    token = value.strip().casefold()
    if re.fullmatch(r"[a-z0-9_]+", token):
        compact = token.replace("_", "")
    elif re.fullmatch(r"[a-z0-9]+(?:[ -]+[a-z0-9]+)*", token):
        compact = re.sub(r"[ -]+", "", token)
    else:
        return token
    return _TASK_ENTITY_TYPE_ALIASES.get(compact, compact)


def validate_task_entity_type(value: str) -> str:
    if normalize_task_entity_type(value) not in _TASK_ENTITY_TYPES:
        raise ValueError("entity_type must be a supported task target type")
    return value


TaskEntityType = Annotated[str, AfterValidator(validate_task_entity_type)]


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
    status: TaskStatus = "pending"
    priority: TaskPriority = "medium"
    due_date: Optional[datetime] = None
    entity_type: Optional[TaskEntityType] = Field(default=None, min_length=1, max_length=64)
    entity_id: Optional[int] = Field(default=None, gt=0, le=2_147_483_647)

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("title must not be blank")
        return value

    @field_validator("entity_type", mode="before")
    @classmethod
    def normalize_entity_type(cls, value):
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("entity_type must be a supported target type")
        if not value.strip():
            raise ValueError("entity_type must not be blank")
        return value

    _validate_due_date = field_validator("due_date", mode="before")(_reject_numeric_datetime)

    @model_validator(mode="after")
    def validate_reference_pair(self):
        if (self.entity_id is None) != (self.entity_type is None):
            raise ValueError("entity_id and entity_type must be provided together")
        return self


class TaskUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    assigned_to: Optional[int] = None
    status: Optional[TaskStatus] = None
    priority: Optional[TaskPriority] = None
    due_date: Optional[datetime] = None
    entity_type: Optional[TaskEntityType] = Field(default=None, min_length=1, max_length=64)
    entity_id: Optional[int] = Field(default=None, gt=0, le=2_147_483_647)

    @field_validator("title", "status", "priority", mode="before")
    @classmethod
    def reject_explicit_null(cls, value):
        if value is None:
            raise ValueError("field cannot be null when provided")
        return value

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("title must not be blank")
        return value

    @field_validator("entity_type", mode="before")
    @classmethod
    def normalize_entity_type(cls, value):
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("entity_type must be a supported target type")
        if not value.strip():
            raise ValueError("entity_type must not be blank")
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


class TaskPageOut(BaseModel):
    rows: list[TaskOut]
    total: int
    page: int
    page_size: int
    has_more: bool


class NotificationOut(ORMModel):
    id: int
    user_id: int
    title: str
    message: Optional[str] = None
    link: Optional[str] = None
    is_read: bool
    created_at: datetime
