from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class SearchArgs(BaseModel):
    query: str = Field(min_length=1, max_length=200)
    limit_per_type: int = Field(default=5, ge=1, le=25)

    @field_validator("query")
    @classmethod
    def strip_query(cls, value: str) -> str:
        return value.strip()


class ActiveProductionArgs(BaseModel):
    limit: int = Field(default=25, ge=1, le=100)


class TaskListArgs(BaseModel):
    employee: str | None = Field(default=None, max_length=128)
    department: str | None = Field(default=None, max_length=64)
    status: str | None = Field(default=None, max_length=32)
    date_from: datetime | None = None
    date_to: datetime | None = None
    scope: Literal["mine", "created", "all"] = "all"

    @model_validator(mode="after")
    def validate_dates(self) -> "TaskListArgs":
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from must be before date_to")
        return self


class NotificationArgs(BaseModel):
    target_type: Literal["user_id", "department", "safe_group"]
    user_id: int | None = Field(default=None, ge=1)
    department: str | None = Field(default=None, min_length=1, max_length=64)
    safe_group: Literal["management", "admins"] | None = None
    title: str = Field(min_length=1, max_length=255)
    message: str | None = Field(default=None, max_length=2000)
    link: str | None = Field(default=None, max_length=512)
    entity_type: str | None = Field(default=None, max_length=64)
    entity_id: int | None = Field(default=None, ge=1)
    confirm: bool = False

    @model_validator(mode="after")
    def validate_target(self) -> "NotificationArgs":
        if self.target_type == "user_id" and self.user_id is None:
            raise ValueError("user_id is required for target_type=user_id")
        if self.target_type == "department" and not (self.department or "").strip():
            raise ValueError("department is required for target_type=department")
        if self.target_type == "safe_group" and self.safe_group is None:
            raise ValueError("safe_group is required for target_type=safe_group")
        if self.link:
            link = self.link.strip()
            if not link.startswith("/") or link.startswith("//") or "\\" in link:
                raise ValueError("link must be a relative ERP path")
            self.link = link
        self.title = self.title.strip()
        self.message = self.message.strip() if self.message else None
        self.department = self.department.strip() if self.department else None
        return self


class TaskCreateArgs(BaseModel):
    assignee_user_id: int | None = Field(default=None, ge=1)
    department: str | None = Field(default=None, min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    priority: Literal["low", "medium", "high", "urgent"] = "medium"
    due_date: datetime | None = None
    entity_type: str | None = Field(default=None, max_length=64)
    entity_id: int | None = Field(default=None, ge=1)
    confirm: bool = False

    @model_validator(mode="after")
    def validate_assignee(self) -> "TaskCreateArgs":
        has_user = self.assignee_user_id is not None
        has_department = bool((self.department or "").strip())
        if has_user == has_department:
            raise ValueError("Provide exactly one of assignee_user_id or department")
        self.title = self.title.strip()
        self.description = self.description.strip() if self.description else None
        self.department = self.department.strip() if self.department else None
        return self
