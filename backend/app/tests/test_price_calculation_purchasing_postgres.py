"""Price-calculation Purchasing transition and rollback on migrated PostgreSQL."""

from uuid import uuid4


from app.libs.dto.planning.price_calculation_request_update import PriceCalculationPurchasingIn
from app.models.planning import costing_service
from app.models.planning.variant_pricing_service import baseline
from app.schemas import AuditLog, Model, Notification, PriceCalculationRequest, User
from app.tests.test_customer_create_postgres import chain, customer_pg_sessions  # noqa: F401


def _create_case(sessions) -> dict[str, int | str]:
    token = uuid4().hex
    model_code = f"PG-PC-PUR-{token}"
    with sessions.begin() as db:
        model = Model(
            code=model_code,
            name="PostgreSQL purchasing costing fixture",
            category="T-shirt",
            details_json={"general": {"model_no": model_code, "variant_no": "PG"}},
            status="approved",
        )
        purchaser = User(
            name=f"Purchaser {token}",
            email=f"purchaser-{token}@example.invalid",
            password_hash="unused-test-hash",
            factory_code="MIL",
            extra_permissions=["price_calculation.purchasing"],
        )
        finance = User(
            name=f"Finance {token}",
            email=f"finance-{token}@example.invalid",
            password_hash="unused-test-hash",
            factory_code="MIL",
            extra_permissions=["finance.view"],
        )
        wildcard = User(
            name=f"Wildcard {token}",
            email=f"wildcard-{token}@example.invalid",
            password_hash="unused-test-hash",
            factory_code="MIL",
            extra_permissions=["*"],
        )
        inactive_finance = User(
            name=f"Inactive finance {token}",
            email=f"inactive-finance-{token}@example.invalid",
            password_hash="unused-test-hash",
            factory_code="MIL",
            extra_permissions=["finance.view"],
            is_active=False,
        )
        db.add_all([model, purchaser, finance, wildcard, inactive_finance])
        db.flush()
        request = PriceCalculationRequest(
            model_id=model.id,
            active_model_id=model.id,
            factory_code="MIL",
            workflow_state="collecting",
            price_baseline_json=baseline(model),
            created_by_id=purchaser.id,
        )
        db.add(request)
        db.flush()
        return {
            "request_id": request.id,
            "purchaser_id": purchaser.id,
            "finance_id": finance.id,
            "wildcard_id": wildcard.id,
            "inactive_finance_id": inactive_finance.id,
            "model_code": model_code,
        }


def _eligible_finance_ids(db):
    from app.models.price_calculation_service import is_finance_pricing_user
    from app.core.deps import user_permissions

    return sorted(
        user.id
        for user in db.query(User).filter_by(is_active=True).all()
        if is_finance_pricing_user(user) and "*" not in user_permissions(user)
    )


def _update(sessions, case, payload):
    with sessions() as db:
        return costing_service.update_purchasing_details(
            db, case["request_id"], payload, db.get(User, case["purchaser_id"])
        )


def test_pg_purchasing_completion_transition_recipients_and_audit_actor(customer_pg_sessions, monkeypatch):
    from app.tests.test_price_calculation_status_postgres import app_for, auth
    from fastapi.testclient import TestClient

    sessions = customer_pg_sessions
    case = _create_case(sessions)
    rid = case["request_id"]
    with sessions.begin() as db:
        request = db.get(PriceCalculationRequest, rid)
        request.materials_json = [{"key": "fabric", "name": "Fabric", "unit": "kg", "consumption": 1, "rate": None}]
        notices = db.query(Notification).count()
    partial = _update(sessions, case, PriceCalculationPurchasingIn(fabric_price=4.5))
    assert partial["purchasing_status"] == "in_progress"
    complete = _update(sessions, case, PriceCalculationPurchasingIn(sewing_cost=0))
    assert complete["purchasing_status"] == "in_progress"  # Saving is never submission.
    assert complete["materials"][0]["rate"] == 4.5  # Omitted field is preserved.
    with TestClient(app_for(sessions)) as client:
        submitted = client.post(
            f"/api/price-calculation/requests/{rid}/submit/purchasing",
            headers=auth(case["purchaser_id"]),
            json={"expected_revision": complete["revision"]},
        )
        assert submitted.status_code == 200, submitted.text
        assert submitted.json()["purchasing_status"] == "complete"
        assert (
            client.patch(
                f"/api/price-calculation/requests/{rid}/purchasing",
                headers=auth(case["purchaser_id"]),
                json={"sewing_cost": 2},
            ).status_code
            == 409
        )
    with sessions() as db:
        assert db.query(Notification).count() == notices  # Other contribution is still missing.
        audits = (
            db.query(AuditLog)
            .filter_by(entity_type="PriceCalculationRequest", entity_id=rid)
            .order_by(AuditLog.id)
            .all()
        )
        assert [row.action for row in audits] == [
            "save_purchasing_price_draft",
            "save_purchasing_price_draft",
            "submit_price_costs",
        ]
        assert all(row.user_id == case["purchaser_id"] and row.entry_hash for row in audits)
    chain(sessions)


def test_pg_purchasing_request_audit_and_notification_rollback_then_retry(customer_pg_sessions, monkeypatch):
    from fastapi.testclient import TestClient
    from app.tests.pricing_pg_checks import draft_failure
    from app.tests.test_price_calculation_status_postgres import app_for, auth

    sessions = customer_pg_sessions
    for fault in ("write", "audit", "commit"):
        case = _create_case(sessions)
        rid = case["request_id"]
        with sessions() as db:
            notices = db.query(Notification).count()
        with draft_failure(sessions, monkeypatch, rid, fault) as attempted:
            with TestClient(app_for(sessions), raise_server_exceptions=False) as client:
                assert (
                    client.patch(
                        f"/api/price-calculation/requests/{rid}/purchasing",
                        headers=auth(case["purchaser_id"]),
                        json={"fabric_price": 4.5, "sewing_cost": 0},
                    ).status_code
                    == 500
                )
        with sessions() as db:
            row = db.get(PriceCalculationRequest, rid)
            assert (row.fabric_price, row.sewing_cost, row.purchasing_updated_by_id, row.revision) == (
                None,
                None,
                None,
                1,
            )
            assert db.query(AuditLog).filter_by(entity_type="PriceCalculationRequest", entity_id=rid).count() == 0
            assert all(db.get(AuditLog, key) is None for key in attempted)
            assert db.query(Notification).count() == notices
        result = _update(sessions, case, PriceCalculationPurchasingIn(fabric_price=4.5, sewing_cost=0))
        assert result["revision"] == 2 and result["purchasing_status"] == "in_progress"
        with sessions() as db:
            assert db.get(PriceCalculationRequest, rid).purchasing_submitted_at is None
            assert db.query(AuditLog).filter_by(entity_type="PriceCalculationRequest", entity_id=rid).count() == 1
    chain(sessions)
