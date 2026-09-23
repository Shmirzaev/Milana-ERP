from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.package_workflows import ManualPackageReceiptIn


def _payload(**overrides) -> dict:
    return {
        "request_key": str(uuid4()),
        "model_id": 1,
        "color": "Navy",
        "weight_kg": 1,
        "count": 1,
        "pack_quantities": [1],
        **overrides,
    }


@pytest.mark.parametrize("field", ["model_id", "warehouse_id"])
def test_manual_package_receipt_foreign_key_accepts_integer_maximum(field):
    parsed = ManualPackageReceiptIn.model_validate(_payload(**{field: 2_147_483_647}))

    assert getattr(parsed, field) == 2_147_483_647


@pytest.mark.parametrize("field", ["model_id", "warehouse_id"])
def test_manual_package_receipt_foreign_key_rejects_integer_overflow(field):
    with pytest.raises(ValidationError):
        ManualPackageReceiptIn.model_validate(_payload(**{field: 2_147_483_648}))
