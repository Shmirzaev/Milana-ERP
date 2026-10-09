from types import SimpleNamespace

import pytest

from app.api.routes.cutting_passports import _compute
from app.db.session import SessionLocal
from app.models import Bundle, Item, CuttingPassport, CuttingRecord, MaterialReservation, ProductionOrderMaterial, StockBatch
from app.tests.test_passport_cutting_submission import passport_cutting  # noqa: F401


def calculation(**changes):
    values = dict(meter_mode=True, pieces=600, beka_per_piece_kg=0, other_beka_per_piece_kg=0.015,
                  ribana_per_piece_kg=0, scrap_kg=0, layer_weight_kg=0, total_layers=0,
                  fabric_width_m=1.77, lay_length_m=7.72, gramage=0.191, planned_kg=0, size_range="48-56")
    return _compute(SimpleNamespace(**(values | changes)))


@pytest.mark.parametrize("length,per_piece,total", [(7.72, 1.559, 935.4), (7.88, 1.591, 954.6)])
def test_workbook_metre_formulas(length, per_piece, total):
    result = calculation(lay_length_m=length)
    assert result["per_piece_weight_kg"] == per_piece
    assert result["theoretical_kg"] == total
    assert calculation(lay_length_m=length, fabric_width_m=0, gramage=0) == result


def test_binding_is_added_once_and_ratios_use_metres():
    result = calculation(layer_weight_kg=7.72, total_layers=120, beka_per_piece_kg=0.01, scrap_kg=2, planned_kg=960)
    assert result["actual_kg"] == 934.4
    assert result["theoretical_kg"] == 943.4
    assert result["actual_kg_per_piece"] == round(934.4 / 600, 6)
    assert result["gross_kg_per_piece"] == 1.6
    assert calculation(size_range="")["per_piece_weight_kg"] is None
    assert calculation(pieces=0)["actual_kg_per_piece"] is None


def test_mode_defaults_off_and_round_trips(client, auth_headers):
    payload = dict(passport_no="METRES", date="2026-10-09T00:00:00Z", size_range="48-56", pieces=600,
                   lay_length_m=7.72, fabric_width_m=1.77, gramage=0.191, other_beka_per_piece_kg=0.015)
    saved = client.post("/api/cutting-passports", json=payload, headers=auth_headers)
    assert saved.status_code == 201, saved.text
    old = saved.json()
    assert old["meter_mode"] is False
    url = f"/api/cutting-passports/{old['id']}"
    updated = client.patch(url, json=payload | {"meter_mode": True}, headers=auth_headers)
    assert updated.status_code == 200, updated.text
    assert updated.json()["theoretical_kg"] == 935.4
    assert client.get(url, headers=auth_headers).json()["meter_mode"] is True
    restored = client.patch(url, json=payload, headers=auth_headers)
    assert restored.json()["theoretical_kg"] == old["theoretical_kg"]


def test_mixed_unit_handoff(client, auth_headers, passport_cutting):
    batches, order, _, payload = passport_cutting
    pid = payload["cutting_passport_id"]
    with SessionLocal() as db:
        batch = db.get(StockBatch, batches[0]["id"])
        item = Item(sku="METRE-FABRIC", name="Metre fabric", category="fabric", unit="m")
        db.add(item)
        db.flush()
        batch.item_id = item.id
        batch.unit = "m"
        db.query(ProductionOrderMaterial).filter_by(production_order_id=order["id"], stock_batch_id=batch.id).one().unit = "m"
        for row in db.query(MaterialReservation).filter_by(production_order_id=order["id"], stock_batch_id=batch.id):
            row.unit = "m"
            row.item_id = item.id
        materials = [dict(row) for row in db.get(CuttingPassport, pid).materials]
        materials[0].update(meter_mode=True, beka_per_piece_kg=0.01, lay_length_m=2)
        db.commit()
    form = dict(passport_no="MIXED", date="2026-10-09T00:00:00Z", production_order_id=order["id"], size_range="46", materials=materials)
    saved = client.patch(f"/api/cutting-passports/{pid}", headers=auth_headers, json=form)
    assert saved.status_code == 200, saved.text
    assert [row["meter_mode"] for row in saved.json()["materials"]] == [True, False]
    result = client.post("/api/cutting/records", headers=auth_headers, json=payload)
    assert result.status_code == 201, result.text
    assert [(row["quantity"], row["unit"]) for row in result.json()["materials"]] == [(6.6, "m"), (6.5, "kg")]
    with SessionLocal() as db:
        assert [float(db.get(StockBatch, row["id"]).quantity) for row in batches] == [93.4, 93.5]
        assert db.query(Bundle).filter_by(production_order_id=order["id"]).one().quantity == 10
        record = db.get(CuttingRecord, result.json()["id"])
        assert record.input_unit == "m" and record.layer_material_kg == 0 and record.beika_kg == 0
    assert client.post("/api/cutting/records", headers=auth_headers, json=payload).status_code in (400, 409)
    form["materials"][0]["meter_mode"] = False
    assert client.patch(f"/api/cutting-passports/{pid}", headers=auth_headers, json=form).status_code in (400, 409)


def test_metre_mode_rejects_kg_inventory(client, auth_headers, passport_cutting):
    batches, order, _, payload = passport_cutting
    with SessionLocal() as db:
        materials = [dict(row, meter_mode=True) for row in db.get(CuttingPassport, payload["cutting_passport_id"]).materials]
    response = client.patch(f"/api/cutting-passports/{payload['cutting_passport_id']}", headers=auth_headers,
                            json=dict(passport_no="BAD-UNIT", date="2026-10-09T00:00:00Z", production_order_id=order["id"], materials=materials))
    assert response.status_code == 400, response.text
    with SessionLocal() as db:
        assert all(db.get(StockBatch, row["id"]).quantity == 100 for row in batches)
