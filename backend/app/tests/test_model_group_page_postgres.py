"""Grouped catalog totals execute once on PostgreSQL's successful-page path."""
import pytest
from sqlalchemy import event

from app.models.catalog import models_service
from app.schemas import Model, Role, User
from app.tests.test_modelcolor_create_postgres import pg_sessions  # noqa: F401


@pytest.fixture(scope="module")
def grouped_catalog(pg_sessions):
    with pg_sessions.begin() as db:
        actor = User(name="Group paging QA", email="group-page@example.invalid",
                     password_hash="unused", role=Role(name="Group paging QA", permissions=["*"]))
        db.add(actor)
        db.flush()
        for number, variants in [("XJ5614", ["01", "02"]), ("XJ5415", ["01"]), ("XJ999", [])]:
            for variant in ["", *variants]:
                db.add(Model(
                    code=number + ("-" + variant if variant else ""),
                    name="uniquevariant" if number == "XJ5614" and variant == "01" else "Group paging",
                    catalog_scope="standard",
                    status="approved" if variant == "01" else "draft",
                    details_json={"general": {"model_no": number, "variant_no": variant}},
                ))
        db.add(Model(code="XJ7777", name="Legacy", catalog_scope="standard",
                     details_json={"legacy_import": True, "general": {"model_no": "XJ7777"}}))
        db.add(Model(code="ECO200", name="Other scope", catalog_scope="usluga", factory_code="ECO",
                     details_json={"general": {"model_no": "ECO200"}}))
        actor_id = actor.id
    return pg_sessions, actor_id


def read_groups(grouped_catalog, **kwargs):
    sessions, actor_id = grouped_catalog
    engine = sessions.kw["bind"]
    statements = []

    def record(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(" ".join(statement.lower().split()))

    with sessions() as db:
        actor = db.get(User, actor_id)
        event.listen(engine, "before_cursor_execute", record)
        try:
            result = models_service.list_model_variant_groups(actor, db, **kwargs)
        finally:
            event.remove(engine, "before_cursor_execute", record)
    grouped = [sql for sql in statements if "group by models.model_group_key" in sql]
    return result, grouped


@pytest.mark.parametrize("compact", [False, True])
def test_pg_group_page_total_counts_families_once_and_keeps_prefix_order(grouped_catalog, compact):
    first, queries = read_groups(grouped_catalog, q="XJ", compact=compact,
                                 include_total=True, page=1, page_size=1)
    assert first["total"] == 3
    assert [row["group_model_no"] for row in first["rows"]] == ["XJ5614"]
    assert first["rows"][0]["variant_count"] == 2
    assert len(queries) == 1 and "count(*) over ()" in queries[0]
    second, queries = read_groups(grouped_catalog, q="XJ", compact=compact,
                                  include_total=True, page=2, page_size=1)
    assert second["total"] == 3
    assert [row["group_model_no"] for row in second["rows"]] == ["XJ5415"]
    assert len(queries) == 1


def test_pg_group_page_empty_first_uses_window_only(grouped_catalog):
    result, queries = read_groups(grouped_catalog, q="NO_MATCH_QA_20261119",
                                  compact=True, include_total=True)
    assert result["rows"] == [] and result["total"] == 0
    assert len(queries) == 1 and "count(*) over ()" in queries[0]


def test_pg_group_page_empty_later_preserves_exact_count_fallback(grouped_catalog):
    result, queries = read_groups(grouped_catalog, q="XJ", compact=True,
                                  include_total=True, page=9999, page_size=1)
    assert result["rows"] == [] and result["total"] == 3
    assert len(queries) == 2
    assert sum("count(*) over ()" in sql for sql in queries) == 1


def test_pg_group_page_without_total_keeps_count_disabled(grouped_catalog):
    rows, queries = read_groups(grouped_catalog, q="XJ", compact=True,
                                include_total=False, page_size=1)
    assert [row["group_model_no"] for row in rows] == ["XJ5614"]
    assert len(queries) == 1 and "count(" not in queries[0]


def test_pg_group_page_filtered_variant_still_expands_whole_family(grouped_catalog):
    result, queries = read_groups(grouped_catalog, q="uniquevariant", compact=True, include_total=True)
    assert result["total"] == 1
    family = result["rows"][0]
    assert family["group_model_no"] == "XJ5614"
    assert {row["variant_no"] for row in family["variants"]} == {"01", "02"}
    assert len(queries) == 1


def test_pg_group_page_scope_legacy_status_and_clamps(grouped_catalog):
    standard, queries = read_groups(grouped_catalog, compact=True, include_total=True,
                                    page=-7, page_size=500)
    assert standard["total"] == 3 and len(standard["rows"]) == 3
    assert standard["page"] == 1 and standard["page_size"] == 100
    assert len(queries) == 1
    legacy, _ = read_groups(grouped_catalog, compact=True, include_total=True, include_legacy_import=True)
    assert legacy["total"] == 4
    approved, _ = read_groups(grouped_catalog, q="XJ", status="approved", compact=True, include_total=True)
    assert approved["total"] == 2
    eco, _ = read_groups(grouped_catalog, catalog_scope="usluga", compact=True, include_total=True)
    assert eco["total"] == 1 and eco["rows"][0]["group_model_no"] == "ECO200"


def test_pg_group_page_sqlite_path_still_reports_group_totals(client, auth_headers):
    from app.db import session as session_module

    with session_module.SessionLocal.begin() as db:
        for code in ["SQLITE_WINDOW_QA", "SQLITE_WINDOW_QA-01"]:
            db.add(Model(code=code, name="SQLite paging QA",
                         details_json={"general": {"model_no": "SQLITE_WINDOW_QA"}}))
    response = client.get("/api/models/variant-groups",
                          params={"q": "SQLITE_WINDOW_QA", "include_total": True, "page_size": 1},
                          headers=auth_headers)
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 1
