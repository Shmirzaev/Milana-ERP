from datetime import datetime
from typing import Optional
from pydantic import BaseModel

from app.schemas.common import ORMModel


class TaskIn(BaseModel):
    title: str
    description: Optional[str] = None
    assigned_to: Optional[int] = None
    status: str = "pending"
    priority: str = "medium"
    due_date: Optional[datetime] = None
    entity_type: Optional[str] = None
    entity_id: Optional[int] = None


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    assigned_to: Optional[int] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    due_date: Optional[datetime] = None
    entity_type: Optional[str] = None
    entity_id: Optional[int] = None


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
    is_read: bool
    created_at: datetime
