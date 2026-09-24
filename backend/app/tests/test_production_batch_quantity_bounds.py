"""Keep alternate production-batch writers within the database INTEGER range."""

from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.db.session import SessionLocal
from app.models import AuditLog, Model, ProductionBatch, ProductionOrder
from app.api.routes.production import CuttingBatchUpdateIn, SplitBatchLineIn
from app.schemas.production import ProductionBatchIn
from app.services.production import create_production_batches


MAX_INTEGER_QUANTITY = 2_147_483_647


def _production_order(db) -> ProductionOrder:
    model_id = db.query(Model.id).order_by(Model.id).first()
    if not model_id:
        pytest.skip("The test seed has no model to attach to the production order")
    order = ProductionOrder(
        production_no=f"DB01-BATCH-{uuid4().hex}",
        production_type="branded_stock",
        model_id=int(model_id[0]),
        status="new",
        planned_quantity=1,
    )
    db.add(order)
    db.flush()
    return order


def test_batch_creation_accepts_maximum_signed_integer_quantity():
    assert ProductionBatchIn(planned_quantity=MAX_INTEGER_QUANTITY).planned_quantity == MAX_INTEGER_QUANTITY
    assert SplitBatchLineIn(planned_quantity=MAX_INTEGER_QUANTITY).planned_quantity == MAX_INTEGER_QUANTITY
    assert CuttingBatchUpdateIn(planned_quantity=MAX_INTEGER_QUANTITY).planned_quantity == MAX_INTEGER_QUANTITY

    with SessionLocal() as db:
        order = _production_order(db)

        created = create_production_batches(
            db,
            order.id,
            [{"planned_quantity": MAX_INTEGER_QUANTITY}],
        )
        assert len(created) == 1
        assert created[0].planned_quantity == MAX_INTEGER_QUANTITY
        db.rollback()


def test_batch_creation_rejects_overflow_before_inserting_any_batches():
    with SessionLocal() as db:
        order = _production_order(db)
        order_id = int(order.id)
        order_count_before = db.query(ProductionOrder).count() - 1
        before = db.query(ProductionBatch).filter(
            ProductionBatch.production_order_id == order_id,
        ).count()
        with pytest.raises(HTTPException) as rejected:
            create_production_batches(
                db,
                order_id,
                [
                    {"planned_quantity": 5},
                    {"planned_quantity": MAX_INTEGER_QUANTITY + 1},
                ],
            )

        assert rejected.value.status_code == 400
        assert "supported maximum" in rejected.value.detail
        db.rollback()
        assert db.query(ProductionBatch).filter(
            ProductionBatch.production_order_id == order_id,
        ).count() == before
        assert db.query(ProductionOrder).count() == order_count_before


def test_missing_order_still_precedes_invalid_batch_quantity():
    with SessionLocal() as db:
        with pytest.raises(HTTPException) as rejected:
            create_production_batches(
                db,
                0,
                [{"planned_quantity": MAX_INTEGER_QUANTITY + 1}],
            )

    assert rejected.value.status_code == 404
    assert rejected.value.detail == "Production order not found"


@pytest.mark.parametrize("quantity", [float("inf"), 1.5, True])
def test_invalid_batch_conversion_fails_as_client_error_without_writes(quantity):
    with SessionLocal() as db:
        order = _production_order(db)
        before = db.query(ProductionBatch).filter(
            ProductionBatch.production_order_id == order.id,
        ).count()
        with pytest.raises(HTTPException) as rejected:
            create_production_batches(
                db,
                order.id,
                [{"planned_quantity": quantity}],
            )

        assert rejected.value.status_code == 400
        assert "must be an integer" in rejected.value.detail
        db.rollback()
        assert db.query(ProductionBatch).filter(
            ProductionBatch.production_order_id == order.id,
        ).count() == before


def test_batch_quantity_overflow_preserves_authentication_precedence(client):
    with SessionLocal() as db:
        before = tuple(
            db.query(model).count()
            for model in (ProductionOrder, ProductionBatch, AuditLog)
        )

    response = client.post(
        "/api/production-orders",
        json={
            "production_type": "branded_stock",
            "model_id": 1,
            "batches": [{"planned_quantity": MAX_INTEGER_QUANTITY + 1}],
        },
    )

    assert response.status_code == 401, response.text
    with SessionLocal() as db:
        after = tuple(
            db.query(model).count()
            for model in (ProductionOrder, ProductionBatch, AuditLog)
        )
    assert after == before


@pytest.mark.parametrize("quantity", [MAX_INTEGER_QUANTITY + 1, 1.5, True])
def test_batch_request_models_reject_overflow_fractional_and_boolean_quantities(quantity):
    request_models = (
        ProductionBatchIn,
        SplitBatchLineIn,
        CuttingBatchUpdateIn,
    )

    for request_model in request_models:
        with pytest.raises(ValueError):
            request_model(planned_quantity=quantity)
