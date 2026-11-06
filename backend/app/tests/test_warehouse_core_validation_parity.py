"""Creation-refusal wording must not replace Pydantic's enum validator."""
from enum import Enum
from typing import Annotated

import pytest
from pydantic import AfterValidator, TypeAdapter, ValidationError

from app.libs.dto.inventory.warehouse_create_type import (
    WAREHOUSE_CREATE_TYPES, WarehouseCreateType,
)
from app.libs.enums.inventory import WarehouseType


def legacy_subset(value):
    if value not in WAREHOUSE_CREATE_TYPES:
        raise ValueError("Warehouse type is not permitted for creation")
    return value


legacy = TypeAdapter(Annotated[WarehouseType, AfterValidator(legacy_subset)])
candidate = TypeAdapter(WarehouseCreateType)


class Foreign(str, Enum):
    WASTE = "waste"


@pytest.mark.parametrize("member", list(WarehouseType))
def test_every_known_member_keeps_its_creation_subset(member):
    if member in WAREHOUSE_CREATE_TYPES:
        assert candidate.validate_python(member, strict=True) is member
    else:
        with pytest.raises(ValidationError) as error:
            candidate.validate_python(member, strict=True)
        assert error.value.errors()[0]["type"] == "value_error"


@pytest.mark.parametrize("value", [
    "waste", b"waste", bytearray(b"waste"), Foreign.WASTE,
    WarehouseType.WASTE, "raw_material", WarehouseType.WAREHOUSE,
    "unknown", "", None, 4,
])
@pytest.mark.parametrize("strict", [False, True])
def test_python_validation_matches_core_legacy_behavior(value, strict):
    def outcome(adapter):
        try:
            result = adapter.validate_python(value, strict=strict)
            return ("accepted", result)
        except ValidationError as error:
            return ("refused", tuple(item["type"] for item in error.errors()))
    assert outcome(candidate) == outcome(legacy)


@pytest.mark.parametrize("value", ['"waste"', '"raw_material"', '"unknown"', 'null'])
@pytest.mark.parametrize("strict", [False, True])
def test_json_validation_matches_legacy_outcome(value, strict):
    def outcome(adapter):
        try:
            return ("accepted", adapter.validate_json(value, strict=strict))
        except ValidationError as error:
            return ("refused", tuple(item["type"] for item in error.errors()))
    assert outcome(candidate) == outcome(legacy)


def test_error_lists_only_creatable_values():
    with pytest.raises(ValidationError) as caught:
        candidate.validate_python("unknown")
    message = caught.value.errors()[0]["msg"]
    assert all(repr(item.value) in message for item in WAREHOUSE_CREATE_TYPES)
    assert "raw_material" not in message and "warehouse" not in message


def test_input_json_schema_lists_only_creatable_values():
    from app.libs.dto.inventory.warehouse_input import WarehouseIn

    values = WarehouseIn.model_json_schema()["properties"]["type"]["enum"]
    assert values == [member.value for member in WAREHOUSE_CREATE_TYPES]
