from typing import Optional

from pydantic import BaseModel


class ModelImageIn(BaseModel):
    file_url: str
    file_name: Optional[str] = None
    content_type: Optional[str] = None
    image_type: Optional[str] = None
    is_primary: bool = False
