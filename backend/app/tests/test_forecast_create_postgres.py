"""Real create atomicity/constraints; only an explicitly owned disposable DB."""
import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from decimal import Decimal
from threading import Barrier

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError, DataError
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.libs.dto.planning.forecast_recommendation_input import ForecastRecommendationIn
from app.libs.enums.planning import ForecastRecommendationStatus, ForecastRecommendationType
from app.models.planning import forecasting_recommendations_service as service
from app.schemas import AuditLog, Brand, Collection, ForecastRecommendation, Item, Model, Role, User


@pytest.fixture(scope="module")
def sessions():
    raw = os.environ.get("FORECAST_CREATE_REVIEW_URL")
    if not raw:
        pytest.skip("Set FORECAST_CREATE_REVIEW_URL to an owned disposable review_forecast_ database")
    url = make_url(raw)
    assert url.get_backend_name() == "postgresql"
    assert url.host in {"localhost", "127.0.0.1"} and url.database.startswith("review_forecast_")
    engine = create_engine(url, isolation_level="READ COMMITTED", connect_args={"options": "-c statement_timeout=15000 -c lock_timeout=8000"})
    Base.metadata.create_all(engine)
    yield engine, sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def case(sessions):
    engine, factory = sessions
    with engine.begin() as connection:
        connection.exec_driver_sql("TRUNCATE forecast_recommendations, audit_logs, models, items, brands, collections, users, roles RESTART IDENTITY CASCADE")
    with factory.begin() as db:
        role = Role(name="Forecast reviewer", permissions=["forecasting.view", "forecasting.manage"])
        db.add(role); db.flush()
        user = User(name="Forecast reviewer", email="forecast-test@example.invalid", password_hash="unused", role_id=role.id, factory_code="MIL", is_active=True)
        model = Model(code="FORECAST-MIL", name="Scoped model", status="approved", factory_code="MIL")
        other = Model(code="FORECAST-BST", name="Other model", status="approved", factory_code="BST")
        brand = Brand(name="Forecast brand")
        item = Item(sku="FORECAST-FAB", name="Material", category="fabric", unit="kg")
        db.add_all([user, model, other, brand, item]); db.flush()
        collection = Collection(name="Forecast collection", brand_id=brand.id)
        db.add(collection); db.flush()
        ids = {"user": user.id, "model": model.id, "other": other.id, "brand": brand.id, "item": item.id, "collection": collection.id}
    return engine, factory, ids


def payload(ids, **changes):
    fields = dict(recommendation_type="item_reorder", model_id=ids["model"], item_id=ids["item"], brand_id=ids["brand"], collection_id=ids["collection"], suggested_quantity="12.34567", unit="kg", confidence="manual-other", source_json={"free": [1, {"nested": True}]})
    fields.update(changes)
    return ForecastRecommendationIn(**fields)


def counts(factory):
    with factory() as db:
        return db.query(ForecastRecommendation).count(), db.query(AuditLog).count()


def create(factory, ids, **changes):
    with factory() as db:
        return service.create_recommendation(db, payload(ids, **changes), ["MIL"], db.get(User, ids["user"]))


@pytest.mark.parametrize("kind", ["item_reorder", "branded_stock_production"])
def test_real_create_typed_result_rounding_and_duplicate_request_policy(case, kind):
    _, factory, ids = case
    first = create(factory, ids, recommendation_type=kind)
    second = create(factory, ids, recommendation_type=kind)
    assert first.id != second.id and counts(factory) == (2, 2)
    assert first.recommendation_type is ForecastRecommendationType(kind)
    assert first.status is ForecastRecommendationStatus.OPEN
    assert first.suggested_quantity == pytest.approx(12.3457)
    assert first.source_json == {"free": [1, {"nested": True}]}
    assert first.confidence == "manual-other" and first.reviewed_at is None
    with factory() as db:
        stored = db.get(ForecastRecommendation, first.id)
        assert stored.suggested_quantity == Decimal("12.3457")
        assert stored.created_by == ids["user"]
        listed = service.list_recommendations(db, ["MIL"], None)
        assert [row["id"] for row in listed] == [second.id, first.id]
        assert service.list_recommendations(db, ["BST"], None) == []


@pytest.mark.parametrize("field", ["model_id", "item_id", "brand_id", "collection_id"])
def test_dangling_references_refused_without_any_write(case, field):
    _, factory, ids = case
    with pytest.raises(HTTPException) as failure:
        create(factory, ids, **{field: 2147483647})
    assert failure.value.status_code == 400
    assert counts(factory) == (0, 0)


@pytest.mark.parametrize("model", [None, "other"])
def test_factory_refusal_before_insert(case, model):
    _, factory, ids = case
    with pytest.raises(HTTPException) as failure:
        create(factory, ids, model_id=ids[model] if model else None)
    assert failure.value.status_code == 403
    assert counts(factory) == (0, 0)


@pytest.mark.parametrize("point", ["insert_sql", "audit_call", "audit_sql", "commit", "typed_result"])
def test_fault_rolls_back_business_and_audit_then_allows_retry(case, monkeypatch, point):
    engine, factory, ids = case
    def fail(*args, **kwargs):
        raise RuntimeError("injected forecast failure")
    def sql_failure(conn, cursor, statement, parameters, context, executemany):
        target = "INSERT INTO forecast_recommendations" if point == "insert_sql" else "INSERT INTO audit_logs"
        if statement.startswith(target): fail()
    with monkeypatch.context() as scoped:
        if point in {"insert_sql", "audit_sql"}: event.listen(engine, "before_cursor_execute", sql_failure)
        if point == "audit_call": scoped.setattr(service, "log_action", fail)
        if point == "typed_result": scoped.setattr(service.ForecastRecommendationCreatedOut, "model_validate", fail)
        try:
            with factory() as db:
                if point == "commit": event.listen(db, "before_commit", fail)
                with pytest.raises(RuntimeError, match="injected forecast failure"):
                    service.create_recommendation(db, payload(ids), ["MIL"], db.get(User, ids["user"]))
                db.rollback()
        finally:
            if point in {"insert_sql", "audit_sql"}: event.remove(engine, "before_cursor_execute", sql_failure)
    assert counts(factory) == (0, 0)
    assert create(factory, ids).status is ForecastRecommendationStatus.OPEN
    assert counts(factory) == (1, 1)


def test_schema_helper_uses_same_session_never_commits(case, monkeypatch):
    _, factory, ids = case
    observed = []
    original = service.insert_forecast_recommendation
    def observe(db, command):
        assert isinstance(command.recommendation_type, ForecastRecommendationType)
        assert command.status is ForecastRecommendationStatus.OPEN
        commits = []
        def unexpected_commit(*args): commits.append(True)
        event.listen(db, "before_commit", unexpected_commit)
        try:
            row = original(db, command)
            assert row in db and row.id is not None
            assert not commits
            observed.append(db)
            return row
        finally: event.remove(db, "before_commit", unexpected_commit)
    monkeypatch.setattr(service, "insert_forecast_recommendation", observe)
    with factory() as db:
        service.create_recommendation(db, payload(ids), ["MIL"], db.get(User, ids["user"]))
        assert observed == [db]
    assert counts(factory) == (1, 1)


def test_real_postgres_fk_numeric_and_unchanged_open_storage(case):
    engine, factory, ids = case
    with factory() as db:
        db.add(ForecastRecommendation(recommendation_type="custom-old", status="OLD", model_id=2147483647, suggested_quantity=1))
        with pytest.raises(IntegrityError): db.flush()
        db.rollback()
        db.add(ForecastRecommendation(recommendation_type="custom-old", status="OLD", model_id=ids["model"], suggested_quantity=Decimal("10000000000")))
        with pytest.raises(DataError): db.flush()
        db.rollback()
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO forecast_recommendations (recommendation_type,status,model_id,suggested_quantity,source_json) VALUES ('custom-old',' OLD ',:model,1,'[1,2]')"), {"model": ids["model"]})
    with factory() as db:
        rows = service.list_recommendations(db, ["MIL"], " OLD ")
        assert len(rows) == 1 and rows[0]["recommendation_type"] == "custom-old" and rows[0]["source_json"] is None
        assert db.query(ForecastRecommendation).one().source_json == [1, 2]
        assert db.query(AuditLog).count() == 0


@pytest.mark.parametrize("workers", [2, 4])
def test_concurrent_creates_preserve_separate_rows_and_audit_chain(case, workers):
    _, factory, ids = case
    gate = Barrier(workers)
    def worker(index):
        with factory() as db:
            actor = db.get(User, ids["user"])
            gate.wait(timeout=10)
            return service.create_recommendation(db, payload(ids, reason=f"request-{index}"), ["MIL"], actor).id
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(worker, i) for i in range(workers)]
        results = [future.result(timeout=25) for future in futures]
    assert len(set(results)) == workers and counts(factory) == (workers, workers)
    with factory() as db:
        logs = db.query(AuditLog).order_by(AuditLog.id).all()
        previous = None
        for entry in logs:
            data = dict(prev_hash=previous, user_id=ids["user"], action="create_forecast_recommendation", entity_type="ForecastRecommendation", entity_id=entry.entity_id, old_value=None, new_value=entry.new_value_json)
            expected = hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
            assert entry.prev_hash == previous and entry.entry_hash == expected
            previous = expected
        assert {entry.entity_id for entry in logs} == set(results)


@pytest.mark.parametrize("mutation", ["omit_factory", "omit_audit", "truncate_quantity"])
def test_business_probes_reject_deliberately_broken_operation(case, monkeypatch, mutation):
    """Prove critical assertions fail against changed behavior, not just green code."""
    _, factory, ids = case
    def probe():
        if mutation == "omit_factory":
            try:
                create(factory, ids, model_id=ids["other"])
            except HTTPException as error:
                assert error.status_code == 403
                return
            raise AssertionError("factory refusal missing")
        before = counts(factory)
        row = create(factory, ids)
        assert row.suggested_quantity == pytest.approx(12.3457), "fraction lost"
        assert counts(factory) == (before[0] + 1, before[1] + 1), "audit missing"
    probe()
    if mutation == "omit_factory":
        monkeypatch.setattr(service, "require_recommendation_factory_access", lambda *args, **kwargs: None)
        expected = "factory refusal missing"
    elif mutation == "omit_audit":
        monkeypatch.setattr(service, "log_action", lambda *args, **kwargs: None)
        expected = "audit missing"
    else:
        original = service.insert_forecast_recommendation
        monkeypatch.setattr(service, "insert_forecast_recommendation", lambda db, command: original(db, replace(command, suggested_quantity=Decimal(int(command.suggested_quantity)))))
        expected = "fraction lost"
    with pytest.raises(AssertionError, match=expected):
        probe()
