from types import SimpleNamespace as Row

from app.models import planning_service as planning


def test_requirement_aggregation_preserves_matching_order_and_legacy_rows(monkeypatch):
    item = Row(sku="FAB-1", name="Fabric", composition_json=[
        {"name": " Cotton ", "percentage": "80"},
        {"name": "Polyester", "percentage": "bad"},
        {"name": " "}, "invalid",
    ])
    boms = {7: [
        Row(item_id=4, item=item, size=None, color=None, quantity_per_piece=0.5, unit="kg"),
        Row(item_id=4, item=item, size="M", color="blue", quantity_per_piece=0.25, unit="m"),
        Row(item_id=None, item=None, size=None, color="red", quantity_per_piece=1, unit="piece"),
    ]}
    monkeypatch.setattr(planning, "_bom_by_model", lambda db, ids: boms)
    monkeypatch.setattr(planning, "_available_stock_for_items", lambda db, ids: {4: 2.0, None: 0.0})
    rows = planning._requirements_from_lines(None, [
        Row(model_id=7, size="M", color="blue", quantity=4),
        Row(model_id=7, size="S", color="red", quantity=2),
    ])
    assert rows == [
        {"item_id": 4, "sku": "FAB-1", "name": "Fabric", "composition": [
            {"name": "Cotton", "percentage": 80.0},
            {"name": "Polyester", "percentage": 0.0},
        ], "unit": "kg", "required_quantity": 4.0, "available_quantity": 2.0, "shortage": 2.0},
        {"item_id": None, "sku": "", "name": "", "composition": [], "unit": "piece",
         "required_quantity": 2.0, "available_quantity": 0.0, "shortage": 2.0},
    ]


def test_missing_sales_order_returns_empty_requirements():
    class MissingOrderSession:
        def get(self, model, key):
            return None

    assert planning.material_requirements_for_sales_order(MissingOrderSession(), 999) == []
