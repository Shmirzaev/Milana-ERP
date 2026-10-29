"""Price-calculation Purchasing transition and rollback on migrated PostgreSQL."""

from collections import Counter
from uuid import uuid4

import pytest
from sqlalchemy.orm import object_session

from app.libs.dto.planning.price_calculation_request_update import PriceCalculationPurchasingIn
from app.models import price_calculation_service as pricing
from app.models.planning import costing_service
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
        request = PriceCalculationRequest(model_id=model.id, created_by_id=purchaser.id)
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


def _update(sessions, case: dict[str, int | str], payload: PriceCalculationPurchasingIn) -> dict:
    with sessions() as db:
        purchaser = db.get(User, case["purchaser_id"])
        assert purchaser is not None
        return costing_service.update_purchasing_details(
            db,
            request_id=case["request_id"],
            payload=payload,
            current=purchaser,
        )


def _completion_notifications(db, case: dict[str, int | str]) -> list[Notification]:
    return (
        db.query(Notification)
        .filter(
            Notification.title == "Purchasing costs completed",
            Notification.message == f"Model {case['model_code']} price request was updated.",
            Notification.link == "/finance/price-calculation",
        )
        .order_by(Notification.id)
        .all()
    )


def _eligible_finance_ids(db) -> list[int]:
    """Snapshot every active, explicitly granted Finance recipient in this DB."""
    recipient_ids = []
    for user in db.query(User).filter(User.is_active.is_(True)).all():
        role_permissions = user.role.permissions if user.role is not None else []
        grants = set(role_permissions or []) | set(user.extra_permissions or [])
        if "finance.view" in grants and "*" not in grants:
            recipient_ids.append(user.id)
    return sorted(recipient_ids)


def _assert_recipient_multiplicity(notifications, expected_ids, *, per_recipient: int = 1):
    assert Counter(row.user_id for row in notifications) == Counter(
        {user_id: per_recipient for user_id in expected_ids}
    )


def _request_audits(db, request_id: int) -> list[AuditLog]:
    return (
        db.query(AuditLog)
        .filter(
            AuditLog.action == "update_purchasing_costs",
            AuditLog.entity_type == "PriceCalculationRequest",
            AuditLog.entity_id == request_id,
        )
        .order_by(AuditLog.id)
        .all()
    )


def test_pg_purchasing_completion_transition_recipients_and_audit_actor(customer_pg_sessions, monkeypatch):
    sessions = customer_pg_sessions
    case = _create_case(sessions)
    with sessions() as db:
        # This module-scoped fixture shares a DB across cases. Earlier cases may
        # leave active Finance users; notification policy correctly reaches all
        # eligible users, so snapshot the grants instead of assuming one user.
        expected_finance_ids = _eligible_finance_ids(db)
    assert case["finance_id"] in expected_finance_ids
    assert case["wildcard_id"] not in expected_finance_ids
    assert case["inactive_finance_id"] not in expected_finance_ids
    writer_sessions = []
    persist = pricing.apply_purchasing_contribution

    def observe_persistence(db, request, command, *, updated_by_id):
        assert db.bind.dialect.name == "postgresql"
        assert object_session(request) is db
        writer_sessions.append(db)
        return persist(db, request, command, updated_by_id=updated_by_id)

    monkeypatch.setattr(pricing, "apply_purchasing_contribution", observe_persistence)

    partial = _update(sessions, case, PriceCalculationPurchasingIn(fabric_price=4.5))
    assert partial["purchasing_status"] == "in_progress"
    with sessions() as db:
        request = db.get(PriceCalculationRequest, case["request_id"])
        assert request is not None
        assert float(request.fabric_price) == pytest.approx(4.5)
        assert request.sewing_cost is None
        assert request.purchasing_updated_by_id == case["purchaser_id"]
        assert _completion_notifications(db, case) == []
        first = _request_audits(db, case["request_id"])
        assert len(first) == 1
        assert first[0].user_id == case["purchaser_id"]
        assert first[0].new_value_json == {"fabric_price": 4.5, "sewing_cost": None}

    complete = _update(
        sessions,
        case,
        PriceCalculationPurchasingIn(fabric_price=4.5, sewing_cost=0.1674),
    )
    assert complete["purchasing_status"] == "complete"
    with sessions() as db:
        notifications = _completion_notifications(db, case)
        _assert_recipient_multiplicity(notifications, expected_finance_ids)
        assert all(
            (row.title, row.message, row.link)
            == (
                "Purchasing costs completed",
                f"Model {case['model_code']} price request was updated.",
                "/finance/price-calculation",
            )
            for row in notifications
        )
        assert case["wildcard_id"] not in {row.user_id for row in notifications}
        assert case["inactive_finance_id"] not in {row.user_id for row in notifications}
        audits = _request_audits(db, case["request_id"])
        assert len(audits) == 2
        assert [row.user_id for row in audits] == [case["purchaser_id"]] * 2
        assert audits[1].new_value_json == {"fabric_price": 4.5, "sewing_cost": 0.1674}

    # A completed-to-completed edit is audited but does not re-notify Finance.
    _update(sessions, case, PriceCalculationPurchasingIn(fabric_price=5.0, sewing_cost=0.2))
    with sessions() as db:
        notifications = _completion_notifications(db, case)
        _assert_recipient_multiplicity(notifications, expected_finance_ids)
        assert len(_request_audits(db, case["request_id"])) == 3

    # The legacy PATCH contract treats omitted values as None, clearing both.
    cleared = _update(sessions, case, PriceCalculationPurchasingIn())
    assert cleared["purchasing_status"] == "new"
    with sessions() as db:
        request = db.get(PriceCalculationRequest, case["request_id"])
        assert request is not None
        assert (request.fabric_price, request.sewing_cost) == (None, None)
        notifications = _completion_notifications(db, case)
        _assert_recipient_multiplicity(notifications, expected_finance_ids)

    _update(sessions, case, PriceCalculationPurchasingIn(fabric_price=4.5, sewing_cost=0.1674))
    with sessions() as db:
        notifications = _completion_notifications(db, case)
        _assert_recipient_multiplicity(notifications, expected_finance_ids, per_recipient=2)
        assert len(_request_audits(db, case["request_id"])) == 5
    assert len(writer_sessions) == 5
    chain(sessions)


def test_pg_purchasing_request_audit_and_notification_rollback_then_retry(
    customer_pg_sessions, monkeypatch
):
    sessions = customer_pg_sessions
    case = _create_case(sessions)
    with sessions() as db:
        # The module-scoped customer_pg_sessions fixture retains prior cases.
        # Read eligibility independently so the rollback assertions cover every
        # active Finance recipient without mutating or narrowing production policy.
        expected_finance_ids = _eligible_finance_ids(db)
    assert case["finance_id"] in expected_finance_ids
    assert case["wildcard_id"] not in expected_finance_ids
    assert case["inactive_finance_id"] not in expected_finance_ids
    original_notify = pricing._notify_finance
    attempted_sessions = []

    def fail_after_notification_is_flushed(db, request, title):
        original_notify(db, request, title)
        db.flush()
        assert request.fabric_price == 4.5
        assert request.sewing_cost == 0.1674
        assert request.purchasing_updated_by_id == case["purchaser_id"]
        notifications = _completion_notifications(db, case)
        _assert_recipient_multiplicity(notifications, expected_finance_ids)
        assert all(
            (row.title, row.message, row.link)
            == (
                "Purchasing costs completed",
                f"Model {case['model_code']} price request was updated.",
                "/finance/price-calculation",
            )
            for row in notifications
        )
        attempted_sessions.append(db)
        raise RuntimeError("injected after price request, audit and notification were staged")

    payload = PriceCalculationPurchasingIn(fabric_price=4.5, sewing_cost=0.1674)
    with monkeypatch.context() as patch:
        patch.setattr(pricing, "_notify_finance", fail_after_notification_is_flushed)
        with sessions() as db:
            purchaser = db.get(User, case["purchaser_id"])
            assert purchaser is not None
            with pytest.raises(RuntimeError, match="after price request, audit and notification"):
                costing_service.update_purchasing_details(
                    db,
                    request_id=case["request_id"],
                    payload=payload,
                    current=purchaser,
                )
            assert attempted_sessions == [db]
            assert object_session(db.get(PriceCalculationRequest, case["request_id"])) is db
            assert len(db.info.get("audit.chain.queues", {})) == 1
            db.rollback()

    with sessions() as db:
        persisted = db.get(PriceCalculationRequest, case["request_id"])
        assert persisted is not None
        assert (persisted.fabric_price, persisted.sewing_cost, persisted.purchasing_updated_by_id) == (None, None, None)
        assert _request_audits(db, case["request_id"]) == []
        assert _completion_notifications(db, case) == []

    result = _update(sessions, case, payload)
    assert result["purchasing_status"] == "complete"
    with sessions() as db:
        persisted = db.get(PriceCalculationRequest, case["request_id"])
        assert persisted is not None
        assert float(persisted.fabric_price) == pytest.approx(4.5)
        assert float(persisted.sewing_cost) == pytest.approx(0.1674)
        assert persisted.purchasing_updated_by_id == case["purchaser_id"]
        audits = _request_audits(db, case["request_id"])
        assert len(audits) == 1
        assert audits[0].user_id == case["purchaser_id"]
        assert audits[0].new_value_json == {"fabric_price": 4.5, "sewing_cost": 0.1674}
        notifications = _completion_notifications(db, case)
        _assert_recipient_multiplicity(notifications, expected_finance_ids)
        assert all(
            (row.title, row.message, row.link)
            == (
                "Purchasing costs completed",
                f"Model {case['model_code']} price request was updated.",
                "/finance/price-calculation",
            )
            for row in notifications
        )
    chain(sessions)
