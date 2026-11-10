"""Real migrated PostgreSQL locking, uniqueness, rollback and replay checks."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.libs.dto.planning.price_calculation_request_input import PriceCalculationCreateIn
from app.models.planning import variant_pricing_service as workflow
from app.schemas import AuditLog, CuttingPassport, Model, Notification, PriceCalculationRequest, User
from app.schemas.planning.price_calculation_persistence import apply_workflow_fields
from app.tests.test_price_calculation_status_postgres import app_for, auth, customer_pg_sessions  # noqa: F401


def seed(sessions):
    marker = uuid4().hex
    with sessions.begin() as db:
        model = Model(code=marker, name="Variant pricing PG", status="approved")
        users = [User(name=name, email=f"{marker}-{name}@example.invalid", password_hash="unused", factory_code="MIL", extra_permissions=permissions)
            for name, permissions in [("sales", ["sales.orders"]), ("purchasing", ["price_calculation.purchasing"]),
                ("accessories", ["price_calculation.accessories"]), ("finance", ["finance.view", "price_calculation.approve"])]]
        db.add_all([model, *users]); db.flush()
        return model.id, {user.name: user.id for user in users}


def ready_case(sessions):
    model_id, users = seed(sessions)
    with sessions() as db:
        response = workflow.create_request(db, PriceCalculationCreateIn(model_id=model_id), db.get(User, users["sales"]))
    with sessions.begin() as db:
        request = db.get(PriceCalculationRequest, response["id"])
        apply_workflow_fields(db, request, materials_json=[{"key": "fabric", "name": "Fabric", "unit": "m", "consumption": 1.5, "rate": 2}],
            sewing_cost=.5, no_accessories_reason="No trims required", passport_snapshot_json={"has_print": False})
    return model_id, response["id"], users


def test_pg_concurrent_creation_one_slot_audit_and_team_notice(customer_pg_sessions):
    sessions = customer_pg_sessions
    model_id, users = seed(sessions)
    barrier = Barrier(8)
    def create(_):
        barrier.wait(timeout=15)
        with TestClient(app_for(sessions)) as client:
            result = client.post("/api/price-calculation/requests", headers=auth(users["sales"]), json={"model_id": model_id})
            assert result.status_code == 201, result.text
            return result.json()["id"]
    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(pool.map(create, range(8)))
    assert len(set(ids)) == 1
    with sessions() as db:
        assert db.query(PriceCalculationRequest).filter_by(model_id=model_id).count() == 1
        assert db.query(AuditLog).filter_by(entity_type="PriceCalculationRequest", entity_id=ids[0], action="create").count() == 1
        for team in ("purchasing", "accessories"):
            assert db.query(Notification).filter_by(user_id=users[team], title="Variant price information required").count() == 1
        duplicate = PriceCalculationRequest(model_id=model_id, active_model_id=model_id, created_by_id=users["sales"])
        db.add(duplicate)
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()


def test_pg_parallel_submissions_retry_once_and_single_finance_notification(customer_pg_sessions):
    sessions = customer_pg_sessions
    model_id, request_id, users = ready_case(sessions)
    with sessions() as db:
        revision = db.get(PriceCalculationRequest, request_id).revision
    barrier = Barrier(2)
    def submit(team):
        barrier.wait(timeout=15)
        with TestClient(app_for(sessions)) as client:
            response = client.post(f"/api/price-calculation/requests/{request_id}/submit/{team}", headers=auth(users[team]), json={"expected_revision": revision})
            return team, response.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, ("purchasing", "accessories")))
    assert sorted(status for _, status in results) == [200, 409]
    retry_team = next(team for team, status in results if status == 409)
    with sessions() as db:
        revision = db.get(PriceCalculationRequest, request_id).revision
    with TestClient(app_for(sessions)) as client:
        response = client.post(f"/api/price-calculation/requests/{request_id}/submit/{retry_team}", headers=auth(users[retry_team]), json={"expected_revision": revision})
        assert response.status_code == 200, response.text
        assert response.json()["workflow_state"] == "awaiting_finance"
        assert response.json()["cost_price"] == 3.6
    with sessions() as db:
        assert db.query(Notification).filter_by(user_id=users["finance"], title="Price ready for Finance approval").count() == 1
        assert db.get(Model, model_id).selling_price is None


def test_pg_approval_race_one_price_and_audit_and_atomic_rollback(customer_pg_sessions, monkeypatch):
    sessions = customer_pg_sessions
    model_id, request_id, users = ready_case(sessions)
    with sessions.begin() as db:
        request = db.get(PriceCalculationRequest, request_id)
        now = datetime.now(timezone.utc)
        apply_workflow_fields(db, request, purchasing_submitted_at=now, accessories_submitted_at=now, workflow_state="awaiting_finance")
        revision = request.revision
    original = workflow.apply_request_selling_price
    def fail_after_price(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("Injected transaction failure after price persistence")
    with monkeypatch.context() as patch:
        patch.setattr(workflow, "apply_request_selling_price", fail_after_price)
        with TestClient(app_for(sessions), raise_server_exceptions=False) as client:
            failed = client.post(f"/api/price-calculation/requests/{request_id}/approve", headers=auth(users["finance"]), json={"expected_revision": revision, "selling_price": 5})
            assert failed.status_code == 500
    with sessions() as db:
        assert db.get(Model, model_id).selling_price is None
        request = db.get(PriceCalculationRequest, request_id)
        assert request.workflow_state == "awaiting_finance" and request.approved_at is None and request.active_model_id == model_id
    barrier = Barrier(2)
    def approve(price):
        barrier.wait(timeout=15)
        with TestClient(app_for(sessions)) as client:
            response = client.post(f"/api/price-calculation/requests/{request_id}/approve", headers=auth(users["finance"]), json={"expected_revision": revision, "selling_price": price})
            return response.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(approve, (5, 6)))
    assert sorted(result) == [200, 409]
    with sessions() as db:
        assert float(db.get(Model, model_id).selling_price) in {5, 6}
        assert db.query(AuditLog).filter_by(entity_type="PriceCalculationRequest", entity_id=request_id, action="approve_variant_price").count() == 1


def test_pg_source_change_makes_pending_approval_stale(customer_pg_sessions):
    sessions = customer_pg_sessions
    model_id, users = seed(sessions)
    with sessions.begin() as db:
        passport = CuttingPassport(passport_no=uuid4().hex[:20], date=datetime.now(timezone.utc), model_code=db.get(Model, model_id).code,
            size_range="S", meter_mode=True, lay_length_m=2)
        db.add(passport); db.flush()
        workflow.sync_passport_pricing(db, passport, db.get(User, users["sales"]))
        request = db.query(PriceCalculationRequest).filter_by(active_model_id=model_id).one()
        now = datetime.now(timezone.utc)
        apply_workflow_fields(db, request, materials_json=[{**row, "rate": 1} for row in request.materials_json],
            sewing_cost=0, no_accessories_reason="No trims", purchasing_submitted_at=now, accessories_submitted_at=now, workflow_state="awaiting_finance")
        request_id, passport_id, revision = request.id, passport.id, request.revision
    with sessions.begin() as db:
        passport = db.get(CuttingPassport, passport_id)
        passport.lay_length_m = 3
        workflow.sync_passport_pricing(db, passport, db.get(User, users["sales"]))
    with TestClient(app_for(sessions)) as client:
        response = client.post(f"/api/price-calculation/requests/{request_id}/approve", headers=auth(users["finance"]), json={"expected_revision": revision, "selling_price": 6})
        assert response.status_code == 409, response.text
    with sessions() as db:
        assert db.get(Model, model_id).selling_price is None
