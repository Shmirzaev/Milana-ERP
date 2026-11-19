"""Real PostgreSQL selector parity for the numeric necessary-condition guard."""
import itertools

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import String, column, select, values

from app.api.routes import catalog
from app.core.deps import get_current_user, get_db
from app.core.model_search import (
    normalized_model_code_column, normalized_model_code_match, normalized_model_code_pattern,
)
from app.models.catalog import models_service
from app.schemas import Model, ModelImage, Role, User
from app.tests.test_modelcolor_create_postgres import pg_sessions  # noqa: F401


@pytest.fixture(scope="module")
def selector_catalog(pg_sessions):
    with pg_sessions.begin() as db:
        actor = User(name="Numeric selector QA", email="numeric-selector@example.invalid",
                     password_hash="unused", factory_code="MIL",
                     role=Role(name="Numeric selector QA", permissions=["*"]))
        db.add(actor)
        db.flush()
        codes = ["KJ13065-V-6979", "КJ13-065-V-6979", "PJ99101-009913",
                 "PJ99102-V-009913", "00123", "1-2-3", "--1--2---3--",
                 "ABC123456XYZ", "123%456", "123_456", "123\\456",
                 "１２３", "١٢٣", "", "ZZZ"]
        rows = []
        for n, code in enumerate(codes):
            row = Model(code=code, name="Name-only 123456" if code == "ZZZ" else "Selector fixture",
                        status="approved" if n % 2 else "draft", catalog_scope="standard",
                        details_json={"general": {"model_no": code, "variant_no": ""}})
            db.add(row)
            rows.append(row)
        legacy = Model(code="LEGACY123", name="Legacy selector", catalog_scope="standard",
                       details_json={"legacy_import": True})
        eco = Model(code="ECO123", name="Eco selector", catalog_scope="usluga", factory_code="ECO")
        db.add_all([legacy, eco])
        db.flush()
        db.add(ModelImage(model_id=rows[0].id, file_url="/storage/model-files/numeric-qa.png",
                          image_type="model", is_primary=True))
        result = {"actor_id": actor.id, "first_id": rows[0].id, "legacy_id": legacy.id,
                  "eco_id": eco.id, "name_only_id": rows[-1].id}
    return pg_sessions, result


def old_match(column, pattern, *, dialect_name):
    return normalized_model_code_column(column).ilike(pattern)


def service_pair(selector_catalog, monkeypatch, **kwargs):
    sessions, fixture = selector_catalog
    actual = models_service.normalized_model_code_match
    with sessions() as db:
        actor = db.get(User, fixture["actor_id"])
        current = models_service.list_model_options(actor, db, **kwargs)
        with monkeypatch.context() as patch:
            patch.setattr(models_service, "normalized_model_code_match", old_match)
            previous = models_service.list_model_options(actor, db, **kwargs)
    assert current == previous
    assert actual is normalized_model_code_match
    return current


@pytest.mark.parametrize("term", [
    "KJ13065-V-6979", "V-009913", "V=009913", "1-2-3", "001", "123", "999999",
    "%123", "12_345", "123%456", r"123\%456", r"123\_456", r"123\\456", "１２３", "١٢٣", "kj",
])
def test_pg_selector_actual_http_order_paging_body_headers(selector_catalog, monkeypatch, term):
    sessions, fixture = selector_catalog
    app = FastAPI()
    app.include_router(catalog.router, prefix="/api")

    def database():
        with sessions() as db:
            yield db

    def actor():
        with sessions() as db:
            row = db.get(User, fixture["actor_id"])
            _ = row.role.permissions
            return row

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_user] = actor
    with TestClient(app) as client:
        for page in (1, 2, 99):
            query = {"search": term, "page": page, "page_size": 2}
            current = client.get("/api/model-options", params=query)
            with monkeypatch.context() as patch:
                patch.setattr(models_service, "normalized_model_code_match", old_match)
                previous = client.get("/api/model-options", params=query)
            assert current.status_code == previous.status_code == 200
            assert current.content == previous.content
            assert current.headers == previous.headers


@pytest.mark.parametrize("scope,status", [
    ("standard", None), ("standard", "approved"), ("standard", "draft"), ("usluga", None),
])
def test_pg_selector_scope_status_names_and_legacy(selector_catalog, monkeypatch, scope, status):
    result = service_pair(selector_catalog, monkeypatch, search="123", catalog_scope=scope,
                          status=status, page_size=50)
    ids = {item["id"] for item in result["items"]}
    _, fixture = selector_catalog
    assert fixture["legacy_id"] not in ids
    if scope == "standard" and status is None:
        assert fixture["name_only_id"] in ids
        assert fixture["eco_id"] not in ids
    if scope == "usluga":
        assert ids == {fixture["eco_id"]}


def test_pg_selector_ids_lookup_keeps_bypass_and_thumbnail(selector_catalog, monkeypatch):
    _, fixture = selector_catalog
    selected = [fixture["first_id"], fixture["legacy_id"]]
    result = service_pair(selector_catalog, monkeypatch, ids=selected, search="does-not-match123",
                          status="does-not-match", page_size=50)
    assert {item["id"] for item in result["items"]} == set(selected)
    first = next(item for item in result["items"] if item["id"] == fixture["first_id"])
    assert first["thumbnail_url"] == "/storage/model-files/numeric-qa.png"


def test_pg_adversarial_values_preserve_null_and_wildcard_truth(selector_catalog):
    sessions, _ = selector_catalog
    codes = [None, "", "123", "1-2-3", "--1--2---3--", "КJ13-065-V-6979",
             "123%456", "123_456", "123\\456", "00123", "１２３", "١٢٣", "x\n123z"]
    codes += ["".join(parts) for parts in itertools.product("123-%_\\Кé ", repeat=3)]
    samples = values(column("code", String), name="samples").data([(x,) for x in codes])
    col = samples.c.code
    patterns = ["123", "001", "13065-V-6979", "1-2-3", "123%456", "12_345",
                r"123\%456", r"123\_456", r"123\\456", "１２３", "١٢٣", "%", "_", ""]
    with sessions() as db:
        for term in patterns:
            pattern = normalized_model_code_pattern(term)
            old = normalized_model_code_column(col).ilike(pattern)
            new = normalized_model_code_match(col, pattern, dialect_name="postgresql")
            before = list(db.execute(select(col).select_from(samples).where(old)).scalars())
            after = list(db.execute(select(col).select_from(samples).where(new)).scalars())
            assert before == after, term


def test_pg_compiled_cache_binds_new_digits_on_repeated_queries(selector_catalog):
    sessions, _ = selector_catalog
    with sessions() as db:
        def ids(pattern):
            return db.query(Model.id).filter(normalized_model_code_match(
                Model.code, pattern, dialect_name="postgresql",
            )).order_by(Model.id).all()
        first, second, again = ids("%13065%"), ids("%009913%"), ids("%13065%")
        assert first and second and first != second
        assert again == first
