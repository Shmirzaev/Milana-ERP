from decimal import Decimal
from uuid import uuid4

import pytest

from app.libs.dto.planning.price_calculation_request_input import PriceCalculationCreateIn
from app.models import price_calculation_service as pricing
from app.models.planning import costing_service
from app.schemas import AuditLog, Model, Notification, User
from app.schemas.planning.price_calculation import PriceCalculationRequest

pytest_plugins = ["app.tests.test_price_calculation_purchasing_transactions"]


def seed(factory, margin='-12.50'):
    token = uuid4().hex
    with factory() as db:
        model = Model(code=token, name='Creation test', category='T-shirt', status='approved',
                      details_json={'costing': {'target_margin_pct': margin}})
        sales = User(name='Sales', email=f'{token}@example.invalid', password_hash='unused', extra_permissions=['sales.orders'])
        recipient = User(name='Finance and cutting', email=f'{token}r@example.invalid', password_hash='unused',
                         extra_permissions=['finance.view', 'cutting.records'])
        db.add_all([model, sales, recipient])
        db.commit()
        return model.id, sales.id, recipient.id


def create(factory, model_id, sales_id):
    with factory() as db:
        return costing_service.create_price_request(db, PriceCalculationCreateIn(model_id=model_id), db.get(User, sales_id))


def test_creation_duplicate_and_notification_deduplication(isolated_session_factory):
    factory = isolated_session_factory
    model_id, sales_id, recipient_id = seed(factory)
    first = create(factory, model_id, sales_id)
    second = create(factory, model_id, sales_id)
    assert first['id'] != second['id']
    with factory() as db:
        rows = db.query(PriceCalculationRequest).order_by(PriceCalculationRequest.id).all()
        assert len(rows) == 2
        assert all(row.profit_percentage == Decimal('-12.50') and row.accessories_json == [] for row in rows)
        assert db.query(AuditLog).filter_by(action='create', entity_type='PriceCalculationRequest').count() == 2
        notifications = db.query(Notification).filter_by(user_id=recipient_id, title='New price calculation request').all()
        assert len(notifications) == 2
        assert all(row.link == '/finance/price-calculation' for row in notifications)


def test_failure_after_flushed_notifications_rolls_back_everything(monkeypatch, isolated_session_factory):
    factory = isolated_session_factory
    model_id, sales_id, recipient_id = seed(factory)
    original = pricing._notify_new_request
    def fail(db, request):
        original(db, request)
        db.flush()
        assert db.query(AuditLog).filter_by(entity_id=request.id, entity_type='PriceCalculationRequest').count() == 1
        assert db.query(Notification).filter_by(user_id=recipient_id).count() == 1
        raise RuntimeError('injected failure')
    monkeypatch.setattr(pricing, '_notify_new_request', fail)
    with factory() as db:
        with pytest.raises(RuntimeError, match='injected failure'):
            costing_service.create_price_request(db, PriceCalculationCreateIn(model_id=model_id), db.get(User, sales_id))
        db.rollback()
    with factory() as db:
        assert db.query(PriceCalculationRequest).count() == 0
        assert db.query(AuditLog).count() == 0
        assert db.query(Notification).count() == 0
