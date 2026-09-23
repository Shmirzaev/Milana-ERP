import pytest
from pydantic import ValidationError

from app.schemas.price_calculation import PriceCalculationAccessoryIn


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_accessory_price_rejects_non_finite_values(value):
    with pytest.raises(ValidationError):
        PriceCalculationAccessoryIn(price=value)


def test_accessory_price_preserves_none_zero_and_finite_values():
    assert PriceCalculationAccessoryIn().price is None
    assert PriceCalculationAccessoryIn(price=0).price == 0
    assert PriceCalculationAccessoryIn(price="12.345").price == pytest.approx(12.345)
