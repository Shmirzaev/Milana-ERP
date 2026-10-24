from decimal import Decimal
from typing import Annotated, Generic, TypeVar, Optional
from pydantic import BaseModel, BeforeValidator, ConfigDict

from app.core.costs import validate_unit_cost

StoredUnitCost = Annotated[Decimal, BeforeValidator(validate_unit_cost)]

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
