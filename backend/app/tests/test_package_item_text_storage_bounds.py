import pytest
from pydantic import ValidationError

from app.schemas.tracking import PackageEditItemIn, PackageItemIn


@pytest.mark.parametrize(("schema", "field", "maximum"), [
    (PackageItemIn, "color", 64),
    (PackageItemIn, "size", 32),
    (PackageEditItemIn, "color", 64),
    (PackageEditItemIn, "size", 32),
])
def test_package_item_text_matches_storage_width(schema, field, maximum):
    payload = {"model_id": 1, "color": "Navy", "size": "M", "quantity": 1}
    accepted = schema.model_validate({**payload, field: "x" * maximum})

    assert getattr(accepted, field) == "x" * maximum
    with pytest.raises(ValidationError):
        schema.model_validate({**payload, field: "x" * (maximum + 1)})
