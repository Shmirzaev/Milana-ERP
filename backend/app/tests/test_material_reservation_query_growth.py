from sqlalchemy import event

from app.services import inventory
from app.tests.test_material_reservation_concurrency import _line, _stock
from app.tests.conftest import TestSessionLocal


def test_material_reservation_reference_and_availability_reads_are_batched():
    ids = _stock(TestSessionLocal, item_count=50)
    lines = [_line(ids, 1, item=index, batch=index) for index in range(50)]
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
        # The per-line item, batch, movement and availability reads are now
        # set-based; numbering remains intentionally serialized per reservation.
        assert sum("from items" in sql for sql in statements) == 1
        assert sum("stock_batches.item_id" in sql and "group by" in sql for sql in statements) == 1
        assert sum("material_reservations.item_id" in sql and "group by" in sql for sql in statements) == 1
        assert sum("stock_movements.item_id" in sql for sql in statements) == 1
