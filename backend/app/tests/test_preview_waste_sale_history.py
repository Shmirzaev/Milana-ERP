from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import JSON, Column, DateTime, Integer, MetaData, Numeric, String, Table, create_engine, insert, select

from scripts.preview_waste_sale_history import main, preview_waste_sale_history


@pytest.fixture
def history_db():
    engine = create_engine("sqlite:///:memory:")
    metadata = MetaData()
    records = Table("waste_records", metadata,
                    Column("id", Integer, primary_key=True), Column("quantity", Numeric(14, 4)),
                    Column("status", String))
    sales = Table("waste_sales", metadata,
                  Column("id", Integer, primary_key=True), Column("waste_record_id", Integer),
                  Column("buyer_name", String), Column("quantity", Numeric(14, 4)),
                  Column("unit_price", Numeric(12, 2)), Column("total_amount", Numeric(14, 2)),
                  Column("sold_at", DateTime(timezone=True)))
    audits = Table("audit_logs", metadata,
                   Column("id", Integer, primary_key=True), Column("action", String),
                   Column("entity_type", String), Column("entity_id", Integer),
                   Column("new_value_json", JSON))
    replays = Table("idempotency_records", metadata,
                    Column("id", Integer, primary_key=True), Column("scope", String),
                    Column("response_json", JSON), Column("status_code", Integer))
    metadata.create_all(engine)
    try:
        yield engine, records, sales, audits, replays
    finally:
        engine.dispose()


def test_preview_flags_candidates_without_exposing_buyer_or_changing_rows(history_db):
    engine, records, sales, audits, replays = history_db
    now = datetime(2026, 9, 25, tzinfo=timezone.utc)
    with engine.begin() as connection:
        connection.execute(insert(records), [{"id": 1, "quantity": 5, "status": "sold"},
                                             {"id": 11, "quantity": 20, "status": "received_by_waste_department"}])
        connection.execute(insert(sales), [
            {"id": 10, "waste_record_id": 1, "buyer_name": "Secret buyer", "quantity": 3,
             "unit_price": 2, "total_amount": 6, "sold_at": now},
            {"id": 11, "waste_record_id": 1, "buyer_name": "Secret buyer", "quantity": 3,
             "unit_price": 2, "total_amount": 6, "sold_at": now + timedelta(minutes=1)},
            {"id": 12, "waste_record_id": 1, "buyer_name": "Other", "quantity": 1,
             "unit_price": 2, "total_amount": 3, "sold_at": now},
        ])
        connection.execute(insert(audits), {"id": 21, "action": "sell", "entity_type": "WasteRecord",
                                            "entity_id": 1, "new_value_json": {"quantity": 3}})
        connection.execute(insert(replays), [
            {"id": 31, "scope": "waste.sales.3.1", "response_json": {"id": 10}, "status_code": 200},
            {"id": 32, "scope": "waste.sales.3.1", "response_json": {"id": 99}, "status_code": 200},
            {"id": 33, "scope": "waste.sales.3.11", "response_json": {"id": 100}, "status_code": 200},
            {"id": 34, "scope": "waste.sales.3.1", "response_json": {"status": "cancelled"}, "status_code": 409},
        ])
    with engine.connect() as connection:
        before = connection.execute(select(sales).order_by(sales.c.id)).all()
        report = preview_waste_sale_history(connection, 1)
        after = connection.execute(select(sales).order_by(sales.c.id)).all()
    assert before == after
    assert report["sold_quantity"] == "7.0000"
    assert report["remaining_quantity"] == "-2.0000"
    assert report["success_replay_ids"] == [31, 32]
    assert {issue["kind"] for issue in report["issues"]} == {
        "oversold", "possible_repeat", "amount_mismatch", "orphan_success_replay", "sale_audit_count_mismatch",
    }
    assert "Secret buyer" not in str(report)
    assert {tuple(issue["sale_ids"]) for issue in report["issues"] if issue["kind"] == "possible_repeat"} == {(10, 11)}


def test_preview_clean_partial_sale_and_read_only_mode(history_db):
    engine, records, sales, audits, _replays = history_db
    with engine.begin() as connection:
        connection.execute(insert(records), {"id": 1, "quantity": 5, "status": "received_by_waste_department"})
        connection.execute(insert(sales), {"id": 7, "waste_record_id": 1, "buyer_name": "Buyer",
                                          "quantity": 2, "unit_price": Decimal("1.25"),
                                          "total_amount": Decimal("2.50")})
        connection.execute(insert(audits), {"id": 8, "action": "sell", "entity_type": "WasteRecord",
                                            "entity_id": 1, "new_value_json": {"quantity": 2}})
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA query_only = ON")
        try:
            report = preview_waste_sale_history(connection, 1)
            assert connection.exec_driver_sql("PRAGMA query_only").scalar_one() == 1
        finally:
            connection.exec_driver_sql("PRAGMA query_only = OFF")
    assert report["issues"] == []
    assert report["remaining_quantity"] == "3.0000"


def test_preview_requires_target_and_schema(history_db):
    engine, records, *_ = history_db
    with engine.connect() as connection:
        with pytest.raises(ValueError, match="positive"):
            preview_waste_sale_history(connection, 0)
        with pytest.raises(ValueError, match="does not exist"):
            preview_waste_sale_history(connection, 1)
    engine.dispose()
    empty = create_engine("sqlite:///:memory:")
    try:
        with empty.connect() as connection, pytest.raises(RuntimeError, match="Required table is missing"):
            preview_waste_sale_history(connection, 1)
    finally:
        empty.dispose()


def test_cli_requires_explicit_database(monkeypatch):
    monkeypatch.delenv("WASTE_SALE_PREVIEW_DATABASE_URL", raising=False)
    with pytest.raises(SystemExit, match="WASTE_SALE_PREVIEW_DATABASE_URL"):
        main(["1"])
