from uuid import uuid4

from sqlalchemy import event

from app.api.routes.production import _estimated_material_composition
from app.models import Item
from app.tests.conftest import TestSessionLocal


def test_estimated_material_composition_reads_only_composition_fields():
    marker = uuid4().hex
    composition = [
        {"name": "Cotton", "percentage": 80},
        {"name": "Polyester", "percentage": 20},
    ]
    with TestSessionLocal() as db:
        item = Item(
            sku=f"MAT-COMP-{marker}",
            name=f"Composition projection {marker}",
            category="fabric",
            unit="kg",
            composition_json=composition,
        )
        db.add(item)
        db.commit()

        statements = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            normalized = " ".join(statement.lower().split())
            if normalized.startswith("select") and " from items " in normalized:
                statements.append(normalized)

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            result = _estimated_material_composition(db, item.sku)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    assert result == [
        {"name": "Cotton", "percentage": 80.0},
        {"name": "Polyester", "percentage": 20.0},
    ]
    assert len(statements) == 1, statements
    assert "items.id" in statements[0]
    assert "items.composition_json" in statements[0]
    assert "items.name" not in statements[0]
    assert "items.default_cost" not in statements[0]
