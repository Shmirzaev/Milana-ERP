from math import ceil
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.db.session import SessionLocal
from app.models import (
    CuttingMaterialUsage,
    CuttingRecord,
    Department,
    Item,
    Model,
    ProductionBatch,
    ProductionOrder,
    StockBatch,
    Supplier,
    Warehouse,
    WorkOrder,
)
from app.services.traceability import _cutting_payload, build_traceability


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


def _reference_counts(statements):
    return {
        "batches": sum(" from stock_batches " in statement for statement in statements),
        "suppliers": sum(" from suppliers " in statement for statement in statements),
        "warehouses": sum(" from warehouses " in statement for statement in statements),
        "total": len(statements),
    }


def _cutting_case(db, record_count):
    suffix = uuid4().hex[:8].upper()
    model_id = db.query(Model.id).order_by(Model.id).first()[0]
    department_id = db.query(Department.id).order_by(Department.id).first()[0]
    item = Item(
        sku=f"PERF21-C-I-{suffix}", name=f"PERF21 fabric {suffix}",
        category="fabric", unit="kg", track_batch=True,
    )
    order = ProductionOrder(
        production_no=f"PERF21-C-PO-{suffix}", production_type="branded_stock",
        model_id=model_id, status="cutting", planned_quantity=record_count,
    )
    suppliers = [Supplier(name=f"PERF21 supplier {suffix} {number}") for number in range(record_count)]
    warehouses = [
        Warehouse(name=f"PERF21 warehouse {suffix} {number}", type="fabric_storage")
        for number in range(record_count)
    ]
    db.add_all([item, order, *suppliers, *warehouses])
    db.flush()
    work_order = WorkOrder(
        production_order_id=order.id, department_id=department_id,
        operation="cutting", status="in_progress",
        planned_input_qty=record_count, planned_output_qty=record_count,
    )
    stock_batches = [
        StockBatch(
            item_id=item.id,
            batch_no=f"PERF21-C-SB-{suffix}-{number:04d}",
            supplier_id=supplier.id,
            warehouse_id=warehouse.id,
            color=f"color-{number}",
            quantity=1,
            unit="kg",
            cost_per_unit=number + 1,
            qc_status="passed",
        )
        for number, (supplier, warehouse) in enumerate(zip(suppliers, warehouses, strict=True))
    ]
    db.add_all([work_order, *stock_batches])
    db.flush()
    records = [
        CuttingRecord(
            work_order_id=work_order.id,
            fabric_batch_id=stock_batch.id,
            input_quantity=1,
            input_unit="kg",
            cut_pieces=1,
            report_piece_count=1,
            passed_pieces=1,
            defective_pieces=0,
            waste_quantity=0,
            waste_unit="kg",
            layer_material_kg=1,
            beika_kg=0,
            material_rolls_used=1,
            bundle_count=0,
            total_bundled_quantity=0,
        )
        for stock_batch in stock_batches
    ]
    db.add_all(records)
    db.commit()
    return {
        "order_id": order.id,
        "record_ids": [record.id for record in records],
        "batch_ids": [batch.id for batch in stock_batches],
        "supplier_names": [supplier.name for supplier in suppliers],
        "warehouse_names": [warehouse.name for warehouse in warehouses],
    }


@pytest.mark.parametrize("record_count", [1, 50, 401])
def test_traceability_batches_cutting_material_references(record_count):
    with SessionLocal() as db:
        case = _cutting_case(db, record_count)

    with SessionLocal() as db:
        order = db.get(ProductionOrder, case["order_id"])
        payload, statements = _select_trace(
            db,
            lambda: build_traceability(
                db,
                subject_type="production_order",
                production_order=order,
            ),
        )

    expected_chunks = ceil(record_count / 400)
    counts = _reference_counts(statements)
    assert counts["batches"] == expected_chunks, counts
    assert counts["suppliers"] == expected_chunks, counts
    assert counts["warehouses"] == expected_chunks, counts
    assert counts["total"] == 13 + (3 * expected_chunks), counts
    assert [row["id"] for row in payload["cutting_records"]] == case["record_ids"]
    assert [row["id"] for row in payload["material_batches"]] == case["batch_ids"]
    assert [row["supplier_name"] for row in payload["material_batches"]] == case["supplier_names"]
    assert [row["warehouse_name"] for row in payload["material_batches"]] == case["warehouse_names"]


def test_traceability_cutting_maps_match_scalar_payload_dedupe_and_missing_gap():
    with SessionLocal() as db:
        suffix = uuid4().hex[:8].upper()
        model_id = db.query(Model.id).order_by(Model.id).first()[0]
        department_id = db.query(Department.id).order_by(Department.id).first()[0]
        item = Item(
            sku=f"PERF21-C-S-I-{suffix}", name="Semantic fabric", category="fabric",
            unit="kg", track_batch=True,
        )
        order = ProductionOrder(
            production_no=f"PERF21-C-S-PO-{suffix}", production_type="branded_stock",
            model_id=model_id, status="cutting", planned_quantity=10,
        )
        supplier = Supplier(name=f"PERF21 semantic supplier {suffix}")
        warehouse = Warehouse(name=f"PERF21 semantic warehouse {suffix}", type="fabric_storage")
        db.add_all([item, order, supplier, warehouse])
        db.flush()
        batches = [
            ProductionBatch(
                production_order_id=order.id, batch_no=f"PERF21-C-S-PB-{suffix}-{number}",
                batch_index=number + 1, planned_quantity=5,
            )
            for number in range(2)
        ]
        work_order = WorkOrder(
            production_order_id=order.id, department_id=department_id,
            operation="cutting", status="in_progress",
            planned_input_qty=10, planned_output_qty=10,
        )
        stock_batches = [
            StockBatch(
                item_id=item.id, batch_no=f"PERF21-C-S-SB-{suffix}-{number}",
                supplier_id=supplier.id, warehouse_id=warehouse.id,
                color="navy", quantity=10, unit="kg", cost_per_unit=3,
                qc_status="passed",
            )
            for number in range(2)
        ]
        db.add_all([*batches, work_order, *stock_batches])
        db.flush()
        target_records = [
            CuttingRecord(
                work_order_id=work_order.id, production_batch_id=batches[0].id,
                fabric_batch_id=stock_batches[0].id,
                input_quantity=2, input_unit="kg", cut_pieces=5, report_piece_count=5,
                passed_pieces=5, defective_pieces=0, waste_quantity=0, waste_unit="kg",
                layer_material_kg=2, beika_kg=0, material_rolls_used=1,
                bundle_count=0, total_bundled_quantity=0,
            ),
            CuttingRecord(
                work_order_id=work_order.id, production_batch_id=batches[0].id,
                fabric_batch_id=stock_batches[0].id,
                input_quantity=1, input_unit="kg", cut_pieces=2, report_piece_count=2,
                passed_pieces=2, defective_pieces=0, waste_quantity=0, waste_unit="kg",
                layer_material_kg=1, beika_kg=0, material_rolls_used=1,
                bundle_count=0, total_bundled_quantity=0,
            ),
            CuttingRecord(
                work_order_id=work_order.id, production_batch_id=batches[0].id,
                fabric_batch_id=None,
                input_quantity=1, input_unit="kg", cut_pieces=1, report_piece_count=1,
                passed_pieces=1, defective_pieces=0, waste_quantity=0, waste_unit="kg",
                layer_material_kg=1, beika_kg=0, material_rolls_used=1,
                bundle_count=0, total_bundled_quantity=0,
            ),
        ]
        excluded = CuttingRecord(
            work_order_id=work_order.id, production_batch_id=batches[1].id,
            fabric_batch_id=stock_batches[1].id,
            input_quantity=1, input_unit="kg", cut_pieces=1, report_piece_count=1,
            passed_pieces=1, defective_pieces=0, waste_quantity=0, waste_unit="kg",
            layer_material_kg=1, beika_kg=0, material_rolls_used=1,
            bundle_count=0, total_bundled_quantity=0,
        )
        db.add_all([*target_records, excluded])
        db.flush()
        db.add_all([
            CuttingMaterialUsage(
                cutting_record_id=target_records[0].id, stock_batch_id=stock_batches[1].id,
                quantity=0.5, unit="kg", position=2,
            ),
            CuttingMaterialUsage(
                cutting_record_id=target_records[0].id, stock_batch_id=stock_batches[0].id,
                quantity=1.5, unit="kg", position=1,
            ),
        ])
        db.commit()
        ids = {
            "order": order.id,
            "batch": batches[0].id,
            "records": [record.id for record in target_records],
            "main_stock_batch": stock_batches[0].id,
        }

    with SessionLocal() as db:
        scalar_row = db.get(CuttingRecord, ids["records"][0])
        scalar_payload, scalar_material, scalar_gap = _cutting_payload(db, scalar_row)
    with SessionLocal() as db:
        payload = build_traceability(
            db,
            subject_type="production_batch",
            production_order=db.get(ProductionOrder, ids["order"]),
            production_batch_id=ids["batch"],
        )

    assert [row["id"] for row in payload["cutting_records"]] == ids["records"]
    assert payload["cutting_records"][0] == scalar_payload
    assert payload["material_batches"] == [scalar_material]
    assert scalar_gap is None
    assert [row["position"] for row in payload["cutting_records"][0]["materials"]] == [1, 2]
    assert "No fabric batch linked to cutting record" in payload["gaps"]
    assert payload["material_batches"][0]["id"] == ids["main_stock_batch"]
