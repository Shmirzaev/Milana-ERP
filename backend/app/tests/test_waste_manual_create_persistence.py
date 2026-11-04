"""Manual creation retains valuation, audit order and transaction ownership."""

from types import SimpleNamespace

import pytest

from app.libs.dto.inventory.waste_input import WasteIn
from app.models.inventory import waste_service


def test_manual_create_flushes_before_audit_and_commits_once(monkeypatch):
    events = []
    class Session:
        def add(self, record):
            events.append(("add", record))
        def flush(self):
            events.append(("flush",))
            events[0][1].id = 42
        def commit(self):
            events.append(("commit",))
        def refresh(self, record):
            events.append(("refresh", record))

    db = Session()
    monkeypatch.setattr(waste_service, "_unit_cost_for_waste", lambda *args: 2.5)
    def audit(session, user, action, entity, entity_id, *, new_value):
        assert session is db
        events.append(("audit", action, entity, entity_id, new_value))
    monkeypatch.setattr(waste_service, "log_action", audit)
    record = waste_service.create_waste(db, WasteIn(waste_type="fabric", quantity=3, unit="kg", estimated_value=999), SimpleNamespace(id=7))
    assert [event[0] for event in events] == ["add", "flush", "audit", "commit", "refresh"]
    assert (record.created_by, record.status, record.estimated_value) == (7, "recorded", 7.5)
    assert events[2][1:] == ("create", "WasteRecord", 42, {"type": "fabric", "qty": 3.0})


def test_manual_create_does_not_commit_if_audit_fails(monkeypatch):
    events = []
    class Session:
        def add(self, record):
            self.record = record
        def flush(self):
            self.record.id = 42
        def commit(self):
            events.append("commit")
        def refresh(self, record):
            events.append("refresh")
    monkeypatch.setattr(waste_service, "_unit_cost_for_waste", lambda *args: 0)
    def fail(*args, **kwargs):
        raise RuntimeError("audit failure")
    monkeypatch.setattr(waste_service, "log_action", fail)
    with pytest.raises(RuntimeError, match="audit failure"):
        waste_service.create_waste(Session(), WasteIn(waste_type="fabric", quantity=1, unit="kg"), SimpleNamespace(id=7))
    assert events == []
