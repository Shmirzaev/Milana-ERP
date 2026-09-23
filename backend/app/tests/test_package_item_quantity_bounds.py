import pytest
from pydantic import ValidationError

from app.schemas.tracking import PackageItemIn


def _payload(quantity: int) -> dict:
    return {"model_id": 1, "color": "Navy", "size": "M", "quantity": quantity}


def test_package_item_quantity_accepts_postgresql_integer_maximum():
    parsed = PackageItemIn.model_validate(_payload(2_147_483_647))

    assert parsed.quantity == 2_147_483_647


def test_package_item_quantity_rejects_postgresql_integer_overflow():
    with pytest.raises(ValidationError):
        PackageItemIn.model_validate(_payload(2_147_483_648))
