"""Batch caches must preserve first-grade size evidence and transaction boundaries."""
import pytest
from fastapi import HTTPException
from sqlalchemy import event

from app.db.session import SessionLocal
from app.models import Package, FinishedGoodsStock
from app.services import packages as service
from app.tests.test_first_grade_singles import output as output


@pytest.mark.parametrize("count", [1, 5])
def test_first_grade_bulk_reuses_size_evidence_and_decrements_budget(monkeypatch, output, count):
    monkeypatch.setattr(service, "save_qr_image", lambda *_args: "/test/qr.png")
    monkeypatch.setattr(service, "save_barcode_image", lambda *_args: None)
    statements = []
    with SessionLocal() as db:
        def capture(_conn, _cursor, statement, *_args):
            normalized = " ".join(statement.lower().split())
            if normalized.startswith("select") and " from sewing_records " in normalized:
                statements.append(normalized)
        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            packages = service.create_packages_bulk(db, count=count, **output, packaging_department_code="PKG")
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)
        assert len(packages) == count
        assert all(package.stock_kind == "first_grade" for package in packages)
        assert db.query(FinishedGoodsStock).filter(FinishedGoodsStock.production_order_id == output["production_order_id"]).count() == count
        assert len(statements) == 1


def test_first_grade_bulk_size_overrun_rolls_back_all_packages(monkeypatch, output):
    monkeypatch.setattr(service, "save_qr_image", lambda *_args: "/test/qr.png")
    monkeypatch.setattr(service, "save_barcode_image", lambda *_args: None)
    with SessionLocal() as db:
        with pytest.raises(HTTPException) as error:
            service.create_packages_bulk(db, count=6, **output, packaging_department_code="PKG")
        assert error.value.detail == "FIRST_GRADE_SIZE_EXCEEDED"
        db.rollback()
        assert db.query(Package).filter(Package.production_order_id == output["production_order_id"]).count() == 0
        assert db.query(FinishedGoodsStock).filter(FinishedGoodsStock.production_order_id == output["production_order_id"]).count() == 0


def test_package_write_context_cannot_survive_rollback(monkeypatch, output):
    monkeypatch.setattr(service, "save_qr_image", lambda *_args: "/test/qr.png")
    monkeypatch.setattr(service, "save_barcode_image", lambda *_args: None)
    with SessionLocal() as db:
        context = service.PackageWriteContext.empty()
        service.create_package(db, **output, packaging_department_code="PKG", _write_context=context)
        db.rollback()
        with pytest.raises(HTTPException, match="another transaction"):
            service.create_package(db, **output, packaging_department_code="PKG", _write_context=context)
        assert db.query(Package).filter(Package.production_order_id == output["production_order_id"]).count() == 0
