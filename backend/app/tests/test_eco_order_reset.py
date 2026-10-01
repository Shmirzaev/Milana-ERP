"""Guard the one-time reset against collateral deletion and stale review."""
import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import Column, ForeignKey, Integer, MetaData, Table

from app.models import Department, Model, ProductionOrder, WorkOrder, AuditLog, PayrollQrLabel
from app.tests.conftest import TestSessionLocal

spec = importlib.util.spec_from_file_location("eco_reset", Path(__file__).parents[2] / "scripts/reset_eco_orders_20261001.py")
reset = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reset)


@pytest.fixture
def reviewed(client):
    with TestSessionLocal() as db:
        model = db.query(Model).first()
        department = db.query(Department).filter_by(code="ECT").first()
        if not department:
            department = Department(code="ECT", name="Eco Cutting")
            db.add(department)
            db.flush()
        orders = []
        for number in reset.ORDER_NUMBERS:
            order = ProductionOrder(production_no=number, production_type="branded_stock", source_type="usluga", model_id=model.id, planned_quantity=20)
            db.add(order)
            db.flush()
            db.add(WorkOrder(production_order_id=order.id, department_id=department.id, operation="cutting"))
            orders.append(order)
        db.flush()
        yield db, orders
        db.rollback()


def test_reset_removes_only_reviewed_rows_and_retains_audit(reviewed):
    db, orders = reviewed
    other = ProductionOrder(production_no="OTHER-KEEP", production_type="branded_stock", model_id=orders[0].model_id)
    db.add(other)
    db.flush()
    before_audit = db.query(AuditLog).count()
    _, fingerprint, _ = reset.prepare(db)
    result = reset.apply_reviewed(db, fingerprint)
    assert result["deleted"]["production_orders"] == 6
    assert db.query(ProductionOrder).filter(ProductionOrder.production_no.in_(reset.ORDER_NUMBERS)).count() == 0
    assert db.query(ProductionOrder).filter_by(production_no="OTHER-KEEP").count() == 1
    assert db.query(AuditLog).count() == before_audit + 1
    assert result["protected_fingerprints"]["payroll_records"]


def test_reset_rejects_changed_review_before_deleting(reviewed):
    db, orders = reviewed
    _, fingerprint, _ = reset.prepare(db)
    orders[0].planned_quantity += 1
    db.flush()
    with pytest.raises(ValueError, match="fingerprint"):
        reset.apply_reviewed(db, fingerprint)
    assert db.query(ProductionOrder).filter(ProductionOrder.production_no.in_(reset.ORDER_NUMBERS)).count() == 6


def test_reset_rejects_other_factory_work(reviewed):
    db, orders = reviewed
    department = db.query(Department).filter_by(code="CUT").one()
    work = db.query(WorkOrder).filter_by(production_order_id=orders[0].id).one()
    work.department_id = department.id
    db.flush()
    with pytest.raises(ValueError, match="Cross-factory"):
        reset.prepare(db)


def test_reset_rejects_payroll_dependencies(reviewed):
    db, orders = reviewed
    db.add(PayrollQrLabel(factory_code="ECO", label_uid="ECO-PROTECTED", production_order_id=orders[0].id,
                          operation_code="SEW", operation_name="Sew", quantity=1, rate_per_piece=10))
    db.flush()
    with pytest.raises(ValueError, match="Protected dependency: payroll_qr_labels"):
        reset.prepare(db)


def test_reset_rejects_unmapped_database_dependency(reviewed):
    db, orders = reviewed
    metadata = MetaData()
    Table("production_orders", metadata, autoload_with=db.connection())
    extra = Table("future_eco_dependency", metadata, Column("id", Integer, primary_key=True),
                  Column("production_order_id", ForeignKey("production_orders.id")))
    extra.create(db.connection())
    db.execute(extra.insert().values(id=1, production_order_id=orders[0].id))
    try:
        with pytest.raises(ValueError, match="Protected dependency: future_eco_dependency"):
            reset.prepare(db)
    finally:
        extra.drop(db.connection())
        reset.Base.metadata.remove(reset.Base.metadata.tables["future_eco_dependency"])


def test_reset_rejects_incomplete_order_selection(reviewed):
    db, orders = reviewed
    orders[-1].production_no = "USL-CHANGED"
    db.flush()
    with pytest.raises(ValueError, match="selection changed"):
        reset.prepare(db)
