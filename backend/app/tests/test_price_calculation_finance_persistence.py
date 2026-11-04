from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

from app.schemas.catalog.model_price_persistence import apply_request_selling_price
from app.schemas.planning.price_calculation_persistence import apply_finance_contribution
from app.libs.dto.planning.price_calculation_request_update import PriceCalculationFinanceIn


def test_finance_omission_and_explicit_null_keep_distinct_update_semantics():
    db = Mock()
    request = SimpleNamespace(selling_price=12, exchange_rate=100, finance_updated_by_id=1)
    changes = PriceCalculationFinanceIn(selling_price=None).model_dump(exclude_unset=True)
    apply_finance_contribution(db, request, changes, updated_by_id=7)
    assert request.selling_price is None
    assert request.exchange_rate == 100
    assert request.finance_updated_by_id == 7
    db.flush.assert_not_called()
    db.commit.assert_not_called()


def test_catalog_price_participant_flushes_supplied_values_without_commit():
    db = Mock()
    model = SimpleNamespace()
    timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    apply_request_selling_price(db, model, price=Decimal('12.34'), request_id=8, updated_at=timestamp)
    assert (model.selling_price, model.selling_price_currency, model.selling_price_source) == (Decimal('12.34'), 'USD', 'price_request')
    assert (model.selling_price_request_id, model.selling_price_updated_at) == (8, timestamp)
    db.flush.assert_called_once_with()
    db.commit.assert_not_called()


def test_finance_service_preserves_audit_flush_attach_commit_order(monkeypatch):
    from app.models.planning import costing_service as service

    events = []
    request = SimpleNamespace(id=2, selling_price=5, exchange_rate=9, finance_updated_by_id=1)
    actor = SimpleNamespace(id=7)
    db = Mock()
    db.flush.side_effect = lambda: events.append('flush')
    db.commit.side_effect = lambda: events.append('commit')
    db.refresh.side_effect = lambda row: events.append('refresh')
    monkeypatch.setattr(service.pricing, 'is_finance_pricing_user', lambda actor: True)
    monkeypatch.setattr(service, 'load_price_request', lambda db, request_id: request)
    monkeypatch.setattr(service, 'log_action', lambda db, actor, action, kind, key, **kwargs: events.append(('audit', kwargs)))
    monkeypatch.setattr(service.pricing, 'attach_completed_selling_price', lambda db, request, actor: events.append('attach'))
    monkeypatch.setattr(service.pricing, 'serialize_price_request', lambda request: {'id': request.id})
    result = service.update_finance_details(db, 2, PriceCalculationFinanceIn(selling_price=None), actor)
    assert result == {'id': 2}
    assert request.selling_price is None and request.exchange_rate == 9
    assert events == [('audit', {'old_value': {'selling_price': 5}, 'new_value': {'selling_price': None}}), 'flush', 'attach', 'commit', 'refresh']


def test_positive_price_rejected_before_any_write_when_costs_incomplete(monkeypatch):
    import pytest
    from fastapi import HTTPException
    from app.models.planning import costing_service as service

    db = Mock()
    request = SimpleNamespace(selling_price=5, finance_updated_by_id=1)
    monkeypatch.setattr(service.pricing, 'is_finance_pricing_user', lambda actor: True)
    monkeypatch.setattr(service, 'load_price_request', lambda db, request_id: request)
    monkeypatch.setattr(service.pricing, 'cutting_status', lambda request: 'new')
    with pytest.raises(HTTPException) as error:
        service.update_finance_details(db, 2, PriceCalculationFinanceIn(selling_price=12), SimpleNamespace(id=7))
    assert error.value.status_code == 409
    assert (request.selling_price, request.finance_updated_by_id) == (5, 1)
    db.flush.assert_not_called()
    db.commit.assert_not_called()
