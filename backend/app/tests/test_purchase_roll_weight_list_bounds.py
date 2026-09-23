import pytest
from pydantic import ValidationError

from app.schemas.purchasing import PurchaseOrderReceiveLineIn


def _receive_line(roll_count: int) -> dict:
    return {
        "purchase_order_line_id": 1,
        "received_quantity": roll_count,
        "batch_no": "ROLL-LIMIT-TEST",
        "roll_weights_kg": [1.0] * roll_count,
    }


def test_purchase_receipt_roll_weight_list_uses_existing_1000_roll_limit():
    boundary = PurchaseOrderReceiveLineIn.model_validate(_receive_line(1000))
    assert len(boundary.roll_weights_kg) == 1000

    with pytest.raises(ValidationError):
        PurchaseOrderReceiveLineIn.model_validate(_receive_line(1001))


def test_purchase_receipt_roll_weights_remain_optional():
    line = PurchaseOrderReceiveLineIn.model_validate({
        "purchase_order_line_id": 1,
        "received_quantity": 1,
        "batch_no": "ROLL-LIMIT-OPTIONAL",
    })
    assert line.roll_weights_kg == []
