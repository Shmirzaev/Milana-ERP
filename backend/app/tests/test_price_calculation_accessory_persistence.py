from types import SimpleNamespace

import pytest

from app.models import price_calculation_service as pricing
from app.schemas.planning.price_calculation_persistence import apply_accessory_contribution


class FlushOnlySession:
    def __init__(self):
        self.flush_calls = 0

    def flush(self):
        self.flush_calls += 1

    def commit(self):
        raise AssertionError("persistence helper must not commit")


def test_persistence_uses_supplied_session_and_only_owned_fields():
    db = FlushOnlySession()
    request = SimpleNamespace(accessories_json=[], accessories_updated_by_id=1, finance_updated_by_id=7)
    rows = [{"name": "Label", "price": 0}]
    apply_accessory_contribution(db, request, rows, updated_by_id=42)
    assert request.accessories_json == rows
    assert request.accessories_updated_by_id == 42
    assert request.finance_updated_by_id == 7
    assert db.flush_calls == 1


def test_normalization_completion_transition_and_audit(monkeypatch):
    db = FlushOnlySession()
    request = SimpleNamespace(id=9, accessories_json=[])
    actor = SimpleNamespace(id=42)
    events = []
    monkeypatch.setattr(pricing, "log_action", lambda *args, **kwargs: events.append(("audit", kwargs["new_value"])))
    monkeypatch.setattr(pricing, "_notify_finance", lambda *args: events.append(("notify", args[2])))
    pricing.update_accessories(db, request, [
        {"name": "  Label  ", "price": 0}, {"name": "  ", "price": None},
        {"name": None, "price": 2},
    ], actor)
    assert request.accessories_json == [{"name": "Label", "price": 0}, {"name": None, "price": 2}]
    assert events == [("audit", {"accessories": request.accessories_json})]
    pricing.update_accessories(db, request, [{"name": "Label", "price": 1}], actor)
    pricing.update_accessories(db, request, [{"name": "Label", "price": 2}], actor)
    assert [event[0] for event in events] == ["audit", "audit", "notify", "audit"]


def test_flush_failure_prevents_audit_and_notification(monkeypatch):
    class FailingSession:
        def flush(self):
            raise RuntimeError("flush failed")
    monkeypatch.setattr(pricing, "log_action", lambda *args, **kwargs: pytest.fail("unexpected audit"))
    monkeypatch.setattr(pricing, "_notify_finance", lambda *args: pytest.fail("unexpected notification"))
    with pytest.raises(RuntimeError, match="flush failed"):
        pricing.update_accessories(FailingSession(), SimpleNamespace(id=1, accessories_json=[]), [{"name": "A", "price": 0}], SimpleNamespace(id=3))
