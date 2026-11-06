"""Item image request contract."""

from typing import Optional

from pydantic import BaseModel


class ItemImageIn(BaseModel):
    image_url: Optional[str] = None
