from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from threading import Event
import json
import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, literal_column, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.api.routes import catalog
from app.models import Model


def _copy_code(source_code: str, index: int) -> str:
    suffix = "-COPY" if index == 1 else f"-COPY-{index}"
    return f"{source_code[: max(1, 64 - len(suffix))]}{suffix}"


@pytest.fixture(scope="module")
def catalog_postgres_engine():
    raw_url = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw_url:
        pytest.skip("Set STABILIZATION_POSTGRES_URL through the disposable PostgreSQL launcher")
    url = make_url(raw_url)
    if url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"} or url.query:
        pytest.fail("Catalog plan tests require a loopback PostgreSQL URL without connection overrides")

    schema = f"catalog_family_{uuid4().hex}"
    engine = create_engine(
        url,
        connect_args={"options": f"-csearch_path={schema} -clock_timeout=15000 -cstatement_timeout=20000"},
        pool_size=4,
        max_overflow=0,
        isolation_level="READ COMMITTED",
    )
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        connection.exec_driver_sql(
            """
            CREATE TABLE models (
                id serial PRIMARY KEY,
                created_at timestamptz NOT NULL DEFAULT now(),
                updated_at timestamptz NOT NULL DEFAULT now(),
                code varchar(64) NOT NULL UNIQUE,
                name varchar(255) NOT NULL,
                catalog_scope varchar(16) NOT NULL DEFAULT 'standard',
                factory_code varchar(3),
                category varchar(64),
                description text,
                brand_id integer,
                collection_id integer,
                product_type varchar(64),
                season varchar(64),
                constructor_employee_id integer,
                designer_employee_id integer,
                details_json jsonb,
                status varchar(32) NOT NULL DEFAULT 'draft',
                created_by integer,
                approved_by integer,
                approved_at timestamptz,
                sam_minutes numeric(8, 2) NOT NULL DEFAULT 0,
                selling_price numeric(14, 4),
                selling_price_currency varchar(3),
                selling_price_source varchar(32),
                selling_price_request_id integer,
                selling_price_updated_at timestamptz,
                is_legacy_import boolean GENERATED ALWAYS AS
                    ((coalesce(details_json ->> 'legacy_import', 'false')) = 'true') STORED,
                model_group_key text GENERATED ALWAYS AS (
                    'model:' || lower(btrim(coalesce(
                        nullif(btrim(details_json -> 'general' ->> 'model_no'), ''),
                        nullif(btrim(details_json -> 'general' ->> 'modelNo'), ''),
                        btrim(code)
                    )))
                ) STORED
            )
            """
        )
        connection.exec_driver_sql(
            "CREATE INDEX ix_models_model_group_key_id "
            "ON models (is_legacy_import, model_group_key, id DESC)"
        )
        connection.exec_driver_sql(
            "INSERT INTO models (code, name, details_json) "
            "SELECT 'UNRELATED-' || value, 'Unrelated model', "
            "jsonb_build_object('general', jsonb_build_object('model_no', 'UNRELATED-' || value)) "
            "FROM generate_series(1, 50000) AS value"
        )
        connection.exec_driver_sql("ANALYZE models")
    try:
        yield engine
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()


def _plan_text(db, statement) -> str:
    compiled = statement.compile(bind=db.get_bind(), compile_kwargs={"literal_binds": True})
    plan = db.execute(text(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {compiled}")).scalar_one()
    return json.dumps(plan, sort_keys=True)


def test_postgres_clone_candidates_use_code_index_and_bounded_projection(catalog_postgres_engine):
    sessions = sessionmaker(bind=catalog_postgres_engine, autoflush=False, expire_on_commit=False)
    marker = uuid4().hex
    source_code = f"PG-CLONE-{marker}-{'X' * 40}"[:64]
    with sessions() as db:
        db.add_all(
            [Model(code=source_code, name="PostgreSQL clone source")]
            + [
                Model(code=_copy_code(source_code, index), name="Existing PostgreSQL clone")
                for index in range(1, 402)
            ]
        )
        db.commit()
        candidates = [_copy_code(source_code, index) for index in range(1, 401)]
        plan_text = _plan_text(db, select(Model.code).where(Model.code.in_(candidates)))
        statements: list[str] = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            normalized = " ".join(statement.lower().split())
            if normalized.startswith("select") and "models.code" in normalized:
                statements.append(normalized)

        event.listen(catalog_postgres_engine, "before_cursor_execute", capture)
        try:
            candidate = catalog._unique_model_copy_code(db, source_code)
        finally:
            event.remove(catalog_postgres_engine, "before_cursor_execute", capture)

    assert candidate == _copy_code(source_code, 402)
    assert len(statements) == 2
    assert "models_code_key" in plan_text
    assert "Seq Scan" not in plan_text


@pytest.mark.parametrize("family_size", [1, 50, 401])
def test_postgres_approval_family_uses_generated_key_index(catalog_postgres_engine, family_size):
    sessions = sessionmaker(bind=catalog_postgres_engine, autoflush=False, expire_on_commit=False)
    marker = uuid4().hex[:8]
    model_no = f"PG-FAMILY-{marker}"
    with sessions() as db:
        family = [
            Model(
                code=model_no if index == 0 else f"{model_no}-V-{index}",
                name="PostgreSQL approval family",
                details_json={
                    "general": {
                        "model_no": model_no,
                        **({} if index == 0 else {"variant_no": f"V-{index}"}),
                    }
                },
            )
            for index in range(family_size)
        ]
        db.add_all(family)
        db.commit()
        source_id = int(family[0].id)
        db.expunge_all()
        source = db.get(Model, source_id)
        group_key = catalog._model_group_key(source)
        family_statement = (
            select(Model)
            .where(
                Model.catalog_scope == "standard",
                literal_column("models.is_legacy_import").is_(False),
                literal_column("models.model_group_key") == group_key,
            )
            .order_by(Model.id)
        )
        plan_text = _plan_text(db, family_statement)
        model_selects: list[str] = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            normalized = " ".join(statement.lower().split())
            if normalized.startswith("select") and " from models " in f" {normalized} ":
                model_selects.append(normalized)

        event.listen(catalog_postgres_engine, "before_cursor_execute", capture)
        try:
            rows = catalog._approval_family(db, source)
        finally:
            event.remove(catalog_postgres_engine, "before_cursor_execute", capture)

    assert len(rows) == family_size
    assert len(model_selects) == 1
    assert "ix_models_model_group_key_id" in plan_text
    assert "Seq Scan" not in plan_text


def test_postgres_concurrent_clone_numbering_serializes_same_namespace(catalog_postgres_engine):
    sessions = sessionmaker(bind=catalog_postgres_engine, autoflush=False, expire_on_commit=False)
    source_code = f"PG-CONCURRENT-{uuid4().hex}-{'Z' * 32}"[:64]
    first_has_code = Event()
    release_first = Event()

    def allocate_first() -> str:
        with sessions() as db:
            code = catalog._unique_model_copy_code(db, source_code)
            db.add(Model(code=code, name="First concurrent clone"))
            db.flush()
            first_has_code.set()
            assert release_first.wait(10)
            db.commit()
            return code

    def allocate_second() -> str:
        with sessions() as db:
            code = catalog._unique_model_copy_code(db, source_code)
            db.add(Model(code=code, name="Second concurrent clone"))
            db.commit()
            return code

    with ThreadPoolExecutor(max_workers=2) as workers:
        first = workers.submit(allocate_first)
        assert first_has_code.wait(10)
        second = workers.submit(allocate_second)
        with pytest.raises(FutureTimeout):
            second.result(timeout=0.2)
        release_first.set()
        codes = [first.result(timeout=10), second.result(timeout=10)]

    assert codes == [_copy_code(source_code, 1), _copy_code(source_code, 2)]


def test_postgres_clone_numbering_lock_releases_on_rollback(catalog_postgres_engine):
    sessions = sessionmaker(bind=catalog_postgres_engine, autoflush=False, expire_on_commit=False)
    source_code = f"PG-ROLLBACK-{uuid4().hex}-{'R' * 32}"[:64]
    with sessions() as db:
        candidate = catalog._unique_model_copy_code(db, source_code)
        db.add(Model(code=candidate, name="Rolled back clone"))
        db.flush()
        db.rollback()

    with sessions() as db:
        reused = catalog._unique_model_copy_code(db, source_code)
        db.rollback()

    assert candidate == reused == _copy_code(source_code, 1)
