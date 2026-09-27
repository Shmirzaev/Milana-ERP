import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.api.routes.cutting_passports import cutting_operator_options
from app.api.routes.inventory import list_received_stock_colors
from app.api.routes.tasks import list_tasks
from app.db.base import Base
from app.db.session import SessionLocal
from app.models import Item, StockBatch, Task, User, Warehouse


@pytest.fixture(scope="module", params=["sqlite", "postgres"])
def directory_sessions(request):
    if request.param == "sqlite":
        yield SessionLocal
        return
    raw = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw:
        pytest.skip("Requires disposable PostgreSQL")
    url = make_url(raw)
    assert url.get_backend_name() == "postgresql"
    assert url.host in {"127.0.0.1", "localhost", "::1"}
    assert not url.query
    schema = f"perf35_directories_{uuid4().hex}"
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        Base.metadata.create_all(engine)
        yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()


def _selects(db, callback):
    statements: list[tuple[str, dict]] = []

    def capture(_connection, _cursor, statement, _parameters, context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(
                (" ".join(statement.lower().split()), dict(context.execution_options))
            )

    event.listen(db.bind, "before_cursor_execute", capture)
    try:
        result = callback()
    finally:
        event.remove(db.bind, "before_cursor_execute", capture)
    return result, statements


@pytest.mark.parametrize("row_count", [1, 50, 401])
def test_task_directory_pages_in_sql_with_exact_total(directory_sessions, row_count):
    marker = uuid4().hex[:10]
    with directory_sessions() as db:
        actor = User(
            name=f"Task owner {marker}",
            email=f"perf35-task-{marker}@example.invalid",
            password_hash="unused",
            is_active=True,
        )
        db.add(actor)
        db.flush()
        rows = [
            Task(
                title=f"PERF35 {marker} {index:04d}",
                assigned_to=actor.id,
                created_by=actor.id,
                status="pending",
                priority="medium",
            )
            for index in range(row_count)
        ]
        db.add_all(rows)
        db.commit()

        page = (row_count - 1) // 50 + 1
        result, statements = _selects(
            db,
            lambda: list_tasks(
                db,
                actor,
                scope="mine",
                page=page,
                page_size=50,
            ),
        )

        task_reads = [sql for sql, _options in statements if " from tasks " in sql]
        assert len(task_reads) == 2
        assert sum(" limit " in sql for sql in task_reads) == 1
        assert result["total"] == row_count
        assert len(result["rows"]) == (50 if row_count == 50 else 1)
        assert result["has_more"] is False
        expected_ids = [row.id for row in sorted(rows, key=lambda row: row.id, reverse=True)]
        start = (page - 1) * 50
        assert [row.id for row in result["rows"]] == expected_ids[start:start + 50]


@pytest.mark.parametrize("row_count", [1, 50, 401])
def test_cutting_operator_pages_stream_policy_rows_with_bounded_response(
    directory_sessions,
    row_count,
):
    marker = uuid4().hex[:10]
    with directory_sessions() as db:
        users = [
            User(
                name=f"PERF35 {marker} operator {index:04d}",
                email=f"perf35-operator-{marker}-{index}@example.invalid",
                password_hash="unused",
                factory_code="MIL",
                is_active=True,
            )
            for index in range(row_count)
        ]
        db.add_all(users)
        db.commit()
        current = SimpleNamespace(
            factory_code="MIL",
            session_factory_code="MIL",
            role=None,
            department=None,
            extra_permissions=[],
            access_policy=None,
        )
        page = (row_count - 1) // 50 + 1
        result, statements = _selects(
            db,
            lambda: cutting_operator_options(
                db,
                current,
                q=marker,
                page=page,
                page_size=50,
            ),
        )

        user_reads = [
            (sql, options)
            for sql, options in statements
            if " from users " in sql and "users.is_active" in sql
        ]
        assert len(user_reads) == 1
        selected = user_reads[0][0].split(" from users", 1)[0]
        assert "users.password_hash" not in selected
        assert "users.email" not in selected
        assert user_reads[0][1].get("yield_per") == 400
        assert user_reads[0][1].get("stream_results") is True
        assert result["total"] == row_count
        assert len(result["rows"]) == (50 if row_count == 50 else 1)
        assert result["has_more"] is False


@pytest.mark.parametrize("row_count", [1, 50, 401])
def test_inventory_color_pages_group_and_page_in_sql(directory_sessions, row_count):
    marker = uuid4().hex[:10].upper()
    with directory_sessions() as db:
        item = Item(
            sku=f"PERF35-COLOR-{marker}",
            name="PERF35 color pagination",
            category="fabric",
            unit="kg",
        )
        warehouse = Warehouse(
            name=f"PERF35 color warehouse {marker}",
            type="materials",
        )
        db.add_all([item, warehouse])
        db.flush()
        batches = [
            StockBatch(
                item_id=item.id,
                batch_no=f"PERF35-COLOR-{marker}-{index:04d}",
                color=f"PERF35-{marker}-{index:04d}",
                quantity=1,
                unit="kg",
                cost_per_unit=1,
                warehouse_id=warehouse.id,
            )
            for index in range(row_count)
        ]
        db.add_all(batches)
        db.commit()
        current = SimpleNamespace(
            factory_code="MIL",
            session_factory_code="MIL",
            role=None,
            extra_permissions=[],
            access_policy=None,
        )
        page = (row_count - 1) // 50 + 1
        result, statements = _selects(
            db,
            lambda: list_received_stock_colors(
                db,
                current,
                q=f"PERF35-{marker}",
                page=page,
                page_size=50,
            ),
        )

        color_reads = [sql for sql, _options in statements if " from stock_batches " in sql]
        assert len(color_reads) == 2
        assert all("group by lower(trim(stock_batches.color))" in sql for sql in color_reads)
        assert sum(" limit " in sql for sql in color_reads) == 1
        assert result["total"] == row_count
        assert len(result["rows"]) == (50 if row_count == 50 else 1)
        assert result["has_more"] is False


def test_new_directory_pages_preserve_legacy_array_shapes(directory_sessions):
    marker = uuid4().hex[:10].upper()
    with directory_sessions() as db:
        actor = User(
            name=f"PERF35 {marker} actor",
            email=f"perf35-parity-{marker}@example.invalid",
            password_hash="unused",
            factory_code="MIL",
            is_active=True,
        )
        item = Item(
            sku=f"PERF35-PARITY-{marker}",
            name="PERF35 parity item",
            category="fabric",
            unit="kg",
        )
        warehouse = Warehouse(
            name=f"PERF35 parity warehouse {marker}",
            type="materials",
        )
        db.add_all([actor, item, warehouse])
        db.flush()
        db.add(Task(
            title=f"PERF35 parity {marker}",
            assigned_to=actor.id,
            created_by=actor.id,
            status="pending",
            priority="medium",
        ))
        db.add(StockBatch(
            item_id=item.id,
            batch_no=f"PERF35-PARITY-{marker}",
            color=f"PERF35-{marker}",
            quantity=1,
            unit="kg",
            cost_per_unit=1,
            warehouse_id=warehouse.id,
        ))
        db.commit()
        current = SimpleNamespace(
            factory_code="MIL",
            session_factory_code="MIL",
            role=None,
            department=None,
            extra_permissions=[],
            access_policy=None,
        )

        legacy_tasks = list_tasks(db, actor)
        paged_tasks = list_tasks(db, actor, page=1, page_size=50)
        assert [row.id for row in legacy_tasks] == [
            row.id for row in paged_tasks["rows"]
        ]
        legacy_operators = cutting_operator_options(db, current, q=marker)
        paged_operators = cutting_operator_options(
            db, current, q=marker, page=1, page_size=50
        )
        assert [row.id for row in legacy_operators] == [
            row.id for row in paged_operators["rows"]
        ]
        legacy_colors = list_received_stock_colors(db, current, q=marker)
        paged_colors = list_received_stock_colors(
            db, current, q=marker, page=1, page_size=50
        )
        assert legacy_colors == paged_colors["rows"]
