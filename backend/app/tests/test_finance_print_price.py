"""Purchasing -> Finance print-price ownership and protected handoff."""
from decimal import Decimal

import pytest

from app.db.session import SessionLocal
from app.schemas import Model, PriceCalculationRequest
from app.tests.test_variant_price_workflow import setup, save_costs, submit, protected_facts


@pytest.mark.parametrize("printing_cost", [0, 0.25])
def test_finance_owns_print_price_and_approval_requires_it(client, auth_headers, printing_cost):
    data = setup(client, f"finance-print-{printing_cost}", has_print=True)
    base = f"/api/price-calculation/requests/{data['request_id']}"
    with SessionLocal() as db:
        before = protected_facts(db)
    # Reject old/forged Purchasing clients rather than silently overwriting Finance.
    denied = client.patch(base + "/purchasing", headers=data["purchasing"], json={"printing_cost": 12})
    assert denied.status_code == 422
    assert client.patch(base + "/finance", headers=data["purchasing"], json={"printing_cost": 12}).status_code == 403
    request = save_costs(client, data)
    assert request["printing_required"] is True
    request = submit(client, data, "accessories", submit(client, data, "purchasing", request))
    assert request["workflow_state"] == "awaiting_finance"
    assert request["cost_price"] is None and "printing_costs" in request["calculation_issues"]
    assert client.post(base + "/approve", headers=auth_headers, json={"expected_revision": request["revision"], "selling_price": 6}).status_code == 409
    for invalid in (-1, "NaN", "Infinity"):
        assert client.patch(base + "/finance", headers=data["finance"], json={"printing_cost": invalid}).status_code == 422
    saved = client.patch(base + "/finance", headers=data["finance"], json={
        "expected_revision": request["revision"], "printing_cost": printing_cost, "selling_price": 6})
    assert saved.status_code == 200, saved.text
    result = saved.json()
    assert result["printing_cost"] == printing_cost
    assert result["cost_price"] == pytest.approx(4.65 + printing_cost)
    assert "printing_costs" not in result["calculation_issues"]
    assert client.patch(base + "/finance", headers=data["finance"], json={"expected_revision": request["revision"], "printing_cost": 99}).status_code == 409
    cleared = client.patch(base + "/finance", headers=data["finance"], json={"expected_revision": result["revision"], "printing_cost": None})
    assert cleared.status_code == 200 and cleared.json()["cost_price"] is None
    assert client.post(base + "/approve", headers=auth_headers, json={"expected_revision": cleared.json()["revision"], "selling_price": 6}).status_code == 409
    restored = client.patch(base + "/finance", headers=data["finance"], json={"expected_revision": cleared.json()["revision"], "printing_cost": printing_cost})
    assert restored.status_code == 200
    result = restored.json()
    # Partial saves must preserve Finance's saved print amount.
    saved = client.patch(base + "/finance", headers=data["finance"], json={"expected_revision": result["revision"], "exchange_rate": 12500})
    assert saved.status_code == 200 and saved.json()["printing_cost"] == printing_cost
    approved = client.post(base + "/approve", headers=auth_headers, json={"expected_revision": saved.json()["revision"], "selling_price": 6})
    assert approved.status_code == 200, approved.text
    with SessionLocal() as db:
        request = db.get(PriceCalculationRequest, data["request_id"])
        assert request.printing_cost == Decimal(str(printing_cost))
        assert request.approval_snapshot_json["printing_cost"] == printing_cost
        assert db.get(Model, data["model_id"]).selling_price == 6
        assert protected_facts(db) == before
