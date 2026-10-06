from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import event, func, select

from app.api.routes.process_tracking import list_processes
from app.api.routes.super_data import list_super_data_tables
from app.db.base import Base
from app.db.session import SessionLocal
from app.models import Model, ModelBOM, ModelImage, ProductionOrder, User


@pytest.mark.parametrize("count", [1, 50, 401])
def test_process_tracking_projects_image_metadata_without_changing_precedence(count):
    marker = uuid4().hex
    with SessionLocal() as db:
        for index in range(count):
            model = Model(code=f"CTX-{marker}-{index}", name="Projection", status="approved")
            db.add(model)
            db.flush()
            db.add_all([
                ModelImage(model_id=model.id, file_url=f"/storage/model-files/{marker}-{index}.png",
                           file_name="preview.png", content_type="image/png", image_type="model",
                           is_primary=True, file_data=b"large image content" * 4096),
                ModelBOM(model_id=model.id, photo_url=f"/storage/model-files/material-{marker}-{index}.png",
                         quantity_per_piece=1, unit="kg"),
                ProductionOrder(production_no=f"CTX-{marker}-{index}", production_type="branded_stock",
                                model_id=model.id, planned_quantity=10, status="new"),
            ])
        db.commit()
    with SessionLocal() as db:
        user = db.query(User).filter(User.email == "admin@example.com").one()
        statements = []
        def capture(_conn, _cursor, statement, _parameters, _context, _many):
            statements.append(" ".join(statement.lower().split()))
        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            rows = list_processes(db, user, q=marker, page_size=500)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)
    assert len(rows) == min(count, 100)
    assert all(row["model_image_url"].startswith(f"/storage/model-files/{marker}") for row in rows)
    assert all(row["material_image_url"].startswith(f"/storage/model-files/material-{marker}") for row in rows)
    image_queries = [sql for sql in statements if " from model_images " in sql]
    assert len(image_queries) == 1
    assert all("file_data" not in sql for sql in statements)
    assert sum(" from model_bom " in sql for sql in statements) == 1
    assert not any(sql.startswith(("insert", "update", "delete")) for sql in statements)


def test_data_console_exact_counts_use_one_read_and_preserve_repair_permissions():
    with SessionLocal() as db:
        expected = {table.name: db.scalar(select(func.count()).select_from(table)) for table in Base.metadata.sorted_tables}
        statements = []
        def capture(_conn, _cursor, statement, _parameters, _context, _many):
            statements.append(statement)
        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            rows = list_super_data_tables(db, SimpleNamespace())
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)
        assert {row.name: row.row_count for row in rows} == expected
        assert len(statements) == 1
        assert statements[0].lower().count("union all") == len(expected) - 1
        assert {(row.name, column.name) for row in rows for column in row.columns if column.editable} == {("departments", "name")}
