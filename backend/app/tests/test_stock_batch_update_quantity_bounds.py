import pytest
from pydantic import ValidationError

from app.schemas.inventory import StockBatchUpdate


def test_stock_batch_update_accepts_numeric_column_limit():
    update = StockBatchUpdate(quantity="9999999999.9999")

    assert update.quantity == 9999999999.9999


@pytest.mark.parametrize("quantity", ["10000000000", "NaN", "Infinity", "-Infinity"])
def test_stock_batch_update_rejects_nonrepresentable_quantity(quantity):
    with pytest.raises(ValidationError):
        StockBatchUpdate(quantity=quantity)


def test_stock_batch_update_keeps_negative_quantity_validation():
    with pytest.raises(ValidationError):
        StockBatchUpdate(quantity="-0.0001")
