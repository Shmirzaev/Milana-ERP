"""Persist the public-number Nastil identity on real owned PostgreSQL."""
import pytest

from app.models.production_service import create_production_batches
from app.schemas import Model, ProductionBatch, ProductionOrder, SalesOrder
from app.tests.test_numbering_postgres_concurrency import numbering_postgres_sessions  # noqa: F401


@pytest.mark.parametrize(("production_no", "sales_no", "expected"), [
    ("PO-0887", None, ["0887-01", "0887-02"]),
    ("PO-0999", "SO-0421", ["0421-01", "0421-02"]),
    ("USL-0027", None, ["0027-01", "0027-02"]),
])
def test_public_batch_identity_survives_commit_and_retry(numbering_postgres_sessions, production_no, sales_no, expected):
    sessions, _ = numbering_postgres_sessions
    with sessions.begin() as db:
        model = Model(code=production_no, name="Numbering QA")
        sales = SalesOrder(order_no=sales_no) if sales_no else None
        db.add(model)
        if sales:
            db.add(sales)
        db.flush()
        order = ProductionOrder(production_no=production_no, model_id=model.id,
                                production_type="client_order" if sales else "branded_stock",
                                sales_order_id=sales.id if sales else None, planned_quantity=12)
        db.add(order)
        db.flush()
        order_id = order.id
        batches = create_production_batches(db, order_id, [{"planned_quantity": 5}, {"planned_quantity": 7}])
        assert [row.batch_no for row in batches] == expected
        ids = [row.id for row in batches]
    with sessions.begin() as db:
        rows = db.query(ProductionBatch).filter_by(production_order_id=order_id).order_by(ProductionBatch.batch_index).all()
        assert [(row.id, row.batch_no, row.planned_quantity) for row in rows] == list(zip(ids, expected, [5, 7]))
        retry = create_production_batches(db, order_id, [{"planned_quantity": 12}])
        assert {row.id for row in retry} == set(ids)
