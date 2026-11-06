from typing import Literal
from pydantic import BaseModel, Field


class NotificationSendIn(BaseModel):
    target_type: Literal["user_id", "department", "safe_group"]
    user_id: int | None = Field(default=None, ge=1)
    department: str | None = Field(default=None, min_length=1, max_length=64)
    safe_group: Literal["management", "admins"] | None = None
    title: str = Field(min_length=1, max_length=255)
    message: str | None = Field(default=None, max_length=2000)
    link: str | None = Field(default=None, max_length=512)
    entity_type: str | None = Field(default=None, max_length=64)
    entity_id: int | None = Field(default=None, ge=1)
