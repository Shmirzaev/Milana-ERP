from decimal import Decimal

from app.db.session import SessionLocal
from app.models import WasteRecord, WasteSale
from app.services.finance import waste_cost, waste_income


def _report(client, auth_headers) -> tuple[dict, dict]:
    waste = client.get("/api/finance/waste-report", headers=auth_headers)
    dashboard = client.get("/api/finance/dashboard", headers=auth_headers)
    assert waste.status_code == 200, waste.text
    assert dashboard.status_code == 200, dashboard.text
    return waste.json(), dashboard.json()


def test_finance_waste_income_uses_recorded_partial_and_repeated_sales(client, auth_headers):
    with SessionLocal() as db:
        unsold = WasteRecord(
            waste_type="Unsold", quantity=10, unit="kg", sellable=True,
            estimated_value=25, status="received_by_waste_department",
        )
        partially_sold = WasteRecord(
            waste_type="Partially sold", quantity=10, unit="kg", sellable=True,
            estimated_value=100, status="received_by_waste_department",
        )
        discarded = WasteRecord(
            waste_type="Discarded", quantity=1, unit="kg", sellable=False,
            estimated_value=7, status="recorded",
        )
        db.add_all([unsold, partially_sold, discarded])
        db.flush()
        sold_record_id = partially_sold.id
        db.commit()

    waste, dashboard = _report(client, auth_headers)
    assert waste == {"cost": None, "income": None, "currency": None}
    assert dashboard["waste_income"] is None
    with SessionLocal() as db:
        assert waste_cost(db) == 7 and waste_income(db) == 0

    with SessionLocal() as db:
        db.add(WasteSale(
            waste_record_id=sold_record_id, buyer_name="Buyer one",
            quantity=2, unit_price=3, total_amount=6,
        ))
        db.commit()
    waste, dashboard = _report(client, auth_headers)
    assert waste == {"cost": None, "income": None, "currency": None}
    assert dashboard["waste_income"] is None
    with SessionLocal() as db:
        assert waste_income(db) == 6

    with SessionLocal() as db:
        db.add(WasteSale(
            waste_record_id=sold_record_id, buyer_name="Buyer two",
            quantity=1, unit_price=Decimal("8.75"), total_amount=Decimal("8.75"),
        ))
        db.commit()
    waste, dashboard = _report(client, auth_headers)
    assert waste == {"cost": None, "income": None, "currency": None}
    assert dashboard["waste_income"] is None
    with SessionLocal() as db:
        assert waste_income(db) == 14.75
