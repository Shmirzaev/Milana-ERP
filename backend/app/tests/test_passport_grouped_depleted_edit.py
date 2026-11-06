"""Notes on proven grouped cuts survive depletion; archived sourcing stays blocked."""
from copy import deepcopy

from app.db.session import SessionLocal
from app.schemas import CuttingMaterialUsage, CuttingPassport, StockBatch, StockMovement
from app.tests.test_passport_batch_allocations import allocation_case, save, confirm  # noqa: F401


def _exhaust_group(client, headers, case):
    with SessionLocal() as db:
        for source_id, quantity in zip(case["batches"], (100, 200)):
            db.get(StockBatch, source_id).quantity = quantity
        db.commit()
    created = save(client, headers, case)
    assert created.status_code == 201, created.text
    confirmed = confirm(client, headers, case, created.json())
    assert confirmed.status_code == 201, confirmed.text
    with SessionLocal() as db:
        assert all(db.get(StockBatch, key).archived_at is not None for key in case["batches"])
        assert [db.get(StockBatch, key).quantity for key in case["batches"]] == [0, 0]
    return created.json(), confirmed.json()


def test_notes_on_confirmed_group_survive_full_central_depletion(client, auth_headers, allocation_case):
    case = allocation_case
    passport, cut = _exhaust_group(client, auth_headers, case)
    url = f"/api/cutting-passports/{passport['id']}"
    opened = client.get(url, headers=auth_headers)
    assert opened.status_code == 200, opened.text
    changed = client.put(url, headers=auth_headers, json={**opened.json(), "notes": "Notes after full consumption"})
    assert changed.status_code == 200, changed.text
    assert client.get(url, headers=auth_headers).json()["notes"] == "Notes after full consumption"
    with SessionLocal() as db:
        assert [db.get(StockBatch, key).quantity for key in case["batches"]] == [0, 0]
        assert all(db.get(StockBatch, key).archived_at is not None for key in case["batches"])
        assert db.query(StockMovement).filter_by(reference_type="CuttingRecord", reference_id=cut["id"]).count() == 2
        assert [row.quantity for row in db.query(CuttingMaterialUsage).filter_by(cutting_record_id=cut["id"]).order_by(CuttingMaterialUsage.position)] == [100, 200]


def test_depleted_used_group_cannot_change_sources_or_be_reused_as_a_new_passport(client, auth_headers, allocation_case):
    case = allocation_case
    passport, _ = _exhaust_group(client, auth_headers, case)
    url = f"/api/cutting-passports/{passport['id']}"
    opened = client.get(url, headers=auth_headers).json()
    changed = deepcopy(opened)
    changed["materials"][0]["batch_allocations"][0]["quantity"] = 99
    changed["materials"][0]["batch_allocations"][1]["quantity"] = 201
    refused = client.put(url, headers=auth_headers, json=changed)
    assert refused.status_code == 409, refused.text
    assert "locked after Cutting confirmation" in refused.text
    with SessionLocal() as db:
        original = db.get(StockBatch, case["batches"][1])
        unrecorded = StockBatch(item_id=original.item_id, warehouse_id=original.warehouse_id,
            batch_no="UNRECORDED-METADATA-SOURCE", quantity=200, unit=original.unit,
            color=original.color, width=original.width, gsm=original.gsm, qc_status="passed")
        db.add(unrecorded); db.commit()
        forged = deepcopy(opened)
        forged["materials"][0]["batch_allocations"][1]["stock_batch_id"] = unrecorded.id
    refused = client.put(url, headers=auth_headers, json=forged)
    assert refused.status_code == 409, refused.text
    assert "locked after Cutting confirmation" in refused.text
    new = save(client, auth_headers, case)
    assert new.status_code == 409, new.text
    assert "active fabric inventory batches" in new.text
    with SessionLocal() as db:
        assert db.query(CuttingPassport).filter_by(production_order_id=case["order_id"]).count() == 1
        assert [db.get(StockBatch, key).quantity for key in case["batches"]] == [0, 0]
