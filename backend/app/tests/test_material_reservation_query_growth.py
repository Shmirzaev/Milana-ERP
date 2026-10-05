import pytest
from sqlalchemy import event

from app.services import inventory
from app.tests.test_material_reservation_concurrency import _line, _stock
from app.tests.conftest import TestSessionLocal


@pytest.mark.parametrize("line_count", [1, 50, 401])
def test_material_reservation_reference_number_and_availability_reads_are_batched(line_count):
    ids = _stock(TestSessionLocal, item_count=line_count)
    lines = [_line(ids, 1, item=index, batch=index) for index in range(line_count)]
    with TestSessionLocal() as db:
        statements: list[str] = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement.lower())

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            created = inventory.create_material_reservations(
                db,
                production_order_id=ids["orders"][0],
                lines=lines,
                user_id=None,
            )
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

        assert len(created) == len(lines)
        # References, availability and the transaction-scoped number range are
        # read once; the returned collection still contains every required row.
        assert sum("from items" in sql for sql in statements) == 1
        assert sum("stock_batches.item_id" in sql and "group by" in sql for sql in statements) == 1
        assert sum("material_reservations.item_id" in sql and "group by" in sql for sql in statements) == 1
        assert sum("stock_movements.item_id" in sql for sql in statements) == 1
        number_reads = [
            sql for sql in statements
            if "material_reservations.reservation_no" in sql
            and "order by material_reservations.reservation_no desc" in sql
        ]
        assert len(number_reads) == 1
