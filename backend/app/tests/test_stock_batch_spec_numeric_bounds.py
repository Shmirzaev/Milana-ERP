import pytest
from pydantic import ValidationError

from app.schemas.inventory import StockBatchIn, StockBatchUpdate


_SCHEMAS = (StockBatchIn, StockBatchUpdate)
_LIMITS = {
    "width": 99_999_999.99,
    "gsm": 99_999_999.999999,
}


def _validate(schema, **values):
    if schema is StockBatchIn:
        return schema(
            item_id=1,
            batch_no="NUMERIC-BOUND",
            quantity=1,
            unit="kg",
            warehouse_id=1,
            **values,
        )
    return schema(**values)


@pytest.mark.parametrize("schema", _SCHEMAS)
@pytest.mark.parametrize(("field", "maximum"), _LIMITS.items())
def test_stock_batch_spec_accepts_column_limit_and_float_rounding(schema, field, maximum):
    model = _validate(schema, **{field: str(maximum)})
    rounded_input = _validate(schema, **{field: "1.23456789"})

    assert getattr(model, field) == maximum
    assert getattr(rounded_input, field) == 1.23456789


@pytest.mark.parametrize("schema", _SCHEMAS)
@pytest.mark.parametrize("field", _LIMITS)
@pytest.mark.parametrize("value", ["100000000", "-100000000", "Infinity", "-Infinity", "NaN"])
def test_stock_batch_spec_rejects_nonrepresentable_width_and_gsm(schema, field, value):
    with pytest.raises(ValidationError):
        _validate(schema, **{field: value})
