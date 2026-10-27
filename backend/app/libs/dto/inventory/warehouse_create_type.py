"""Warehouse creation is a subset of the source-recognized vocabulary."""
from typing import Annotated, Any

from pydantic import AfterValidator, ValidationError, WithJsonSchema
from pydantic_core import PydanticCustomError, core_schema

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
# The refusal names exactly the values this action accepts, so the error and the
# published subset cannot drift apart and offer a value the API then refuses.
_EXPECTED = "{}, or {}".format(
    ", ".join(repr(value) for value in _CREATE_VALUES[:-1]), repr(_CREATE_VALUES[-1])
)


def warehouse_enum_refusal(value: Any, handler) -> WarehouseType:
    """Keep core enum conversion and translate only its enum refusal."""
    try:
        return handler(value)
    except ValidationError as exc:
        if all(error["type"] == "enum" for error in exc.errors()):
            raise PydanticCustomError("enum", "Input should be {expected}", {"expected": _EXPECTED}) from exc
        raise


class WarehouseEnumRefusal:
    @classmethod
    def __get_pydantic_core_schema__(cls, source, handler):
        enum_schema = handler(source)
        return core_schema.json_or_python_schema(
            json_schema=core_schema.custom_error_schema(
                enum_schema, custom_error_type="enum",
                custom_error_context={"expected": _EXPECTED},
            ),
            python_schema=core_schema.no_info_wrap_validator_function(
                warehouse_enum_refusal, enum_schema,
            ),
        )


def require_creatable_warehouse_type(value: WarehouseType) -> WarehouseType:
    if value not in WAREHOUSE_CREATE_TYPES:
        raise ValueError("Warehouse type is not permitted for creation")
    return value


# Runtime values are canonical enum members, while OpenAPI truthfully describes
# this action's eleven accepted values rather than the full legacy vocabulary.
WarehouseCreateType = Annotated[
    WarehouseType,
    WarehouseEnumRefusal,
    AfterValidator(require_creatable_warehouse_type),
    WithJsonSchema({"type": "string", "enum": [value.value for value in WAREHOUSE_CREATE_TYPES]}),
]
