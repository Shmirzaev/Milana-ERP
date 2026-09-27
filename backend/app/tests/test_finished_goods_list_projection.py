from uuid import uuid4

from sqlalchemy import event

from app.models import Brand, FinishedGoodsStock, Model
from app.tests.conftest import TestSessionLocal, test_engine


def test_finished_goods_lists_project_stock_payload_columns_without_deferred_reads(
    client, auth_headers
):
    marker = uuid4().hex[:10]
    with TestSessionLocal() as db:
        model = Model(
            code=f"FG-PROJ-{marker}",
            name=f"Projection model {marker}",
            status="approved",
        )
        brand = Brand(name=f"Projection brand {marker}", is_active=True)
        db.add_all([model, brand])
        db.flush()
        stock = FinishedGoodsStock(
            model_id=model.id,
            brand_id=brand.id,
            color="Navy",
            size="M",
            quantity=2,
            available_qty=2,
            reserved_qty=0,
            sold_qty=0,
            cost_per_piece=12.5,
            selling_price=20,
            status="available",
        )
        db.add(stock)
        db.commit()
        stock_id, brand_id = stock.id, brand.id

    statements: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(" ".join(statement.lower().split()))

    event.listen(test_engine, "before_cursor_execute", capture)
    try:
        regular = client.get(
            "/api/finished-goods",
            params={"brand_id": brand_id, "page": 1, "page_size": 10},
            headers=auth_headers,
        )
        branded = client.get(
            "/api/finished-goods/branded-stock",
            params={"page": 1, "page_size": 10},
            headers=auth_headers,
        )
    finally:
        event.remove(test_engine, "before_cursor_execute", capture)

    assert regular.status_code == branded.status_code == 200
    assert regular.json()["rows"][0]["id"] == stock_id
    assert branded.json()["rows"][0]["id"] == stock_id

    stock_reads = [statement for statement in statements if " from finished_goods_stock " in statement]
    assert len(stock_reads) == 4, statements  # Two counts and two row reads; no deferred columns.
    row_reads = [statement for statement in stock_reads if " limit " in statement]
    assert len(row_reads) == 2
    for statement in row_reads:
        selected_columns = statement.split(" from finished_goods_stock", 1)[0]
        for unrelated in ("finished_goods_stock.created_at", "finished_goods_stock.updated_at"):
            assert unrelated not in selected_columns
