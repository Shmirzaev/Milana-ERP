import pytest
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


def test_sequence_expands_after_9999_without_recycling_or_alias_collisions(reference_db):
    from app.models import BusinessOrderAlias

    reference_db.add_all([Reference(number="PO-9998"), Reference(number="PO-900")])
    reference_db.flush()
    assert _next_order(reference_db, Reference, "number", "PO") == "PO-9999"
    reference_db.add(Reference(number="PO-9999"))
    reference_db.add(BusinessOrderAlias(
        namespace="PO",
        entity_id=42,
        reference="PO-10000",
        canonical_reference="PO-0202",
    ))
    reference_db.flush()
    assert _next_order(reference_db, Reference, "number", "PO") == "PO-10001"


def test_high_volume_qr_references_keep_existing_format(reference_db):
    from datetime import datetime, timezone

    year = datetime.now(timezone.utc).year
    reference_db.add(Reference(number=f"BND-{year}-010000"))
    reference_db.flush()
    assert _next(reference_db, Reference, "number", "BND") == f"BND-{year}-010001"


def test_five_digit_standalone_production_reference_resolves_as_public_order():
    from app.core.order_reference import canonical_order_reference
    from app.models import Model, ProductionOrder
    from app.tests.conftest import TestSessionLocal

    with TestSessionLocal() as db:
        model = Model(code="DB07-FIVE-DIGIT", name="Five digit model", status="approved")
        db.add(model)
        db.flush()
        order = ProductionOrder(
            production_no="PO-10000",
            production_type="client_order",
            model_id=model.id,
            planned_quantity=1,
        )
        db.add(order)
        db.commit()
        assert canonical_order_reference(db, "SO", "PO-10000") == "PO-10000"


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


def test_branded_planning_sequence_expands_after_four_digit_minimum():
    from app.models import BrandedPlanningOrder
    from app.services.numbering import next_branded_planning_order_no
    from app.tests.conftest import TestSessionLocal

    with TestSessionLocal() as db:
        db.add(BrandedPlanningOrder(order_no="9998", ordered_for_type="milana", ordered_for_name="Milana"))
        db.flush()
        assert next_branded_planning_order_no(db) == "9999"
        db.add(BrandedPlanningOrder(order_no="9999", ordered_for_type="milana", ordered_for_name="Milana"))
        db.flush()
        assert next_branded_planning_order_no(db) == "10000"
        db.add(BrandedPlanningOrder(order_no="10000", ordered_for_type="milana", ordered_for_name="Milana"))
        db.flush()
        assert next_branded_planning_order_no(db) == "10001"
