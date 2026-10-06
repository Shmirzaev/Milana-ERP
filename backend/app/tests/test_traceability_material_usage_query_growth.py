from math import ceil
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.db.session import SessionLocal
from app.models import Item, StockBatch, Warehouse
from app.services.traceability import _batch_material_usage


def _select_trace(db, callback):
    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().lower().startswith("select"):
            statements.append(" ".join(statement.lower().split()))

    event.listen(db.bind, "before_cursor_execute", capture)
    try:
        result = callback()
    finally:
        event.remove(db.bind, "before_cursor_execute", capture)
    return result, statements


def _stock_batch_selects(statements):
    return sum(" from stock_batches " in statement for statement in statements)


def _stock_batches(db, count):
    suffix = uuid4().hex[:8].upper()
    items = [
        Item(
            sku=f"PERF21-M-I-{suffix}-{number:04d}",
            name=f"PERF21 material {suffix} {number}",
            category="fabric",
            unit="kg",
            track_batch=True,
        )
        for number in range(count)
    ]
    warehouse = Warehouse(name=f"PERF21 material warehouse {suffix}", type="fabric_storage")
    db.add_all([*items, warehouse])
    db.flush()
    batches = [
        StockBatch(
            item_id=item.id,
            batch_no=f"PERF21-M-SB-{suffix}-{number:04d}",
            color=f"color-{number}",
            quantity=1,
            unit="kg",
            cost_per_unit=number + 1,
            warehouse_id=warehouse.id,
            qc_status="passed",
        )
        for number, item in enumerate(items)
    ]
    db.add_all(batches)
    db.commit()
    return {
        "ids": [row.id for row in batches],
        "batch_nos": [row.batch_no for row in batches],
        "item_names": [row.name for row in items],
    }


@pytest.mark.parametrize("batch_count", [1, 50, 401])
def test_batch_material_usage_batches_origin_lookups(batch_count):
    with SessionLocal() as db:
        case = _stock_batches(db, batch_count)

    data = {
        "material_batches": [],
        "cutting_records": [
            {
                "materials": [
                    {
                        "stock_batch_id": batch_id,
                        "quantity": number + 1,
                        "unit": "kg",
                    }
                ],
                "beika_materials": [],
                "beika_kg": 0,
            }
            for number, batch_id in enumerate(case["ids"])
        ],
    }
    with SessionLocal() as db:
        rows, statements = _select_trace(db, lambda: _batch_material_usage(db, data))

    assert _stock_batch_selects(statements) == ceil(batch_count / 400), statements
    assert [row["stock_batch_id"] for row in rows] == case["ids"]
    assert [row["batch_no"] for row in rows] == case["batch_nos"]
    assert [row["item_name"] for row in rows] == case["item_names"]
    assert [row["used_quantity"] for row in rows] == [float(number) for number in range(1, batch_count + 1)]


def test_batch_material_usage_preserves_grouping_fallbacks_and_cached_origins():
    with SessionLocal() as db:
        case = _stock_batches(db, 2)
    missing_id = max(case["ids"]) + 1_000_000
    cached_origin = {
        "id": case["ids"][0],
        "batch_no": "FROZEN-BATCH",
        "item_id": 987654,
        "item_sku": "FROZEN-SKU",
        "item_name": "Frozen material name",
        "color": "frozen-color",
    }
    data = {
        "material_batches": [cached_origin],
        "cutting_records": [
            {
                "fabric_batch_id": missing_id,
                "input_quantity": 99,
                "input_unit": "ignored",
                "materials": [
                    {"stock_batch_id": case["ids"][0], "quantity": 2, "unit": "kg"},
                    {"stock_batch_id": case["ids"][1], "quantity": -0.5, "unit": "kg"},
                ],
                "beika_materials": [
                    {"stock_batch_id": case["ids"][1], "quantity": 1, "unit": "kg"},
                ],
                "beika_kg": 99,
            },
            {
                "materials": [
                    {"stock_batch_id": case["ids"][0], "quantity": 3, "unit": "kg"},
                ],
                "beika_materials": [],
                "beika_kg": 0.25,
            },
            {
                "fabric_batch_id": missing_id,
                "input_quantity": 4,
                "input_unit": "kg",
                "materials": [],
                "beika_materials": [],
                "beika_kg": 0,
            },
            {
                "fabric_batch_id": case["ids"][1],
                "input_quantity": 1,
                "input_unit": "yards",
                "materials": [],
                "beika_materials": [
                    {"stock_batch_id": case["ids"][1], "quantity": -2, "unit": "kg"},
                ],
                "beika_kg": 99,
            },
        ],
    }

    with SessionLocal() as db:
        rows, statements = _select_trace(db, lambda: _batch_material_usage(db, data))
        empty_rows, empty_statements = _select_trace(
            db,
            lambda: _batch_material_usage(db, {"material_batches": [], "cutting_records": []}),
        )

    assert _stock_batch_selects(statements) == 1, statements
    assert empty_rows == []
    assert empty_statements == []
    assert [
        (row["usage_type"], row["stock_batch_id"], row["unit"], row["used_quantity"])
        for row in rows
    ] == [
        ("fabric", case["ids"][0], "kg", 5.0),
        ("fabric", case["ids"][1], "kg", -0.5),
        ("beika", case["ids"][1], "kg", -1.0),
        ("beika", None, "kg", 0.25),
        ("fabric", missing_id, "kg", 4.0),
        ("fabric", case["ids"][1], "yards", 1.0),
    ]
    assert rows[0] == {
        "usage_type": "fabric",
        "stock_batch_id": case["ids"][0],
        "batch_no": "FROZEN-BATCH",
        "item_id": 987654,
        "item_sku": "FROZEN-SKU",
        "item_name": "Frozen material name",
        "color": "frozen-color",
        "used_quantity": 5.0,
        "unit": "kg",
        "scope": "production_batch",
    }
    assert rows[3]["item_name"] == "Beyka"
    assert rows[4]["item_name"] == "Main fabric"
    assert rows[4]["batch_no"] is None
