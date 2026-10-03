"""WF08: waste sales must be capped at remaining sellable waste and safe to retry."""

from decimal import Decimal
from uuid import uuid4

import pytest

from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.models import Role, User, WasteRecord, WasteSale


def _waste(*, quantity=10, sellable=True, status="received_by_waste_department"):
    marker = uuid4().hex[:10]
    with SessionLocal() as db:
        role = Role(name=f"WF08 seller {marker}", permissions=["waste.sell", "waste.receive", "*"])
        user = User(
            name=f"WF08 seller {marker}", email=f"wf08-{marker}@example.com",
            password_hash="unused-wf08-hash", role=role, factory_code="MIL", is_active=True,
        )
        db.add_all([role, user])
        db.flush()
        record = WasteRecord(
            waste_type="cutting", quantity=quantity, unit="kg", sellable=sellable, status=status,
        )
        db.add(record)
        db.commit()
        return {
            "wid": record.id, "quantity": quantity,
            "headers": {"Authorization": f"Bearer {create_access_token(user.id)}"},
        }


def _sell(account, *, quantity, price=2.0, buyer="Buyer", key=None):
    headers = dict(account["headers"])
    if key:
        headers["Idempotency-Key"] = key
    return account["client"].post(
        f"/api/waste/{account['wid']}/sell",
        headers=headers,
        json={"buyer_name": buyer, "quantity": quantity, "unit_price": price},
    )


# ------------------------------------------------------------ capacity capping

def test_sale_cannot_exceed_remaining_waste_quantity(client):
    account = _waste(quantity=10)
    account["client"] = client
    response = _sell(account, quantity=11)
    assert response.status_code == 400, response.text
    assert "remaining" in response.text.lower()
    with SessionLocal() as db:
        assert db.query(WasteSale).filter(WasteSale.waste_record_id == account["wid"]).count() == 0
        assert db.get(WasteRecord, account["wid"]).status == "received_by_waste_department"


def test_second_partial_sale_is_capped_by_what_is_left(client):
    account = _waste(quantity=10)
    account["client"] = client
    assert _sell(account, quantity=6, key="wf08-a").status_code == 200
    over = _sell(account, quantity=5, key="wf08-b")
    assert over.status_code == 400, over.text
    assert "remaining" in over.text.lower()


def test_partial_sale_does_not_mark_remaining_waste_sold(client):
    """The core WF08 defect: leftover waste was marked sold after any sale."""
    account = _waste(quantity=10)
    account["client"] = client
    assert _sell(account, quantity=4, key="wf08-partial").status_code == 200
    with SessionLocal() as db:
        record = db.get(WasteRecord, account["wid"])
        assert record.status == "received_by_waste_department", "leftover waste must stay sellable"
    # The remaining 6 kg must still be sellable.
    assert _sell(account, quantity=6, key="wf08-rest").status_code == 200
    with SessionLocal() as db:
        assert db.get(WasteRecord, account["wid"]).status == "sold"
        assert db.query(WasteSale).filter(WasteSale.waste_record_id == account["wid"]).count() == 2


# --------------------------------------------------------------- retry safety

def test_repeated_keyed_sale_executes_once(client):
    account = _waste(quantity=10)
    account["client"] = client
    first = _sell(account, quantity=5, key="wf08-retry")
    second = _sell(account, quantity=5, key="wf08-retry")
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json() == first.json()
    with SessionLocal() as db:
        assert db.query(WasteSale).filter(WasteSale.waste_record_id == account["wid"]).count() == 1


def test_exhausted_waste_cannot_be_sold_again(client):
    account = _waste(quantity=5)
    account["client"] = client
    assert _sell(account, quantity=5, key="wf08-full").status_code == 200
    again = _sell(account, quantity=1, key="wf08-extra")
    assert again.status_code == 400
    with SessionLocal() as db:
        assert db.query(WasteSale).filter(WasteSale.waste_record_id == account["wid"]).count() == 1


# ------------------------------------------------------------------ precision

@pytest.mark.parametrize("quantity,price", [
    (0, 2.0),
    (-1, 2.0),
    (1, -2.0),
    (float("inf"), 2.0),
    (float("nan"), 2.0),
    (1, float("inf")),
    (0.00001, 2.0),
    (1, 0.001),
    (10_000_000_000, 2.0),
])
def test_invalid_sale_values_are_rejected(client, quantity, price):
    account = _waste(quantity=Decimal("10000000000"))
    account["client"] = client
    response = _sell(account, quantity=quantity, price=price, key="wf08-bad")
    assert response.status_code == 400, response.text
    with SessionLocal() as db:
        assert db.query(WasteSale).filter(WasteSale.waste_record_id == account["wid"]).count() == 0


def test_blank_buyer_name_is_rejected(client):
    account = _waste(quantity=10)
    account["client"] = client
    response = _sell(account, quantity=1, buyer="   ", key="wf08-blank")
    assert response.status_code == 400


def test_unkeyed_legacy_sale_still_works(client):
    """A missing Idempotency-Key must keep the pre-existing behaviour working."""
    account = _waste(quantity=10)
    account["client"] = client
    response = _sell(account, quantity=3)
    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        assert db.query(WasteSale).filter(WasteSale.waste_record_id == account["wid"]).count() == 1
