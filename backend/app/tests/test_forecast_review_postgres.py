"""Real PostgreSQL behaviour of the forecast review write.

Only an explicitly owned disposable review database on the identity-pinned
review instance may be used. The instance pins are re-verified inside the
fixture, so the module cannot silently run against another server.
"""
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from app.libs.dto.planning.forecast_recommendation_input import ForecastRecommendationIn
from app.libs.dto.planning.forecast_recommendation_update import ForecastRecommendationPatch
from app.libs.enums.planning import ForecastRecommendationStatus
from app.models.planning import forecasting_recommendations_service as service
from app.schemas import AuditLog, Brand, Collection, ForecastRecommendation, Item, Model, Role, User

@pytest.fixture(scope="module")
def sessions():
    # BLOCKED until the independently reviewed shared owned-target guard is
    # integrated. Never enter the former unguarded create_all/TRUNCATE path.
    pytest.skip("BLOCKED: reviewed owned PostgreSQL fixture and GO_PG required")


@pytest.fixture
def case(sessions):
    engine, factory = sessions
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "TRUNCATE forecast_recommendations, audit_logs, models, items, brands, "
            "collections, users, roles RESTART IDENTITY CASCADE"
        )
    with factory.begin() as db:
        role = Role(name="Forecast reviewer", permissions=["forecasting.view", "forecasting.manage"])
        db.add(role)
        db.flush()
        user = User(
            name="Forecast reviewer",
            email="forecast-review-pg@example.invalid",
            password_hash="unused",
            role_id=role.id,
            factory_code="MIL",
            is_active=True,
        )
        model = Model(code="REVIEW-MIL", name="Scoped model", status="approved", factory_code="MIL")
        other = Model(code="REVIEW-BST", name="Other model", status="approved", factory_code="BST")
        brand = Brand(name="Forecast brand")
        item = Item(sku="REVIEW-FAB", name="Material", category="fabric", unit="kg")
        db.add_all([user, model, other, brand, item])
        db.flush()
        collection = Collection(name="Forecast collection", brand_id=brand.id)
        db.add(collection)
        db.flush()
        ids = {
            "user": user.id,
            "model": model.id,
            "other": other.id,
            "brand": brand.id,
            "item": item.id,
            "collection": collection.id,
        }
    return engine, factory, ids


def _create(factory, ids, **changes):
    fields = dict(
        recommendation_type="item_reorder",
        model_id=ids["model"],
        item_id=ids["item"],
        brand_id=ids["brand"],
        collection_id=ids["collection"],
        suggested_quantity="12.34567",
        unit="kg",
    )
    fields.update(changes)
    payload = ForecastRecommendationIn(**fields)
    with factory() as db:
        return service.create_recommendation(db, payload, ["MIL"], db.get(User, ids["user"]))


def _review(factory, ids, row_id, status, factory_codes=("MIL",)):
    with factory() as db:
        return service.update_recommendation(
            db,
            row_id,
            ForecastRecommendationPatch(status=status),
            list(factory_codes),
            db.get(User, ids["user"]),
        )


def test_real_review_stores_the_plain_status_and_audits_the_plain_action(case):
    _, factory, ids = case
    created = _create(factory, ids)

    result = _review(factory, ids, created.id, "accepted")

    assert result.status is ForecastRecommendationStatus.ACCEPTED
    with factory() as db:
        stored = db.get(ForecastRecommendation, created.id)
        assert stored.status == "accepted"
        assert type(stored.status) is str
        assert stored.reviewed_by == ids["user"]
        assert stored.reviewed_at is not None
        audit = (
            db.query(AuditLog)
            .filter(
                AuditLog.entity_type == "ForecastRecommendation",
                AuditLog.entity_id == created.id,
                AuditLog.action == "accepted_forecast_recommendation",
            )
            .one()
        )
        assert audit.action == "accepted_forecast_recommendation"
        assert "ForecastRecommendationStatus" not in audit.action
        assert audit.old_value_json == {"status": "open"}
        assert audit.new_value_json == {"status": "accepted"}


def test_real_review_keeps_the_audit_hash_chain(case):
    _, factory, ids = case
    created = _create(factory, ids)
    _review(factory, ids, created.id, "dismissed")

    with factory() as db:
        logs = db.query(AuditLog).order_by(AuditLog.id).all()
        previous = None
        for entry in logs:
            data = dict(
                prev_hash=previous,
                user_id=ids["user"],
                action=entry.action,
                entity_type=entry.entity_type,
                entity_id=entry.entity_id,
                old_value=entry.old_value_json,
                new_value=entry.new_value_json,
            )
            expected = hashlib.sha256(
                json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
            ).hexdigest()
            assert entry.prev_hash == previous and entry.entry_hash == expected
            previous = expected
        assert [entry.action for entry in logs] == [
            "create_forecast_recommendation",
            "dismissed_forecast_recommendation",
        ]


def test_the_schema_owned_review_write_emits_one_update_and_never_commits(case, monkeypatch):
    engine, factory, ids = case
    created = _create(factory, ids)
    statements = []
    original = service.apply_forecast_recommendation_review

    def observe(db, command, row):
        commits = []

        def unexpected_commit(*args):
            commits.append(True)

        event.listen(db, "before_commit", unexpected_commit)
        try:
            assert command.status is ForecastRecommendationStatus.CONVERTED
            result = original(db, command, row)
            assert not commits, "the schema-owned review write must not commit"
            return result
        finally:
            event.remove(db, "before_commit", unexpected_commit)

    monkeypatch.setattr(service, "apply_forecast_recommendation_review", observe)

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        _review(factory, ids, created.id, "converted")
    finally:
        event.remove(engine, "before_cursor_execute", record)
    updates = [
        statement
        for statement in statements
        if statement.lstrip().upper().startswith("UPDATE FORECAST_RECOMMENDATIONS")
    ]
    assert len(updates) == 1, statements


def test_real_review_refuses_an_out_of_scope_recommendation_without_writes(case):
    _, factory, ids = case
    created = _create(factory, ids)
    with factory() as db:
        before = (db.query(ForecastRecommendation).count(), db.query(AuditLog).count())

    with pytest.raises(HTTPException) as failure:
        _review(factory, ids, created.id, "accepted", factory_codes=("BST",))

    assert failure.value.status_code == 404
    with factory() as db:
        after = (db.query(ForecastRecommendation).count(), db.query(AuditLog).count())
        assert db.get(ForecastRecommendation, created.id).status == "open"
    assert after == before


def test_real_review_of_a_legacy_stored_status_is_allowed(case):
    _, factory, ids = case
    with factory() as db:
        db.add(
            ForecastRecommendation(
                recommendation_type="old_custom_type",
                status=" OLD_STATUS ",
                model_id=ids["model"],
                suggested_quantity=1,
            )
        )
        db.commit()
        row_id = db.query(ForecastRecommendation).one().id

    result = _review(factory, ids, row_id, "accepted")

    assert result.status is ForecastRecommendationStatus.ACCEPTED
    assert result.recommendation_type == "old_custom_type"
    with factory() as db:
        stored = db.get(ForecastRecommendation, row_id)
        assert stored.status == "accepted"
        audit = (
            db.query(AuditLog)
            .filter(AuditLog.entity_type == "ForecastRecommendation", AuditLog.entity_id == row_id)
            .one()
        )
        assert audit.old_value_json == {"status": " OLD_STATUS "}
        assert audit.new_value_json == {"status": "accepted"}


@pytest.mark.parametrize("point", ["update", "audit_insert", "commit"])
def test_real_review_failure_rolls_back_and_retry_succeeds(case, point):
    engine, factory, ids = case
    created = _create(factory, ids)
    with factory() as db:
        row = db.get(ForecastRecommendation, created.id)
        before = (row.status, row.reviewed_by, row.reviewed_at, row.updated_at)
        audit_before = db.query(AuditLog).filter_by(entity_type="ForecastRecommendation", entity_id=created.id).count()

    def fail(*args, **kwargs):
        raise RuntimeError("injected review failure")

    def fail_sql(conn, cursor, statement, parameters, context, executemany):
        normalized = statement.lstrip().upper()
        if (point == "update" and normalized.startswith("UPDATE FORECAST_RECOMMENDATIONS")) or (
            point == "audit_insert" and normalized.startswith("INSERT INTO AUDIT_LOGS")
        ):
            fail()

    with factory() as db:
        actor = db.get(User, ids["user"])
        if point == "commit":
            event.listen(db, "before_commit", fail)
        else:
            event.listen(engine, "before_cursor_execute", fail_sql)
        try:
            with pytest.raises(RuntimeError, match="injected review failure"):
                service.update_recommendation(db, created.id, ForecastRecommendationPatch(status="accepted"), ["MIL"], actor)
            db.rollback()
        finally:
            if point != "commit":
                event.remove(engine, "before_cursor_execute", fail_sql)
    with factory() as db:
        row = db.get(ForecastRecommendation, created.id)
        assert (row.status, row.reviewed_by, row.reviewed_at, row.updated_at) == before
        assert db.query(AuditLog).filter_by(entity_type="ForecastRecommendation", entity_id=created.id).count() == audit_before
    assert _review(factory, ids, created.id, "accepted").status is ForecastRecommendationStatus.ACCEPTED
    with factory() as db:
        assert db.get(ForecastRecommendation, created.id).status == "accepted"
        assert db.query(AuditLog).filter_by(entity_type="ForecastRecommendation", entity_id=created.id).count() == audit_before + 1


def test_concurrent_reviews_preserve_existing_last_writer_behavior(case, monkeypatch):
    _, factory, ids = case
    created = _create(factory, ids)
    barrier = Barrier(2, timeout=10)
    original = service.apply_forecast_recommendation_review

    def synchronize(db, command, row):
        barrier.wait()
        return original(db, command, row)

    monkeypatch.setattr(service, "apply_forecast_recommendation_review", synchronize)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_review, factory, ids, created.id, value) for value in ("accepted", "dismissed")]
        results = [future.result(timeout=30) for future in futures]
    # A post-commit refresh can observe the other concurrent writer.
    assert all(result.status.value in {"accepted", "dismissed"} for result in results)
    with factory() as db:
        row = db.get(ForecastRecommendation, created.id)
        logs = db.query(AuditLog).filter_by(entity_type="ForecastRecommendation", entity_id=created.id).order_by(AuditLog.id).all()
        reviews = [entry for entry in logs if entry.action != "create_forecast_recommendation"]
        assert len(reviews) == 2
        assert {entry.new_value_json["status"] for entry in reviews} == {"accepted", "dismissed"}
        assert [entry.old_value_json["status"] for entry in reviews] == ["open", "open"]
        assert row.status == reviews[-1].new_value_json["status"]
