"""Derived price statuses and finance gating on owned migrated PostgreSQL."""
from collections import Counter

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import price_calculation
from app.core.deps import get_db
from app.core.security import create_access_token
from app.schemas import AuditLog, Model, Notification, PriceCalculationRequest
from app.tests.test_price_calculation_purchasing_postgres import (
    _create_case, _eligible_finance_ids, customer_pg_sessions,  # noqa: F401
)


def app_for(sessions):
    app = FastAPI()
    app.include_router(price_calculation.router, prefix='/api')
    def session():
        with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = session
    return app


def auth(user_id):
    return {'Authorization': f'Bearer {create_access_token(user_id)}'}


def statuses(response, expected):
    assert response.status_code == 200, response.text
    data = response.json()
    assert tuple(data[name + '_status'] for name in ('cutting', 'purchasing', 'accessories', 'overall')) == expected
    return data


def test_pg_signed_status_transitions_finance_gate_and_notifications(customer_pg_sessions):
    sessions = customer_pg_sessions
    case = _create_case(sessions)
    rid = case['request_id']; url = f'/api/price-calculation/requests/{rid}'
    finance = auth(case['finance_id']); admin = auth(case['wildcard_id']); purchaser = auth(case['purchaser_id'])
    with sessions() as retained:
        row = retained.get(PriceCalculationRequest, rid)
        model = retained.get(Model, row.model_id)
        initial_model_price = (model.selling_price, model.selling_price_request_id)
        recipients = _eligible_finance_ids(retained)
        assert case['finance_id'] in recipients and case['wildcard_id'] not in recipients
        with TestClient(app_for(sessions), raise_server_exceptions=False) as client:
            assert client.get('/api/price-calculation/requests').status_code == 401
            assert client.patch(url + '/finance', headers=purchaser, json={'selling_price': 10}).status_code == 403
            assert client.patch('/api/price-calculation/requests/2147483647/finance', headers=purchaser, json={'selling_price': 10}).status_code == 403
            assert client.patch('/api/price-calculation/requests/2147483647/finance', headers=finance, json={'selling_price': 10}).status_code == 404
            listing = client.get('/api/price-calculation/requests', headers=finance)
            assert listing.status_code == 200, listing.text
            initial = next(x for x in listing.json() if x['id'] == rid)
            assert [initial[k + '_status'] for k in ('cutting', 'purchasing', 'accessories', 'overall')] == ['new'] * 4
            assert client.patch(url + '/finance', headers=finance, json={'selling_price': 10}).status_code == 409
            statuses(client.patch(url + '/cutting', headers=admin, json={'kroy_no': 'SYNTHETIC'}), ('in_progress', 'new', 'new', 'in_progress'))
            statuses(client.patch(url + '/purchasing', headers=purchaser, json={'fabric_price': 2, 'sewing_cost': 0}), ('in_progress', 'in_progress', 'new', 'in_progress'))
            statuses(client.patch(url + '/accessories', headers=admin, json={'accessories': [{'name': 'button', 'price': 0}]}), ('in_progress', 'in_progress', 'in_progress', 'in_progress'))
            assert client.patch(url + '/finance', headers=finance, json={'selling_price': 10}).status_code == 409
            cut = {'kroy_no': 'SYNTHETIC', 'fabric_width_m': 1, 'lay_length_m': 2, 'size_count': 3, 'gramage': 4, 'binding_kg_per_piece': 0}
            statuses(client.patch(url + '/cutting', headers=admin, json=cut), ('complete', 'in_progress', 'in_progress', 'in_progress'))
            assert client.patch(url + '/finance', headers=finance, json={'selling_price': 10}).status_code == 409
            statuses(client.patch(url + '/purchasing', headers=purchaser, json={'fabric_price': 2, 'sewing_cost': 3}), ('complete', 'complete', 'in_progress', 'in_progress'))
            assert client.patch(url + '/finance', headers=finance, json={'selling_price': 10}).status_code == 409
            statuses(client.patch(url + '/accessories', headers=admin, json={'accessories': [{'name': 'button', 'price': 1}]}), ('complete', 'complete', 'complete', 'in_progress'))
            statuses(client.patch(url + '/finance', headers=finance, json={'selling_price': 10}), ('complete', 'complete', 'complete', 'complete'))
            # Completed-to-completed updates must not emit a second transition notice.
            statuses(client.patch(url + '/cutting', headers=admin, json=cut), ('complete', 'complete', 'complete', 'complete'))
        retained.expire_all()
        assert row.selling_price == 10
        assert float(model.selling_price) == 10 and model.selling_price_request_id == rid
        assert initial_model_price != (model.selling_price, model.selling_price_request_id)
        assert retained.query(AuditLog).filter_by(entity_type='PriceCalculationRequest', entity_id=rid, action='update_finance_price').count() == 1
        for title in ('Cutting details completed', 'Purchasing costs completed', 'Accessory costs completed'):
            notices = retained.query(Notification).filter_by(title=title, message=f"Model {case['model_code']} price request was updated.", link='/finance/price-calculation').all()
            assert Counter(n.user_id for n in notices) == Counter(recipients)
