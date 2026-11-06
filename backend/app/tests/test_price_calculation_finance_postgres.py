"""Signed finance updates on an approved migrated PostgreSQL fixture."""
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.models import audit_service
from app.schemas import AuditLog, Model, Notification, PriceCalculationRequest
from app.tests.test_price_calculation_purchasing_postgres import _create_case, customer_pg_sessions  # noqa: F401
from app.tests.test_price_calculation_status_postgres import app_for, auth


def complete_costs(sessions, rid):
    with sessions.begin() as db:
        row = db.get(PriceCalculationRequest, rid)
        row.kroy_no = 'SYNTHETIC'
        row.fabric_width_m = 1
        row.lay_length_m = 2
        row.size_count = 3
        row.gramage = 4
        row.binding_kg_per_piece = 0
        row.fabric_price = 2
        row.sewing_cost = 3
        row.accessories_json = [{'name': 'тугма 🧵', 'price': 1}]


def effects(db, rid, mid):
    return db.query(AuditLog).filter(
        ((AuditLog.entity_type == 'PriceCalculationRequest') & (AuditLog.entity_id == rid) & (AuditLog.action == 'update_finance_price')) |
        ((AuditLog.entity_type == 'Model') & (AuditLog.entity_id == mid) & (AuditLog.action == 'attach_selling_price'))
    ).order_by(AuditLog.id).all()


def test_signed_finance_refusal_omission_null_and_attachment(customer_pg_sessions):
    sessions = customer_pg_sessions
    case = _create_case(sessions)
    rid = case['request_id']
    url = f'/api/price-calculation/requests/{rid}/finance'
    with sessions() as retained:
        request = retained.get(PriceCalculationRequest, rid)
        mid = request.model_id
        model = retained.get(Model, mid)
        notices = retained.query(Notification).count()
        with TestClient(app_for(sessions), raise_server_exceptions=False) as client:
            assert client.patch(url, json={'selling_price': 12}).status_code == 401
            assert client.patch(url, headers=auth(case['purchaser_id']), json={'selling_price': 12}).status_code == 403
            assert client.patch('/api/price-calculation/requests/2147483647/finance', headers=auth(case['purchaser_id']), json={}).status_code == 403
            assert client.patch('/api/price-calculation/requests/2147483647/finance', headers=auth(case['finance_id']), json={}).status_code == 404
            assert client.patch(url, headers=auth(case['finance_id']), json={'selling_price': 12}).status_code == 409
            with sessions() as check:
                assert check.get(PriceCalculationRequest, rid).selling_price is None
                assert effects(check, rid, mid) == []
            complete_costs(sessions, rid)
            response = client.patch(url, headers=auth(case['finance_id']), json={'selling_price': 12.3456, 'exchange_rate': 100})
            assert response.status_code == 200, response.text
            response = client.patch(url, headers=auth(case['finance_id']), json={'exchange_rate': None})
            assert response.status_code == 200, response.text
            response = client.patch(url, headers=auth(case['finance_id']), json={'selling_price': None})
            assert response.status_code == 200, response.text
        retained.expire_all()
        assert request.selling_price is None and request.exchange_rate is None
        assert request.finance_updated_by_id == case['finance_id']
        assert (model.selling_price, model.selling_price_currency, model.selling_price_source, model.selling_price_request_id) == (Decimal('12.3456'), 'USD', 'price_request', rid)
        assert model.selling_price_updated_at is not None
        audits = effects(retained, rid, mid)
        assert len(audits) == 4 and len({a.id for a in audits}) == 4
        assert all(a.user_id == case['finance_id'] and a.entry_hash for a in audits)
        finance = [a for a in audits if a.action == 'update_finance_price']
        assert [a.new_value_json for a in finance] == [{'selling_price': 12.3456, 'exchange_rate': 100.0}, {'exchange_rate': None}, {'selling_price': None}]
        assert retained.query(Notification).count() == notices


@pytest.mark.parametrize('fault', ['audit', 'commit'])
def test_signed_finance_rollback_and_retry(customer_pg_sessions, monkeypatch, fault):
    sessions = customer_pg_sessions
    case = _create_case(sessions)
    rid = case['request_id']
    complete_costs(sessions, rid)
    with sessions() as db:
        mid = db.get(PriceCalculationRequest, rid).model_id
        assert effects(db, rid, mid) == []
        notices = db.query(Notification).count()
    engine = sessions.kw['bind']
    suffix = uuid4().hex[:12]
    trigger, function = f'pr391_guard_{suffix}', f'pr391_abort_{suffix}'
    attempted, observed = [], []
    finalize = audit_service._finalize_postgres_audits
    def observe_finalize(db):
        finalize(db)
        audits = effects(db, rid, mid)
        assert len(audits) == 2 and all(a.id > 0 and a.entry_hash for a in audits)
        assert {a.action for a in audits} == {'update_finance_price', 'attach_selling_price'}
        attempted.extend(a.id for a in audits)
        observed.append('finalized')
        if fault == 'audit':
            raise RuntimeError('injected after audit finalization')
    def capture(context):
        exc = context.original_exception
        if getattr(exc, 'pgcode', None) == '23514':
            observed.append((context.statement, exc.diag.constraint_name))
    if fault == 'commit':
        try:
            with engine.begin() as conn:
                conn.exec_driver_sql(f"""CREATE FUNCTION {function}() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
                    RAISE EXCEPTION 'fixture commit failure' USING ERRCODE = '23514', CONSTRAINT = '{trigger}'; END; $$""")
                conn.exec_driver_sql(f"""CREATE CONSTRAINT TRIGGER {trigger} AFTER UPDATE ON price_calculation_requests
                    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN (NEW.id = {int(rid)}) EXECUTE FUNCTION {function}()""")
            event.listen(engine, 'handle_error', capture)
        except Exception as exc:
            raise RuntimeError(f'HOLD: uncertain setup; inspect {trigger} and {function}') from exc
    url = f'/api/price-calculation/requests/{rid}/finance'
    try:
        with monkeypatch.context() as patch:
            patch.setattr(audit_service, '_finalize_postgres_audits', observe_finalize)
            with TestClient(app_for(sessions), raise_server_exceptions=False) as client:
                assert client.patch(url, headers=auth(case['finance_id']), json={'selling_price': 23.45}).status_code == 500
        assert observed == (['finalized'] if fault == 'audit' else ['finalized', (None, trigger)])
        assert len(attempted) == len(set(attempted)) == 2
        with sessions() as db:
            request, model = db.get(PriceCalculationRequest, rid), db.get(Model, mid)
            assert request.selling_price is None and request.finance_updated_by_id is None
            assert model.selling_price is None and model.selling_price_request_id is None
            assert effects(db, rid, mid) == []
            assert all(db.get(AuditLog, audit_id) is None for audit_id in attempted)
            assert db.query(Notification).count() == notices
    finally:
        if fault == 'commit':
            event.remove(engine, 'handle_error', capture)
            with engine.begin() as conn:
                conn.exec_driver_sql(f'DROP TRIGGER {trigger} ON price_calculation_requests')
                conn.exec_driver_sql(f'DROP FUNCTION {function}()')
    with TestClient(app_for(sessions), raise_server_exceptions=False) as client:
        response = client.patch(url, headers=auth(case['finance_id']), json={'selling_price': 23.45})
        assert response.status_code == 200, response.text
    with sessions() as db:
        request, model = db.get(PriceCalculationRequest, rid), db.get(Model, mid)
        assert request.selling_price == Decimal('23.4500') and request.finance_updated_by_id == case['finance_id']
        assert (model.selling_price, model.selling_price_currency, model.selling_price_source, model.selling_price_request_id) == (Decimal('23.4500'), 'USD', 'price_request', rid)
        audits = effects(db, rid, mid)
        assert len(audits) == 2 and all(a.id > 0 and a.id not in attempted and a.entry_hash for a in audits)
        assert all(a.user_id == case['finance_id'] for a in audits)
        assert db.query(Notification).count() == notices


def test_concurrent_finance_updates_wait_and_last_writer_wins(customer_pg_sessions, monkeypatch):
    """Observe the second real request UPDATE waiting on the first transaction."""
    import sys
    import threading
    import time
    from sqlalchemy import text
    from app.models.planning import costing_service
    from app.tests.pg_approved_instance import _park

    sessions = customer_pg_sessions
    case = _create_case(sessions)
    rid = case['request_id']
    complete_costs(sessions, rid)
    with sessions() as db:
        mid = db.get(PriceCalculationRequest, rid).model_id
        notices = db.query(Notification).count()
    both_loaded, first_flushed, release = threading.Event(), threading.Event(), threading.Event()
    pids, responses, failures = {}, {}, []
    original = costing_service.apply_finance_contribution
    def coordinate(db, request, changes, *, updated_by_id):
        name = 'first' if changes['selling_price'] == 11 else 'second'
        pids[name] = db.scalar(text('select pg_backend_pid()'))
        if name == 'first':
            if not both_loaded.wait(10):
                raise RuntimeError('second request did not load within bound')
            original(db, request, changes, updated_by_id=updated_by_id)
            def hold(session, _context):
                first_flushed.set()
                if not release.wait(20):
                    raise RuntimeError('first writer release timed out')
            event.listen(db, 'after_flush', hold, once=True)
        else:
            both_loaded.set()
            if not first_flushed.wait(10):
                raise RuntimeError('first update did not flush within bound')
            original(db, request, changes, updated_by_id=updated_by_id)
    def send(name, price):
        try:
            with TestClient(app_for(sessions), raise_server_exceptions=False) as client:
                responses[name] = client.patch(f'/api/price-calculation/requests/{rid}/finance',
                    headers=auth(case['finance_id']), json={'selling_price': price})
        except BaseException as exc:
            failures.append(exc)
    monkeypatch.setattr(costing_service, 'apply_finance_contribution', coordinate)
    first = threading.Thread(target=send, args=('first', 11), daemon=True)
    second = threading.Thread(target=send, args=('second', 22), daemon=True)
    first.start(); second.start()
    try:
        assert first_flushed.wait(10)
        deadline = time.monotonic() + 10
        blocked = False
        with sessions() as observer:
            while time.monotonic() < deadline:
                if pids.get('second') and observer.scalar(text('select :holder = any(pg_blocking_pids(:waiter))'),
                        {'holder': pids['first'], 'waiter': pids['second']}):
                    blocked = True
                    break
                time.sleep(0.05)
        assert blocked, f'owned backend did not wait: {pids}'
    finally:
        release.set()
        first.join(25); second.join(25)
        if first.is_alive() or second.is_alive():
            active = sys.exc_info()[1]
            errors = ([active] if active else []) + failures
            _park('PR391_FINANCE_WRITERS_UNKNOWN', (sessions, first, second, release, pids, responses), errors)
            raise RuntimeError('HOLD observer unexpectedly returned')
    assert not failures and set(responses) == {'first', 'second'}
    assert all(response.status_code == 200 for response in responses.values())
    with sessions() as db:
        request, model = db.get(PriceCalculationRequest, rid), db.get(Model, mid)
        assert request.selling_price == Decimal('22.0000')
        assert (model.selling_price, model.selling_price_currency, model.selling_price_source, model.selling_price_request_id) == (Decimal('22.0000'), 'USD', 'price_request', rid)
        audits = effects(db, rid, mid)
        assert len(audits) == 4 and len({a.id for a in audits}) == 4
        assert [a.new_value_json['selling_price'] for a in audits if a.action == 'update_finance_price'] == [11.0, 22.0]
        assert db.query(Notification).count() == notices
