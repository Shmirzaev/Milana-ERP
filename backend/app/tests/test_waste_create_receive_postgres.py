"""Public create/receive persistence and rollback on an owned PostgreSQL DB."""
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.routes.waste import router
from app.core.deps import get_db
from app.core.security import create_access_token
from app.models import audit_service
from app.schemas import AuditLog, Item, Notification, Role, StockBatch, User, Warehouse, WasteRecord
from app.tests.test_modelsize_create_postgres import pg_sessions as pg_sessions  # noqa: F401


def _public_snapshot(db):
    tables = db.execute(text("SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname='public' ORDER BY tablename")).scalars().all()
    quote = db.bind.dialect.identifier_preparer.quote
    return {name: db.execute(text(f'SELECT row_to_json(t)::text FROM public.{quote(name)} AS t ORDER BY 1')).scalars().all() for name in tables}


def _sequences(db):
    return dict(db.execute(text("SELECT sequencename,last_value FROM pg_catalog.pg_sequences WHERE schemaname='public' ORDER BY sequencename")).all())


def _seed(sessions):
    suffix = uuid4().hex[:10]
    with sessions.begin() as db:
        allowed = Role(name=f'waste-create-{suffix}', permissions=['waste.receive'])
        denied = Role(name=f'waste-denied-{suffix}', permissions=[])
        db.add_all([allowed, denied])
        db.flush()
        actor = User(name='Waste actor', email=f'actor-{suffix}@example.invalid', password_hash='unused', role_id=allowed.id, factory_code='MIL', is_active=True)
        other = User(name='Waste denied', email=f'denied-{suffix}@example.invalid', password_hash='unused', role_id=denied.id, factory_code='MIL', is_active=True)
        item = Item(sku=f'WASTE-{suffix}', name='Fabric', category='fabric', unit='kg', default_cost=Decimal('2'))
        warehouse = Warehouse(name=f'waste-{suffix}', type='fabric_storage')
        db.add_all([actor, other, item, warehouse])
        db.flush()
        batch = StockBatch(item_id=item.id, warehouse_id=warehouse.id, batch_no=f'WB-{suffix}', quantity=Decimal('50'), unit='kg', cost_per_unit=Decimal('3.25'))
        db.add(batch)
        db.flush()
        return actor.id, other.id, item.id, batch.id


def _app(sessions):
    app = FastAPI()
    app.include_router(router)

    def isolated_db():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = isolated_db
    return app


def _batch_row(db, batch_id):
    return db.execute(text('SELECT row_to_json(b)::text FROM stock_batches b WHERE id=:id'), {'id': batch_id}).scalar_one()


def _refusal_without_public_writes(client, sessions, path, headers, expected, payload=None):
    with sessions() as db:
        before = _public_snapshot(db)
        sequences_before = _sequences(db)
    response = client.post(path, headers=headers, json=payload)
    assert response.status_code == expected
    with sessions() as db:
        assert _public_snapshot(db) == before
        sequences_after = _sequences(db)
        print('REFUSAL_SEQUENCE_DELTAS', {name: (value, sequences_after.get(name)) for name, value in sequences_before.items() if sequences_after.get(name) != value})
        assert audit_service.verify_audit_hash_chain(db)['ok']


def _post_with_sequence_observation(client, sessions, path, headers, payload=None):
    with sessions() as db:
        before = _sequences(db)
    response = client.post(path, headers=headers, json=payload)
    with sessions() as db:
        after = _sequences(db)
    print('SUCCESS_SEQUENCE_DELTAS', {name: (value, after.get(name)) for name, value in before.items() if after.get(name) != value})
    return response


@pytest.mark.parametrize('operation', ['create', 'receive'])
def test_waste_create_receive_audit_failure_rolls_back_then_retry(pg_sessions, monkeypatch, operation):  # noqa: F811
    actor, denied, item_id, batch_id = _seed(pg_sessions)
    headers = {'Authorization': f'Bearer {create_access_token(actor)}'}
    denied_headers = {'Authorization': f'Bearer {create_access_token(denied)}'}
    payload = {'item_id': item_id, 'batch_id': batch_id, 'waste_type': 'cutting', 'quantity': 4, 'unit': 'kg', 'sellable': True}
    app = _app(pg_sessions)
    with pg_sessions() as db:
        batch_before = _batch_row(db, batch_id)
        notifications_before = db.query(Notification).count()
    with TestClient(app) as client:
        _refusal_without_public_writes(client, pg_sessions, '/waste', denied_headers, 403, payload)
        if operation == 'receive':
            created = _post_with_sequence_observation(client, pg_sessions, '/waste', headers, payload)
            assert created.status_code == 201, created.text
            wid = created.json()['id']
            _refusal_without_public_writes(client, pg_sessions, f'/waste/{wid}/receive', denied_headers, 403)
            path = f'/waste/{wid}/receive'
        else:
            path = '/waste'
        with pg_sessions() as db:
            before = _public_snapshot(db)
            sequences_before = _sequences(db)
        original = audit_service.add_audit_log_rows
        calls = []

        def fail_after_flush(db, entries):
            original(db, entries)
            db.flush()
            calls.append(len(entries))
            raise RuntimeError('injected create/receive audit finalization failure')

        with monkeypatch.context() as patch:
            patch.setattr(audit_service, 'add_audit_log_rows', fail_after_flush)
            with pytest.raises(RuntimeError, match='injected create/receive audit finalization failure'):
                client.post(path, headers=headers, json=payload if operation == 'create' else None)
        assert calls == [1]
        with pg_sessions() as db:
            assert _public_snapshot(db) == before
            sequences_after = _sequences(db)
            print('SEQUENCE_DELTAS', {name: (value, sequences_after.get(name)) for name, value in sequences_before.items() if sequences_after.get(name) != value})
            assert _batch_row(db, batch_id) == batch_before
            assert db.query(Notification).count() == notifications_before
            assert audit_service.verify_audit_hash_chain(db)['ok']
        # The failed transaction is known rolled back before this new request.
        result = _post_with_sequence_observation(client, pg_sessions, path, headers, payload if operation == 'create' else None)
        assert result.status_code == (201 if operation == 'create' else 200), result.text
        if operation == 'create':
            wid = result.json()['id']
            received = _post_with_sequence_observation(client, pg_sessions, f'/waste/{wid}/receive', headers)
            assert received.status_code == 200, received.text
        _refusal_without_public_writes(client, pg_sessions, f'/waste/{wid}/receive', headers, 400)
        _refusal_without_public_writes(client, pg_sessions, '/waste/2147483647/receive', headers, 404)
    with pg_sessions() as db:
        record = db.get(WasteRecord, wid)
        assert record.item_id == item_id and record.batch_id == batch_id
        assert record.quantity == Decimal('4') and record.estimated_value == Decimal('13')
        assert record.created_by == actor and record.status == 'received_by_waste_department'
        assert _batch_row(db, batch_id) == batch_before
        assert db.query(Notification).count() == notifications_before
        audits = db.query(AuditLog).filter_by(entity_type='WasteRecord', entity_id=wid).order_by(AuditLog.id).all()
        assert [entry.action for entry in audits] == ['create', 'receive']
        assert all(entry.user_id == actor and entry.entry_hash for entry in audits)
        assert audit_service.verify_audit_hash_chain(db)['ok']
