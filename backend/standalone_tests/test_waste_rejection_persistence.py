from datetime import datetime, timezone
from unittest.mock import Mock

from app.schemas.inventory.waste import (
    WasteDisposalRequest,
    WasteRecord,
    persist_disposal_rejection,
)


def test_rejection_applies_decision_without_flushing_or_committing():
    session = Mock()
    request = WasteDisposalRequest(status="pending", waste_record_id=1)
    waste = WasteRecord(status="pending_disposal_approval", quantity=0, sellable=True)
    decided_at = datetime(2026, 11, 4, 12, 30, tzinfo=timezone.utc)

    persist_disposal_rejection(session, request, waste, 42, decided_at)

    assert request.status == "rejected"
    assert request.approved_by == 42
    assert request.approved_at == decided_at
    assert waste.status == "received_by_waste_department"
    assert waste.quantity == 0
    assert waste.sellable is True
    session.assert_not_called()
    session.flush.assert_not_called()
    session.commit.assert_not_called()
    assert session.mock_calls == []
