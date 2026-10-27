"""Real PostgreSQL behaviour of the forecast review write and the quantity floor.

Only an explicitly owned disposable review database on the identity-pinned
review instance may be used. The instance pins are re-verified inside the
fixture, so the module cannot silently run against another server.
"""
import hashlib
import json
import os
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.libs.dto.planning.forecast_recommendation_input import ForecastRecommendationIn
from app.libs.dto.planning.forecast_recommendation_update import ForecastRecommendationPatch
from app.libs.enums.planning import ForecastRecommendationStatus
from app.models.planning import forecasting_recommendations_service as service
from app.schemas import AuditLog, Brand, Collection, ForecastRecommendation, Item, Model, Role, User

EXPECTED_SYSTEM_IDENTIFIER = "7700371345869473300"
EXPECTED_DATA_DIRECTORY = "C:/Users/ismoi/Documents/Codex/2026-10-23/we-x20/work/finance-visual-qa-5aafe01d69/data"
EXPECTED_PORT = 51716


def _normalize(value: str) -> str:
    return value.replace("\\", "/").rstrip("/")


@pytest.fixture(scope="module")
def sessions():
    raw = os.environ.get("FORECAST_REVIEW_REVIEW_URL")
    if not raw:
        pytest.skip("Set FORECAST_REVIEW_REVIEW_URL to an owned disposable review database")
    url = make_url(raw)
    assert url.get_backend_name() == "postgresql"
    assert url.host in {"localhost", "127.0.0.1"}
    assert url.port == EXPECTED_PORT
    assert url.database.startswith("review_")

    import psycopg2

    admin = psycopg2.connect(
        f"postgresql://postgres:postgres@127.0.0.1:{EXPECTED_PORT}/postgres"
    )
    admin.autocommit = True
    cursor = admin.cursor()
    cursor.execute("select system_identifier::text from pg_control_system()")
    system_identifier = cursor.fetchone()[0]
    cursor.execute("select current_setting('data_directory')")
    data_directory = cursor.fetchone()[0]
    cursor.execute("select current_setting('server_version')")
    server_version = cursor.fetchone()[0]
    cursor.execute("select count(*) from pg_database where datname=%s", (url.database,))
    assert cursor.fetchone()[0] == 1, "the task-owned review database must exist"
    cursor.close()
    admin.close()

    assert system_identifier == EXPECTED_SYSTEM_IDENTIFIER, system_identifier
    assert _normalize(data_directory).lower() == EXPECTED_DATA_DIRECTORY.lower(), data_directory
    assert server_version.startswith("17.11"), server_version

    engine = create_engine(
        url,
        isolation_level="READ COMMITTED",
        connect_args={"options": "-c statement_timeout=15000 -c lock_timeout=8000"},
    )
    Base.metadata.create_all(engine)
    yield engine, sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    engine.dispose()


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

    assert result["status"] == "accepted"
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

    assert result["status"] == "accepted"
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


def test_real_quantity_at_the_storage_floor_stores_a_positive_value(case):
    _, factory, ids = case

    created = _create(factory, ids, suggested_quantity="0.00005")

    with factory() as db:
        stored = db.get(ForecastRecommendation, created.id)
        assert stored.suggested_quantity > 0
        assert stored.suggested_quantity == Decimal("0.0001")


def test_real_quantity_below_the_storage_floor_is_refused_before_any_write(case):
    _, factory, ids = case
    with factory() as db:
        before = (db.query(ForecastRecommendation).count(), db.query(AuditLog).count())

    with pytest.raises(Exception):
        ForecastRecommendationIn(recommendation_type="item_reorder", suggested_quantity="0.00001")

    with factory() as db:
        after = (db.query(ForecastRecommendation).count(), db.query(AuditLog).count())
    assert after == before
