"""The warehouse creation refusal names exactly the values the action accepts."""
import pytest
from pydantic import ValidationError

from app.libs.dto.inventory.warehouse_create_type import WAREHOUSE_CREATE_TYPES
from app.libs.dto.inventory.warehouse_input import WarehouseIn
from app.libs.enums.inventory import WarehouseType

ACCEPTED_VALUES = [member.value for member in WAREHOUSE_CREATE_TYPES]
LEGACY_ONLY_VALUES = ["raw_material", "warehouse"]


def test_accepted_values_stay_canonical_members_with_the_same_wire_value():
    for value in ACCEPTED_VALUES:
        payload = WarehouseIn(name="Accepted", type=value)
        assert payload.type is WarehouseType(value)
        assert payload.model_dump(mode="json")["type"] == value


def test_unknown_value_refusal_names_only_the_accepted_subset():
    with pytest.raises(ValidationError) as caught:
        WarehouseIn(name="Refused", type="unknown")
    error = caught.value.errors()[0]
    assert error["type"] == "enum"
    message = error["msg"]
    for value in ACCEPTED_VALUES:
        assert repr(value) in message, message
    for value in LEGACY_ONLY_VALUES:
        assert value not in message, (
            f"the refusal advertises {value!r}, which this action refuses"
        )


@pytest.mark.parametrize("value", LEGACY_ONLY_VALUES)
def test_legacy_only_member_keeps_its_own_refusal(value):
    with pytest.raises(ValidationError) as caught:
        WarehouseIn(name="Refused", type=value)
    assert caught.value.errors()[0]["msg"] == (
        "Value error, Warehouse type is not permitted for creation"
    )


def test_refusal_over_the_api_advertises_no_refused_value(client, auth_headers):
    response = client.post(
        "/api/inventory/warehouses",
        headers=auth_headers,
        json={"name": "Refused", "type": "unknown"},
    )
    assert response.status_code == 422, response.text
    detail = response.text
    for value in LEGACY_ONLY_VALUES:
        assert value not in detail, (
            f"the API refusal advertises {value!r}, which this action refuses"
        )


def test_published_subset_is_unchanged(client):
    document = client.get("/openapi.json").json()
    schemas = document["components"]["schemas"]
    for name in ("WarehouseIn", "WarehouseCreatedOut"):
        published = schemas[name]["properties"]["type"]["enum"]
        assert list(published) == ACCEPTED_VALUES
