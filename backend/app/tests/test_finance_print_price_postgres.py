"""The print-price handoff against an approved migrated PostgreSQL instance."""
from decimal import Decimal

from fastapi.testclient import TestClient

from app.schemas import PriceCalculationRequest, Model
from app.schemas.planning.price_calculation_persistence import apply_workflow_fields
from app.tests.test_price_calculation_status_postgres import app_for, auth, customer_pg_sessions  # noqa: F401
from app.tests.test_variant_price_workflow_postgres import ready_case


def test_pg_print_price_handoff_and_stale_retry(customer_pg_sessions):
    sessions = customer_pg_sessions
    model_id, request_id, users = ready_case(sessions)
    with sessions.begin() as db:
        request = db.get(PriceCalculationRequest, request_id)
        apply_workflow_fields(db, request, passport_snapshot_json={"has_print": True})
        revision = request.revision
    base = f"/api/price-calculation/requests/{request_id}"
    with TestClient(app_for(sessions)) as client:
        for team in ("purchasing", "accessories"):
            response = client.post(base + "/submit/" + team, headers=auth(users[team]), json={"expected_revision": revision})
            assert response.status_code == 200, response.text
            revision = response.json()["revision"]
        assert response.json()["workflow_state"] == "awaiting_finance"
        assert response.json()["cost_price"] is None
        assert client.patch(base + "/purchasing", headers=auth(users["purchasing"]), json={"printing_cost": 1}).status_code == 422
        assert client.post(base + "/approve", headers=auth(users["finance"]), json={"expected_revision": revision, "selling_price": 5}).status_code == 409
        saved = client.patch(base + "/finance", headers=auth(users["finance"]), json={"expected_revision": revision, "printing_cost": 0.3})
        assert saved.status_code == 200, saved.text
        assert saved.json()["cost_price"] == 3.9
        assert client.patch(base + "/finance", headers=auth(users["finance"]), json={"expected_revision": revision, "printing_cost": 2}).status_code == 409
        approved = client.post(base + "/approve", headers=auth(users["finance"]), json={"expected_revision": saved.json()["revision"], "selling_price": 5})
        assert approved.status_code == 200, approved.text
    with sessions() as db:
        request = db.get(PriceCalculationRequest, request_id)
        assert request.printing_cost == Decimal("0.3000")
        assert request.approval_snapshot_json["printing_cost"] == 0.3
        assert db.get(Model, model_id).selling_price == 5
