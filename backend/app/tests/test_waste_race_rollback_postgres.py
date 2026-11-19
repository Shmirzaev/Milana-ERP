"""Owned PostgreSQL public Waste sale contention and finalization rollback."""
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.routes.waste import router
from app.core.deps import get_db
from app.core.security import create_access_token
from app.models import audit_service
from app.models.idempotency_service import request_fingerprint
from app.libs.dto.inventory.waste_sale_input import WasteSaleIn
from app.schemas import AuditLog, IdempotencyRecord, Notification, Role, User, WasteRecord, WasteSale
from app.tests.test_modelsize_create_postgres import pg_sessions as pg_sessions  # noqa: F401


def _setup(sessions):
    suffix = uuid4().hex[:10]
    with sessions.begin() as db:
        role = Role(name=f'waste-race-{suffix}', permissions=['waste.sell'])
        db.add(role)
        db.flush()
        actor = User(name='Waste seller', email=f'waste-race-{suffix}@example.invalid', password_hash='unused', role_id=role.id, factory_code='MIL', is_active=True)
        record = WasteRecord(waste_type='cutting', quantity=10, unit='kg', sellable=True, status='received_by_waste_department')
        control = WasteRecord(waste_type='control', quantity=3, unit='kg', sellable=True, status='recorded')
        db.add_all([actor, record, control])
        db.flush()
        return actor.id, record.id, control.id


def _app(sessions, request_pids=None):
    app = FastAPI()
    app.include_router(router)
    def isolated_db(request: Request):
        with sessions() as db:
            if request_pids is not None:
                key = request.headers.get("Idempotency-Key")
                request_pids[key] = db.execute(text("SELECT pg_backend_pid()")).scalar_one()
            yield db
    app.dependency_overrides[get_db] = isolated_db
    return app


def _public_snapshot(db):
    tables = db.execute(text("SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname='public' ORDER BY tablename")).scalars().all()
    quote = db.bind.dialect.identifier_preparer.quote
    return {name: db.execute(text(f'SELECT row_to_json(t)::text FROM public.{quote(name)} AS t ORDER BY 1')).scalars().all() for name in tables}


def _sequences(db):
    return dict(db.execute(text("SELECT sequencename,last_value FROM pg_catalog.pg_sequences WHERE schemaname='public' ORDER BY sequencename")).all())


def test_waste_sale_postgres_contending_http_requests(pg_sessions):  # noqa: F811
    actor, wid, control = _setup(pg_sessions)
    suffix = uuid4().hex[:10]
    headers = {'Authorization': f'Bearer {create_access_token(actor)}'}
    payload = {'buyer_name': 'Buyer', 'quantity': 6, 'unit_price': 2}
    entered = threading.Barrier(3)
    request_pids = {}
    app = _app(pg_sessions, request_pids)
    with pg_sessions() as db:
        control_before = db.execute(text('SELECT row_to_json(w)::text FROM waste_records w WHERE id=:id'), {'id': control}).scalar_one()
        notification_before = db.query(Notification).count()
        idempotency_before = db.query(IdempotencyRecord).count()
    with pg_sessions() as holder:
        holder.execute(text('SELECT id FROM waste_records WHERE id=:wid FOR UPDATE'), {'wid': wid}).one()
        holder_pid = holder.execute(text('SELECT pg_backend_pid()')).scalar_one()
        def send(key):
            with TestClient(app) as client:
                entered.wait(timeout=10)
                response = client.post(f'/waste/{wid}/sell', headers={**headers, 'Idempotency-Key': key}, json=payload)
                return key, response.status_code, response.json()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(send, f'waste-{suffix}-{n}') for n in range(2)]
            try:
                entered.wait(timeout=10)
                deadline = time.monotonic() + 10
                proven = False
                keys = [f'waste-{suffix}-{n}' for n in range(2)]
                while time.monotonic() < deadline:
                    for future in futures:
                        if future.done():
                            raise AssertionError(f'request finished before lock release: {future.result()}')
                    if all(key in request_pids for key in keys):
                        pids = [request_pids[key] for key in keys]
                        assert len(set(pids)) == 2 and holder_pid not in pids
                        with pg_sessions() as observer:
                            # Follow every blocker edge; the second waiter can be
                            # blocked behind the first waiter rather than holder.
                            def reaches_holder(start):
                                frontier = [start]
                                seen = set()
                                while frontier:
                                    current = frontier.pop()
                                    if current == holder_pid:
                                        return True
                                    if current in seen:
                                        continue
                                    seen.add(current)
                                    blockers = observer.execute(
                                        text('SELECT pg_blocking_pids(:pid)'), {'pid': current}
                                    ).scalar_one()
                                    frontier.extend(blockers)
                                return False
                            proven = all(reaches_holder(pid) for pid in pids)
                        if proven:
                            break
                    time.sleep(0.05)
                assert proven, 'both request backends did not transitively block on holder'
            finally:
                holder.rollback()
            results = [f.result(timeout=20) for f in futures]
            assert sorted(result[1] for result in results) == [200, 400]
            winner_key, _, winner_response = next(result for result in results if result[1] == 200)
    with pg_sessions() as db:
        record = db.get(WasteRecord, wid)
        assert record.status == 'received_by_waste_department'
        assert db.execute(text('SELECT row_to_json(w)::text FROM waste_records w WHERE id=:id'), {'id': control}).scalar_one() == control_before
        sale = db.query(WasteSale).filter_by(waste_record_id=wid).one()
        assert (sale.quantity, sale.unit_price, sale.total_amount) == (Decimal('6'), Decimal('2'), Decimal('12'))
        assert Decimal(str(record.quantity)) - sale.quantity == Decimal('4')
        audit = db.query(AuditLog).filter_by(entity_type='WasteRecord', entity_id=wid, action='sell').one()
        assert audit.new_value_json == {'quantity': 6.0, 'remaining_quantity': 4.0, 'amount': 12.0}
        assert db.query(IdempotencyRecord).count() == idempotency_before + 1
        stored = db.query(IdempotencyRecord).filter_by(key=winner_key).one()
        expected_payload = {'waste_record_id': wid, **WasteSaleIn(**payload).model_dump(mode='json')}
        assert stored.request_hash == request_fingerprint(expected_payload)
        assert stored.response_json == winner_response and stored.status_code == 200 and stored.user_id == actor
        assert db.query(Notification).count() == notification_before
        assert audit_service.verify_audit_hash_chain(db)['ok']


def test_waste_sale_postgres_audit_finalization_rollback(pg_sessions, monkeypatch):  # noqa: F811
    actor, wid, control = _setup(pg_sessions)
    headers = {'Authorization': f'Bearer {create_access_token(actor)}'}
    app = _app(pg_sessions)
    suffix = uuid4().hex[:10]
    payload = {'buyer_name': 'Buyer', 'quantity': 4, 'unit_price': 2}
    with pg_sessions() as db:
        before = _public_snapshot(db)
        sequences = _sequences(db)
    original = audit_service.add_audit_log_rows
    calls = []
    def fail_after_flush(db, entries):
        original(db, entries)
        db.flush()
        calls.append(len(entries))
        raise RuntimeError('injected waste audit finalization failure')
    with monkeypatch.context() as patch:
        patch.setattr(audit_service, 'add_audit_log_rows', fail_after_flush)
        with TestClient(app) as client:
            with pytest.raises(RuntimeError, match='injected waste audit finalization failure'):
                client.post(f'/waste/{wid}/sell', headers={**headers, 'Idempotency-Key': f'fail-{suffix}'}, json=payload)
    assert calls == [1]
    with pg_sessions() as db:
        assert _public_snapshot(db) == before
        after_sequences = _sequences(db)
        print('SEQUENCE_DELTAS', {name: (value, after_sequences.get(name)) for name, value in sequences.items() if after_sequences.get(name) != value})
        assert audit_service.verify_audit_hash_chain(db)['ok']
        assert db.get(WasteRecord, control).status == 'recorded'
    with TestClient(app) as client:
        result = client.post(f'/waste/{wid}/sell', headers={**headers, 'Idempotency-Key': f'retry-{suffix}'}, json=payload)
        assert result.status_code == 200, result.text
    with pg_sessions() as db:
        assert db.query(WasteSale).filter_by(waste_record_id=wid).count() == 1
        assert db.query(AuditLog).filter_by(entity_type='WasteRecord', entity_id=wid, action='sell').count() == 1
        assert audit_service.verify_audit_hash_chain(db)['ok']
