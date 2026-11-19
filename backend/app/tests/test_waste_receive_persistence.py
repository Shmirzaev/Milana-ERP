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
    record = WasteRecord(id=42, status="recorded", waste_type="Offcuts", quantity=2, unit="kg")
    before = {column.key: getattr(record, column.key) for column in WasteRecord.__table__.columns}
    set_received(db, record)
    assert record.status == "received_by_waste_department"
    db.assert_not_called()
    db.flush.assert_not_called()
    db.commit.assert_not_called()
    db.rollback.assert_not_called()
    assert db.mock_calls == []
    assert {column.key: getattr(record, column.key) for column in WasteRecord.__table__.columns if column.key != "status"} == {key: value for key, value in before.items() if key != "status"}


def test_receipt_transitions_then_audits_before_single_commit_and_refresh(monkeypatch):
    record = WasteRecord(id=42, status="recorded")
    actor = SimpleNamespace(id=7)
    db = Mock()
    db.query.return_value.filter.return_value.with_for_update.return_value.populate_existing.return_value.first.return_value = record
    events = []
    monkeypatch.setattr(waste_service, "log_action", lambda session, user, action, kind, ident: events.append((session, user, action, kind, ident, record.status)))
    db.commit.side_effect = lambda: events.append("commit")
    db.refresh.side_effect = lambda obj: events.append(("refresh", obj))
    assert waste_service.receive_waste(db, 42, actor) is record
    assert events == [(db, actor, "receive", "WasteRecord", 42, "received_by_waste_department"), "commit", ("refresh", record)]
    db.commit.assert_called_once_with()
    db.query.assert_called_once_with(WasteRecord)
    query = db.query.return_value.filter.return_value
    query.with_for_update.assert_called_once_with()
    query.with_for_update.return_value.populate_existing.assert_called_once_with()
    query.with_for_update.return_value.populate_existing.return_value.first.assert_called_once_with()
    db.get.assert_not_called()


@pytest.mark.parametrize("status,code", [(None, 404), ("sold", 400), ("received_by_waste_department", 400)])
def test_receipt_refusals_do_not_audit_or_commit(monkeypatch, status, code):
    db = Mock()
    db.query.return_value.filter.return_value.with_for_update.return_value.populate_existing.return_value.first.return_value = None if status is None else WasteRecord(id=42, status=status)
    audit = Mock()
    monkeypatch.setattr(waste_service, "log_action", audit)
    with pytest.raises(HTTPException) as error:
        waste_service.receive_waste(db, 42, SimpleNamespace(id=7))
    assert error.value.status_code == code
    audit.assert_not_called()
    db.commit.assert_not_called()


def _receipt_fixture(permissions):
    from uuid import uuid4
    from app.core.security import create_access_token
    from app.db.session import SessionLocal
    from app.schemas import User

    with SessionLocal() as db:
        user = User(name="Receipt test operator", email=f"receive-{uuid4().hex}@example.com",
                    password_hash="unused", factory_code="MIL", extra_permissions=permissions)
        record = WasteRecord(waste_type="Offcuts", quantity=2.5, unit="kg", sellable=True,
                             estimated_value=12, status="recorded")
        db.add_all([user, record])
        db.commit()
        return record.id, user.id, {"Authorization": f"Bearer {create_access_token(user.id)}"}


def _receipt_readback(wid):
    from app.db.session import SessionLocal
    from app.schemas import AuditLog

    with SessionLocal() as db:
        record = db.get(WasteRecord, wid)
        audits = db.query(AuditLog).filter_by(entity_type="WasteRecord", entity_id=wid, action="receive").all()
        return record.status, [(entry.user_id, entry.action, entry.entity_type, entry.entity_id) for entry in audits]


def test_receive_route_persists_status_and_audit_and_refuses_replay(client):
    wid, actor_id, headers = _receipt_fixture(["waste.receive"])
    response = client.post(f"/api/waste/{wid}/receive", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "received_by_waste_department"
    expected = ("received_by_waste_department", [(actor_id, "receive", "WasteRecord", wid)])
    assert _receipt_readback(wid) == expected
    assert client.post(f"/api/waste/{wid}/receive", headers=headers).status_code == 400
    assert _receipt_readback(wid) == expected


def test_receive_route_denies_without_permission_and_missing_record(client):
    wid, _, headers = _receipt_fixture([])
    assert client.post(f"/api/waste/{wid}/receive", headers=headers).status_code == 403
    assert _receipt_readback(wid) == ("recorded", [])
    _, _, allowed = _receipt_fixture(["waste.receive"])
    assert client.post("/api/waste/999999999/receive", headers=allowed).status_code == 404
    assert _receipt_readback(wid) == ("recorded", [])


def test_receive_rolls_back_flushed_status_and_audit_if_audit_fails(client, monkeypatch):
    wid, actor_id, headers = _receipt_fixture(["waste.receive"])
    real_log_action = waste_service.log_action

    def fail_after_audit(*args, **kwargs):
        real_log_action(*args, **kwargs)
        raise RuntimeError("injected failure after audit flush")

    monkeypatch.setattr(waste_service, "log_action", fail_after_audit)
    with pytest.raises(RuntimeError, match="injected failure"):
        client.post(f"/api/waste/{wid}/receive", headers=headers)
    assert _receipt_readback(wid) == ("recorded", [])

    monkeypatch.setattr(waste_service, "log_action", real_log_action)
    assert client.post(f"/api/waste/{wid}/receive", headers=headers).status_code == 200
    assert _receipt_readback(wid) == ("received_by_waste_department", [(actor_id, "receive", "WasteRecord", wid)])
