"""The super-data table directory must count tables in one DB round trip."""

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, event, insert
from sqlalchemy.orm import Session

from app.api.routes.super_data import _table_directory, _table_metadata_directory, _table_row_counts
from app.tests.test_task_assignment_authorization import _actor


def test_super_data_counts_preserve_table_names_and_counts_with_one_execute():
    metadata = MetaData()
    z_table = Table("z_table", metadata, Column("id", Integer, primary_key=True), Column("name", String))
    a_table = Table("a_table", metadata, Column("id", Integer, primary_key=True), Column("name", String))
    engine = create_engine("sqlite://")
    metadata.create_all(engine)
    with Session(engine) as db:
        db.execute(insert(a_table), [{"name": "one"}, {"name": "two"}])
        db.execute(insert(z_table), [{"name": "only"}])
        db.commit()

        execute_count = 0
        original_execute = db.execute

        def counted_execute(*args, **kwargs):
            nonlocal execute_count
            execute_count += 1
            return original_execute(*args, **kwargs)

        db.execute = counted_execute
        assert _table_row_counts(db, [a_table, z_table]) == {"a_table": 2, "z_table": 1}
        assert execute_count == 1


def _statement_trace(db, callback):
    statements: list[str] = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(" ".join(statement.lower().split()))

    event.listen(db.bind, "before_cursor_execute", capture)
    try:
        return callback(), statements
    finally:
        event.remove(db.bind, "before_cursor_execute", capture)


@pytest.mark.parametrize("table_count", [1, 50, 401])
def test_super_data_table_page_bounds_count_enrichment_and_matches_legacy_prefix(table_count):
    metadata = MetaData()
    tables = [
        Table(
            f"paged_table_{number:04d}",
            metadata,
            Column("id", Integer, primary_key=True),
            Column("name", String),
        )
        for number in range(table_count)
    ]
    engine = create_engine("sqlite://")
    metadata.create_all(engine)
    with Session(engine) as db:
        legacy, legacy_statements = _statement_trace(
            db,
            lambda: _table_directory(db, tables),
        )
        page, page_statements = _statement_trace(
            db,
            lambda: _table_directory(db, tables, page=1, page_size=50),
        )
        directory, directory_statements = _statement_trace(
            db,
            lambda: _table_metadata_directory(tables),
        )

    expected_size = min(table_count, 50)
    assert [row.model_dump() for row in page.rows] == [row.model_dump() for row in legacy[:50]]
    assert page.total == table_count
    assert page.page == 1
    assert page.page_size == 50
    assert page.has_more is (table_count > 50)
    assert len(page.rows) == expected_size
    assert len(legacy_statements) == 1
    assert len(page_statements) == 1
    assert [row.model_dump() for row in directory] == [
        {key: value for key, value in row.model_dump().items() if key != "row_count"}
        for row in legacy
    ]
    assert directory_statements == []
    assert all(statement.startswith("select") for statement in [*legacy_statements, *page_statements])
    assert legacy_statements[0].count(" as table_name") == table_count
    assert page_statements[0].count(" as table_name") == expected_size


def test_super_data_table_page_http_contract_preserves_legacy_auth_and_no_writes(client, auth_headers):
    legacy = client.get("/api/admin/super-data/tables", headers=auth_headers)
    assert legacy.status_code == 200
    assert isinstance(legacy.json(), list)

    paged = client.get(
        "/api/admin/super-data/tables?page=1&page_size=5",
        headers=auth_headers,
    )
    assert paged.status_code == 200
    body = paged.json()
    assert body["rows"] == legacy.json()[:5]
    assert body["total"] == len(legacy.json())
    assert body["page"] == 1
    assert body["page_size"] == 5

    on_demand = client.get(
        "/api/admin/super-data/tables/directory",
        headers=auth_headers,
    )
    assert on_demand.status_code == 200
    assert [
        {key: value for key, value in table.items() if key != "row_count"}
        for table in legacy.json()
    ] == on_demand.json()

    _, regular_headers = _actor()
    assert client.get(
        "/api/admin/super-data/tables?page=1&page_size=5",
        headers=regular_headers,
    ).status_code == 403
    assert client.get(
        "/api/admin/super-data/tables?page_size=201",
        headers=auth_headers,
    ).status_code == 422
    assert client.get(
        "/api/admin/super-data/tables/directory",
        headers=regular_headers,
    ).status_code == 403
    assert client.get("/api/admin/super-data/tables/directory").status_code == 401
    assert client.get("/api/admin/super-data/tables?page=1&page_size=5").status_code == 401
