from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.libs.dto.planning.price_calculation_request_update import PriceCalculationCuttingIn
from app.models import price_calculation_service as pricing
from app.models.planning import costing_service


class Session:
    def __init__(self, fail=False):
        self.events = []
        self.fail = fail

    def flush(self):
        self.events.append('flush')
        if self.fail:
            raise RuntimeError('flush failed')

    def commit(self):
        self.events.append('commit')


def row():
    return SimpleNamespace(id=7, kroy_no=None, cutting_passport_id=None,
                           fabric_width_m=None, lay_length_m=None, size_count=None,
                           gramage=None, binding_kg_per_piece=None)


def test_passport_values_override_input_and_audit_preserves_input(monkeypatch):
    db, request = Session(), row()
    passport = SimpleNamespace(id=9, meter_mode=False, materials=[], fabric_width_m=Decimal('1.2'),
        lay_length_m=None, size_range='S-L', gramage=Decimal('180'),
        beka_per_piece_kg=Decimal('0.01'), other_beka_per_piece_kg=Decimal('0.02'))
    events = []
    monkeypatch.setattr(pricing, '_passport_for_kroy', lambda *args: passport)
    def sizes(p):
        assert (request.kroy_no, request.cutting_passport_id, request.fabric_width_m, request.lay_length_m) == ('K1', 9, Decimal('1.2'), 4.0)
        return []
    monkeypatch.setattr(pricing, 'passport_order_sizes', sizes)
    monkeypatch.setattr(pricing, '_size_count_from_range', lambda *args: 3)
    monkeypatch.setattr(pricing, 'log_action', lambda *args, **kw: events.append(('audit', kw['new_value'])))
    monkeypatch.setattr(pricing, '_notify_finance', lambda *args: events.append(('notify', args[-1])))
    data = dict(kroy_no=' K1 ', fabric_width_m=2.0, lay_length_m=4.0, size_count=8, gramage=200, binding_kg_per_piece=0.5)
    pricing.update_cutting_details(db, request, data, object())
    assert (request.fabric_width_m, request.lay_length_m, request.size_count, request.gramage, request.binding_kg_per_piece) == (Decimal('1.2'), 4.0, 3, Decimal('180'), Decimal('0.03'))
    assert db.events == ['flush']
    assert events == [('audit', dict(kroy_no='K1', cutting_passport_id=9, fabric_width_m=2.0, lay_length_m=4.0, size_count=8, gramage=200, binding_kg_per_piece=0.5)), ('notify', 'Cutting details completed')]
    pricing.update_cutting_details(db, request, data, object())
    assert [x[0] for x in events] == ['audit', 'notify', 'audit']


def test_omitted_fields_clear_and_flush_failure_stops_side_effects(monkeypatch):
    request = row()
    request.fabric_width_m = 5
    monkeypatch.setattr(pricing, '_passport_for_kroy', lambda *args: None)
    monkeypatch.setattr(pricing, 'log_action', lambda *args, **kwargs: pytest.fail('unexpected audit'))
    monkeypatch.setattr(pricing, '_notify_finance', lambda *args: pytest.fail('unexpected notification'))
    db = Session(fail=True)
    with pytest.raises(RuntimeError, match='flush failed'):
        pricing.update_cutting_details(db, request, PriceCalculationCuttingIn(kroy_no='K').model_dump(), object())
    assert request.fabric_width_m is None
    assert db.events == ['flush']


def test_meter_passport_refuses_before_writes(monkeypatch):
    request, db = row(), Session()
    monkeypatch.setattr(pricing, '_passport_for_kroy', lambda *args: SimpleNamespace(meter_mode=False, materials=[{'meter_mode': True}]))
    with pytest.raises(HTTPException) as error:
        pricing.update_cutting_details(db, request, {'kroy_no': 'K'}, object())
    assert error.value.status_code == 400
    assert request.kroy_no is None and db.events == []


def test_permission_precedes_lookup(monkeypatch):
    monkeypatch.setattr(pricing, 'is_cutting_pricing_user', lambda current: False)
    monkeypatch.setattr(costing_service, 'load_price_request', lambda *args: pytest.fail('lookup must not happen'))
    with pytest.raises(HTTPException) as error:
        costing_service.update_cutting_details(Session(), 999, PriceCalculationCuttingIn(kroy_no='K'), object())
    assert error.value.status_code == 403
