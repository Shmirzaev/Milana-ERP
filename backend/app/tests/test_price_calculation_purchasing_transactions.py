from uuid import uuid4

import pytest

from app.core.deps import user_permissions
from app.libs.dto.planning.price_calculation_request_update import PriceCalculationPurchasingIn
from app.models import price_calculation_service as pricing
from app.models.planning import costing_service
from app.schemas import AuditLog, Model, Notification, User
from app.schemas.planning.price_calculation import PriceCalculationRequest


@pytest.fixture
def isolated_session_factory(tmp_path):
    """Give this module a private SQLite database, independent of app settings."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import app.schemas  # noqa: F401 - register all models before creating tables
    from app.db.base import Base

    engine = create_engine(
        f"sqlite:///{tmp_path / 'purchasing-transactions.db'}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()


def _create_purchasing_case(session_factory) -> dict[str, int | str]:
    token = uuid4().hex
    model_code = f"PC-PUR-{token}"
    with session_factory() as db:
        model = Model(
            code=model_code,
            name="Purchasing persistence test model",
            category="T-shirt",
            details_json={"general": {"model_no": model_code, "variant_no": "TEST"}},
            status="approved",
        )
        purchaser = User(
            name=f"Purchaser {token}",
            email=f"purchaser-{token}@example.invalid",
            password_hash="unused-test-hash",
            extra_permissions=["price_calculation.purchasing"],
        )
        finance = User(
            name=f"Finance {token}",
            email=f"finance-{token}@example.invalid",
            password_hash="unused-test-hash",
            extra_permissions=["finance.view"],
        )
        wildcard = User(
            name=f"Wildcard {token}",
            email=f"wildcard-{token}@example.invalid",
            password_hash="unused-test-hash",
            extra_permissions=["*"],
        )
        inactive_finance = User(
            name=f"Inactive finance {token}",
            email=f"inactive-finance-{token}@example.invalid",
            password_hash="unused-test-hash",
            extra_permissions=["finance.view"],
            is_active=False,
        )
        db.add_all([model, purchaser, finance, wildcard, inactive_finance])
        db.flush()
        request = PriceCalculationRequest(model_id=model.id, created_by_id=purchaser.id)
        db.add(request)
        db.commit()
        return {
            "request_id": request.id,
            "purchaser_id": purchaser.id,
            "finance_id": finance.id,
            "wildcard_id": wildcard.id,
            "inactive_finance_id": inactive_finance.id,
            "model_code": model_code,
        }


def _update(session_factory, case: dict[str, int | str], payload: PriceCalculationPurchasingIn) -> dict:
    with session_factory() as db:
        purchaser = db.get(User, case["purchaser_id"])
        assert purchaser is not None
        return costing_service.update_purchasing_details(
            db,
            request_id=case["request_id"],
            payload=payload,
            current=purchaser,
        )


def _finance_completion_notifications(db, case: dict[str, int | str]) -> list[Notification]:
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


def _eligible_finance_recipient_ids(db) -> set[int]:
    return {
        user.id
        for user in db.query(User).filter(User.is_active.is_(True)).all()
        if pricing.is_finance_pricing_user(user) and "*" not in user_permissions(user)
    }


def _purchasing_audits(db, case: dict[str, int | str]) -> list[AuditLog]:
    return (
        db.query(AuditLog)
        .filter(
            AuditLog.action == "update_purchasing_costs",
            AuditLog.entity_type == "PriceCalculationRequest",
            AuditLog.entity_id == case["request_id"],
        )
        .order_by(AuditLog.id)
        .all()
    )


def test_real_finance_notifications_follow_purchasing_completion_transitions(isolated_session_factory):
    session_factory = isolated_session_factory
    case = _create_purchasing_case(session_factory)

    partial = _update(session_factory, case, PriceCalculationPurchasingIn(fabric_price=4.5))
    assert partial["purchasing_status"] == "in_progress"
    with session_factory() as db:
        assert _finance_completion_notifications(db, case) == []

    completed = _update(
        session_factory,
        case,
        PriceCalculationPurchasingIn(fabric_price=4.5, sewing_cost=0.1674),
    )
    assert completed["purchasing_status"] == "complete"
    with session_factory() as db:
        notifications = _finance_completion_notifications(db, case)
        assert {row.user_id for row in notifications} == _eligible_finance_recipient_ids(db)
        assert case["finance_id"] in {row.user_id for row in notifications}
        assert case["wildcard_id"] not in {row.user_id for row in notifications}
        assert case["inactive_finance_id"] not in {row.user_id for row in notifications}
        assert notifications[0].title == "Purchasing costs completed"
        assert notifications[0].message == f"Model {case['model_code']} price request was updated."
        assert notifications[0].link == "/finance/price-calculation"

    _update(session_factory, case, PriceCalculationPurchasingIn(fabric_price=5.0, sewing_cost=0.2))
    with session_factory() as db:
        notifications = _finance_completion_notifications(db, case)
        assert len(notifications) == len(_eligible_finance_recipient_ids(db))

    cleared = _update(session_factory, case, PriceCalculationPurchasingIn())
    assert cleared["purchasing_status"] == "new"
    with session_factory() as db:
        notifications = _finance_completion_notifications(db, case)
        assert len(notifications) == len(_eligible_finance_recipient_ids(db))

    _update(session_factory, case, PriceCalculationPurchasingIn(fabric_price=4.5, sewing_cost=0.1674))
    with session_factory() as db:
        notifications = _finance_completion_notifications(db, case)
        assert len(notifications) == 2 * len(_eligible_finance_recipient_ids(db))
        recipient_ids = {row.user_id for row in notifications}
        assert case["finance_id"] in recipient_ids
        assert case["wildcard_id"] not in recipient_ids
        assert case["inactive_finance_id"] not in recipient_ids


def test_request_audit_and_finance_notification_roll_back_together_then_retry(monkeypatch, isolated_session_factory):
    session_factory = isolated_session_factory
    case = _create_purchasing_case(session_factory)
    original_notify_finance = pricing._notify_finance

    def fail_after_notification_is_flushed(db, request, title):
        original_notify_finance(db, request, title)
        db.flush()
        assert len(_purchasing_audits(db, case)) == 1
        notifications = _finance_completion_notifications(db, case)
        assert {row.user_id for row in notifications} == _eligible_finance_recipient_ids(db)
        raise RuntimeError("injected after request, audit and notification flush")

    payload = PriceCalculationPurchasingIn(fabric_price=4.5, sewing_cost=0.1674)
    with monkeypatch.context() as patch:
        patch.setattr(pricing, "_notify_finance", fail_after_notification_is_flushed)
        with session_factory() as db:
            purchaser = db.get(User, case["purchaser_id"])
            assert purchaser is not None
            with pytest.raises(RuntimeError, match="after request, audit and notification flush"):
                costing_service.update_purchasing_details(
                    db,
                    request_id=case["request_id"],
                    payload=payload,
                    current=purchaser,
                )
            staged = db.get(PriceCalculationRequest, case["request_id"])
            assert staged is not None
            assert float(staged.fabric_price) == pytest.approx(4.5)
            assert float(staged.sewing_cost) == pytest.approx(0.1674)
            assert staged.purchasing_updated_by_id == case["purchaser_id"]
            assert len(_purchasing_audits(db, case)) == 1
            notifications = _finance_completion_notifications(db, case)
            assert {row.user_id for row in notifications} == _eligible_finance_recipient_ids(db)
            db.rollback()

    with session_factory() as db:
        persisted = db.get(PriceCalculationRequest, case["request_id"])
        assert persisted is not None
        assert persisted.fabric_price is None
        assert persisted.sewing_cost is None
        assert persisted.purchasing_updated_by_id is None
        assert _purchasing_audits(db, case) == []
        assert _finance_completion_notifications(db, case) == []

    result = _update(session_factory, case, payload)
    assert result["purchasing_status"] == "complete"
    with session_factory() as db:
        persisted = db.get(PriceCalculationRequest, case["request_id"])
        assert persisted is not None
        assert float(persisted.fabric_price) == pytest.approx(4.5)
        assert float(persisted.sewing_cost) == pytest.approx(0.1674)
        assert persisted.purchasing_updated_by_id == case["purchaser_id"]
        assert len(_purchasing_audits(db, case)) == 1
        notifications = _finance_completion_notifications(db, case)
        assert {row.user_id for row in notifications} == _eligible_finance_recipient_ids(db)
