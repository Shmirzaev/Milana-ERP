"""Cutting-price signed requests on the owned migrated PostgreSQL fixture."""
from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient

from app.schemas import AuditLog, CuttingPassport, Notification, PriceCalculationRequest
from app.tests.test_price_calculation_purchasing_postgres import (
    _create_case, customer_pg_sessions,  # noqa: F401
)
from app.tests.test_price_calculation_status_postgres import app_for, auth


def _effects(db, case):
    audits = db.query(AuditLog).filter_by(entity_type='PriceCalculationRequest', entity_id=case['request_id'], action='save_cutting_price_draft').order_by(AuditLog.id).all()
    notices = db.query(Notification).filter_by(title='Cutting details completed', message=f"Model {case['model_code']} price request was updated.", link='/finance/price-calculation').all()
    return audits, notices



def test_signed_failure_rollback_and_retry(customer_pg_sessions, monkeypatch):
    from app.tests.pricing_pg_checks import draft_failure
    sessions=customer_pg_sessions
    for fault in ('write','audit','commit'):
        case=_create_case(sessions); rid=case['request_id']
        payload={'kroy_no':'MANUAL','fabric_width_m':1,'lay_length_m':2,'size_count':2,'gramage':.2,'binding_kg_per_piece':0}
        with draft_failure(sessions,monkeypatch,rid,fault) as attempted:
            with TestClient(app_for(sessions),raise_server_exceptions=False) as client:
                assert client.patch(f'/api/price-calculation/requests/{rid}/cutting',headers=auth(case['wildcard_id']),json=payload).status_code==500
        with sessions() as db:
            row=db.get(PriceCalculationRequest,rid)
            assert row.kroy_no is None and row.materials_json==[] and row.revision==1
            assert _effects(db,case)==([],[])
            assert all(db.get(AuditLog,key) is None for key in attempted)
        with TestClient(app_for(sessions)) as client:
            retry=client.patch(f'/api/price-calculation/requests/{rid}/cutting',headers=auth(case['wildcard_id']),json=payload)
            assert retry.status_code==200 and retry.json()['materials'][0]['consumption']==.2
        with sessions() as db:
            audits,notices=_effects(db,case)
            assert len(audits)==1 and audits[0].entry_hash and audits[0].user_id==case['wildcard_id']
            assert notices==[]


def test_signed_passport_manual_refusals_and_readback(customer_pg_sessions):
    sessions=customer_pg_sessions; case=_create_case(sessions); rid=case['request_id']; number=uuid4().hex[:20]
    with sessions.begin() as db:
        valid=CuttingPassport(passport_no=number,date=datetime.now(timezone.utc),model_code=case['model_code'],size_range='S, M',fabric_width_m=1.5,lay_length_m=3,gramage=.2)
        wrong=CuttingPassport(passport_no=number+'w',date=datetime.now(timezone.utc),model_code='OTHER')
        metre=CuttingPassport(passport_no=number+'m',date=datetime.now(timezone.utc),model_code=case['model_code'],size_range='S, M',materials=[{'meter_mode':True,'lay_length_m':3,'size_range':'S, M'}])
        db.add_all([valid,wrong,metre]);db.flush();passport_id=valid.id
    url=f'/api/price-calculation/requests/{rid}/cutting';headers=auth(case['wildcard_id'])
    with TestClient(app_for(sessions)) as client:
        assert client.patch(url,json={'kroy_no':number}).status_code==401
        assert client.patch(url,headers=auth(case['purchaser_id']),json={'kroy_no':number}).status_code==403
        assert client.patch('/api/price-calculation/requests/2147483647/cutting',headers=headers,json={'kroy_no':number}).status_code==404
        assert client.patch(url,headers=headers,json={'kroy_no':number,'fabric_width_m':0}).status_code==422
        assert client.patch(url,headers=headers,json={'kroy_no':number+'w'}).status_code==409
        saved=client.patch(url,headers=headers,json={'kroy_no':number,'fabric_width_m':9})
        assert saved.status_code==200 and saved.json()['materials'][0]['consumption']==.45
        with sessions() as db:
            row=db.get(PriceCalculationRequest,rid)
            assert row.cutting_passport_id==passport_id and float(row.fabric_width_m)==1.5
        saved=client.patch(url,headers=headers,json={'kroy_no':number+'m'})
        assert saved.status_code==200 and saved.json()['materials'][0]['unit']=='m' and saved.json()['materials'][0]['consumption']==1.5
        fallback=client.patch(url,headers=headers,json={'kroy_no':number+'unknown'})
        assert fallback.status_code==200 and fallback.json()['cutting_status']=='in_progress'
    with sessions() as db:
        row=db.get(PriceCalculationRequest,rid)
        assert row.cutting_passport_id is None and row.fabric_width_m is None
        assert len(_effects(db,case)[0])==3 and _effects(db,case)[1]==[]

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
            assert notices == []
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
