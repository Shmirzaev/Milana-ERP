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
    with pytest.raises(HTTPException) as error:
        _next_order(reference_db, Reference, "number", "PO")
    assert error.value.status_code == 409


def test_high_volume_qr_references_keep_existing_format(reference_db):
    from datetime import datetime, timezone

    year = datetime.now(timezone.utc).year
    reference_db.add(Reference(number=f"BND-{year}-010000"))
    reference_db.flush()
    assert _next(reference_db, Reference, "number", "BND") == f"BND-{year}-010001"


def test_compact_order_search_finds_all_legacy_years_without_cross_order_matches(reference_db):
    from app.core.order_reference import order_reference_contains

    values = ["PO-2025-000202", "PO-2026-000202", "PO-0202", "PO-2026-001202", "SO-2026-000202"]
    reference_db.add_all([Reference(number=number) for number in values])
    reference_db.flush()
    found = reference_db.query(Reference.number).filter(order_reference_contains(Reference.number, "%po-0202%")).all()
    assert {value for (value,) in found} == set(values[:3])
    exact = reference_db.query(Reference.number).filter(order_reference_contains(Reference.number, "%PO-2025-000202%")).all()
    assert exact == [("PO-2025-000202",)]
