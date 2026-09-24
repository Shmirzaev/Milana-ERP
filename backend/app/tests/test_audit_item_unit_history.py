from __future__ import annotations

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, insert, select

from scripts.audit_item_unit_history import _SOURCES, audit_item_unit_history, main


@pytest.fixture
def synthetic_database():
    engine = create_engine("sqlite:///:memory:")
    metadata = MetaData()
    items = Table(
        "items",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("unit", String(32)),
    )
    tables = {}
    for _name, model, item_column, batch_column in _SOURCES:
        columns = [Column("id", Integer, primary_key=True), Column("unit", String(32))]
        if item_column:
            columns.append(Column(item_column, Integer))
        if batch_column:
            columns.append(Column(batch_column, Integer))
        tables[model.__tablename__] = Table(model.__tablename__, metadata, *columns)
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(insert(items), [{"id": 1, "unit": "kg"}, {"id": 2, "unit": ""}])
        stock_batches = tables["stock_batches"]
        connection.execute(
            insert(stock_batches),
            [
                {"id": 1, "item_id": 1, "unit": "kg"},
                {"id": 2, "item_id": 1, "unit": "m"},
                {"id": 3, "item_id": 1, "unit": None},
                {"id": 4, "item_id": 2, "unit": "kg"},
                {"id": 5, "item_id": 999, "unit": "kg"},
                {"id": 6, "item_id": None, "unit": "kg"},
                {"id": 7, "item_id": 1, "unit": "   "},
            ],
        )
        for name, model, item_column, batch_column in _SOURCES:
            if name == "stock_batches":
                continue
            table = tables[model.__tablename__]
            source_rows = []
            for row_id, unit in enumerate(("kg", "m", None, "kg", "kg", "kg", "   "), 1):
                row = {"id": row_id, "unit": unit}
                item_ids = (1, 1, 1, 2, 999, None, 1)
                if item_column:
                    row[item_column] = item_ids[row_id - 1]
                if batch_column:
                    row[batch_column] = row_id
                source_rows.append(row)
            connection.execute(
                insert(table),
                source_rows,
            )
    try:
        yield engine, items, tables
    finally:
        engine.dispose()


def test_audit_reports_exact_mismatches_and_skips_missing_units(synthetic_database):
    engine, _items, _tables = synthetic_database

    with engine.connect() as connection:
        report = audit_item_unit_history(connection)

    for table_name, result in report["tables"].items():
        uses_batch = any(name == table_name and batch_column for name, _model, _item_column, batch_column in _SOURCES)
        assert result["scanned_count"] == (7 if uses_batch else 6), table_name
        assert result["equal_count"] == 1, table_name
        assert result["missing_unit_count"] == 3, table_name
        assert result["unresolved_item_count"] == (2 if uses_batch else 1), table_name
        assert result["mismatch_count"] == 1, table_name
        assert result["mismatches"] == [
            {"row_id": 2, "item_id": 1, "row_unit": "m", "item_unit": "kg"}
        ], table_name
        assert result["unresolved_items"][0]["row_id"] == 5, table_name
        assert result["unresolved_items"][0]["reason"] in {
            "item not found", "batch item not found",
        }, table_name
        if uses_batch:
            assert result["unresolved_items"][1]["row_id"] == 6, table_name
            assert result["unresolved_items"][1]["reason"] == "batch item not found", table_name


def test_audit_resolves_batch_links_and_reports_conflicting_item_references(synthetic_database):
    engine, _items, tables = synthetic_database
    with engine.begin() as connection:
        connection.execute(
            insert(tables["production_order_materials"]),
            {"id": 8, "stock_batch_id": 1, "unit": "m"},
        )
        connection.execute(
            insert(tables["waste_records"]),
            {"id": 8, "item_id": 2, "batch_id": 1, "unit": "pcs"},
        )

    with engine.connect() as connection:
        report = audit_item_unit_history(connection)

    production_materials = report["tables"]["production_order_materials"]
    assert production_materials["mismatch_count"] == 2
    assert production_materials["mismatches"][-1] == {
        "row_id": 8,
        "item_id": 1,
        "row_unit": "m",
        "item_unit": "kg",
    }

    waste_rows = report["tables"]["waste_records"]
    assert waste_rows["unresolved_items"][-1] == {
        "row_id": 8,
        "item_id": 2,
        "batch_id": 1,
        "reason": "item does not match batch item",
    }


def test_audit_does_not_change_synthetic_rows(synthetic_database):
    engine, items, tables = synthetic_database

    def snapshot(connection):
        state = {"items": connection.execute(select(items).order_by(items.c.id)).all()}
        for name, table in tables.items():
            state[name] = connection.execute(select(table).order_by(table.c.id)).all()
        return state

    with engine.connect() as connection:
        before = snapshot(connection)
        audit_item_unit_history(connection)
        after = snapshot(connection)

    assert after == before


def test_audit_fails_closed_when_required_table_is_missing():
    engine = create_engine("sqlite:///:memory:")
    try:
        with engine.connect() as connection, pytest.raises(RuntimeError, match="Required table is missing"):
            audit_item_unit_history(connection)
    finally:
        engine.dispose()


def test_audit_preserves_an_existing_sqlite_read_only_mode(synthetic_database):
    engine, _items, _tables = synthetic_database
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA query_only = ON")
        try:
            audit_item_unit_history(connection)
            assert connection.exec_driver_sql("PRAGMA query_only").scalar_one() == 1
        finally:
            connection.exec_driver_sql("PRAGMA query_only = OFF")


def test_cli_requires_an_explicit_database_target(monkeypatch):
    monkeypatch.delenv("ITEM_UNIT_AUDIT_DATABASE_URL", raising=False)
    with pytest.raises(SystemExit, match="ITEM_UNIT_AUDIT_DATABASE_URL"):
        main()
