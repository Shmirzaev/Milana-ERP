"""Table-level contract for the sales-order vocabulary.

`SalesOrderStatus` owns the nineteen persisted `sales_orders.status` strings.
The CHECK constraint and the column default are derived from it, so the enum,
the rendered DDL and the stored default have to stay equal to the pre-refactor
values.

The expected members and the expected CHECK text are written out as literals
here. They are the independent expectation; the enum module is only the
subject under test, so a mistake in it cannot make this test agree with
itself.

This file is table-level: it says nothing about which states a particular
business operation may use. The create operation's own input contract lives
in `test_sales_order_create_contract.py`.

The last tests here cover storage truthfulness: the columns stay annotated as
raw strings, the schema writer stores the enum's value, and a fresh or expired
read returns that plain string rather than an enum member.
"""
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateTable

from app.libs.enums.sales import SalesOrderItemSourceType, SalesOrderStatus, SalesOrderType
from app.schemas import SalesOrder, SalesOrderItem
from app.schemas.sales.sales_order_persistence import create_sales_order_item, create_sales_order_row
from app.tests.conftest import TestSessionLocal


EXPECTED_ORDER_STATUS = (
    ("DRAFT", "draft"),
    ("PENDING_SALES_APPROVAL", "pending_sales_approval"),
    ("CONFIRMED", "confirmed"),
    ("PLANNING", "planning"),
    ("PLANNING_APPROVED", "planning_approved"),
    ("IN_PRODUCTION", "in_production"),
    ("PRODUCTION", "production"),
    ("CUTTING", "cutting"),
    ("PRINTING", "printing"),
    ("SEWING", "sewing"),
    ("PACKAGING", "packaging"),
    ("STORAGE", "storage"),
    ("READY_TO_SHIP", "ready_to_ship"),
    ("READY", "ready"),
    ("RESERVED", "reserved"),
    ("SHIPPED", "shipped"),
    ("DELIVERED", "delivered"),
    ("CLOSED", "closed"),
    ("CANCELLED", "cancelled"),
)
EXPECTED_ORDER_TYPE = (
    ("CLIENT_ORDER", "client_order"),
    ("BRANDED_STOCK_SALE", "branded_stock_sale"),
    ("BRANDED_STOCK", "branded_stock"),
)
EXPECTED_ITEM_SOURCE_TYPE = (
    ("PRODUCE_NEW", "produce_new"),
    ("FROM_STOCK", "from_stock"),
    ("FIRST_GRADE", "first_grade"),
)
EXPECTED_STATUS_CHECK = (
    "status IN ('draft', 'pending_sales_approval', 'confirmed', 'planning', 'planning_approved', "
    "'in_production', 'production', 'cutting', 'printing', 'sewing', 'packaging', 'storage', "
    "'ready_to_ship', 'ready', 'reserved', 'shipped', 'delivered', 'closed', 'cancelled')"
)


def _status_constraint():
    for constraint in SalesOrder.__table__.constraints:
        if constraint.name == "ck_sales_orders_status":
            return constraint
    raise AssertionError("ck_sales_orders_status is not defined on the sales_orders table")


def test_sales_order_status_enum_matches_the_persisted_vocabulary():
    assert [(status.name, status.value) for status in SalesOrderStatus] == list(EXPECTED_ORDER_STATUS)


def test_sales_order_type_enum_matches_the_written_order_types():
    assert [(value.name, value.value) for value in SalesOrderType] == list(EXPECTED_ORDER_TYPE)


def test_sales_order_item_source_type_enum_matches_the_written_source_types():
    assert [(value.name, value.value) for value in SalesOrderItemSourceType] == list(EXPECTED_ITEM_SOURCE_TYPE)


def test_status_check_text_is_the_pre_refactor_ddl():
    assert str(_status_constraint().sqltext) == EXPECTED_STATUS_CHECK


def test_status_check_is_rendered_into_the_sales_orders_ddl():
    ddl = str(CreateTable(SalesOrder.__table__).compile(dialect=postgresql.dialect()))
    assert f"CHECK ({EXPECTED_STATUS_CHECK})" in ddl


def test_sales_order_without_an_explicit_status_persists_draft():
    assert SalesOrder.__table__.c.status.default.arg == "draft"
    with TestSessionLocal() as db:
        order = SalesOrder(order_no=f"RF011-{uuid4().hex}", total_amount=0)
        db.add(order)
        db.commit()
        order_id = int(order.id)
    with TestSessionLocal() as db:
        assert db.get(SalesOrder, order_id).status == "draft"


@pytest.mark.parametrize("status", [value for _, value in EXPECTED_ORDER_STATUS])
def test_database_accepts_every_persisted_status(status):
    with TestSessionLocal() as db:
        order = SalesOrder(order_no=f"RF011-{uuid4().hex}", status=status, total_amount=0)
        db.add(order)
        db.commit()
        order_id = int(order.id)
    with TestSessionLocal() as db:
        assert db.get(SalesOrder, order_id).status == status


def test_database_rejects_a_status_outside_the_enum():
    with TestSessionLocal() as db:
        db.add(SalesOrder(order_no=f"RF011-{uuid4().hex}", status="not_an_order_status", total_amount=0))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_the_mapped_columns_stay_annotated_as_raw_strings():
    assert SalesOrder.__table__.c.status.type.python_type is str
    assert SalesOrder.__table__.c.order_type.type.python_type is str
    assert SalesOrderItem.__table__.c.source_type.type.python_type is str


def _write_one_order(db, *, order_type=SalesOrderType.CLIENT_ORDER, status=SalesOrderStatus.DRAFT):
    return create_sales_order_row(
        db,
        order_no=f"RF011-{uuid4().hex}",
        customer_id=None,
        order_type=order_type,
        status=status,
        deadline=None,
        printing_instructions=None,
        printing_attachments=None,
        notes=None,
        created_by=None,
    )


def test_the_schema_writer_stores_the_raw_enum_value_in_the_column():
    with TestSessionLocal() as db:
        order = _write_one_order(db)
        db.commit()
        order_id = int(order.id)
    with TestSessionLocal() as db:
        row = db.execute(
            text("SELECT status, order_type FROM sales_orders WHERE id = :id"),
            {"id": order_id},
        ).one()
    assert row.status == "draft"
    assert row.order_type == "client_order"


def test_the_schema_writer_stores_the_raw_source_type_in_the_line_column():
    with TestSessionLocal() as db:
        model_id = db.execute(
            text("SELECT id FROM models WHERE code = :code"), {"code": "T-SHIRT-001"}
        ).scalar()
        assert model_id is not None, "the seeded database must contain the T-SHIRT-001 model"
        order = _write_one_order(db)
        line = create_sales_order_item(
            db,
            sales_order_id=int(order.id),
            model_id=int(model_id),
            brand_id=None,
            collection_id=None,
            color="white",
            size="M",
            quantity=1,
            requested_pack_count=None,
            unit_price=0,
            printing_required=False,
            source_type=SalesOrderItemSourceType.FIRST_GRADE,
            notes=None,
        )
        db.commit()
        line_id = int(line.id)
    with TestSessionLocal() as db:
        row = db.execute(
            text("SELECT source_type FROM sales_order_items WHERE id = :id"),
            {"id": line_id},
        ).one()
    assert row.source_type == "first_grade"


def test_a_fresh_session_reads_a_plain_string_not_an_enum_member():
    with TestSessionLocal() as db:
        order = _write_one_order(db)
        db.commit()
        order_id = int(order.id)
    with TestSessionLocal() as db:
        loaded = db.get(SalesOrder, order_id)
        assert type(loaded.status) is str
        assert type(loaded.order_type) is str


def test_an_expired_attribute_reloads_as_a_plain_string():
    with TestSessionLocal() as db:
        order = _write_one_order(db)
        db.commit()
        db.expire_all()
        loaded = db.get(SalesOrder, int(order.id))
        assert type(loaded.status) is str
        assert loaded.status == "draft"
