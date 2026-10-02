from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.inventory import AccessoryIssueLineIn


def test_accessory_issue_quantity_accepts_numeric_14_4_maximum_exactly():
    line = AccessoryIssueLineIn(item_name="Manual item", quantity="9999999999.9999")

    assert line.quantity == Decimal("9999999999.9999")


@pytest.mark.parametrize("quantity", [
    "0",
    "-0.0001",
    "NaN",
    "Infinity",
    "10000000000",
    "1.00001",
])
def test_accessory_issue_quantity_rejects_nonpositive_nonfinite_or_unrepresentable_values(quantity):
    with pytest.raises(ValidationError):
        AccessoryIssueLineIn(item_name="Manual item", quantity=quantity)


def test_accessory_issue_quantity_keeps_four_decimal_places_exact():
    line = AccessoryIssueLineIn(item_name="Manual item", quantity="0.1001")

    assert line.quantity == Decimal("0.1001")
