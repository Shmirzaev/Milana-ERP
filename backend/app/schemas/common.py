from typing import Generic, TypeVar, Optional
from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class SchemaModel(BaseModel):
    model_config = ConfigDict(protected_namespaces=())


class ORMModel(SchemaModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int = 1
    page_size: int = 50


class MessageOut(SchemaModel):
    message: str
    detail: Optional[str] = None
