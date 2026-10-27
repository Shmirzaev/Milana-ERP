"""Warehouse creation is a subset of the source-recognized vocabulary."""
from typing import Annotated, Any

from pydantic import BeforeValidator, WithJsonSchema
from pydantic_core import PydanticCustomError

from app.libs.enums.inventory import WarehouseType

WAREHOUSE_CREATE_TYPES = (
    WarehouseType.FABRIC_STORAGE,
    WarehouseType.ACCESSORY_STORAGE,
    WarehouseType.PACKAGING,
    WarehouseType.CUTTING,
    WarehouseType.ECO_COTTON_CUTTING,
    WarehouseType.PRINTING,
    WarehouseType.SEWING,
    WarehouseType.BESTTEX_PACKAGING,
    WarehouseType.ECO_COTTON_PACKAGING,
    WarehouseType.FINISHED_GOODS,
    WarehouseType.WASTE,
)

_CREATE_VALUES = tuple(member.value for member in WAREHOUSE_CREATE_TYPES)
_MEMBER_BY_VALUE = {member.value: member for member in WarehouseType}
# The refusal names exactly the values this action accepts, so the error and the
# published subset cannot drift apart and offer a value the API then refuses.
_EXPECTED = "{}, or {}".format(
    ", ".join(repr(value) for value in _CREATE_VALUES[:-1]), repr(_CREATE_VALUES[-1])
)


def require_creatable_warehouse_type(value: Any) -> WarehouseType:
    """Return the canonical member for an accepted value, else refuse.

    A canonical member outside the creation subset keeps its own refusal. Any
    other value is refused with the accepted subset, never with the wider
    source-recognized vocabulary.
    """
    if isinstance(value, WarehouseType):
        if value in WAREHOUSE_CREATE_TYPES:
            return value
        raise ValueError("Warehouse type is not permitted for creation")
    if isinstance(value, str):
        member = _MEMBER_BY_VALUE.get(value)
        if member is not None:
            if member in WAREHOUSE_CREATE_TYPES:
                return member
            raise ValueError("Warehouse type is not permitted for creation")
    raise PydanticCustomError("enum", "Input should be {expected}", {"expected": _EXPECTED})


# Runtime values are canonical enum members, while OpenAPI truthfully describes
# this action's eleven accepted values rather than the full legacy vocabulary.
WarehouseCreateType = Annotated[
    WarehouseType,
    BeforeValidator(require_creatable_warehouse_type),
    WithJsonSchema({"type": "string", "enum": [value.value for value in WAREHOUSE_CREATE_TYPES]}),
]
