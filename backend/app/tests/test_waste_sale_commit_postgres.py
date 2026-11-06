"""Waste sale transaction and remaining-quantity coverage on migrated PostgreSQL."""
from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import event

from app.core.security import create_access_token
from app.models import audit_service
from app.schemas import AuditLog, IdempotencyRecord, Role, User, WasteRecord, WasteSale
from app.tests.test_modelsize_create_postgres import pg_sessions as pg_sessions  # noqa: F401
from app.tests.test_waste_race_rollback_postgres import _app, _public_snapshot, _setup


def test_pg_sale_deferred_commit_failure_rolls_back_replay_then_retry(pg_sessions):
    actor, wid, _ = _setup(pg_sessions)
    key = f'sale-commit-{uuid4().hex}'
    headers = {'Authorization': f'Bearer {create_access_token(actor)}', 'Idempotency-Key': key}
    payload = {'buyer_name': 'Buyer', 'quantity': 10, 'unit_price': 2}
    engine = pg_sessions.kw['bind']
    with pg_sessions() as db:
        before = _public_snapshot(db)
    with engine.begin() as conn:
        conn.exec_driver_sql("""CREATE FUNCTION pr407_sale_commit_abort() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
            RAISE EXCEPTION 'fixture commit failure' USING ERRCODE = '23514', CONSTRAINT = 'pr407_sale_commit_guard'; END; $$""")
        conn.exec_driver_sql(f"""CREATE CONSTRAINT TRIGGER pr407_sale_commit_guard AFTER INSERT ON waste_sales
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN (NEW.waste_record_id = {int(wid)})
            EXECUTE FUNCTION pr407_sale_commit_abort()""")
    observed = []
    def capture(context):
        exc = context.original_exception
        if getattr(exc, 'pgcode', None) == '23514':
            observed.append((context.statement, exc.diag.constraint_name))
    event.listen(engine, 'handle_error', capture)
    try:
        with TestClient(_app(pg_sessions), raise_server_exceptions=False) as client:
            assert client.post(f'/waste/{wid}/sell', headers=headers, json=payload).status_code == 500
        assert observed == [(None, 'pr407_sale_commit_guard')]
        with pg_sessions() as db:
            assert _public_snapshot(db) == before
            assert db.query(IdempotencyRecord).filter_by(key=key).count() == 0
            assert audit_service.verify_audit_hash_chain(db)['ok']
    finally:
        event.remove(engine, 'handle_error', capture)
        with engine.begin() as conn:
            conn.exec_driver_sql('DROP TRIGGER pr407_sale_commit_guard ON waste_sales')
            conn.exec_driver_sql('DROP FUNCTION pr407_sale_commit_abort()')
    with TestClient(_app(pg_sessions)) as client:
        response = client.post(f'/waste/{wid}/sell', headers=headers, json=payload)
        assert response.status_code == 200, response.text
        assert client.post(f'/waste/{wid}/sell', headers=headers, json=payload).json() == response.json()
    with pg_sessions() as db:
        assert db.get(WasteRecord, wid).status == 'sold'
        assert db.query(WasteSale).filter_by(waste_record_id=wid).count() == 1
        assert db.query(IdempotencyRecord).filter_by(key=key).one().response_json == response.json()
        assert db.query(AuditLog).filter_by(entity_type='WasteRecord', entity_id=wid, action='sell').count() == 1
        assert audit_service.verify_audit_hash_chain(db)['ok']


def test_pg_sale_auth_partial_then_exhaust_and_replay(pg_sessions):
    actor, wid, _ = _setup(pg_sessions)
    suffix = uuid4().hex
    with pg_sessions.begin() as db:
        role = Role(name=f'denied-sale-{suffix}', permissions=[])
        db.add(role); db.flush()
        denied = User(name='Denied seller', email=f'denied-{suffix}@example.invalid', password_hash='unused', role_id=role.id, factory_code='MIL', is_active=True)
        db.add(denied); db.flush(); denied_id = denied.id
    path = f'/waste/{wid}/sell'
    payload = {'buyer_name': 'Buyer', 'quantity': 4, 'unit_price': 2}
    headers = {'Authorization': f'Bearer {create_access_token(actor)}', 'Idempotency-Key': f'partial-{suffix}'}
    with pg_sessions() as db:
        before = _public_snapshot(db)
    with TestClient(_app(pg_sessions)) as client:
        assert client.post(path, json=payload).status_code == 401
        assert client.post(path, headers={'Authorization': f'Bearer {create_access_token(denied_id)}'}, json=payload).status_code == 403
        with pg_sessions() as db:
            assert _public_snapshot(db) == before
        first = client.post(path, headers=headers, json=payload)
        assert first.status_code == 200, first.text
        assert client.post(path, headers=headers, json=payload).json() == first.json()
        with pg_sessions() as db:
            assert db.get(WasteRecord, wid).status == 'received_by_waste_department'
            assert db.query(WasteSale).filter_by(waste_record_id=wid).one().quantity == Decimal('4')
        second = client.post(path, headers={**headers, 'Idempotency-Key': f'exhaust-{suffix}'}, json={**payload, 'quantity': 6})
        assert second.status_code == 200, second.text
    with pg_sessions() as db:
        assert db.get(WasteRecord, wid).status == 'sold'
        sales = db.query(WasteSale).filter_by(waste_record_id=wid).order_by(WasteSale.id).all()
        assert [row.quantity for row in sales] == [Decimal('4'), Decimal('6')]
        assert [row.total_amount for row in sales] == [Decimal('8'), Decimal('12')]
        assert db.query(AuditLog).filter_by(entity_type='WasteRecord', entity_id=wid, action='sell').count() == 2
        assert db.query(IdempotencyRecord).filter(IdempotencyRecord.key.in_([f'partial-{suffix}', f'exhaust-{suffix}'])).count() == 2
        assert audit_service.verify_audit_hash_chain(db)['ok']
