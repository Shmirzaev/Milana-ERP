from uuid import uuid4
from time import perf_counter
import tracemalloc

import pytest
from sqlalchemy import event
from sqlalchemy.dialects import postgresql


def _capture_selects(client, request):
    from app.db import session as session_module

    statements: list[str] = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(" ".join(statement.split()))

    event.listen(session_module.engine, "before_cursor_execute", capture)
    try:
        response = request()
    finally:
        event.remove(session_module.engine, "before_cursor_execute", capture)
    return response, statements


def _seed_models(*, approved: int, draft: int = 0) -> str:
    from app.db import session as session_module
    from app.models import Model

    prefix = f"BOUND-{uuid4().hex[:10].upper()}"
    db = session_module.SessionLocal()
    try:
        rows = []
        for index in range(approved + draft):
            status = "approved" if index < approved else "draft"
            code = f"{prefix}-{index:04d}"
            rows.append(
                Model(
                    code=code,
                    name=f"{prefix} model {index:04d}",
                    status=status,
                    details_json={"general": {"model_no": code}},
                    created_by=1,
                )
            )
        db.add_all(rows)
        db.commit()
    finally:
        db.close()
    return prefix


@pytest.fixture
def seed_models(request):
    prefixes: list[str] = []

    def seed(*, approved: int, draft: int = 0) -> str:
        prefix = _seed_models(approved=approved, draft=draft)
        prefixes.append(prefix)
        return prefix

    def cleanup() -> None:
        from app.db import session as session_module
        from app.models import Model

        db = session_module.SessionLocal()
        try:
            for prefix in prefixes:
                db.query(Model).filter(Model.code.like(f"{prefix}%")).delete(synchronize_session=False)
            db.commit()
        finally:
            db.close()

    request.addfinalizer(cleanup)
    return seed


def test_models_default_and_filtered_requests_are_always_bounded(client, auth_headers, seed_models):
    prefix = seed_models(approved=135, draft=7)

    default, statements = _capture_selects(
        client,
        lambda: client.get("/api/models", headers=auth_headers),
    )
    assert default.status_code == 200, default.text
    assert len(default.json()) <= 50
    assert default.headers["x-page"] == "1"
    assert default.headers["x-page-size"] == "50"
    assert default.headers["x-has-more"] in {"true", "false"}
    model_statements = [statement for statement in statements if " FROM models " in f" {statement} "]
    assert len(model_statements) == 1
    assert "model_bom" not in model_statements[0].lower()

    filtered = client.get(
        "/api/models",
        params={"status": "approved", "q": prefix, "include_total": "false"},
        headers=auth_headers,
    )
    assert filtered.status_code == 200, filtered.text
    assert len(filtered.json()) == 50

    allowed_keys = {
        "id", "code", "name", "category", "brand_id", "status",
        "thumbnail_url", "selling_price", "selling_price_currency", "created_at", "updated_at",
    }
    assert set(filtered.json()[0]) == allowed_keys
    assert not ({"images", "bom", "sizes", "colors", "details_json"} & set(filtered.json()[0]))


def test_models_count_uses_the_same_filters_without_disabling_pagination(client, auth_headers, seed_models):
    prefix = seed_models(approved=1105, draft=9)
    response, statements = _capture_selects(
        client,
        lambda: client.get(
            "/api/models",
            params={
                "status": "approved",
                "q": prefix,
                "include_total": "true",
                "page": 12,
                "page_size": 100,
            },
            headers=auth_headers,
        ),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 1105
    assert len(body["rows"]) == 5
    assert body["page"] == 12
    assert body["page_size"] == 100
    assert body["has_more"] is False
    model_statements = [statement for statement in statements if " FROM models " in f" {statement} "]
    assert len(model_statements) == 2
    assert all("models.status" in statement and "lower" in statement.lower() for statement in model_statements)

    first_page = client.get(
        "/api/models",
        params={"q": prefix, "page_size": 100, "include_total": "false"},
        headers=auth_headers,
    )
    assert first_page.status_code == 200
    assert len(first_page.json()) == 100

    oversized = client.get("/api/models?page_size=500", headers=auth_headers)
    assert oversized.status_code == 422


def test_model_options_are_compact_searchable_and_support_selected_ids(client, auth_headers, seed_models):
    prefix = seed_models(approved=64, draft=3)
    page, statements = _capture_selects(
        client,
        lambda: client.get(
            "/api/model-options",
            params={"status": "approved", "search": prefix, "page": 1, "page_size": 30},
            headers=auth_headers,
        ),
    )
    assert page.status_code == 200, page.text
    body = page.json()
    assert len(body["items"]) == 30
    assert body["has_more"] is True
    assert set(body["items"][0]) == {
        "id", "code", "name", "thumbnail_url", "selling_price", "selling_price_currency",
    }
    model_statements = [statement for statement in statements if " FROM models " in f" {statement} "]
    assert len(model_statements) == 1
    assert "model_bom" not in model_statements[0].lower()

    selected_id = body["items"][0]["id"]
    selected = client.get(
        "/api/model-options",
        params=[("ids", selected_id), ("ids", 999_999_999), ("page_size", 2)],
        headers=auth_headers,
    )
    assert selected.status_code == 200, selected.text
    assert [row["id"] for row in selected.json()["items"]] == [selected_id]

    assert client.get("/api/model-options?page_size=51", headers=auth_headers).status_code == 422
    assert client.get("/api/model-options?search=x&page_size=50", headers=auth_headers).status_code == 200
    too_long = client.get(f"/api/model-options?search={'x' * 101}", headers=auth_headers)
    assert too_long.status_code == 422


def test_variants_use_a_targeted_bounded_database_query(client, auth_headers):
    suffix = uuid4().hex[:10].upper()
    family = f"TARGET-{suffix}"
    other_family = f"OTHER-{suffix}"
    family_ids = []

    for model_no, variant_no in ((family, "V-1"), (family, "V-2"), (other_family, "V-9")):
        created = client.post(
            "/api/models",
            json={
                "code": f"{model_no}-{variant_no}",
                "name": f"{model_no} name",
                "status": "approved",
                "details_json": {"general": {"model_no": model_no, "variant_no": variant_no}},
            },
            headers=auth_headers,
        )
        assert created.status_code == 201, created.text
        if model_no == family:
            family_ids.append(created.json()["id"])

    variants, statements = _capture_selects(
        client,
        lambda: client.get(
            f"/api/models/{family_ids[0]}/variants?page=1&page_size=1",
            headers=auth_headers,
        ),
    )
    assert variants.status_code == 200, variants.text
    assert len(variants.json()) == 1
    assert variants.json()[0]["model_id"] in family_ids
    assert variants.headers["x-has-more"] == "true"

    model_select = next(
        statement
        for statement in statements
        if " FROM models " in f" {statement} "
        and ("JSON_EXTRACT" in statement.upper() or "model_group_key" in statement)
    )
    normalized = model_select.lower()
    assert " where " in f" {normalized} "
    assert "json_extract" in normalized or "model_group_key" in normalized
    assert " limit " in f" {normalized} "
    assert all(row["model_id"] in family_ids for row in variants.json())
    relation_selects = [
        statement for statement in statements
        if "model_images" in statement.lower() or "model_bom" in statement.lower()
    ]
    assert len(relation_selects) == 2

    assert client.get(
        f"/api/models/{family_ids[0]}/variants?page_size=101",
        headers=auth_headers,
    ).status_code == 422
    assert client.get("/api/models/999999999/variants", headers=auth_headers).status_code == 404


def test_postgresql_variant_predicate_uses_the_generated_family_index_columns():
    from app.api.routes.catalog import _variant_group_predicate

    class PostgreSQLBind:
        class dialect:
            name = "postgresql"

    class PostgreSQLSession:
        @staticmethod
        def get_bind():
            return PostgreSQLBind()

    predicate = _variant_group_predicate(
        PostgreSQLSession(),
        group_key="model:example",
        model_no="EXAMPLE",
    )
    sql = str(predicate.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "models.is_legacy_import IS false" in sql
    assert "models.model_group_key = 'model:example'" in sql


def test_large_model_fixture_has_bounded_payload_and_memory(client, auth_headers, capsys, seed_models):
    prefix = seed_models(approved=6606)
    params = {"status": "approved", "q": prefix, "page": 1, "page_size": 100}
    warmup = client.get("/api/models", params=params, headers=auth_headers)
    assert warmup.status_code == 200
    assert len(warmup.json()) == 100

    tracemalloc.start()
    started = perf_counter()
    responses = [client.get("/api/models", params=params, headers=auth_headers) for _ in range(10)]
    elapsed = perf_counter() - started
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert all(response.status_code == 200 for response in responses)
    assert all(len(response.json()) == 100 for response in responses)
    payload_bytes = len(responses[-1].content)
    with capsys.disabled():
        print(
            "\nmodel-list benchmark: "
            f"6606 matching rows, 10 requests, {elapsed * 1000 / 10:.1f} ms/request, "
            f"{payload_bytes} bytes/response, {peak / 1024 / 1024:.2f} MiB traced peak"
        )
