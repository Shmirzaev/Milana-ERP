"""Real PostgreSQL checks for truthful list quantities; isolated review DB only."""
import os
from contextlib import contextmanager
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.schemas import Customer, Model, SalesOrder, SalesOrderItem, AuditLog
from app.models.sales import orders_service


@pytest.fixture(scope="module")
def sessions():
    raw = os.environ.get("SALES_LIST_REVIEW_URL")
    if not raw:
        pytest.skip("Set SALES_LIST_REVIEW_URL to an owned disposable review database")
    url = make_url(raw)
    assert url.host in {"localhost", "127.0.0.1"} and url.database.startswith("review_sales_list_")
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    yield engine, sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def case(sessions):
    engine, factory = sessions
    with engine.begin() as conn:
        conn.exec_driver_sql("TRUNCATE sales_orders, customers, models, audit_logs RESTART IDENTITY CASCADE")
    with factory.begin() as db:
        customer = Customer(name="Quantity customer")
        model = Model(code="QTY-001", name="Quantity model", status="approved")
        db.add_all([customer, model]); db.flush()
        return engine, factory, customer.id, model.id


def seed(case, quantities, *, packs=None, status="draft", kind="client_order", number=None):
    _, factory, customer, model = case
    with factory.begin() as db:
        order = SalesOrder(order_no=number or f"SO-TEST-{db.query(SalesOrder).count()+1}",
            customer_id=customer, order_type=kind, status=status, total_amount=42,
            created_at=datetime(2026,10,26,12,tzinfo=timezone.utc))
        db.add(order); db.flush()
        for qty in quantities:
            db.add(SalesOrderItem(sales_order_id=order.id, model_id=model, color="white",size="M",
                quantity=qty, requested_pack_count=packs, unit_price=7,source_type="from_stock" if packs else "produce_new"))
        return order.id


def test_two_six_empty_and_pack_piece_semantics(case):
    _, factory, _, _ = case
    expected = {seed(case,[2],number="SO-0004"):2, seed(case,[2,4],number="SO-0005"):6,
        seed(case,[]):0, seed(case,[0],packs=4,kind="branded_stock_sale"):0,
        seed(case,[13],packs=2,kind="branded_stock_sale"):13}
    with factory() as db:
        page = orders_service.list_sales_orders(db,include_total=True)
        assert {r['id']:r['total_quantity'] for r in page['rows']} == expected
        assert page['total']==5
        assert all(r['total_amount']==42 and r['customer_name']=='Quantity customer' for r in page['rows'])
        # The separate detail contract is unchanged; it still supplies its items.
        detail=orders_service._serialize_sales_order(db,db.get(SalesOrder,min(expected)),include_items=True)
        assert 'total_quantity' not in detail and detail['items'][0]['quantity']==2


def test_legacy_envelope_pagination_filters_and_route(case):
    _, factory, customer, _ = case
    ids=[seed(case,[2],status="draft"),seed(case,[6],status="confirmed"),seed(case,[0],packs=2,kind="branded_stock_sale")]
    with factory() as db:
        legacy=orders_service.list_sales_orders(db,page=2,page_size=1)
        assert isinstance(legacy,list) and legacy[0]['id']==ids[1] and legacy[0]['total_quantity']==6
        from app.api.routes.sales import list_sales_orders
        page=list_sales_orders(db,None,status="confirmed",order_type="client_order",customer_id=customer,
            q="QTY-001",created_from=date(2026,10,26),created_to=date(2026,10,26),include_total=True,page_size=1)
        assert page['total']==1 and page['rows'][0]['id']==ids[1] and page['rows'][0]['total_quantity']==6
        assert orders_service.list_sales_orders(db,q="nonexistent",include_total=True)['rows']==[]
        assert orders_service.list_sales_orders(db,created_to=date(2026,10,25))==[]


@contextmanager
def capture(engine):
    statements=[]
    def hook(conn,cursor,statement,parameters,context,executemany):
        statements.append((statement,parameters,cursor.rowcount))
    event.listen(engine,'after_cursor_execute',hook)
    try: yield statements
    finally: event.remove(engine,'after_cursor_execute',hook)


def test_grouped_page_bounded_query_and_no_item_hydration(case):
    engine,factory,_,_=case
    for i in range(4): seed(case,[i+1])
    measurements=[]
    loaded=[]
    def item_load(row,ctx): loaded.append(row.id)
    event.listen(SalesOrderItem,'load',item_load)
    try:
        for size in [4,20]:
            if size==20:
                for i in range(24): seed(case,[2,4])
            with factory() as db, capture(engine) as sql:
                page=orders_service.list_sales_orders(db,include_total=True,page=1,page_size=size)
            assert len(page['rows'])==size
            aggregate=[x for x in sql if 'sum(sales_order_items.quantity)' in x[0].lower()]
            assert len(aggregate)==1
            statement,params,count=aggregate[0]
            assert 'GROUP BY sales_order_items.sales_order_id' in statement and ' IN (' in statement
            assert set(params.values())=={r['id'] for r in page['rows']}
            assert count<=size
            assert not any(x[0].lstrip().upper().startswith(('INSERT','UPDATE','DELETE')) for x in sql)
            measurements.append(len(sql))
        assert measurements[0]==measurements[1] and measurements[1]<=4
        assert loaded==[]
        with factory() as db,capture(engine) as sql:
            assert orders_service.list_sales_orders(db,q='absent')==[]
        assert not any('sum(sales_order_items.quantity)' in x[0].lower() for x in sql)
    finally: event.remove(SalesOrderItem,'load',item_load)


def test_list_preserves_caller_pending_work_without_commit_or_flush(case):
    engine,factory,_,_=case
    seed(case,[2])
    with factory() as db:
        pending=Customer(name='Not flushed');db.add(pending)
        with capture(engine) as sql:
            result=orders_service.list_sales_orders(db,include_total=True)
        assert result['rows'][0]['total_quantity']==2 and pending.id is None
        assert pending in db.new and db.in_transaction()
        assert all(not x[0].lstrip().upper().startswith(('INSERT','UPDATE','DELETE','COMMIT')) for x in sql)
        db.rollback()
    with factory() as db:
        assert db.query(Customer).count()==1 and db.query(AuditLog).count()==0


def test_list_dto_has_required_integer_total_without_changing_detail():
    from app.libs.dto.sales.sales_order_output import SalesOrderListRow, SalesOrderOut, SalesOrderDetail
    from app.libs.enums.sales import SalesOrderStatus
    assert SalesOrderListRow.model_fields['total_quantity'].annotation is int
    assert SalesOrderListRow.model_fields['total_quantity'].is_required()
    assert SalesOrderListRow.model_fields['status'].annotation is SalesOrderStatus
    assert 'total_quantity' not in SalesOrderOut.model_fields
    assert 'total_quantity' not in SalesOrderDetail.model_fields
