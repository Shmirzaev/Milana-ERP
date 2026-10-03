"""DB08 — the production-order quantity is an integer end to end.

Guards the alignment between the ORM column, the Pydantic request/response
schemas and the read path for the order quantity. A pure type-alignment check,
so the ORM-only SQLite schema built by ``conftest`` is sufficient; no
concurrency or locking claim is made here.
"""

from __future__ import annotations

from typing import Union, get_args, get_origin

import pytest
from pydantic import ValidationError
from sqlalchemy import Integer

from app.models.production import ProductionBatch, ProductionOrder
from app.models.sales import SalesOrderItem
from app.schemas.production import ProductionBatchIn, ProductionOrderIn, ProductionOrderOut
from app.schemas.sales import SalesOrderItemIn
from app.tests.conftest import TestSessionLocal


def _is_integral(annotation) -> bool:
    """True for ``int`` and for ``Optional[int]``/``int | None``."""
    if annotation is int:
        return True
    if get_origin(annotation) is Union:
        return all(arg is type(None) or _is_integral(arg) for arg in get_args(annotation))
    return False


QUANTITY_COLUMNS = [
    (ProductionOrder, "planned_quantity"),
    (ProductionBatch, "planned_quantity"),
    (SalesOrderItem, "quantity"),
]

QUANTITY_FIELDS = [
    (ProductionOrderIn, "planned_quantity"),
    (ProductionBatchIn, "planned_quantity"),
    (SalesOrderItemIn, "quantity"),
]


@pytest.mark.parametrize("model, column", QUANTITY_COLUMNS, ids=lambda v: getattr(v, "__name__", v))
def test_quantity_column_is_integer(model, column):
    column_type = model.__table__.columns[column].type
    assert isinstance(column_type, Integer), (
        f"{model.__tablename__}.{column} must be INTEGER, got {column_type!r}"
    )


@pytest.mark.parametrize("schema, field", QUANTITY_FIELDS, ids=lambda v: getattr(v, "__name__", v))
def test_quantity_schema_field_is_integral(schema, field):
    annotation = schema.model_fields[field].annotation
    assert _is_integral(annotation), (
        f"{schema.__name__}.{field} must be an integer type, got {annotation!r}"
    )


def test_fractional_production_quantity_is_rejected():
    """A fractional garment quantity is not a valid request."""
    with pytest.raises(ValidationError):
        ProductionOrderIn(production_type="client_order", model_id=1, planned_quantity=12.5)

    with pytest.raises(ValidationError):
        ProductionBatchIn(batch_no="DB08-B", planned_quantity=12.5)

    with pytest.raises(ValidationError):
        SalesOrderItemIn(model_id=1, color="white", size="M", quantity=12.5)


def test_integral_production_quantity_is_accepted():
    order = ProductionOrderIn(production_type="client_order", model_id=1, planned_quantity=12)
    assert order.planned_quantity == 12
    assert isinstance(order.planned_quantity, int)


def test_read_path_returns_int():
    """A stored quantity is read back as an int, not a float."""
    with TestSessionLocal() as db:
        order = ProductionOrder(
            production_no="DB08-INT-1",
            production_type="client_order",
            model_id=1,
            planned_quantity=12,
        )
        db.add(order)
        db.commit()
        db.refresh(order)

        assert isinstance(order.planned_quantity, int)
        assert order.planned_quantity == 12

        payload = ProductionOrderOut.model_validate(order)
        assert payload.planned_quantity == 12
        assert isinstance(payload.planned_quantity, int)
