from types import SimpleNamespace
from typing import get_type_hints

from app.libs.types.planning import PriceCalculationPurchasingCommand
from app.models import price_calculation_service as pricing
from app.schemas.planning import price_calculation_persistence
from app.schemas.planning.price_calculation import PriceCalculationRequest


class FlushOnlySession:
    def __init__(self):
        self.flush_calls = 0

    def flush(self):
        self.flush_calls += 1

    def commit(self):
        raise AssertionError("persistence helper must not commit")


def test_purchasing_command_is_used_at_business_and_persistence_boundaries():
    assert get_type_hints(pricing.update_purchasing_details)["command"] is PriceCalculationPurchasingCommand
    assert get_type_hints(price_calculation_persistence.apply_purchasing_contribution)["command"] is PriceCalculationPurchasingCommand
    assert get_type_hints(price_calculation_persistence.apply_purchasing_contribution)["request"] is PriceCalculationRequest


def test_purchasing_persistence_updates_only_owned_fields_and_flushes_supplied_session():
    db = FlushOnlySession()
    request = SimpleNamespace(
        fabric_price=1.25,
        sewing_cost=0.5,
        purchasing_updated_by_id=7,
        finance_updated_by_id=8,
    )
    command = PriceCalculationPurchasingCommand(fabric_price=None, sewing_cost=0.0)

    price_calculation_persistence.apply_purchasing_contribution(
        db, request, command, updated_by_id=42
    )

    assert (request.fabric_price, request.sewing_cost, request.purchasing_updated_by_id) == (None, 0.0, 42)
    assert request.finance_updated_by_id == 8
    assert db.flush_calls == 1


def test_purchasing_completion_audits_then_notifies_finance(monkeypatch):
    events = []
    request = SimpleNamespace(id=19, fabric_price=None, sewing_cost=None)
    actor = SimpleNamespace(id=42)
    command = PriceCalculationPurchasingCommand(fabric_price=4.5, sewing_cost=0.1674)

    def persist(db, row, values, *, updated_by_id):
        events.append(("persist", db, updated_by_id))
        row.fabric_price = values.fabric_price
        row.sewing_cost = values.sewing_cost

    def audit(db, current, action, entity, entity_id, *, new_value):
        events.append(("audit", action, entity, entity_id, new_value))

    def notify(db, row, title):
        events.append(("notify", title))

    monkeypatch.setattr(pricing, "apply_purchasing_contribution", persist)
    monkeypatch.setattr(pricing, "log_action", audit)
    monkeypatch.setattr(pricing, "_notify_finance", notify)
    db = object()

    pricing.update_purchasing_details(db, request, command, actor)

    assert events == [
        ("persist", db, actor.id),
        ("audit", "update_purchasing_costs", "PriceCalculationRequest", request.id,
         {"fabric_price": 4.5, "sewing_cost": 0.1674}),
        ("notify", "Purchasing costs completed"),
    ]
