"""Expose the same aggregate balance enforced by waste sale writes."""

from uuid import uuid4

from app.api.routes import waste
from app.db.session import SessionLocal
from app.models import WasteRecord, WasteSale


def test_waste_list_reports_partial_sale_balance_without_writes(client, auth_headers):
    marker = uuid4().hex[:12]
    with SessionLocal() as db:
        record = WasteRecord(
            waste_type=f"Remaining balance {marker}",
            quantity=10,
            unit="kg",
            sellable=True,
            estimated_value=20,
            status="received_by_waste_department",
        )
        db.add(record)
        db.flush()
        db.add_all([
            WasteSale(waste_record_id=record.id, buyer_name="Buyer A", quantity=2.25, unit_price=1, total_amount=2.25),
            WasteSale(waste_record_id=record.id, buyer_name="Buyer B", quantity=1.75, unit_price=1, total_amount=1.75),
        ])
        db.commit()
        record_id = int(record.id)

    with SessionLocal() as db:
        rows = waste.list_waste(db, object(), status="received_by_waste_department", sellable=True)
        row = next(result for result in rows if result.id == record_id)

        assert row.quantity == 10
        assert row.remaining_quantity == 6
        assert list(db.dirty) == []

    with SessionLocal() as db:
        assert db.get(WasteRecord, record_id).quantity == 10
        assert db.query(WasteSale).filter_by(waste_record_id=record_id).count() == 2

    response = client.get(
        "/api/waste?status=received_by_waste_department&sellable=true",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    api_row = next(row for row in response.json() if row["id"] == record_id)
    assert api_row["quantity"] == 10
    assert api_row["remaining_quantity"] == 6
