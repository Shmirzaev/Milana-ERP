"""Waste reads use the recorded valuation and never rewrite history."""

from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import func

from app.api.routes import waste
from app.db.session import SessionLocal
from app.services.finance import waste_cost, waste_income
from app.models import Item, StockBatch, Warehouse, WasteRecord


def _valued_waste() -> tuple[int, int]:
    suffix = uuid4().hex[:10]
    with SessionLocal() as db:
        item = Item(
            sku=f"WASTE-READ-{suffix}",
            name="Synthetic waste valuation material",
            category="fabric",
            unit="kg",
            default_cost=3,
        )
        warehouse = Warehouse(name=f"Waste read warehouse {suffix}", type="raw_material")
        db.add_all([item, warehouse])
        db.flush()
        batch = StockBatch(
            item_id=item.id,
            batch_no=f"WASTE-READ-{suffix}",
            quantity=100,
            unit="kg",
            cost_per_unit=4,
            warehouse_id=warehouse.id,
        )
        db.add(batch)
        db.flush()
        record = WasteRecord(
            item_id=item.id,
            batch_id=batch.id,
            waste_type="Synthetic historical offcuts",
            quantity=2.5,
            unit="kg",
            sellable=True,
            estimated_value=7.25,
            status="sold",
        )
        db.add(record)
        db.commit()
        return record.id, batch.id


def _stored_value(record_id: int) -> float:
    with SessionLocal() as db:
        return float(db.get(WasteRecord, record_id).estimated_value)


def test_list_uses_recorded_value_without_dirtying_or_committing_session():
    record_id, batch_id = _valued_waste()
    with SessionLocal() as db:
        db.get(StockBatch, batch_id).cost_per_unit = 9
        db.commit()

    with SessionLocal() as db, patch.object(db, "commit", wraps=db.commit) as commit:
        rows = waste.list_waste(db, object(), status="sold", sellable=True)
        row = next(result for result in rows if result.id == record_id)

        assert float(row.estimated_value) == 7.25
        assert list(db.dirty) == []
        commit.assert_not_called()

    assert _stored_value(record_id) == 7.25


def test_list_get_keeps_filters_authorization_and_history_when_rate_changes(client, auth_headers):
    record_id, batch_id = _valued_waste()

    assert client.get("/api/waste?status=sold&sellable=true").status_code == 401

    first = client.get("/api/waste?status=sold&sellable=true", headers=auth_headers)
    assert first.status_code == 200, first.text
    first_row = next(row for row in first.json() if row["id"] == record_id)
    assert first_row["estimated_value"] == 7.25
    assert first_row["status"] == "sold" and first_row["sellable"] is True
    assert _stored_value(record_id) == 7.25

    with SessionLocal() as db:
        db.get(StockBatch, batch_id).cost_per_unit = 11
        db.commit()

    second = client.get("/api/waste?status=sold&sellable=true", headers=auth_headers)
    assert second.status_code == 200, second.text
    second_row = next(row for row in second.json() if row["id"] == record_id)
    assert second_row["estimated_value"] == 7.25
    assert _stored_value(record_id) == 7.25

    assert all(row["status"] == "sold" and row["sellable"] is True for row in second.json())


def test_related_waste_summaries_keep_authorization_and_persisted_totals(client, auth_headers):
    record_id, batch_id = _valued_waste()
    with SessionLocal() as db:
        db.get(StockBatch, batch_id).cost_per_unit = 11
        db.commit()
        expected_cost = float(
            db.query(func.coalesce(func.sum(WasteRecord.estimated_value), 0))
            .filter(WasteRecord.sellable.is_(False))
            .scalar()
        )
        expected_sold_quantity = float(
            db.query(func.coalesce(func.sum(WasteRecord.quantity), 0))
            .filter(WasteRecord.status == "sold")
            .scalar()
        )

    projected = client.get("/api/waste?status=sold&sellable=true", headers=auth_headers)
    assert projected.status_code == 200, projected.text
    assert next(row for row in projected.json() if row["id"] == record_id)["estimated_value"] == 7.25

    for path in ("/api/finance/waste-report", "/api/dashboard/waste"):
        assert client.get(path).status_code == 401

    report = client.get("/api/finance/waste-report", headers=auth_headers)
    assert report.status_code == 200, report.text
    assert report.json() == {"cost": None, "income": None, "currency": None}
    with SessionLocal() as db:
        assert waste_cost(db) == expected_cost
        assert waste_income(db) == 0

    dashboard = client.get("/api/dashboard/waste", headers=auth_headers)
    assert dashboard.status_code == 200, dashboard.text
    assert dashboard.json()["by_status"]["sold"] == expected_sold_quantity
    assert _stored_value(record_id) == 7.25


def test_list_marks_missing_recorded_cost_unavailable(client, auth_headers):
    with SessionLocal() as db:
        record = WasteRecord(
            waste_type="Historical cost unknown",
            quantity=2,
            unit="kg",
            sellable=True,
            estimated_value=0,
            status="received_by_waste_department",
        )
        db.add(record)
        db.commit()
        record_id = int(record.id)

    response = client.get("/api/waste?status=received_by_waste_department&sellable=true", headers=auth_headers)
    assert response.status_code == 200, response.text
    row = next(row for row in response.json() if row["id"] == record_id)
    assert row["estimated_value"] is None
