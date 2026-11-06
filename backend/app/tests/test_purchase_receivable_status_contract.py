"""Receipt eligibility retains its stored-string subset and refusal order."""
from types import SimpleNamespace
from typing import get_type_hints
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.libs.enums.purchasing import PurchaseOrderStatus
from app.models import purchasing_service


def test_receivable_subset_is_canonical_and_matches_legacy_strings():
    subset = purchasing_service.ORDER_RECEIVABLE_STATUSES
    assert get_type_hints(purchasing_service)["ORDER_RECEIVABLE_STATUSES"] == frozenset[PurchaseOrderStatus]
    assert all(type(status) is PurchaseOrderStatus for status in subset)
    assert subset == {"sent", "approved", "partially_received"}


@pytest.mark.parametrize("status", ["sent", "approved", "partially_received"])
def test_stored_receivable_status_reaches_line_validation(status):
    db = MagicMock(bind=None)
    db.query.return_value.options.return_value.filter.return_value.populate_existing.return_value.one_or_none.return_value = SimpleNamespace(status=status)
    with pytest.raises(HTTPException) as exc:
        purchasing_service.receive_purchase_order(db, order_id=1, data={"lines": []}, current=None)
    assert (exc.value.status_code, exc.value.detail) == (400, "At least one receive line is required")
    db.expire.assert_not_called()


@pytest.mark.parametrize("status", ["draft", "received", "SENT", " sent ", "unknown", ""])
def test_non_receivable_stored_status_refused_before_line_validation(status):
    db = MagicMock(bind=None)
    db.query.return_value.options.return_value.filter.return_value.populate_existing.return_value.one_or_none.return_value = SimpleNamespace(status=status)
    with pytest.raises(HTTPException) as exc:
        purchasing_service.receive_purchase_order(db, order_id=1, data={"lines": []}, current=None)
    assert (exc.value.status_code, exc.value.detail) == (409, f"Cannot receive a purchase order in status '{status}'")
    db.expire.assert_not_called()


def test_missing_order_precedes_line_validation():
    db = MagicMock(bind=None)
    db.query.return_value.options.return_value.filter.return_value.populate_existing.return_value.one_or_none.return_value = None
    with pytest.raises(HTTPException) as exc:
        purchasing_service.receive_purchase_order(db, order_id=1, data={"lines": []}, current=None)
    assert (exc.value.status_code, exc.value.detail) == (404, "Purchase order not found")
    db.expire.assert_not_called()
