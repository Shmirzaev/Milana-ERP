"""Concurrent receipt serializes the existing single-transition contract."""
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.routes.waste import router
from app.core.deps import get_db
from app.core.security import create_access_token
from app.models import audit_service
from app.schemas import AuditLog, Notification, Role, User, WasteRecord
from app.tests.test_modelsize_create_postgres import pg_sessions as pg_sessions  # noqa: F401
from app.tests.test_waste_race_rollback_postgres import _public_snapshot, _sequences


def test_receipt_concurrent_observed_recorded_characterization(pg_sessions):  # noqa: F811
    suffix = uuid4().hex[:10]
    with pg_sessions.begin() as db:
        role = Role(name=f'receipt-race-{suffix}', permissions=['waste.receive'])
        db.add(role)
        db.flush()
        actor = User(name='Receipt actor', email=f'receipt-{suffix}@example.invalid',
                     password_hash='unused', role_id=role.id, factory_code='MIL', is_active=True)
        record = WasteRecord(waste_type='cutting', quantity=10, unit='kg', sellable=True, status='recorded')
        control = WasteRecord(waste_type='control', quantity=3, unit='kg', sellable=True, status='recorded')
        db.add_all([actor, record, control])
        db.flush()
        actor_id, record_id, control_id = actor.id, record.id, control.id
    barrier = threading.Barrier(3, timeout=10)
    pids = {}
    app = FastAPI()
    app.include_router(router)

    def isolated_db(request: Request):
        with pg_sessions() as db:
            pids[request.headers["X-Test-Request"]] = db.execute(text("SELECT pg_backend_pid()")).scalar_one()
            yield db

    app.dependency_overrides[get_db] = isolated_db
    with pg_sessions() as db:
        control_before = db.execute(text('SELECT row_to_json(w)::text FROM waste_records w WHERE id=:id'), {'id': control_id}).scalar_one()
        notifications_before = db.query(Notification).count()
        sequences_before = _sequences(db)
        rows_before = _public_snapshot(db)
        unrelated_waste_before = db.execute(text(
            'SELECT row_to_json(w)::text FROM waste_records w WHERE id<>:id ORDER BY 1'
        ), {'id': record_id}).scalars().all()
        unrelated_audit_before = db.execute(text(
            "SELECT row_to_json(a)::text FROM audit_logs a WHERE "
            "(entity_type='WasteRecord' AND entity_id=:id AND action='receive') IS NOT TRUE ORDER BY 1"
        ), {'id': record_id}).scalars().all()
    headers = {'Authorization': f'Bearer {create_access_token(actor_id)}'}

    def receive(key):
        with TestClient(app) as client:
            barrier.wait()
            response = client.post(f'/waste/{record_id}/receive',
                                   headers={**headers, "X-Test-Request": key})
            return response.status_code, response.json()

    with pg_sessions() as holder:
        holder.execute(text("SELECT id FROM waste_records WHERE id=:id FOR UPDATE"), {"id": record_id}).one()
        holder_pid = holder.execute(text("SELECT pg_backend_pid()")).scalar_one()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(receive, str(n)) for n in range(2)]
            try:
                barrier.wait()
                deadline = time.monotonic() + 10
                proven = False
                while time.monotonic() < deadline:
                    assert not any(f.done() for f in futures), "receipt finished before lock release"
                    if len(pids) == 2:
                        with pg_sessions() as observer:
                            def reaches_holder(start):
                                pending, seen = [start], set()
                                while pending:
                                    pid = pending.pop()
                                    if pid == holder_pid:
                                        return True
                                    if pid in seen:
                                        continue
                                    seen.add(pid)
                                    pending.extend(observer.execute(
                                        text("SELECT pg_blocking_pids(:pid)"), {"pid": pid}
                                    ).scalar_one())
                                return False
                            proven = len(set(pids.values())) == 2 and all(
                                reaches_holder(pid) for pid in pids.values()
                            )
                        if proven:
                            break
                    time.sleep(0.05)
                assert proven, "both requests did not block on the held row"
            finally:
                holder.rollback()
            results = [f.result(timeout=20) for f in futures]
    assert sorted(status for status, _ in results) == [200, 400]
    assert next(body for status, body in results if status == 200)["status"] == "received_by_waste_department"
    assert next(body for status, body in results if status == 400) == {
        "detail": "Can't receive from status 'received_by_waste_department'"
    }
    with pg_sessions() as db:
        final = db.get(WasteRecord, record_id)
        audits = db.query(AuditLog).filter_by(entity_type='WasteRecord', entity_id=record_id, action='receive').order_by(AuditLog.id).all()
        assert db.execute(text('SELECT row_to_json(w)::text FROM waste_records w WHERE id=:id'), {'id': control_id}).scalar_one() == control_before
        assert len(audits) == 1 and audits[0].user_id == actor_id
        assert final.status == 'received_by_waste_department'
        assert db.query(Notification).count() == notifications_before
        assert audit_service.verify_audit_hash_chain(db)['ok']
        sequences_after = _sequences(db)
        rows_after = _public_snapshot(db)
        # Only the receipt target and its audit entries can be affected.
        for table in rows_before.keys() | rows_after.keys():
            if table not in {'waste_records', 'audit_logs'}:
                assert rows_after.get(table) == rows_before.get(table), table
        assert db.execute(text(
            'SELECT row_to_json(w)::text FROM waste_records w WHERE id<>:id ORDER BY 1'
        ), {'id': record_id}).scalars().all() == unrelated_waste_before
        assert db.execute(text(
            "SELECT row_to_json(a)::text FROM audit_logs a WHERE "
            "(entity_type='WasteRecord' AND entity_id=:id AND action='receive') IS NOT TRUE ORDER BY 1"
        ), {'id': record_id}).scalars().all() == unrelated_audit_before
        target_row = db.execute(text('SELECT row_to_json(w)::text FROM waste_records w WHERE id=:id'),
                                {'id': record_id}).scalar_one()
        audit_rows = [{'id': row.id, 'action': row.action, 'actor': row.user_id,
                       'old': row.old_value_json, 'new': row.new_value_json,
                       'prev_hash': row.prev_hash, 'entry_hash': row.entry_hash} for row in audits]
        print('RECEIPT_RACE_CHARACTERIZATION', {'responses': results, 'final_status': final.status,
              'target_row': target_row, 'audit_count': len(audits), 'audit_rows': audit_rows,
              'sequence_changes': {key: (value, sequences_after.get(key)) for key, value in sequences_before.items()
                                   if sequences_after.get(key) != value}}, flush=True)
