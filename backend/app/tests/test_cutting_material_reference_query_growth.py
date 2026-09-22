from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from app.api.routes import production
from app.models import Item, StockBatch, Warehouse
from app.tests.conftest import TestSessionLocal


def _material_references(count: int) -> tuple[list[int], list[dict]]:
    marker = uuid4().hex[:10]
    with TestSessionLocal() as db:
        warehouse = Warehouse(name=f"Cutting reference {marker}", type="materials")
        items = [
            Item(
                sku=f"CUT-REF-{marker}-{index}",
                name=f"Cutting fabric {index}",
                category="fabric" if index % 2 == 0 else "semi_finished",
                unit="kg",
            )
            for index in range(count)
        ]
        db.add_all([warehouse, *items])
        db.flush()
        batches = [
            StockBatch(
                item_id=item.id,
                warehouse_id=warehouse.id,
                batch_no=f"CUT-REF-{marker}-{index}",
                quantity=10,
                unit="kg",
                qc_status="passed",
            )
            for index, item in enumerate(items)
        ]
        db.add_all(batches)
        db.commit()
        batch_ids = [int(batch.id) for batch in batches]
    return batch_ids, [
        {
            "stock_batch_id": batch_id,
            "quantity": float(index + 1),
            "unit": " kg ",
            "details": None,
        }
        for index, batch_id in enumerate(batch_ids)
    ]


@pytest.mark.parametrize("material_count", [1, 50, 401])
def test_cutting_material_reference_reads_have_bounded_query_growth(material_count):
    batch_ids, raw_materials = _material_references(material_count)
    with TestSessionLocal() as db:
        reference_reads = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            lowered = statement.lower()
            if statement.lstrip().upper().startswith("SELECT") and (
                "stock_batches" in lowered or "items" in lowered
            ):
                reference_reads.append(statement)

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            rows = production._validate_cutting_materials(db, raw_materials)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    assert len(reference_reads) == 1
    assert [row["stock_batch_id"] for row in rows] == batch_ids
    assert [row["quantity"] for row in rows] == [float(index + 1) for index in range(material_count)]
    assert {row["unit"] for row in rows} == {"kg"}


def test_cutting_material_validation_keeps_input_order_and_error_contract():
    batch_ids, raw_materials = _material_references(2)
    duplicate = [raw_materials[0], {**raw_materials[1], "stock_batch_id": batch_ids[0]}]
    with TestSessionLocal() as db:
        with pytest.raises(HTTPException) as repeated:
            production._validate_cutting_materials(db, duplicate)
        assert repeated.value.status_code == 400
        assert repeated.value.detail == "The same fabric batch cannot be consumed more than once"

        missing = [
            {**raw_materials[0], "stock_batch_id": 2_000_000_000},
            {**raw_materials[1], "stock_batch_id": 0, "unit": ""},
        ]
        with pytest.raises(HTTPException) as absent:
            production._validate_cutting_materials(db, missing)
        assert absent.value.status_code == 404
        assert absent.value.detail == "Cutting material #1 inventory batch not found"
