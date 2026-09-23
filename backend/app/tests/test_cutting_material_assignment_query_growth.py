from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.models import ProductionOrderMaterial
from app.services.cutting_material_assignment import _replacement_material_rows


def test_cutting_material_replacement_reads_only_primary_and_selected_rows():
    engine = create_engine("sqlite://")
    ProductionOrderMaterial.__table__.create(engine)
    with Session(engine) as db:
        rows = [
            ProductionOrderMaterial(
                production_order_id=10,
                stock_batch_id=1000 + index,
                estimated_quantity=1,
                unit="kg",
                position=index + 1,
            )
            for index in range(401)
        ]
        db.add_all(rows)
        db.commit()

        statements = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            selected = _replacement_material_rows(db, 10, 1250, 1399)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    assert [(row.stock_batch_id, row.position) for row in selected] == [
        (1000, 1), (1250, 251), (1399, 400),
    ]
    assert len(statements) == 1
    assert "production_order_materials.stock_batch_id in" in statements[0]
    assert "select production_order_materials.id" in statements[0]
    assert "limit ?" in statements[0]
    engine.dispose()
