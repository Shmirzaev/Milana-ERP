"""Receipt transition and transaction ordering, independent of the database."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from app.models.inventory import waste_service
from app.schemas.inventory.waste import WasteRecord
from app.schemas.inventory.waste_receive_persistence import set_received


def test_receipt_persistence_uses_caller_session_without_flushing_or_committing():
    db = Mock()
    record = WasteRecord(status="recorded")
    set_received(db, record)
    assert record.status == "received_by_waste_department"
    db.assert_not_called()
    db.flush.assert_not_called()
    db.commit.assert_not_called()


def test_receipt_transitions_then_audits_before_single_commit_and_refresh(monkeypatch):
    record = WasteRecord(id=42, status="recorded")
    actor = SimpleNamespace(id=7)
    db = Mock()
    db.get.return_value = record
    events = []
    monkeypatch.setattr(waste_service, "log_action", lambda session, user, action, kind, ident: events.append((session, user, action, kind, ident, record.status)))
    db.commit.side_effect = lambda: events.append("commit")
    db.refresh.side_effect = lambda obj: events.append(("refresh", obj))
    assert waste_service.receive_waste(db, 42, actor) is record
    assert events == [(db, actor, "receive", "WasteRecord", 42, "received_by_waste_department"), "commit", ("refresh", record)]
    db.commit.assert_called_once_with()


@pytest.mark.parametrize("status,code", [(None, 404), ("sold", 400), ("received_by_waste_department", 400)])
def test_receipt_refusals_do_not_audit_or_commit(monkeypatch, status, code):
    db = Mock()
    db.get.return_value = None if status is None else WasteRecord(id=42, status=status)
    audit = Mock()
    monkeypatch.setattr(waste_service, "log_action", audit)
    with pytest.raises(HTTPException) as error:
        waste_service.receive_waste(db, 42, SimpleNamespace(id=7))
    assert error.value.status_code == code
    audit.assert_not_called()
    db.commit.assert_not_called()
