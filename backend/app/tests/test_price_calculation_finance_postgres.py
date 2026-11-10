"""Signed Finance drafts are isolated from explicit publication on migrated PG."""

from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from app.schemas import AuditLog, Model, Notification, PriceCalculationRequest
from app.tests.test_price_calculation_purchasing_postgres import _create_case, customer_pg_sessions  # noqa: F401
from app.tests.test_price_calculation_status_postgres import app_for, auth
from app.tests.pricing_pg_checks import draft_failure, versioned_draft_race


def test_signed_finance_refusal_omission_null_and_attachment(customer_pg_sessions):
    sessions = customer_pg_sessions
    case = _create_case(sessions)
    rid = case["request_id"]
    url = f"/api/price-calculation/requests/{rid}/finance"
    with sessions() as retained:
        request = retained.get(PriceCalculationRequest, rid)
        model = retained.get(Model, request.model_id)
        notices = retained.query(Notification).count()
        with TestClient(app_for(sessions)) as client:
            assert client.patch(url, json={"selling_price": 12}).status_code == 401
            assert client.patch(url, headers=auth(case["purchaser_id"]), json={"selling_price": 12}).status_code == 403
            assert (
                client.patch(
                    "/api/price-calculation/requests/2147483647/finance", headers=auth(case["finance_id"]), json={}
                ).status_code
                == 404
            )
            response = client.patch(
                url, headers=auth(case["finance_id"]), json={"selling_price": 12.3456, "exchange_rate": 100}
            )
            assert response.status_code == 200, response.text
            assert (
                client.post(
                    f"/api/price-calculation/requests/{rid}/approve",
                    headers=auth(case["finance_id"]),
                    json={"expected_revision": response.json()["revision"], "selling_price": 12},
                ).status_code
                == 403
            )
            assert (
                client.post(
                    f"/api/price-calculation/requests/{rid}/approve",
                    headers=auth(case["wildcard_id"]),
                    json={"expected_revision": response.json()["revision"], "selling_price": 12},
                ).status_code
                == 409
            )
            assert client.patch(url, headers=auth(case["finance_id"]), json={"exchange_rate": None}).status_code == 200
            retained.expire_all()
            assert request.selling_price == Decimal("12.3456") and request.exchange_rate is None
            assert client.patch(url, headers=auth(case["finance_id"]), json={"selling_price": None}).status_code == 200
        retained.expire_all()
        assert request.selling_price is None and request.exchange_rate is None
        assert request.finance_updated_by_id == case["finance_id"]
        assert model.selling_price is None and model.selling_price_request_id is None
        audits = (
            retained.query(AuditLog)
            .filter_by(entity_type="PriceCalculationRequest", entity_id=rid)
            .order_by(AuditLog.id)
            .all()
        )
        assert [row.new_value_json for row in audits] == [
            {"selling_price": 12.3456, "exchange_rate": 100.0},
            {"exchange_rate": None},
            {"selling_price": None},
        ]
        assert all(
            row.action == "save_finance_price_draft" and row.user_id == case["finance_id"] and row.entry_hash
            for row in audits
        )
        assert retained.query(Notification).count() == notices


@pytest.mark.parametrize("fault", ["audit", "commit"])
def test_signed_finance_rollback_and_retry(customer_pg_sessions, monkeypatch, fault):
    sessions = customer_pg_sessions
    case = _create_case(sessions)
    rid = case["request_id"]
    url = f"/api/price-calculation/requests/{rid}/finance"
    with draft_failure(sessions, monkeypatch, rid, fault) as attempted:
        with TestClient(app_for(sessions), raise_server_exceptions=False) as client:
            assert client.patch(url, headers=auth(case["finance_id"]), json={"selling_price": 23.45}).status_code == 500
    with sessions() as db:
        request = db.get(PriceCalculationRequest, rid)
        assert request.selling_price is None and request.finance_updated_by_id is None and request.revision == 1
        assert db.get(Model, request.model_id).selling_price is None
        assert db.query(AuditLog).filter_by(entity_type="PriceCalculationRequest", entity_id=rid).count() == 0
        assert all(db.get(AuditLog, key) is None for key in attempted)
    with TestClient(app_for(sessions)) as client:
        response = client.patch(url, headers=auth(case["finance_id"]), json={"selling_price": 23.45})
        assert response.status_code == 200, response.text
    with sessions() as db:
        request = db.get(PriceCalculationRequest, rid)
        assert request.selling_price == Decimal("23.4500") and request.revision == 2
        assert db.get(Model, request.model_id).selling_price is None
        audits = db.query(AuditLog).filter_by(entity_type="PriceCalculationRequest", entity_id=rid).all()
        assert len(audits) == 1 and audits[0].entry_hash and audits[0].id not in attempted


def test_concurrent_finance_updates_wait_and_last_writer_wins(customer_pg_sessions, monkeypatch):
    """Historical gate identity: stale last writer is now refused after real waiting."""
    sessions = customer_pg_sessions
    case = _create_case(sessions)
    result = versioned_draft_race(
        sessions, monkeypatch, case, "finance", [{"selling_price": 11}, {"selling_price": 22}]
    )
    assert result["selling_price"] == 11
    with sessions() as db:
        row = db.get(PriceCalculationRequest, case["request_id"])
        assert row.selling_price == 11 and row.revision == 2
        assert db.get(Model, row.model_id).selling_price is None
        assert db.query(AuditLog).filter_by(entity_type="PriceCalculationRequest", entity_id=row.id).count() == 1
