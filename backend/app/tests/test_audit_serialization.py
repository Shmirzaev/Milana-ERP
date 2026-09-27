from datetime import datetime, timezone

from sqlalchemy import event

from app.db.session import SessionLocal
from app.models import AuditLog, User
from app.services.audit import log_action, verify_audit_hash_chain


def test_audit_log_serializes_datetime_in_json_payload():
    db = SessionLocal()
    try:
        user = db.query(User).first()
        assert user is not None

        payload = {
            "deadline": datetime(2026, 5, 19, 0, 0, tzinfo=timezone.utc),
            "assigned_to": user.id,
            "changes": [{"at": datetime(2026, 5, 20, 12, 30, tzinfo=timezone.utc)}],
        }
        log_action(db, user, "update", "WorkOrder", 123, new_value=payload)
        db.commit()

        row = db.query(AuditLog).order_by(AuditLog.id.desc()).first()
        assert row is not None
        assert isinstance(row.new_value_json["deadline"], str)
        assert row.new_value_json["deadline"].startswith("2026-05-19T00:00:00")
        assert isinstance(row.new_value_json["changes"][0]["at"], str)
        assert row.entry_hash and len(row.entry_hash) == 64
    finally:
        db.close()


def test_audit_log_hash_chain_links_entries():
    db = SessionLocal()
    try:
        user = db.query(User).first()
        assert user is not None
        first = log_action(db, user, "update", "AuditHashTest", 1, new_value={"step": 1})
        second = log_action(db, user, "update", "AuditHashTest", 2, new_value={"step": 2})
        db.commit()

        assert first.entry_hash and len(first.entry_hash) == 64
        assert second.entry_hash and len(second.entry_hash) == 64
        assert second.prev_hash == first.entry_hash
        assert second.entry_hash != first.entry_hash
    finally:
        db.close()


def test_sqlite_audit_head_is_reused_within_transaction(monkeypatch):
    from app.services import audit

    db = SessionLocal()
    try:
        user = db.query(User).first()
        assert user is not None
        calls = 0
        original = audit._latest_entry_hash

        def counted(session):
            nonlocal calls
            calls += 1
            return original(session)

        monkeypatch.setattr(audit, "_latest_entry_hash", counted)
        first = log_action(db, user, "update", "AuditHeadReuse", 1, new_value={"step": 1})
        second = log_action(db, user, "update", "AuditHeadReuse", 2, new_value={"step": 2})
        db.commit()

        assert calls == 1
        assert second.prev_hash == first.entry_hash
    finally:
        db.close()


def test_sqlite_audit_head_discards_rolled_back_savepoint(monkeypatch):
    db = SessionLocal()
    try:
        user = db.query(User).first()
        assert user is not None
        first = log_action(db, user, "update", "AuditHeadSavepoint", 1, new_value={"step": 1})
        savepoint = db.begin_nested()
        discarded = log_action(db, user, "update", "AuditHeadSavepoint", 2, new_value={"step": 2})
        savepoint.rollback()
        retained = log_action(db, user, "update", "AuditHeadSavepoint", 3, new_value={"step": 3})
        db.commit()

        assert retained.prev_hash == first.entry_hash
        assert db.query(AuditLog).filter_by(entity_type="AuditHeadSavepoint", entity_id=2).first() is None
        assert verify_audit_hash_chain(db)["ok"] is True
    finally:
        db.close()


def test_sqlite_commit_flag_resets_cached_head_for_session_reuse():
    db = SessionLocal()
    try:
        user = db.query(User).first()
        assert user is not None
        committed = log_action(
            db, user, "update", "AuditHeadCommitFlag", 1,
            new_value={"step": 1}, commit=True,
        )
        following = log_action(
            db, user, "update", "AuditHeadCommitFlag", 2,
            new_value={"step": 2},
        )
        db.commit()

        assert committed.prev_hash is None or committed.prev_hash != following.entry_hash
        assert following.prev_hash == committed.entry_hash
        assert verify_audit_hash_chain(db)["ok"] is True
    finally:
        db.close()


def test_audit_hash_chain_export_and_verify_endpoint(client, auth_headers):
    db = SessionLocal()
    try:
        user = db.query(User).first()
        assert user is not None
        last = db.query(AuditLog.id).order_by(AuditLog.id.desc()).first()
        start_id = int(last[0]) + 1 if last else 1
        first = log_action(db, user, "create", "AuditHashExport", 1, new_value={"step": 1})
        second = log_action(db, user, "update", "AuditHashExport", 1, new_value={"step": 2})
        db.commit()
        first_id = int(first.id)
        second_id = int(second.id)
    finally:
        db.close()

    verify = client.get(f"/api/audit-logs/hash-chain/verify?start_id={start_id}", headers=auth_headers)
    assert verify.status_code == 200, verify.text
    assert verify.json()["ok"] is True
    assert verify.json()["checked"] >= 2

    exported = client.get(f"/api/audit-logs/hash-chain/export?start_id={start_id}&limit=2", headers=auth_headers)
    assert exported.status_code == 200, exported.text
    rows = exported.json()["rows"]
    assert [row["id"] for row in rows] == [first_id, second_id]
    assert rows[1]["prev_hash"] == rows[0]["entry_hash"]


def test_audit_hash_chain_verify_reports_tampered_row():
    db = SessionLocal()
    try:
        user = db.query(User).first()
        assert user is not None
        last = db.query(AuditLog.id).order_by(AuditLog.id.desc()).first()
        start_id = int(last[0]) + 1 if last else 1
        first = log_action(db, user, "create", "AuditHashTamper", 1, new_value={"step": 1})
        second = log_action(db, user, "update", "AuditHashTamper", 1, new_value={"step": 2})
        db.commit()
        second_id = int(second.id)

        second.action = "tampered"
        db.commit()
        result = verify_audit_hash_chain(db, start_id=start_id)
        assert result["ok"] is False
        assert result["first_mismatch"]["id"] == second_id
        assert result["first_mismatch"]["reason"] == "entry_hash_mismatch"

        second.action = "update"
        db.commit()
        assert verify_audit_hash_chain(db, start_id=start_id)["ok"] is True
        assert first.entry_hash and second.entry_hash
    finally:
        db.close()


def test_audit_log_endpoint_returns_manager_summary_and_filters(client, auth_headers):
    db = SessionLocal()
    try:
        user = db.query(User).first()
        assert user is not None
        log_action(
            db,
            user,
            "update",
            "WorkOrder",
            987,
            old_value={"status": "waiting", "deadline": "2026-06-01"},
            new_value={"status": "blocked", "deadline": "2026-06-03"},
        )
        db.commit()
    finally:
        db.close()

    response = client.get(
        "/api/audit-logs?include_total=true&entity_type=WorkOrder&entity_id=987&action=update",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] >= 1
    row = body["rows"][0]
    assert row["summary"].endswith("updated work order #987.")
    assert row["action_label"] == "updated"
    assert row["entity_label"] == "work order"
    assert row["entry_hash"] and len(row["entry_hash"]) == 64
    assert {"field": "status", "from": "waiting", "to": "blocked"} in row["changed_fields"]
    assert "Changed fields" in row["root_cause_hint"]


def test_audit_log_endpoint_computes_changed_fields_once_per_row(client, auth_headers, monkeypatch):
    from app.api.routes import admin

    db = SessionLocal()
    try:
        user = db.query(User).first()
        assert user is not None
        log_action(
            db, user, "update", "AuditSerialization", 991,
            old_value={"status": "waiting"}, new_value={"status": "done"},
        )
        db.commit()
    finally:
        db.close()

    calls = 0
    original = admin._changed_fields

    def counted(old_value, new_value):
        nonlocal calls
        calls += 1
        return original(old_value, new_value)

    monkeypatch.setattr(admin, "_changed_fields", counted)
    response = client.get(
        "/api/audit-logs?entity_type=AuditSerialization&entity_id=991",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    assert calls == 1


def test_hash_chain_start_lookup_projects_only_previous_entry_hash():
    statements = []
    db = SessionLocal()
    try:
        user = db.query(User).first()
        assert user is not None
        log_action(db, user, "create", "AuditHashProjection", 1, new_value={"step": 1})
        second = log_action(db, user, "update", "AuditHashProjection", 2, new_value={"step": 2})
        db.commit()
        start_id = int(second.id)
        legacy_sql = str(
            db.query(AuditLog)
            .filter(AuditLog.id < start_id, AuditLog.entry_hash.isnot(None))
            .statement.compile(dialect=db.bind.dialect)
        ).lower()
        bind = db.get_bind()

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().lower().startswith("select"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(bind, "before_cursor_execute", capture)
        try:
            result = verify_audit_hash_chain(db, start_id=start_id, limit=1)
        finally:
            event.remove(bind, "before_cursor_execute", capture)

        assert result == {
            "ok": True,
            "checked": 1,
            "last_valid_hash": second.entry_hash,
            "first_mismatch": None,
        }
    finally:
        db.close()

    prior_lookup = next(statement for statement in statements if "audit_logs.id <" in statement)
    assert prior_lookup.startswith("select audit_logs.entry_hash ")
    assert "audit_logs.old_value_json" not in prior_lookup
    assert "audit_logs.new_value_json" not in prior_lookup
    assert "audit_logs.old_value_json" in legacy_sql
    assert "audit_logs.new_value_json" in legacy_sql
