"""Signed accessory transitions against the migrated PostgreSQL fixture."""
from collections import Counter

from fastapi.testclient import TestClient

from app.schemas import AuditLog, Notification, PriceCalculationRequest
from app.tests.test_price_calculation_purchasing_postgres import (
    _create_case, _eligible_finance_ids, customer_pg_sessions,  # noqa: F401
)
from app.tests.test_price_calculation_status_postgres import app_for, auth


def test_signed_accessory_transitions_and_retained_readback(customer_pg_sessions):
    sessions = customer_pg_sessions
    case = _create_case(sessions)
    rid = case['request_id']
    url = f'/api/price-calculation/requests/{rid}/accessories'
    missing = '/api/price-calculation/requests/2147483647/accessories'
    admin = auth(case['wildcard_id'])
    denied = auth(case['purchaser_id'])
    with sessions() as retained:
        recipients = _eligible_finance_ids(retained)
        row = retained.get(PriceCalculationRequest, rid)
        with TestClient(app_for(sessions), raise_server_exceptions=False) as client:
            assert client.patch(url, json={}).status_code == 401
            assert client.patch(missing, headers=denied, json={}).status_code == 403
            assert client.patch(missing, headers=admin, json={}).status_code == 404
            assert client.patch(url, headers=admin, json={'accessories': [{'name': 'a', 'price': 1}] * 5}).status_code == 422
            for payload, expected, status in [
                ({'accessories': [{'name': ' Button ', 'price': 0}]}, [{'name': 'Button', 'price': 0}], 'in_progress'),
                ({'accessories': [{'name': 'Button', 'price': 1}]}, [{'name': 'Button', 'price': 1}], 'complete'),
                ({}, [], 'new'),
                ({'accessories': [{'name': 'Button', 'price': 2}]}, [{'name': 'Button', 'price': 2}], 'complete'),
            ]:
                response = client.patch(url, headers=admin, json=payload)
                assert response.status_code == 200, response.text
                assert response.json()['accessories'] == expected
                assert response.json()['accessories_status'] == status
        retained.expire_all()
        assert row.accessories_json == [{'name': 'Button', 'price': 2}]
        assert row.accessories_updated_by_id == case['wildcard_id']
        audits = retained.query(AuditLog).filter_by(entity_type='PriceCalculationRequest', entity_id=rid, action='update_accessory_costs').order_by(AuditLog.id).all()
        assert len(audits) == 4 and len({a.id for a in audits}) == 4
        assert [a.new_value_json['accessories'] for a in audits] == [
            [{'name': 'Button', 'price': 0}], [{'name': 'Button', 'price': 1}], [], [{'name': 'Button', 'price': 2}],
        ]
        notices = retained.query(Notification).filter_by(title='Accessory costs completed', message=f"Model {case['model_code']} price request was updated.", link='/finance/price-calculation').all()
        assert Counter(n.user_id for n in notices) == Counter({user_id: 2 for user_id in recipients})


def _effects(db, case):
    audits = db.query(AuditLog).filter_by(entity_type='PriceCalculationRequest', entity_id=case['request_id'], action='update_accessory_costs').order_by(AuditLog.id).all()
    notices = db.query(Notification).filter_by(title='Accessory costs completed', message=f"Model {case['model_code']} price request was updated.", link='/finance/price-calculation').all()
    return audits, notices


def test_signed_failure_rollback_and_retry(customer_pg_sessions, monkeypatch):
    from sqlalchemy import event
    from uuid import uuid4
    from app.models import audit_service
    from app.models import price_calculation_service as pricing

    sessions = customer_pg_sessions
    engine = sessions.kw['bind']
    for fault in ('notification', 'audit', 'commit'):
        case = _create_case(sessions)
        rid = case['request_id']
        with sessions() as db:
            recipients = _eligible_finance_ids(db)
            initial = db.get(PriceCalculationRequest, rid)
            original = (initial.accessories_json, initial.accessories_updated_by_id)
            assert _effects(db, case) == ([], [])
        assert case['finance_id'] in recipients
        observed, attempted_audit_ids, attempted_request_ids = [], [], []
        notify = pricing._notify_finance
        finalize = audit_service._finalize_postgres_audits
        suffix = uuid4().hex[:12]
        trigger, function = f'pr400_guard_{suffix}', f'pr400_abort_{suffix}'

        def observe_notification(db, request, title):
            attempted_request_ids.append(request.id)
            notify(db, request, title)
            db.flush()
            assert Counter(n.user_id for n in _effects(db, case)[1]) == Counter(recipients)
            if fault == 'notification':
                observed.append('notification_flushed')
                raise RuntimeError('injected after notification flush')

        def observe_finalize(db):
            finalize(db)
            audits, notices = _effects(db, case)
            assert len(audits) == 1 and audits[0].id is not None
            assert Counter(n.user_id for n in notices) == Counter(recipients)
            attempted_audit_ids.append(audits[0].id)
            observed.append('audit_finalized')
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
                raise RuntimeError(f'HOLD: uncertain fixture setup; inspect owned {trigger} and {function}') from exc
        url = f'/api/price-calculation/requests/{rid}/accessories'
        payload = {'accessories': [{'name': 'Button', 'price': 3}]}
        try:
            with monkeypatch.context() as patch:
                patch.setattr(pricing, '_notify_finance', observe_notification)
                patch.setattr(audit_service, '_finalize_postgres_audits', observe_finalize)
                with TestClient(app_for(sessions), raise_server_exceptions=False) as client:
                    assert client.patch(url, headers=auth(case['wildcard_id']), json=payload).status_code == 500
            assert attempted_request_ids == [rid]
            if fault == 'notification':
                assert observed == ['notification_flushed'] and attempted_audit_ids == []
            elif fault == 'audit':
                assert observed == ['audit_finalized'] and len(attempted_audit_ids) == 1
            else:
                assert observed == ['audit_finalized', (None, trigger)] and len(attempted_audit_ids) == 1
            with sessions() as db:
                row = db.get(PriceCalculationRequest, rid)
                assert (row.accessories_json, row.accessories_updated_by_id) == original
                assert _effects(db, case) == ([], [])
                assert all(db.get(AuditLog, audit_id) is None for audit_id in attempted_audit_ids)
        finally:
            if fault == 'commit':
                event.remove(engine, 'handle_error', capture)
                with engine.begin() as conn:
                    conn.exec_driver_sql(f'DROP TRIGGER {trigger} ON price_calculation_requests')
                    conn.exec_driver_sql(f'DROP FUNCTION {function}()')
        with TestClient(app_for(sessions), raise_server_exceptions=False) as client:
            retry = client.patch(url, headers=auth(case['wildcard_id']), json=payload)
            assert retry.status_code == 200, retry.text
        with sessions() as db:
            row = db.get(PriceCalculationRequest, rid)
            audits, notices = _effects(db, case)
            assert row.accessories_json == payload['accessories'] and row.accessories_updated_by_id == case['wildcard_id']
            assert len(audits) == 1 and audits[0].id not in attempted_audit_ids
            assert audits[0].user_id == case['wildcard_id'] and audits[0].new_value_json == {'accessories': payload['accessories']}
            assert Counter(n.user_id for n in notices) == Counter(recipients)


def test_concurrent_unlocked_updates_characterize_stale_completion(customer_pg_sessions, monkeypatch):
    """Both requests read NEW; the second UPDATE waits, then also emits completion."""
    import sys
    import threading
    import time
    from sqlalchemy import text
    from app.tests.pg_approved_instance import _park
    from app.models import price_calculation_service as pricing

    sessions = customer_pg_sessions
    case = _create_case(sessions)
    rid = case['request_id']
    with sessions() as db:
        recipients = _eligible_finance_ids(db)
    assert case['finance_id'] in recipients
    both_loaded, first_flushed, release = threading.Event(), threading.Event(), threading.Event()
    pids, responses, failures = {}, {}, []
    original_apply = pricing.apply_accessory_contribution

    def coordinate(db, request, rows, *, updated_by_id):
        name = rows[0]['name']
        pids[name] = db.execute(text('select pg_backend_pid()')).scalar_one()
        if name == 'first':
            if not both_loaded.wait(10):
                raise RuntimeError('second request did not load within bound')
            original_apply(db, request, rows, updated_by_id=updated_by_id)
            first_flushed.set()
            if not release.wait(15):
                raise RuntimeError('observer did not release first writer within bound')
        else:
            both_loaded.set()
            if not first_flushed.wait(10):
                raise RuntimeError('first update did not flush within bound')
            original_apply(db, request, rows, updated_by_id=updated_by_id)

    def send(name, price):
        try:
            with TestClient(app_for(sessions), raise_server_exceptions=False) as client:
                responses[name] = client.patch(f'/api/price-calculation/requests/{rid}/accessories',
                    headers=auth(case['wildcard_id']), json={'accessories': [{'name': name, 'price': price}]})
        except BaseException as exc:
            failures.append(exc)

    monkeypatch.setattr(pricing, 'apply_accessory_contribution', coordinate)
    first = threading.Thread(target=send, args=('first', 1), daemon=True)
    second = threading.Thread(target=send, args=('second', 2), daemon=True)
    first.start()
    second.start()
    blocked = False
    try:
        assert first_flushed.wait(10), 'first update did not flush'
        deadline = time.monotonic() + 10
        with sessions() as observer:
            while time.monotonic() < deadline:
                if pids.get('second') and observer.execute(text('select :holder = any(pg_blocking_pids(:waiter))'),
                        {'holder': pids['first'], 'waiter': pids['second']}).scalar_one():
                    blocked = True
                    break
                time.sleep(0.05)
        assert blocked, f'owned second backend did not block on first: {pids}'
    finally:
        release.set()
        first.join(20)
        second.join(20)
        if first.is_alive() or second.is_alive():
            active_error = sys.exc_info()[1]
            errors = [active_error] if active_error is not None else []
            errors.extend(failures)
            _park('PR400_CONCURRENT_WRITERS_UNKNOWN',
                  (sessions, first, second, both_loaded, first_flushed, release, pids, responses, failures), errors)
            raise RuntimeError('HOLD observer unexpectedly returned')
    assert not failures, failures
    assert set(responses) == {'first', 'second'}
    assert all(r.status_code == 200 for r in responses.values()), {k: v.text for k, v in responses.items()}
    with sessions() as db:
        row = db.get(PriceCalculationRequest, rid)
        audits, notices = _effects(db, case)
        assert row.accessories_json == [{'name': 'second', 'price': 2}]
        assert row.accessories_updated_by_id == case['wildcard_id']
        assert len(audits) == 2 and len({a.id for a in audits}) == 2
        assert [a.new_value_json['accessories'] for a in audits] == [[{'name': 'first', 'price': 1}], [{'name': 'second', 'price': 2}]]
        assert Counter(n.user_id for n in notices) == Counter({user_id: 2 for user_id in recipients})
