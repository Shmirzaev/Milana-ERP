"""Cutting-price signed requests on the owned migrated PostgreSQL fixture."""
from collections import Counter
from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient

from app.schemas import AuditLog, CuttingPassport, Notification, PriceCalculationRequest
from app.tests.test_price_calculation_purchasing_postgres import (
    _create_case, _eligible_finance_ids, customer_pg_sessions,  # noqa: F401
)
from app.tests.test_price_calculation_status_postgres import app_for, auth


def _effects(db, case):
    audits = db.query(AuditLog).filter_by(entity_type='PriceCalculationRequest', entity_id=case['request_id'], action='update_cutting_price_details').order_by(AuditLog.id).all()
    notices = db.query(Notification).filter_by(title='Cutting details completed', message=f"Model {case['model_code']} price request was updated.", link='/finance/price-calculation').all()
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
            original = (initial.kroy_no, initial.cutting_passport_id, initial.fabric_width_m, initial.lay_length_m, initial.size_count, initial.gramage, initial.binding_kg_per_piece)
            assert _effects(db, case) == ([], [])
        assert case['finance_id'] in recipients
        observed, attempted_audit_ids, attempted_request_ids = [], [], []
        notify = pricing._notify_finance
        finalize = audit_service._finalize_postgres_audits
        suffix = uuid4().hex[:12]
        trigger, function = f'pr399_guard_{suffix}', f'pr399_abort_{suffix}'

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
        url = f'/api/price-calculation/requests/{rid}/cutting'
        payload = {'kroy_no': 'MANUAL', 'fabric_width_m': 1, 'lay_length_m': 2, 'size_count': 3, 'gramage': 4, 'binding_kg_per_piece': 0}
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
                assert (row.kroy_no, row.cutting_passport_id, row.fabric_width_m, row.lay_length_m, row.size_count, row.gramage, row.binding_kg_per_piece) == original
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
            assert (row.kroy_no, row.fabric_width_m, row.lay_length_m, row.size_count, row.gramage, row.binding_kg_per_piece) == ('MANUAL', 1, 2, 3, 4, 0)
            assert len(audits) == 1 and audits[0].id not in attempted_audit_ids
            assert audits[0].user_id == case['wildcard_id'] and audits[0].new_value_json == {**payload, 'cutting_passport_id': None}
            assert Counter(n.user_id for n in notices) == Counter(recipients)


def test_signed_passport_manual_refusals_and_readback(customer_pg_sessions):
    sessions = customer_pg_sessions
    case = _create_case(sessions)
    rid = case['request_id']
    token = uuid4().hex[:20]
    with sessions.begin() as db:
        valid = CuttingPassport(passport_no=token, date=datetime.now(timezone.utc), model_code=case['model_code'],
            size_range='44-48', fabric_width_m=1.5, lay_length_m=None, gramage=180,
            beka_per_piece_kg=0, other_beka_per_piece_kg=0)
        wrong = CuttingPassport(passport_no=token + 'w', date=datetime.now(timezone.utc), model_code='OTHER')
        metre = CuttingPassport(passport_no=token + 'm', date=datetime.now(timezone.utc), model_code=case['model_code'], materials=[{'meter_mode': True}])
        db.add_all([valid, wrong, metre]); db.flush()
        passport_id = valid.id
    url = f'/api/price-calculation/requests/{rid}/cutting'
    headers = auth(case['wildcard_id'])
    payload = {'kroy_no': token, 'fabric_width_m': 2, 'lay_length_m': 3, 'size_count': 9, 'gramage': 200, 'binding_kg_per_piece': 0.5}
    with sessions() as retained:
        recipients = _eligible_finance_ids(retained)
        row = retained.get(PriceCalculationRequest, rid)
        with TestClient(app_for(sessions), raise_server_exceptions=False) as client:
            assert client.patch(url, json=payload).status_code == 401
            missing = '/api/price-calculation/requests/2147483647/cutting'
            assert client.patch(missing, headers=auth(case['purchaser_id']), json=payload).status_code == 403
            assert client.patch(missing, headers=headers, json=payload).status_code == 404
            assert client.patch(url, headers=headers, json={**payload, 'fabric_width_m': 0}).status_code == 422
            for number, status in [(token + 'w', 409), (token + 'm', 400)]:
                assert client.patch(url, headers=headers, json={**payload, 'kroy_no': number}).status_code == status
            retained.expire_all()
            assert row.kroy_no is None and _effects(retained, case) == ([], [])
            response = client.patch(url, headers=headers, json=payload)
            assert response.status_code == 200, response.text
            assert response.json()['cutting_status'] == 'complete'
        retained.expire_all()
        assert (row.cutting_passport_id, float(row.fabric_width_m), float(row.lay_length_m), row.size_count, float(row.gramage), float(row.binding_kg_per_piece)) == (passport_id, 1.5, 3, 3, 180, 0)
        audits, notices = _effects(retained, case)
        assert len(audits) == 1 and audits[0].new_value_json == {**payload, 'cutting_passport_id': passport_id}
        assert Counter(n.user_id for n in notices) == Counter(recipients)
        with TestClient(app_for(sessions), raise_server_exceptions=False) as client:
            result = client.patch(url, headers=headers, json={'kroy_no': token + 'none'})
            assert result.status_code == 200, result.text
            assert result.json()['cutting_status'] == 'in_progress'
        retained.expire_all()
        assert (row.cutting_passport_id, row.fabric_width_m, row.lay_length_m, row.size_count, row.gramage, row.binding_kg_per_piece) == (None, None, None, None, None, None)
        assert len(_effects(retained, case)[0]) == 2


def test_concurrent_passport_update_uses_visible_committed_snapshot(customer_pg_sessions):
    """An uncommitted passport edit does not prevent the request reading its old value."""
    import sys
    import threading
    from sqlalchemy import text
    from app.tests.pg_approved_instance import _park

    sessions = customer_pg_sessions
    case = _create_case(sessions)
    number = uuid4().hex[:20]
    with sessions.begin() as db:
        passport = CuttingPassport(passport_no=number, date=datetime.now(timezone.utc), model_code=case['model_code'],
                                   size_range='44-48', fabric_width_m=1, lay_length_m=2, gramage=4, beka_per_piece_kg=0)
        db.add(passport); db.flush()
        passport_id = passport.id
    ready, release = threading.Event(), threading.Event()
    pids, failures = {}, []

    def edit_passport():
        try:
            with sessions.begin() as db:
                pids['passport'] = db.execute(text('select pg_backend_pid()')).scalar_one()
                row = db.get(CuttingPassport, passport_id)
                row.fabric_width_m = 5
                db.flush()
                ready.set()
                if not release.wait(20):
                    raise RuntimeError('observer did not release passport writer')
        except BaseException as exc:
            failures.append(exc)
            ready.set()

    writer = threading.Thread(target=edit_passport, daemon=True)
    writer.start()
    try:
        assert ready.wait(10) and not failures, failures
        with TestClient(app_for(sessions), raise_server_exceptions=False) as client:
            response = client.patch(f"/api/price-calculation/requests/{case['request_id']}/cutting",
                                    headers=auth(case['wildcard_id']), json={'kroy_no': number})
            assert response.status_code == 200, response.text
            assert response.json()['cutting_status'] == 'complete'
        with sessions() as db:
            row = db.get(PriceCalculationRequest, case['request_id'])
            assert row.cutting_passport_id == passport_id and row.fabric_width_m == 1
            audits, notices = _effects(db, case)
            assert len(audits) == 1 and audits[0].new_value_json['kroy_no'] == number
            assert Counter(n.user_id for n in notices) == Counter(_eligible_finance_ids(db))
    finally:
        release.set()
        writer.join(20)
        if writer.is_alive():
            active_error = sys.exc_info()[1]
            errors = [active_error] if active_error is not None else []
            errors.extend(failures)
            _park('PR399_PASSPORT_WRITER_UNKNOWN', (sessions, writer, ready, release, pids, failures), errors)
            raise RuntimeError('HOLD observer unexpectedly returned')
    assert not failures, failures
    with sessions() as db:
        assert db.get(CuttingPassport, passport_id).fabric_width_m == 5
        assert db.get(PriceCalculationRequest, case['request_id']).fabric_width_m == 1
