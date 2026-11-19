"""The grouped batch selector filters material before the global 500-row cap."""
from datetime import datetime, timezone

from app.db.session import SessionLocal
from app.schemas import Item, StockBatch
from app.tests.test_passport_cutting_submission import passport_cutting  # noqa: F401


def test_same_fabric_lookup_finds_old_lot_behind_500_unrelated_batches(client, auth_headers, passport_cutting):
    batches, order, _, _ = passport_cutting
    with SessionLocal() as db:
        source = db.get(StockBatch, batches[0]["id"])
        item_id = source.item_id
        unrelated = Item(name="Unrelated new fabric", sku="PICKER-UNRELATED", category="fabric", unit="kg", default_cost=0, reorder_level=0)
        db.add(unrelated)
        db.flush()
        db.add_all([StockBatch(item_id=unrelated.id, batch_no=f"NEW-{i}", quantity=1, unit="kg", cost_per_unit=0,
                              warehouse_id=source.warehouse_id, qc_status="passed", received_date=datetime(2099, 1, 1, tzinfo=timezone.utc))
                    for i in range(501)])
        db.commit()
    url = f"/api/cutting-passports/material-batches?production_order_id={order['id']}"
    global_page = client.get(url, headers=auth_headers)
    assert global_page.status_code == 200, global_page.text
    assert len(global_page.json()) == 500
    assert batches[0]["id"] not in {row["id"] for row in global_page.json()}
    filtered = client.get(url + f"&item_id={item_id}", headers=auth_headers)
    assert filtered.status_code == 200, filtered.text
    assert {row["item_id"] for row in filtered.json()} == {item_id}
    assert {row["id"] for row in batches}.issubset({row["id"] for row in filtered.json()})
