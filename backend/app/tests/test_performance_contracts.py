from sqlalchemy import event

from app.db import session as session_module
from app.db.session import SessionLocal
from app.models import Brand, FinishedGoodsStock, Model


def _captured_statements(call):
    statements: list[str] = []

    def before_cursor_execute(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(str(statement).strip())

    event.listen(session_module.engine, "before_cursor_execute", before_cursor_execute)
    try:
        response = call()
    finally:
        event.remove(session_module.engine, "before_cursor_execute", before_cursor_execute)
    return response, statements


def test_finished_goods_list_has_bounded_query_count(client, auth_headers):
    response, statements = _captured_statements(
        lambda: client.get("/api/finished-goods", headers=auth_headers),
    )
    assert response.status_code == 200, response.text
    selects = [statement for statement in statements if statement.upper().startswith("SELECT")]
    assert len(selects) <= 4, selects


def test_branded_stock_get_is_read_only_and_bounded(client, auth_headers):
    response, statements = _captured_statements(
        lambda: client.get("/api/finished-goods/branded-stock", headers=auth_headers),
    )
    assert response.status_code == 200, response.text
    mutations = [
        statement
        for statement in statements
        if statement.upper().startswith(("UPDATE", "INSERT", "DELETE"))
    ]
    selects = [statement for statement in statements if statement.upper().startswith("SELECT")]
    assert mutations == []
    assert len(selects) <= 4, selects


def test_large_json_responses_are_compressed(client, auth_headers):
    response = client.get(
        "/api/finished-goods",
        headers={**auth_headers, "Accept-Encoding": "gzip"},
    )
    assert response.status_code == 200, response.text
    if len(response.content) >= 1024:
        assert response.headers.get("content-encoding") == "gzip"
        assert "Accept-Encoding" in response.headers.get("vary", "")


def test_notification_and_task_summaries_return_counts(client, auth_headers):
    notification_response = client.get("/api/notifications/summary?limit=10", headers=auth_headers)
    assert notification_response.status_code == 200, notification_response.text
    notification_body = notification_response.json()
    assert isinstance(notification_body["count"], int)
    assert isinstance(notification_body["rows"], list)
    assert len(notification_body["rows"]) <= 10

    task_response = client.get("/api/tasks/open-count", headers=auth_headers)
    assert task_response.status_code == 200, task_response.text
    assert isinstance(task_response.json()["count"], int)


def test_branded_order_create_does_not_scan_unrelated_legacy_stock(client, auth_headers):
    db = SessionLocal()
    try:
        target_model = db.query(Model).filter(Model.code == "T-SHIRT-001").one()
        brand = db.query(Brand).filter(Brand.name == "Urban Co.").one()
        unrelated_model = Model(
            code="PERF-UNRELATED-STOCK",
            name="Unrelated performance stock",
            status="approved",
        )
        db.add(unrelated_model)
        db.flush()
        db.add_all(
            [
                FinishedGoodsStock(
                    model_id=unrelated_model.id,
                    color="mixed",
                    size="pack60",
                    quantity=60,
                    available_qty=60,
                    reserved_qty=0,
                    sold_qty=0,
                    status="available",
                )
                for _ in range(250)
            ]
        )
        db.add(
            FinishedGoodsStock(
                model_id=target_model.id,
                brand_id=brand.id,
                color="mixed",
                size="pack60",
                quantity=60,
                available_qty=60,
                reserved_qty=0,
                sold_qty=0,
                status="available",
            )
        )
        db.commit()
        target_model_id = int(target_model.id)
        brand_id = int(brand.id)
    finally:
        db.close()

    response, statements = _captured_statements(
        lambda: client.post(
            "/api/sales-orders",
            json={
                "order_type": "branded_stock_sale",
                "items": [
                    {
                        "model_id": target_model_id,
                        "brand_id": brand_id,
                        "color": "mixed",
                        "size": "pack60",
                        "quantity": 60,
                        "unit_price": 12,
                    }
                ],
            },
            headers=auth_headers,
        )
    )

    assert response.status_code == 201, response.text
    selects = [statement for statement in statements if statement.upper().startswith("SELECT")]
    assert len(selects) <= 30, selects
