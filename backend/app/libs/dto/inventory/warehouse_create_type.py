"""Warehouse creation is a subset of the source-recognized vocabulary."""
from typing import Annotated

from pydantic import AfterValidator, WithJsonSchema

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


def require_creatable_warehouse_type(value: WarehouseType) -> WarehouseType:
    if value not in WAREHOUSE_CREATE_TYPES:
        raise ValueError("Warehouse type is not permitted for creation")
    return value


# Runtime values are canonical enum members, while OpenAPI truthfully describes
# this action's eleven accepted values rather than the full legacy vocabulary.
WarehouseCreateType = Annotated[
    WarehouseType,
    AfterValidator(require_creatable_warehouse_type),
    WithJsonSchema({"type": "string", "enum": [value.value for value in WAREHOUSE_CREATE_TYPES]}),
]
