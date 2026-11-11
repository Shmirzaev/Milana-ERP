"""Real migrated PostgreSQL import rollback and competing Finance approval."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy import text

from app.libs.dto.planning.price_workflow_input import PriceWorkflowActionIn
from app.models.catalog.price_import_service import import_reviewed_prices
from app.models.planning import variant_pricing_service as workflow
from app.schemas import AuditLog, Model, PriceCalculationRequest, User
from app.tests.test_catalog_price_import import manifest_for
from app.tests.test_price_calculation_status_postgres import app_for, auth, customer_pg_sessions  # noqa: F401
from app.tests.test_variant_price_workflow_postgres import ready_case


@pytest.mark.parametrize("heads,allowed", [
    (["0156_variant_price_workflow"], True),
    (["0157_pricing_gate_live_merge"], True),
    (["0155_eco_gate_merge"], False),
    (["0156_gate_live_integration"], False),
    (["unreviewed_future_head"], False),
    (["0156_variant_price_workflow", "0156_gate_live_integration"], False),
    ([], False),
], ids=["pricing", "hr-merge", "pre-pricing", "gate-only", "unknown", "multiple", "empty"])
def test_pg_import_schema_guard_allows_only_reviewed_single_heads(customer_pg_sessions, heads, allowed):
    sessions = customer_pg_sessions
    marker = uuid4().hex
    with sessions.begin() as db:
        actor = User(name="Schema guard QA", email=marker+"@example.invalid", password_hash="unused",
            extra_permissions=["*", "admin.super"])
        model = Model(code=marker, name="Schema guard QA", status="approved")
        db.add_all([actor, model]); db.flush()
        actor_id, model_id = actor.id, model.id
        manifest = manifest_for([model])
    with sessions() as db:
        original = db.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
        before = db.query(AuditLog).count()
        db.execute(text("DELETE FROM alembic_version"))
        for head in heads:
            db.execute(text("INSERT INTO alembic_version (version_num) VALUES (:head)"), {"head":head})
        try:
            if allowed:
                assert import_reviewed_prices(db, manifest, db.get(User, actor_id))["applied"] is False
            else:
                with pytest.raises(HTTPException) as error:
                    import_reviewed_prices(db, manifest, db.get(User, actor_id))
                assert error.value.status_code == 409
        finally:
            db.rollback()
        assert db.execute(text("SELECT version_num FROM alembic_version")).scalars().all() == original
        assert db.query(AuditLog).count() == before
        assert db.get(Model, model_id).selling_price is None


def test_pg_import_deferred_commit_failure_preserves_prices_requests_and_history(customer_pg_sessions):
    sessions = customer_pg_sessions
    marker = uuid4().hex
    with sessions.begin() as db:
        actor = User(
            name="Import admin",
            email=marker + "@example.invalid",
            password_hash="unused",
            extra_permissions=["*", "admin.super"],
        )
        models = [Model(code=marker + str(i), name="Import atomic", status="approved") for i in range(2)]
        db.add_all([actor, *models])
        db.flush()
        active = PriceCalculationRequest(
            model_id=models[0].id,
            active_model_id=models[0].id,
            workflow_state="collecting",
            factory_code="MIL",
            created_by_id=actor.id,
        )
        historical = PriceCalculationRequest(
            model_id=models[1].id,
            workflow_state="approved",
            factory_code="MIL",
            created_by_id=actor.id,
            approval_snapshot_json={"selling_price": 7, "cost_price": 4},
        )
        db.add_all([active, historical])
        db.flush()
        models[1].selling_price = 7
        models[1].selling_price_currency = "USD"
        models[1].selling_price_source = "price_request"
        models[1].selling_price_request_id = historical.id
        ids = [model.id for model in models]
        actor_id = actor.id
        request_id = active.id
        history_id = historical.id
        manifest = manifest_for(models)
    guard = "import_guard_" + marker[:12]
    engine = sessions.kw["bind"]
    with engine.begin() as connection:
        connection.exec_driver_sql(
            f"CREATE FUNCTION {guard}() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'owned import commit failure' USING ERRCODE='23514',CONSTRAINT='{guard}'; END; $$"
        )
        connection.exec_driver_sql(
            f"CREATE CONSTRAINT TRIGGER {guard} AFTER UPDATE ON models DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN (NEW.id={ids[1]}) EXECUTE FUNCTION {guard}()"
        )
    try:
        with sessions() as db:
            with pytest.raises(IntegrityError) as error:
                import_reviewed_prices(db, manifest, db.get(User, actor_id), apply=True)
            assert error.value.orig.pgcode == "23514" and error.value.orig.diag.constraint_name == guard
            db.rollback()
        with sessions() as db:
            assert db.get(Model, ids[0]).selling_price is None and db.get(Model, ids[1]).selling_price == 7
            request = db.get(PriceCalculationRequest, request_id)
            assert request.active_model_id == ids[0] and request.workflow_state == "collecting"
            assert db.get(PriceCalculationRequest, history_id).approval_snapshot_json == {
                "selling_price": 7,
                "cost_price": 4,
            }
            assert db.query(AuditLog).filter(AuditLog.entity_type == "Model", AuditLog.entity_id.in_(ids)).count() == 0
            assert (
                db.query(AuditLog).filter_by(entity_type="PriceCalculationRequest", entity_id=request_id).count() == 0
            )
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f"DROP TRIGGER {guard} ON models")
            connection.exec_driver_sql(f"DROP FUNCTION {guard}()")
    with sessions() as db:
        result = import_reviewed_prices(db, manifest, db.get(User, actor_id), apply=True)
        assert result["update_count"] == 2 and result["readback_verified"]
        assert db.get(PriceCalculationRequest, request_id).workflow_state == "cancelled"
        assert db.get(PriceCalculationRequest, history_id).approval_snapshot_json == {
            "selling_price": 7,
            "cost_price": 4,
        }


def test_pg_import_and_finance_approval_serialize_to_one_winner(customer_pg_sessions):
    sessions = customer_pg_sessions
    model_id, request_id, users = ready_case(sessions)
    with sessions() as db:
        request = db.get(PriceCalculationRequest, request_id)
        workflow.submit_contribution(
            db,
            request_id,
            workflow.PriceContributionTeam.PURCHASING,
            PriceWorkflowActionIn(expected_revision=request.revision),
            db.get(User, users["purchasing"]),
        )
    with sessions() as db:
        request = db.get(PriceCalculationRequest, request_id)
        workflow.submit_contribution(
            db,
            request_id,
            workflow.PriceContributionTeam.ACCESSORIES,
            PriceWorkflowActionIn(expected_revision=request.revision),
            db.get(User, users["accessories"]),
        )
    with sessions.begin() as db:
        admin = User(
            name="Concurrent import",
            email=uuid4().hex + "@example.invalid",
            password_hash="unused",
            extra_permissions=["*", "admin.super"],
        )
        db.add(admin)
        db.flush()
        admin_id = admin.id
        model = db.get(Model, model_id)
        manifest = manifest_for([model])
        revision = db.get(PriceCalculationRequest, request_id).revision
    barrier = Barrier(2)

    def send(operation):
        barrier.wait(timeout=15)
        if operation == "import":
            with sessions() as db:
                try:
                    import_reviewed_prices(db, manifest, db.get(User, admin_id), apply=True)
                    return 200
                except HTTPException as error:
                    db.rollback()
                    return error.status_code
        with TestClient(app_for(sessions)) as client:
            return client.post(
                f"/api/price-calculation/requests/{request_id}/approve",
                headers=auth(users["finance"]),
                json={"expected_revision": revision, "selling_price": 6},
            ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(send, ["import", "approve"]))
    assert sorted(results) == [200, 409]
    with sessions() as db:
        model = db.get(Model, model_id)
        request = db.get(PriceCalculationRequest, request_id)
        assert request.active_model_id is None
        assert (model.selling_price == 6 and request.workflow_state == "approved") or (
            model.selling_price == manifest.prices[0].selling_price and request.workflow_state == "cancelled"
        )
        import_count = (
            db.query(AuditLog)
            .filter_by(entity_type="Model", entity_id=model_id, action="import_catalog_selling_price")
            .count()
        )
        approval_count = (
            db.query(AuditLog)
            .filter_by(entity_type="PriceCalculationRequest", entity_id=request_id, action="approve_variant_price")
            .count()
        )
        assert import_count + approval_count == 1
