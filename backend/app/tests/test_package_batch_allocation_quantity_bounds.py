import pytest
from pydantic import ValidationError

from app.schemas.tracking import PackageBatchAllocationIn


def test_package_batch_allocation_quantity_accepts_postgresql_integer_maximum():
    parsed = PackageBatchAllocationIn(production_batch_id=1, quantity=2_147_483_647)

    assert parsed.quantity == 2_147_483_647


def test_package_batch_allocation_quantity_rejects_postgresql_integer_overflow():
    with pytest.raises(ValidationError):
        PackageBatchAllocationIn(production_batch_id=1, quantity=2_147_483_648)
