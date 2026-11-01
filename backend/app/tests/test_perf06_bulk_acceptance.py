"""PERF06: real-HTTP 500-label boundary, replay and atomic refusal evidence."""

from datetime import datetime, timedelta, timezone
import hashlib
import json
import socket
from threading import Thread
from time import monotonic, sleep
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
import uvicorn

from app.core.security import create_access_token
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.audit_service import verify_audit_hash_chain
from app.schemas import AuditLog, Employee, PayrollPeriod, PayrollQrLabel, PayrollRecord, User
from app.tests.pg_approved_instance import (
    ApprovedInstanceUnavailable,
    create_target_database,
    finalize_target,
    load_approved_instance,
    require_or_skip,
    target_engine,
    verify_approved_instance,
)


@pytest.fixture(params=["sqlite", "postgres"])
def bulk_http(request, tmp_path, monkeypatch):
    target = None
    if request.param == "postgres":
        try:
            instance = load_approved_instance()
            verify_approved_instance(instance)
        except ApprovedInstanceUnavailable as error:
            require_or_skip(error)
        target = create_target_database(instance)
        engine = target_engine(target)
    else:
        engine = create_engine(f"sqlite:///{tmp_path / 'bulk.sqlite'}", connect_args={"check_same_thread": False})
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    server = thread = None
    try:
        Base.metadata.create_all(engine)
        now = datetime.now(timezone.utc)
        with sessions.begin() as db:
            actor = User(name="PERF06 fixture manager", email=f"perf06-{uuid4().hex}@example.com",
                         password_hash="unused-local-fixture", factory_code="MIL", extra_permissions=["*"])
            employee = Employee(factory_code="MIL", employee_no=f"PERF06-{uuid4().hex[:16]}",
                                full_name="PERF06 synthetic worker", status="active")
            db.add_all([actor, employee])
            db.flush()
            period = PayrollPeriod(factory_code="MIL", period_no=f"PERF06-{uuid4().hex}",
                                   name="PERF06 acceptance", start_date=now - timedelta(days=1),
                                   end_date=now + timedelta(days=1), status="open", created_by=actor.id)
            db.add(period)
            db.flush()
            actor_id, employee_id, period_id = actor.id, employee.id, period.id

        def database():
            with sessions() as db:
                yield db

        monkeypatch.setitem(app.dependency_overrides, get_db, database)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            host, port = listener.getsockname()
            server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, lifespan="off",
                                                   proxy_headers=False, log_level="critical"))
            thread = Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
            thread.start()
            deadline = monotonic() + 5
            while not server.started and thread.is_alive() and monotonic() < deadline:
                sleep(0.01)
            assert server.started, "Isolated real-HTTP server did not start"
            headers = {"Authorization": f"Bearer {create_access_token(actor_id, {'factory_code': 'MIL'})}"}
            with httpx.Client(base_url=f"http://{host}:{port}", headers=headers, timeout=60, trust_env=False) as client:
                yield client, sessions, employee_id, period_id
    finally:
        if server is not None:
            server.should_exit = True
        if thread is not None:
            thread.join(timeout=5)
            assert not thread.is_alive(), "Isolated HTTP server did not stop"
        if target is not None:
            finalize_target(target, engine)
        else:
            engine.dispose()


def _issued_payload(case):
    client, _sessions, employee_id, period_id = case
    marker = uuid4().hex
    labels = [{"label_uid": f"PERF06-{marker}-{i}", "operation_section": "sewing",
               "operation_code": "PERF06", "operation_name": "Acceptance issued work",
               "quantity": 1, "rate_per_piece": 2} for i in range(500)]
    issued = client.post("/api/payroll/qr-labels/issue", json={"labels": labels})
    assert issued.status_code == 200, issued.text
    return {"records": [{"scan_uid": label["label_uid"], "employee_id": employee_id,
                          "payroll_period_id": period_id, "quantity": 1, "rate_per_piece": 2}
                         for label in labels]}


def _fingerprints(sessions):
    result = {}
    with sessions() as db:
        for model in (PayrollRecord, PayrollQrLabel, AuditLog):
            rows = [dict(row) for row in db.execute(select(model.__table__).order_by(model.id)).mappings()]
            encoded = json.dumps(rows, sort_keys=True, separators=(",", ":"), default=str).encode()
            result[model.__tablename__] = {"rows": len(rows), "sha256": hashlib.sha256(encoded).hexdigest()}
    return result


def test_perf06_bad_last_row_of_500_rolls_back_every_record_label_and_audit(bulk_http):
    client, sessions, _employee_id, _period_id = bulk_http
    payload = _issued_payload(bulk_http)
    payload["records"][-1]["employee_id"] = 2_000_000_000
    before = _fingerprints(sessions)
    refused = client.post("/api/payroll/records/bulk", json=payload)
    assert refused.status_code == 404, refused.text[:300]
    after = _fingerprints(sessions)
    print(f"PERF06 bad-last-row fingerprints: {before} -> {after}")
    assert after == before


def test_perf06_501_rows_refused_before_record_label_or_audit_mutation(bulk_http):
    client, sessions, _employee_id, _period_id = bulk_http
    payload = _issued_payload(bulk_http)
    payload["records"].append(dict(payload["records"][0]))
    before = _fingerprints(sessions)
    refused = client.post("/api/payroll/records/bulk", json=payload)
    assert refused.status_code == 422, refused.text[:300]
    after = _fingerprints(sessions)
    print(f"PERF06 501-refusal fingerprints: {before} -> {after}")
    assert after == before


def test_perf06_500_distinct_issued_labels_replay_only_audits_request(bulk_http):
    client, sessions, _employee_id, _period_id = bulk_http
    payload = _issued_payload(bulk_http)
    before = _fingerprints(sessions)
    saved = client.post("/api/payroll/records/bulk", json=payload)
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert (body["created_count"], body["duplicate_count"]) == (500, 0)
    record_ids = [row["id"] for row in body["records"]]
    assert len(record_ids) == len(set(record_ids)) == 500
    assert [row["scan_uid"] for row in body["records"]] == [row["scan_uid"] for row in payload["records"]]
    with sessions() as db:
        records = db.query(PayrollRecord).all()
        assert len(records) == len({row.scan_uid for row in records}) == 500
        assert all(row.status == "recorded" and row.quantity == 1 and row.rate_per_piece == 2 for row in records)
        labels = db.query(PayrollQrLabel).all()
        assert len(labels) == 500 and all(row.status == "scanned" for row in labels)
        audits = db.query(AuditLog).filter(AuditLog.entity_type == "PayrollRecord").all()
        individual = [row for row in audits if row.action == "create"]
        summary = [row for row in audits if row.action == "bulk_create"]
        assert len(individual) == 500 and {row.entity_id for row in individual} == set(record_ids)
        assert len(summary) == 1
        assert summary[0].new_value_json == {"created_count": 500, "duplicate_count": 0, "record_ids": record_ids}
    after_save = _fingerprints(sessions)
    assert after_save["payroll_records"]["rows"] - before["payroll_records"]["rows"] == 500
    assert after_save["audit_logs"]["rows"] - before["audit_logs"]["rows"] == 501
    with sessions() as db:
        prior_audits = [dict(row) for row in db.execute(select(AuditLog.__table__).order_by(AuditLog.id)).mappings()]
    replay = client.post("/api/payroll/records/bulk", json=payload)
    assert replay.status_code == 200, replay.text
    assert (replay.json()["created_count"], replay.json()["duplicate_count"]) == (0, 500)
    assert [row["id"] for row in replay.json()["records"]] == record_ids
    after_replay = _fingerprints(sessions)
    print(f"PERF06 exact before/after replay fingerprints: {after_save} -> {after_replay}")
    assert after_replay["payroll_records"] == after_save["payroll_records"], "Duplicate replay changed earnings"
    assert after_replay["payroll_qr_labels"] == after_save["payroll_qr_labels"], "Duplicate replay changed labels"
    with sessions() as db:
        audits = [dict(row) for row in db.execute(select(AuditLog.__table__).order_by(AuditLog.id)).mappings()]
        assert len(audits) == len(prior_audits) + 1, "Each duplicate bulk request must add exactly one summary audit"
        assert audits[:-1] == prior_audits, "Replay must preserve all earlier audit rows"
        summary = audits[-1]
        assert (summary["action"], summary["entity_type"], summary["entity_id"]) == ("bulk_create", "PayrollRecord", None)
        assert summary["user_id"] == prior_audits[-1]["user_id"]
        assert summary["new_value_json"] == {"created_count": 0, "duplicate_count": 500, "record_ids": []}
        assert db.query(AuditLog).filter_by(entity_type="PayrollRecord", action="create").count() == 500
        assert verify_audit_hash_chain(db)["ok"], "Replay summary must preserve a valid audit chain"
