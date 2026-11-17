"""Report parity against a disposable loopback PostgreSQL schema."""
from datetime import date, datetime, timezone
import importlib.util
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.libs.enums.packaging import PackagingReportKind
from app.models import packaging_reports_service as service
from app.schemas import Brand, Department, Model, Package, PackageBatchAllocation, PackageItem, ProductionBatch, ProductionOrder, WorkOrder
from app.tests.test_planning_cutting_factory_postgres import cutting_factory_postgres  # noqa: F401


def test_pages_preserve_legacy_groups_summaries_and_caps(cutting_factory_postgres, monkeypatch):
    sessions, engine = cutting_factory_postgres
    path = Path(__file__).parents[2] / "alembic/versions/0084_model_group_key.py"
    spec = importlib.util.spec_from_file_location("qa_packaging_0084", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.begin() as connection:
        connection.exec_driver_sql("ALTER TABLE models ADD COLUMN is_legacy_import boolean GENERATED ALWAYS AS ((coalesce(details_json ->> 'legacy_import', 'false')) = 'true') STORED")
        connection.exec_driver_sql(f"ALTER TABLE models ADD COLUMN model_group_key text GENERATED ALWAYS AS ({migration.GROUP_KEY_SQL}) STORED")
    day = date(2026, 9, 3)
    with sessions() as db:
        dept = Department(code="PKG", name="Packaging")
        model = Model(code="PAGE-10", name="Page garment", details_json={"general": {"model_no": "M10", "variant_no": "2"}})
        db.add_all([dept, model]); db.flush()
        order = ProductionOrder(production_no="PO-10", production_type="branded_stock", model_id=model.id, planned_quantity=500)
        db.add(order); db.flush()
        batch = ProductionBatch(production_order_id=order.id, batch_no="B2", batch_index=1, planned_quantity=500)
        db.add(batch); db.flush()
        for index in range(105):
            p = Package(package_no=f"PAGE-{index}", barcode=f"PAGE-{index}", production_order_id=order.id,
                        production_batch_id=batch.id, model_id=model.id, color=f"Color {index}", total_quantity=index + 1,
                        capacity=30 + index % 2, packaging_department_code="PKG",
                        packed_at=datetime(2026, 9, 3, 12, tzinfo=timezone.utc), status="packed")
            db.add(p); db.flush()
            db.add(PackageItem(package_id=p.id, model_id=model.id, color=p.color, size="M", quantity=1))
        # A second package shares one group despite using the allocation table.
        duplicate = Package(package_no="PAGE-duplicate", barcode="PAGE-duplicate", production_order_id=order.id,
                            model_id=model.id, color="Color 0", total_quantity=7, capacity=99,
                            packaging_department_code="PKG", packed_at=datetime(2026, 9, 3, 13, tzinfo=timezone.utc), status="packed")
        db.add(duplicate); db.flush()
        db.add_all([PackageBatchAllocation(package_id=duplicate.id, production_batch_id=batch.id, quantity=7),
                    PackageItem(package_id=duplicate.id, model_id=model.id, color=duplicate.color, size="XL", quantity=7)])
        # Same displayed sort keys but different brand identities: first packed
        # timestamp wins even when its package id is larger.
        brands = [Brand(name="Tie brand A"), Brand(name="Tie brand B")]
        db.add_all(brands); db.flush()
        for index, hour in enumerate((15, 14)):
            db.add(Package(package_no=f"PAGE-tie-{index}", barcode=f"PAGE-tie-{index}",
                           production_order_id=order.id, production_batch_id=batch.id, model_id=model.id,
                           brand_id=brands[index].id, color="Tie", total_quantity=50 + index, capacity=60,
                           packaging_department_code="PKG", packed_at=datetime(2026, 9, 3, hour, tzinfo=timezone.utc), status="packed"))
        db.add(WorkOrder(production_order_id=order.id, department_id=dept.id, operation="packaging", status="completed",
                         planned_output_qty=500, passed_qty=490, failed_qty=3,
                         end_time=datetime(2026, 9, 3, 12, tzinfo=timezone.utc)))
        db.commit()
        legacy = service.build_packaging_report(db, "PKG", day, day)
        assert [row["quantity"] for row in legacy["entries"] if row["color"] == "Tie"] == [51, 50]
        for kind in PackagingReportKind:
            expected = legacy[kind.value]
            rows = []
            offset = 0
            while True:
                page = service.build_packaging_report_page(db, "PKG", day, day, kind, offset, 37)
                assert page["total"] == len(expected)
                rows.extend(page["rows"])
                numeric = (("planned_quantity", "packed_quantity", "damaged_quantity", "balance") if kind == PackagingReportKind.COMPLETED else ("package_count", "quantity"))
                for field in numeric:
                    assert page["summary"][field] == (sum(row[field] for row in expected) if expected else None)
                if not page["has_more"]:
                    break
                offset += 37
            assert len(rows) == len(expected)
            assert len({row["row_key"] for row in rows}) == len(rows)
            assert [{key: row.get(key) for key in original} for row, original in zip(rows, expected)] == expected
        monkeypatch.setattr(service, "MAX_REPORT_PACKAGES", 100)
        with pytest.raises(HTTPException) as rejected:
            service.build_packaging_report_page(db, "PKG", day, day, PackagingReportKind.COMPLETED, 0, 100)
        assert rejected.value.status_code == 413
        monkeypatch.setattr(service, "MAX_REPORT_PACKAGES", 0)
        # A range without packages still rejects excess completed work orders.
        db.query(PackageBatchAllocation).delete(synchronize_session=False)
        db.query(PackageItem).delete(synchronize_session=False)
        db.query(Package).delete(synchronize_session=False)
        with pytest.raises(HTTPException) as rejected:
            service.build_packaging_report_page(db, "PKG", day, day, PackagingReportKind.DAILY, 0, 100)
        assert rejected.value.status_code == 413
