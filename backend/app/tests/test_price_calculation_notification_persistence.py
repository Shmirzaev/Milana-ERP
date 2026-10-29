"""Recipient-policy parity for shared price-calculation notification writers."""

from types import SimpleNamespace

import pytest

from app.models import price_calculation_service as service
from app.schemas import Notification, User


class StagingSession:
    """A supplied Session participant may stage rows, never finalize them."""

    def __init__(self, users):
        self.users = users
        self.rows = []

    def query(self, model):
        assert model is User
        return self

    def filter(self, condition):
        assert condition.compare(User.is_active.is_(True))
        return self

    def all(self):
        return self.users

    def add(self, row):
        assert isinstance(row, Notification)
        self.rows.append(row)

    def flush(self):
        pytest.fail("Notification participant flushed the outer operation")

    def commit(self):
        pytest.fail("Notification participant committed the outer operation")

    def rollback(self):
        pytest.fail("Notification participant rolled back the outer operation")


def user(user_id, *permissions):
    return SimpleNamespace(id=user_id, permissions=set(permissions))


def test_new_request_preserves_recipient_deduplication_and_destination_priority(monkeypatch):
    monkeypatch.setattr(service, "user_permissions", lambda actor: actor.permissions)
    monkeypatch.setattr(service, "is_finance_pricing_user", lambda actor: "finance" in actor.permissions)
    monkeypatch.setattr(service, "is_cutting_pricing_user", lambda actor: "cutting" in actor.permissions)
    monkeypatch.setattr(service, "is_price_purchaser", lambda actor: "purchasing" in actor.permissions)
    monkeypatch.setattr(service, "is_accessory_pricing_user", lambda actor: "accessories" in actor.permissions)
    session = StagingSession([
        user(1, "finance", "cutting"), user(1, "finance"),
        user(2, "cutting", "purchasing"), user(3, "purchasing", "accessories"),
        user(4, "accessories"), user(5, "*", "finance"), user(6),
    ])
    request = SimpleNamespace(model=SimpleNamespace(code="MODEL-PRICE-TEST"))

    service._notify_new_request(session, request)

    assert [(row.user_id, row.link) for row in session.rows] == [
        (1, "/finance/price-calculation"), (2, "/cutting/price-calculation"),
        (3, "/purchasing/price-calculation"), (4, "/inventory/accessory-pricing"),
    ]
    assert all(row.title == "New price calculation request" for row in session.rows)
    assert all(row.message == "Model MODEL-PRICE-TEST needs cost information." for row in session.rows)


@pytest.mark.parametrize("title", [
    "Cutting details completed", "Purchasing costs completed", "Accessory costs completed",
])
def test_stage_completion_only_stages_existing_finance_recipients(monkeypatch, title):
    monkeypatch.setattr(service, "user_permissions", lambda actor: actor.permissions)
    session = StagingSession([
        user(11, "finance.view"), user(12, "sales.orders"),
        user(13, "*"), user(14, "finance.view", "*"), user(15, "finance.view"),
    ])
    request = SimpleNamespace(model=SimpleNamespace(code="MODEL-PRICE-TEST"))

    service._notify_finance(session, request, title)

    assert [(row.user_id, row.title, row.message, row.link) for row in session.rows] == [
        (recipient, title, "Model MODEL-PRICE-TEST price request was updated.", "/finance/price-calculation")
        for recipient in (11, 15)
    ]
