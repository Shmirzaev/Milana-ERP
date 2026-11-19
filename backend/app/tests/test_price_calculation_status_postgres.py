"""Derived price statuses and finance gating on owned migrated PostgreSQL."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import price_calculation
from app.core.deps import get_db
from app.core.security import create_access_token
from app.schemas import AuditLog, Model, Notification, PriceCalculationRequest
from app.tests.test_price_calculation_purchasing_postgres import (
    _create_case,
    customer_pg_sessions,  # noqa: F401
)


def app_for(sessions):
    app = FastAPI()
    app.include_router(price_calculation.router, prefix="/api")

    def session():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = session
    return app


def auth(user_id):
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


def test_pg_signed_status_transitions_finance_gate_and_notifications(customer_pg_sessions):
    sessions = customer_pg_sessions
    case = _create_case(sessions)
    rid = case["request_id"]
    url = f"/api/price-calculation/requests/{rid}"
    with sessions() as retained:
        row = retained.get(PriceCalculationRequest, rid)
        model = retained.get(Model, row.model_id)
        notices = retained.query(Notification).count()
        with TestClient(app_for(sessions)) as client:
            assert client.get("/api/price-calculation/requests").status_code == 401
            initial = next(
                x
                for x in client.get("/api/price-calculation/requests", headers=auth(case["finance_id"])).json()
                if x["id"] == rid
            )
            assert initial["workflow_state"] == "collecting" and initial["cost_price"] is None
            cut = {
                "kroy_no": "SYNTHETIC",
                "fabric_width_m": 1,
                "lay_length_m": 2,
                "size_count": 2,
                "gramage": 0.2,
                "binding_kg_per_piece": 0,
            }
            assert client.patch(url + "/cutting", headers=auth(case["wildcard_id"]), json=cut).status_code == 200
            purchase = client.patch(
                url + "/purchasing", headers=auth(case["purchaser_id"]), json={"fabric_price": 2, "sewing_cost": 0}
            )
            assert purchase.status_code == 200 and purchase.json()["purchasing_status"] == "in_progress"
            accessory = client.patch(
                url + "/accessories",
                headers=auth(case["wildcard_id"]),
                json={"accessories": [{"name": "Button", "price": 0}]},
            )
            assert accessory.status_code == 200 and accessory.json()["accessories_status"] == "in_progress"
            first = client.post(
                url + "/submit/purchasing",
                headers=auth(case["purchaser_id"]),
                json={"expected_revision": accessory.json()["revision"]},
            )
            assert first.status_code == 200 and first.json()["workflow_state"] == "collecting"
            second = client.post(
                url + "/submit/accessories",
                headers=auth(case["wildcard_id"]),
                json={"expected_revision": first.json()["revision"]},
            )
            assert second.status_code == 200 and second.json()["workflow_state"] == "awaiting_finance"
            assert second.json()["cost_price"] == 0.5  # .2kg*2 plus .1 packaging; zeros are valid.
            draft = client.patch(
                url + "/finance",
                headers=auth(case["finance_id"]),
                json={"selling_price": 10, "expected_revision": second.json()["revision"]},
            )
            assert draft.status_code == 200 and draft.json()["overall_status"] == "in_progress"
            retained.expire_all()
            assert model.selling_price is None
            approved = client.post(
                url + "/approve",
                headers=auth(case["wildcard_id"]),
                json={"expected_revision": draft.json()["revision"], "selling_price": 10},
            )
            assert approved.status_code == 200, approved.text
            assert approved.json()["workflow_state"] == "approved" and approved.json()["overall_status"] == "complete"
            assert client.patch(url + "/cutting", headers=auth(case["wildcard_id"]), json=cut).status_code == 409
        retained.expire_all()
        assert model.selling_price == 10 and model.selling_price_request_id == rid and row.active_model_id is None
        assert (
            retained.query(AuditLog)
            .filter_by(entity_type="PriceCalculationRequest", entity_id=rid, action="approve_variant_price")
            .count()
            == 1
        )
        notifications = (
            retained.query(Notification)
            .filter_by(user_id=case["finance_id"], title="Price ready for Finance approval")
            .all()
        )
        assert len(notifications) == 1
        assert retained.query(Notification).count() > notices
