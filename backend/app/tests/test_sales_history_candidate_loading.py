from datetime import date, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes import sales as sales_routes
from app.models import Customer, Model, ProductionBatch, ProductionOrder, SalesOrder
from app.tests.conftest import TestSessionLocal


def _history_candidates(count):
    marker = uuid4().hex[:8]
    with TestSessionLocal() as db:
        customer = Customer(name=f"History {marker}")
        model = Model(code=f"HIST-{marker}", name="History model")
        db.add_all([customer, model])
        db.flush()
        expected = []
        for index in range(count):
            created = datetime(2088, 1, 1) + timedelta(minutes=index)
            sale = SalesOrder(order_no=f"HS-{marker}-{index}", customer_id=customer.id,
                              status="draft", created_at=created)
            production = ProductionOrder(production_no=f"HP-{marker}-{index}",
                                         production_type="branded_stock", model_id=model.id,
                                         planned_quantity=1, status="draft", created_at=created)
            db.add_all([sale, production])
            db.flush()
            db.add(ProductionBatch(production_order_id=production.id, batch_no=f"HB-{marker}-{index}",
                                   batch_index=1, planned_quantity=1))
            expected.extend([(created, "sales", sale.id), (created, "production", production.id)])
        db.commit()
        customer_id = customer.id
    # Existing stable sort puts sales first on identical timestamp/id keys.
    expected.sort(key=lambda row: (row[0].isoformat(), row[2]), reverse=True)
    return expected, customer_id


@pytest.mark.parametrize("count", [1, 50, 401])
def test_history_hydrates_only_page_candidates(monkeypatch, count):
    expected, _ = _history_candidates(count)
    monkeypatch.setattr(sales_routes, "_sales_order_history",
                        lambda db, entity, **kw: {"kind": "sales", "id": entity.id})
    monkeypatch.setattr(sales_routes, "_stock_production_history",
                        lambda db, entity, **kw: {"kind": "production", "id": entity.id})
    loaded = []
    def record_loaded(session, instance):
        if isinstance(instance, (SalesOrder, ProductionOrder, ProductionBatch)):
            loaded.append(instance)
    with TestSessionLocal() as db:
        event.listen(db, "loaded_as_persistent", record_loaded)
        result = sales_routes.list_sales_order_history(
            db, None, page=1, page_size=10, include_total=True, created_from=date(2088, 1, 1),
        )
    selected = expected[:10]
    assert result == {"rows": [{"kind": kind, "id": row_id} for _, kind, row_id in selected],
                      "total": count * 2, "page": 1, "page_size": 10}
    entities = [row for row in loaded if isinstance(row, (SalesOrder, ProductionOrder))]
    children = [row for row in loaded if isinstance(row, ProductionBatch)]
    assert len(entities) == len(selected)
    assert len(children) == sum(kind == "production" for _, kind, _ in selected)


def test_history_candidate_paging_filters_and_empty_pages(monkeypatch):
    expected, customer_id = _history_candidates(12)
    monkeypatch.setattr(sales_routes, "_sales_order_history",
                        lambda db, entity, **kw: {"kind": "sales", "id": entity.id})
    monkeypatch.setattr(sales_routes, "_stock_production_history",
                        lambda db, entity, **kw: {"kind": "production", "id": entity.id})
    with TestSessionLocal() as db:
        rows = sales_routes.list_sales_order_history(db, None, page=2, page_size=3)
        assert rows == [{"kind": kind, "id": row_id} for _, kind, row_id in expected[3:6]]
        selected = sales_routes.list_sales_order_history(db, None, customer_id=customer_id,
                                                        status="draft", include_total=True)
        assert selected["total"] == 12
        assert all(row["kind"] == "sales" for row in selected["rows"])
        assert sales_routes.list_sales_order_history(db, None, q="NO-SUCH-HISTORY-ROW") == []
        assert sales_routes.list_sales_order_history(db, None, page=999) == []


def test_history_equal_timestamp_and_id_keeps_sales_before_production(monkeypatch):
    expected, _ = _history_candidates(3)
    monkeypatch.setattr(sales_routes, "_sales_order_history",
                        lambda db, entity, **kw: {"kind": "sales", "id": entity.id})
    monkeypatch.setattr(sales_routes, "_stock_production_history",
                        lambda db, entity, **kw: {"kind": "production", "id": entity.id})
    with TestSessionLocal() as db:
        for model_type, kind in ((SalesOrder, "sales"), (ProductionOrder, "production")):
            ids = [row_id for _, row_kind, row_id in expected if row_kind == kind]
            db.query(model_type).filter(model_type.id.in_(ids)).update(
                {model_type.created_at: datetime(2088, 1, 1)}, synchronize_session=False,
            )
        db.commit()
        result = sales_routes.list_sales_order_history(
            db, None, created_from=date(2088, 1, 1), page_size=200,
        )
    ordered = sorted(expected, key=lambda row: (-row[2], row[1] != "sales"))
    assert result == [{"kind": kind, "id": row_id} for _, kind, row_id in ordered]
