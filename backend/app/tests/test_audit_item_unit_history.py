from __future__ import annotations

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, insert, select

from app.models import (
    ForecastRecommendation,
    MaterialReservation,
    PurchaseOrderLine,
    PurchaseRequestLine,
    StockBatch,
    StockMovement,
)
from scripts.audit_item_unit_history import audit_item_unit_history


_SOURCE_MODELS = (
    StockBatch,
    MaterialReservation,
    PurchaseRequestLine,
    PurchaseOrderLine,
    StockMovement,
    ForecastRecommendation,
)


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
    tables = {
        model.__tablename__: Table(
            model.__tablename__,
            metadata,
            Column("id", Integer, primary_key=True),
            Column("item_id", Integer),
            Column("unit", String(32)),
        )
        for model in _SOURCE_MODELS
    }
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(insert(items), [{"id": 1, "unit": "kg"}, {"id": 2, "unit": ""}])
        for table in tables.values():
            connection.execute(
                insert(table),
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
    try:
        yield engine, items, tables
    finally:
        engine.dispose()


def test_audit_reports_exact_mismatches_and_skips_missing_units(synthetic_database):
    engine, _items, _tables = synthetic_database

    with engine.connect() as connection:
        report = audit_item_unit_history(connection)

    for table_name, result in report["tables"].items():
        assert result["scanned_count"] == 6, table_name
        assert result["equal_count"] == 1, table_name
        assert result["missing_unit_count"] == 3, table_name
        assert result["unresolved_item_count"] == 1, table_name
        assert result["mismatch_count"] == 1, table_name
        assert result["mismatches"] == [
            {"row_id": 2, "item_id": 1, "row_unit": "m", "item_unit": "kg"}
        ], table_name
        assert result["unresolved_items"] == [{"row_id": 5, "item_id": 999}], table_name


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
