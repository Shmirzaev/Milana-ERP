"""Signed accessory drafts, submission and failures on migrated PostgreSQL."""

from fastapi.testclient import TestClient
from app.schemas import AuditLog, Notification, PriceCalculationRequest
from app.tests.test_price_calculation_purchasing_postgres import _create_case, customer_pg_sessions  # noqa: F401
from app.tests.test_price_calculation_status_postgres import app_for, auth
from app.tests.pricing_pg_checks import draft_failure, versioned_draft_race


def test_signed_accessory_transitions_and_retained_readback(customer_pg_sessions):
    sessions = customer_pg_sessions
    case = _create_case(sessions)
    rid = case["request_id"]
    url = f"/api/price-calculation/requests/{rid}/accessories"
    with sessions() as retained:
        row = retained.get(PriceCalculationRequest, rid)
        notices = retained.query(Notification).count()
        with TestClient(app_for(sessions)) as client:
            assert client.patch(url, json={}).status_code == 401
            assert client.patch(url, headers=auth(case["purchaser_id"]), json={}).status_code == 403
            assert (
                client.patch(
                    "/api/price-calculation/requests/2147483647/accessories", headers=auth(case["wildcard_id"]), json={}
                ).status_code
                == 404
            )
            assert (
                client.patch(
                    url, headers=auth(case["wildcard_id"]), json={"accessories": [{"name": "a", "price": 1}] * 5}
                ).status_code
                == 422
            )
            for payload, expected in [
                ({"accessories": [{"name": " Button ", "price": 0}]}, [{"name": "Button", "price": 0}]),
                ({}, []),
                ({"accessories": [{"name": "Button", "price": 2}]}, [{"name": "Button", "price": 2}]),
            ]:
                response = client.patch(url, headers=auth(case["wildcard_id"]), json=payload)
                assert response.status_code == 200, response.text
                assert response.json()["accessories"] == expected
                assert response.json()["accessories_status"] == ("in_progress" if expected else "new")
            submitted = client.post(
                f"/api/price-calculation/requests/{rid}/submit/accessories",
                headers=auth(case["wildcard_id"]),
                json={"expected_revision": response.json()["revision"]},
            )
            assert submitted.status_code == 200 and submitted.json()["accessories_status"] == "complete"
            assert client.patch(url, headers=auth(case["wildcard_id"]), json={}).status_code == 409
        retained.expire_all()
        assert row.accessories_json == [{"name": "Button", "price": 2}] and row.accessories_submitted_at
        assert row.accessories_updated_by_id == case["wildcard_id"]
        audits = (
            retained.query(AuditLog)
            .filter_by(entity_type="PriceCalculationRequest", entity_id=rid)
            .order_by(AuditLog.id)
            .all()
        )
        assert [a.action for a in audits] == ["save_accessory_price_draft"] * 3 + ["submit_price_costs"]
        assert all(a.user_id == case["wildcard_id"] and a.entry_hash for a in audits)
        assert retained.query(Notification).count() == notices


def test_signed_failure_rollback_and_retry(customer_pg_sessions, monkeypatch):
    sessions = customer_pg_sessions
    for fault in ("write", "audit", "commit"):
        case = _create_case(sessions)
        rid = case["request_id"]
        url = f"/api/price-calculation/requests/{rid}/accessories"
        payload = {"accessories": [{"name": "Button", "price": 0}]}
        with sessions() as db:
            notices = db.query(Notification).count()
        with draft_failure(sessions, monkeypatch, rid, fault) as attempted:
            with TestClient(app_for(sessions), raise_server_exceptions=False) as client:
                assert client.patch(url, headers=auth(case["wildcard_id"]), json=payload).status_code == 500
        with sessions() as db:
            row = db.get(PriceCalculationRequest, rid)
            assert row.accessories_json == [] and row.accessories_updated_by_id is None and row.revision == 1
            assert db.query(AuditLog).filter_by(entity_type="PriceCalculationRequest", entity_id=rid).count() == 0
            assert all(db.get(AuditLog, key) is None for key in attempted)
            assert db.query(Notification).count() == notices
        with TestClient(app_for(sessions)) as client:
            result = client.patch(url, headers=auth(case["wildcard_id"]), json=payload)
            assert result.status_code == 200, result.text
        with sessions() as db:
            row = db.get(PriceCalculationRequest, rid)
            assert row.accessories_json == payload["accessories"] and row.accessories_submitted_at is None
            assert db.query(AuditLog).filter_by(entity_type="PriceCalculationRequest", entity_id=rid).count() == 1
            assert db.query(Notification).count() == notices


def test_concurrent_unlocked_updates_characterize_stale_completion(customer_pg_sessions, monkeypatch):
    """Historical gate identity: drafts now lock and reject the stale contributor."""
    sessions = customer_pg_sessions
    case = _create_case(sessions)
    result = versioned_draft_race(
        sessions,
        monkeypatch,
        case,
        "accessories",
        [{"accessories": [{"name": "first", "price": 1}]}, {"accessories": [{"name": "second", "price": 2}]}],
    )
    assert result["accessories"] == [{"name": "first", "price": 1}]
    with sessions() as db:
        row = db.get(PriceCalculationRequest, case["request_id"])
        assert row.revision == 2 and row.accessories_submitted_at is None
        assert db.query(AuditLog).filter_by(entity_type="PriceCalculationRequest", entity_id=row.id).count() == 1
