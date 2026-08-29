from uuid import uuid4

from sqlalchemy import event


def test_inventory_search_uses_windowed_totals_and_bulk_reservations(client, auth_headers):
    from app.db import session as session_module
    from app.models import StockBatch

    marker = f"SEARCH-PERF-{uuid4().hex[:10]}"
    db = session_module.SessionLocal()
    try:
        source = db.query(StockBatch).order_by(StockBatch.id.asc()).first()
        assert source is not None
        rows = [
            StockBatch(
                item_id=source.item_id,
                batch_no=f"{marker}-{index:02d}",
                supplier_id=source.supplier_id,
                quantity=index + 1,
                unit=source.unit,
                cost_per_unit=source.cost_per_unit,
                warehouse_id=source.warehouse_id,
                qc_status="passed",
            )
            for index in range(24)
        ]
        db.add_all(rows)
        db.commit()

        def captured_get(path: str):
            statements: list[str] = []

            def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
                if statement.lstrip().upper().startswith("SELECT"):
                    statements.append(" ".join(statement.split()).lower())

            event.listen(session_module.engine, "before_cursor_execute", capture)
            try:
                response = client.get(path, headers=auth_headers)
            finally:
                event.remove(session_module.engine, "before_cursor_execute", capture)
            return response, statements

        batch_response, batch_statements = captured_get(
            f"/api/inventory/batches?q={marker}&include_total=true&page_size=50",
        )
        assert batch_response.status_code == 200, batch_response.text
        assert batch_response.json()["total"] == 24
        assert len(batch_response.json()["rows"]) == 24
        assert any("count(stock_batches.id) over" in query for query in batch_statements)
        reservation_queries = [
            query for query in batch_statements if " from material_reservations " in query
        ]
        assert len(reservation_queries) == 1, batch_statements
        assert len(batch_statements) <= 8, batch_statements

        stock_response, stock_statements = captured_get(
            f"/api/inventory/stock?q={marker}&include_total=true&page_size=50",
        )
        assert stock_response.status_code == 200, stock_response.text
        assert stock_response.json()["total"] == 1
        assert any("count(items.id) over" in query for query in stock_statements)
    finally:
        db.query(StockBatch).filter(StockBatch.batch_no.like(f"{marker}%")).delete(
            synchronize_session=False,
        )
        db.commit()
        db.close()
