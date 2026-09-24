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
    assert PriceCalculationAccessoryIn(price=9_999_999_999.9999).price == pytest.approx(9_999_999_999.9999)


@pytest.mark.parametrize("value", [10_000_000_000, 1e100])
def test_accessory_price_rejects_values_above_other_price_calculation_inputs(value):
    with pytest.raises(ValidationError):
        PriceCalculationAccessoryIn(price=value)
