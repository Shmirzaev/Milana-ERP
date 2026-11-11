"""Owned migrated PostgreSQL retirement rollback and competing financial writers."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier, Event
from time import monotonic
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import lazyload

from app.libs.dto.planning.price_workflow_input import PriceApprovalIn, PriceRetirementTarget
from app.models.catalog.price_import_service import import_reviewed_prices
from app.models.planning import variant_pricing_policy as policy
from app.models.planning import variant_pricing_reconciliation_service as retirement
from app.models.planning import variant_pricing_service as workflow
from app.schemas import AuditLog, Model, PriceCalculationRequest, User
from app.tests.test_catalog_price_import import manifest_for
from app.tests.test_customer_create_postgres import customer_pg_sessions  # noqa: F401


def seed(sessions, count=1):
    marker = uuid4().hex
    with sessions.begin() as db:
        actor = User(name="Scope admin", email=marker + "@example.invalid", password_hash="unused",
                     extra_permissions=["*", "admin.super"])
        models = [Model(code=marker + str(i), name="Old scoped variant", created_at=policy.CREATED_FROM - timedelta(days=1)) for i in range(count)]
        db.add_all([actor, *models])
        db.flush()
        now = datetime.now(timezone.utc)
        requests = [PriceCalculationRequest(model_id=model.id, active_model_id=model.id, factory_code="MIL",
            created_by_id=actor.id, workflow_state="awaiting_finance", sewing_cost=.5,
            materials_json=[{"key": "fabric", "name": "Fabric", "unit": "kg", "consumption": 1, "rate": 2}],
            accessories_json=[{"name": "Label", "price": .1}], purchasing_submitted_at=now,
            accessories_submitted_at=now, passport_snapshot_json={"has_print": False},
            price_baseline_json=workflow.baseline(model)) for model in models]
        db.add_all(requests)
        db.flush()
        targets = [PriceRetirementTarget(request_id=row.id, model_id=row.model_id, expected_revision=row.revision) for row in requests]
        return actor.id, [model.id for model in models], targets


def facts(db):
    return {table.name: [dict(row._mapping) for row in db.execute(select(table).order_by(table.c.id))]
            for table in (Model.__table__, PriceCalculationRequest.__table__, AuditLog.__table__)}


def test_pg_retirement_deferred_commit_failure_preserves_all_rows(customer_pg_sessions):
    sessions = customer_pg_sessions
    actor_id, model_ids, targets = seed(sessions, 2)
    marker = "retirement_" + uuid4().hex[:12]
    engine = sessions.kw["bind"]
    with sessions() as db:
        before = facts(db)
    with engine.begin() as connection:
        connection.exec_driver_sql(f"CREATE FUNCTION {marker}() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'owned retirement failure' USING ERRCODE='23514',CONSTRAINT='{marker}'; END; $$")
        connection.exec_driver_sql(f"CREATE CONSTRAINT TRIGGER {marker} AFTER UPDATE ON price_calculation_requests DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN (NEW.id={targets[-1].request_id}) EXECUTE FUNCTION {marker}()")
    try:
        with sessions() as db:
            with pytest.raises(IntegrityError) as error:
                retirement.reconcile(db, db.get(User, actor_id), targets, apply=True)
            assert error.value.orig.pgcode == "23514" and error.value.orig.diag.constraint_name == marker
            db.rollback()
        with sessions() as db:
            assert facts(db) == before
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f"DROP TRIGGER {marker} ON price_calculation_requests")
            connection.exec_driver_sql(f"DROP FUNCTION {marker}()")
    with sessions() as db:
        result = retirement.reconcile(db, db.get(User, actor_id), targets, apply=True)
        assert result["readback_verified"]
        for target in targets:
            row = db.get(PriceCalculationRequest, target.request_id)
            assert row.workflow_state == "cancelled" and row.active_model_id is None
            assert row.purchasing_submitted_at and row.accessories_submitted_at
            assert row.materials_json[0]["rate"] == 2 and row.accessories_json[0]["price"] == .1
        assert all(db.get(Model, model_id).selling_price is None for model_id in model_ids)


def test_pg_retirement_and_approval_wait_on_same_model_and_refuse_old_price(customer_pg_sessions):
    sessions = customer_pg_sessions
    actor_id, model_ids, targets = seed(sessions)
    holder = sessions()
    holder.query(Model).options(lazyload("*")).filter_by(id=model_ids[0]).with_for_update(of=Model).one()
    barrier = Barrier(3)
    pids = {}

    def send(operation):
        with sessions() as db:
            pids[operation] = db.execute(text("SELECT pg_backend_pid()")).scalar_one()
            actor = db.get(User, actor_id)
            barrier.wait(timeout=10)
            try:
                if operation == "retire":
                    retirement.reconcile(db, actor, targets, apply=True)
                else:
                    workflow.approve(db, targets[0].request_id,
                        PriceApprovalIn(expected_revision=targets[0].expected_revision, selling_price=6), actor)
                return 200
            except HTTPException as error:
                db.rollback()
                return error.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(send, operation) for operation in ("retire", "approve")]
        try:
            barrier.wait(timeout=10)
            deadline = monotonic() + 8
            waiting = 0
            while monotonic() < deadline:
                with sessions() as diagnostic:
                    waiting = diagnostic.execute(text("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND pid=ANY(:pids) AND wait_event_type='Lock'"), {"pids": list(pids.values())}).scalar_one()
                if waiting == 2:
                    break
                Event().wait(.02)
            assert waiting == 2, "Both financial writers must visibly wait on the owned Model lock"
        finally:
            holder.rollback()
            holder.close()
        assert [future.result(timeout=12) for future in futures] == [200, 409]
    with sessions() as db:
        row = db.get(PriceCalculationRequest, targets[0].request_id)
        assert row.workflow_state == "cancelled" and row.approved_at is None
        assert db.get(Model, model_ids[0]).selling_price is None
        assert db.query(AuditLog).filter_by(entity_type="PriceCalculationRequest", entity_id=row.id, action="cancel_price_request").count() == 1
        assert db.query(AuditLog).filter_by(entity_type="PriceCalculationRequest", entity_id=row.id, action="approve_variant_price").count() == 0


def test_pg_retirement_and_import_serialize_without_duplicate_cancellation(customer_pg_sessions):
    sessions = customer_pg_sessions
    actor_id, model_ids, targets = seed(sessions)
    with sessions() as db:
        manifest = manifest_for([db.get(Model, model_ids[0])])
    barrier = Barrier(2)

    def send(operation):
        with sessions() as db:
            actor = db.get(User, actor_id)
            barrier.wait(timeout=10)
            try:
                if operation == "retire":
                    retirement.reconcile(db, actor, targets, apply=True)
                else:
                    import_reviewed_prices(db, manifest, actor, apply=True)
                return 200
            except HTTPException as error:
                db.rollback()
                return error.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        retired, imported = list(pool.map(send, ("retire", "import")))
    assert imported == 200 and retired in (200, 409)
    with sessions() as db:
        row = db.get(PriceCalculationRequest, targets[0].request_id)
        assert row.workflow_state == "cancelled" and row.active_model_id is None
        assert row.purchasing_submitted_at and row.accessories_submitted_at and row.materials_json[0]["rate"] == 2
        assert db.get(Model, model_ids[0]).selling_price == manifest.prices[0].selling_price
        assert db.query(AuditLog).filter(AuditLog.entity_type == "PriceCalculationRequest", AuditLog.entity_id == row.id,
            AuditLog.action.in_(["cancel_price_request", "cancel_price_request_for_import"])).count() == 1
