from collections import Counter
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
    Package,
    PackageItem,
    PackagingRecord,
    PrintingRecord,
    ProductionBatch,
    ProductionOrder,
    SewingRecord,
    StockBatch,
    Warehouse,
    WorkOrder,
)
from app.services.traceability import package_traceability


_HISTORY_MODELS = (CuttingRecord, PrintingRecord, SewingRecord, PackagingRecord)
_HISTORY_TABLES = (
    "cutting_records",
    "printing_records",
    "sewing_records",
    "packaging_records",
)


def _history_case(db, history_count):
    suffix = uuid4().hex[:8].upper()
    model_id = db.query(Model.id).order_by(Model.id).first()[0]
    department_id = db.query(Department.id).order_by(Department.id).first()[0]
    warehouse_id = db.query(Warehouse.id).order_by(Warehouse.id).first()[0]
    item = Item(
        sku=f"PERF21-H-I-{suffix}",
        name=f"PERF21 history material {suffix}",
        category="fabric",
        unit="kg",
        track_batch=True,
    )
    order = ProductionOrder(
        production_no=f"PERF21-H-PO-{suffix}",
        production_type="branded_stock",
        model_id=model_id,
        status="packaging",
        planned_quantity=history_count,
    )
    db.add_all([item, order])
    db.flush()
    stock_batch = StockBatch(
        item_id=item.id,
        batch_no=f"PERF21-H-SB-{suffix}",
        quantity=history_count,
        unit="kg",
        cost_per_unit=1,
        warehouse_id=warehouse_id,
        qc_status="passed",
    )
    batches = [
        ProductionBatch(
            production_order_id=order.id,
            batch_no=f"PERF21-H-B-{suffix}-{number:04d}",
            batch_index=number + 1,
            planned_quantity=1,
        )
        for number in range(history_count)
    ]
    db.add_all([stock_batch, *batches])
    db.flush()
    work_order = WorkOrder(
        production_order_id=order.id,
        production_batch_id=batches[0].id,
        department_id=department_id,
        operation="packaging",
        status="in_progress",
        planned_input_qty=history_count,
        planned_output_qty=history_count,
    )
    package = Package(
        package_no=f"PERF21-H-P-{suffix}",
        barcode=f"PERF21-H-BC-{suffix}",
        production_order_id=order.id,
        production_batch_id=batches[0].id,
        model_id=model_id,
        color="navy",
        total_quantity=1,
        capacity=1,
        status="packed",
    )
    db.add_all([work_order, package])
    db.flush()
    db.add(
        PackageItem(
            package_id=package.id,
            model_id=model_id,
            color="navy",
            size="M",
            quantity=1,
        )
    )
    cutting_records = [
        CuttingRecord(
            work_order_id=work_order.id,
            production_batch_id=batch.id,
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
        for batch in batches
    ]
    printing_records = [
        PrintingRecord(
            work_order_id=work_order.id,
            production_batch_id=batch.id,
            input_qty=1,
            printed_qty=1,
            passed_qty=1,
            rejected_qty=0,
        )
        for batch in batches
    ]
    sewing_records = [
        SewingRecord(
            work_order_id=work_order.id,
            production_batch_id=batch.id,
            input_qty=1,
            sewn_qty=1,
            passed_qty=1,
            failed_qty=0,
            rework_qty=0,
            rejected_qty=0,
        )
        for batch in batches
    ]
    packaging_records = [
        PackagingRecord(
            work_order_id=work_order.id,
            production_batch_id=batch.id,
            input_qty=1,
            packed_qty=1,
            damaged_qty=0,
            package_count=1,
            total_packed_quantity=1,
        )
        for batch in batches
    ]
    db.add_all([*cutting_records, *printing_records, *sewing_records, *packaging_records])
    db.flush()
    db.add_all(
        CuttingMaterialUsage(
            cutting_record_id=record.id,
            stock_batch_id=stock_batch.id,
            quantity=1,
            unit="kg",
            position=1,
        )
        for record in cutting_records
    )
    db.commit()
    return {
        "package_id": package.id,
        "target_batch_id": batches[0].id,
        "fallback_batch_id": batches[-1].id,
        "record_ids": {
            "cutting_records": [row.id for row in cutting_records],
            "printing_records": [row.id for row in printing_records],
            "sewing_records": [row.id for row in sewing_records],
            "packaging_records": [row.id for row in packaging_records],
        },
    }


def _trace_package(case):
    with SessionLocal() as db:
        package = db.get(Package, case["package_id"])
        statements = []
        loaded = Counter()

        def capture_statement(_connection, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().lower().startswith("select"):
                statements.append(" ".join(statement.lower().split()))

        def capture_load(target, _context):
            loaded[type(target).__name__] += 1

        event.listen(db.bind, "before_cursor_execute", capture_statement)
        for model_cls in (*_HISTORY_MODELS, CuttingMaterialUsage):
            event.listen(model_cls, "load", capture_load)
        try:
            payload = package_traceability(db, package)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture_statement)
            for model_cls in (*_HISTORY_MODELS, CuttingMaterialUsage):
                event.remove(model_cls, "load", capture_load)
    return payload, statements, loaded


@pytest.mark.parametrize("history_count", [1, 50, 401])
def test_package_traceability_pushes_exact_history_scope_into_sql(history_count):
    with SessionLocal() as db:
        case = _history_case(db, history_count)

    payload, statements, loaded = _trace_package(case)

    assert len(statements) == 21, statements
    for model_cls, table in zip(_HISTORY_MODELS, _HISTORY_TABLES, strict=True):
        reads = [statement for statement in statements if f" from {table} " in statement]
        assert len(reads) == 1, statements
        assert f"{table}.production_batch_id in (?)" in reads[0]
        assert loaded[model_cls.__name__] == 1
        assert [row["id"] for row in payload[table]] == case["record_ids"][table][:1]
    assert loaded[CuttingMaterialUsage.__name__] == 1


def test_package_traceability_preserves_full_history_fallback_when_exact_scope_is_empty():
    with SessionLocal() as db:
        case = _history_case(db, 2)
        for model_cls in _HISTORY_MODELS:
            (
                db.query(model_cls)
                .filter(model_cls.production_batch_id == case["target_batch_id"])
                .update({model_cls.production_batch_id: case["fallback_batch_id"]})
            )
        db.commit()

    payload, statements, loaded = _trace_package(case)

    assert len(statements) == 25, statements
    for model_cls, table in zip(_HISTORY_MODELS, _HISTORY_TABLES, strict=True):
        reads = [statement for statement in statements if f" from {table} " in statement]
        assert len(reads) == 2, statements
        assert f"{table}.production_batch_id in (?)" in reads[0]
        assert loaded[model_cls.__name__] == 2
        assert [row["id"] for row in payload[table]] == case["record_ids"][table]
    assert loaded[CuttingMaterialUsage.__name__] == 2
