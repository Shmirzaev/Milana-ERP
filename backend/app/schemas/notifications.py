from pydantic import BaseModel

from app.schemas.tasks import NotificationOut


class NotificationPageOut(BaseModel):
    rows: list[NotificationOut]
    total: int
    page: int
    page_size: int
    has_more: bool
