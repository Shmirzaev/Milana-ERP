import pytest
from fastapi import HTTPException
from sqlalchemy import Column, Integer, String, create_engine
from sqlalchemy.orm import Session, declarative_base

from app.services.numbering import _next_order, _next


Base = declarative_base()


class Reference(Base):
    __tablename__ = "test_business_references"
    id = Column(Integer, primary_key=True)
    number = Column(String, unique=True)


@pytest.fixture
def reference_db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    from app.models import BusinessOrderAlias
    BusinessOrderAlias.__table__.create(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()


@pytest.mark.parametrize("prefix", ["SO", "PO", "USL", "PR", "PUR"])
def test_new_orders_have_four_digits(reference_db, prefix):
    assert _next_order(reference_db, Reference, "number", prefix) == f"{prefix}-0001"
    reference_db.add(Reference(number=f"{prefix}-0001"))
    reference_db.flush()
    assert _next_order(reference_db, Reference, "number", prefix) == f"{prefix}-0002"


def test_compact_sequence_continues_across_legacy_years_and_preserves_references(reference_db):
    existing = ["PO-2024-000202", "PO-2026-000010", "PO-0199", "PO-invalid", "PO-2026-ABC", "SO-9999"]
    reference_db.add_all([Reference(number=number) for number in existing])
    reference_db.flush()
    assert _next_order(reference_db, Reference, "number", "PO") == "PO-0203"
    assert set(value for (value,) in reference_db.query(Reference.number).all()) == set(existing)


def test_sequence_uses_numeric_order_and_never_wraps(reference_db):
    reference_db.add_all([Reference(number="PO-9998"), Reference(number="PO-900")])
    reference_db.flush()
    assert _next_order(reference_db, Reference, "number", "PO") == "PO-9999"
    reference_db.add(Reference(number="PO-9999"))
    reference_db.flush()
    assert _next_order(reference_db, Reference, "number", "PO") == "PO-0001"
    occupied = {value for (value,) in reference_db.query(Reference.number).all()}
    reference_db.add_all([Reference(number=f"PO-{number:04d}") for number in range(1, 10000)
                         if f"PO-{number:04d}" not in occupied])
    reference_db.flush()
    with pytest.raises(HTTPException) as error:
        _next_order(reference_db, Reference, "number", "PO")
    assert error.value.status_code == 409


def test_high_volume_qr_references_keep_existing_format(reference_db):
    from datetime import datetime, timezone

    year = datetime.now(timezone.utc).year
    reference_db.add(Reference(number=f"BND-{year}-010000"))
    reference_db.flush()
    assert _next(reference_db, Reference, "number", "BND") == f"BND-{year}-010001"


def test_order_search_uses_exact_collision_mapping_for_historical_years(reference_db):
    from app.core.order_reference import order_reference_contains
    from app.models import BusinessOrderAlias

    values = ["PO-0202", "PO-0001", "PO-1202", "SO-0202"]
    reference_db.add_all([Reference(number=number) for number in values])
    reference_db.add_all([
        BusinessOrderAlias(namespace="PO", entity_id=1, reference="PO-2025-000202", canonical_reference="PO-0202"),
        BusinessOrderAlias(namespace="PO", entity_id=2, reference="PO-2026-000202", canonical_reference="PO-0001"),
    ])
    reference_db.flush()
    found = reference_db.query(Reference.number).filter(order_reference_contains(Reference.number, "%po-0202%")).all()
    assert found == [("PO-0202",)]
    exact = reference_db.query(Reference.number).filter(order_reference_contains(Reference.number, "%PO-2025-000202%")).all()
    assert exact == [("PO-0202",)]
    other = reference_db.query(Reference.number).filter(order_reference_contains(Reference.number, "%PO-2026-000202%")).all()
    assert other == [("PO-0001",)]


def test_branded_planning_sequence_stops_at_four_digit_capacity():
    from app.models import BrandedPlanningOrder
    from app.services.numbering import next_branded_planning_order_no
    from app.tests.conftest import TestSessionLocal

    with TestSessionLocal() as db:
        db.add(BrandedPlanningOrder(order_no="9998", ordered_for_type="milana", ordered_for_name="Milana"))
        db.flush()
        assert next_branded_planning_order_no(db) == "9999"
        db.add(BrandedPlanningOrder(order_no="9999", ordered_for_type="milana", ordered_for_name="Milana"))
        db.flush()
        with pytest.raises(HTTPException) as error:
            next_branded_planning_order_no(db)
        assert error.value.status_code == 409
        assert "BSO" in error.value.detail
        assert not db.query(BrandedPlanningOrder).filter(BrandedPlanningOrder.order_no == "10000").first()
