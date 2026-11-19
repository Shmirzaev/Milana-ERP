"""Disposal requests retain wire values and free-form reasons."""

import pytest
from pydantic import ValidationError

from app.libs.dto.inventory.waste_disposal_output import WasteDisposalOut
from app.schemas.inventory.waste import WasteRecord, add_disposal_request


@pytest.mark.parametrize("status", ("pending", "approved", "rejected", "disposed"))
def test_disposal_output_wire_status(status):
    output = WasteDisposalOut(id=1, waste_record_id=2, reason="布 🧵", status=status)
    assert output.model_dump(mode="json")["status"] == status
    assert output.reason == "布 🧵"


def test_disposal_output_rejects_unknown_status():
    with pytest.raises(ValidationError):
        WasteDisposalOut(id=1, waste_record_id=2, status="legacy_unknown")


def test_request_helper_adds_and_transitions_before_flush():
    events = []
    waste = WasteRecord(id=2, status="received_by_waste_department")

    class Session:
        def add(self, request):
            events.append(("add", request))
        def flush(self):
            assert waste.status == "pending_disposal_approval"
            assert events[0][1].status == "pending"
            events.append(("flush",))

    request = add_disposal_request(Session(), waste, reason="布 🧵", requested_by=7)
    assert [event[0] for event in events] == ["add", "flush"]
    assert (request.waste_record_id, request.reason, request.requested_by) == (2, "布 🧵", 7)
