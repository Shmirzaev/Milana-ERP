from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.api.routes.cutting_passports import _compute, _report_passports, material_defaults
from app.db.session import SessionLocal
from app.schemas import CuttingPassport, ProductionOrder, ProductionOrderItem, User
from app.schemas.catalog.catalog import ModelSize
from app.models.passport_sizes_service import size_count_from_range
from app.tests.test_cutting_passport_defaults_query_growth import _material_order, _factory_user

SIZES = ["122", "128", "134", "140", "146", "152"]


@pytest.mark.parametrize("selection,count", [
    ("122-152", 6), ("122-152 ×2", 12), (", ".join(SIZES) + " ×2", 12),
    ("128-146", 4), ("128", 1), ("46", 0), ("", 0),
])
def test_exact_order_size_count(selection, count):
    assert size_count_from_range(selection, SIZES + ["122"]) == count


def test_combined_labels_and_unlinked_legacy_passports():
    assert size_count_from_range("40-42", ["40-42", "44-46"]) == 1
    assert size_count_from_range("40-42, 44-46 ×2", ["40-42", "44-46"]) == 4
    assert size_count_from_range("46-56") == 6


@pytest.mark.parametrize("doubled", [False, True])
@pytest.mark.parametrize("metres", [False, True])
def test_exact_count_drives_kg_and_metre_consumption(doubled, metres):
    p = SimpleNamespace(pieces=600, beka_per_piece_kg=.005, other_beka_per_piece_kg=.001,
                        ribana_per_piece_kg=0, scrap_kg=2, layer_weight_kg=2.4, total_layers=50,
                        fabric_width_m=1.8, lay_length_m=3.37, gramage=.191, planned_kg=200,
                        meter_mode=metres, size_range="122-152" + (" ×2" if doubled else ""),
                        production_order=SimpleNamespace(items=[SimpleNamespace(size=s) for s in SIZES]))
    result = _compute(p)
    count = 12 if doubled else 6
    expected = round((3.37 if metres else 1.8 * 3.37 * .191) / count + .006, 6)
    assert result["size_count"] == count
    assert result["per_piece_weight_kg"] == expected
    assert result["theoretical_kg"] == round(expected * 600 + 2, 6)
    assert result["actual_kg"] == 125


def test_saved_passport_list_detail_reports_and_defaults_use_order_sizes(client, auth_headers):
    with SessionLocal() as db:
        oid, batches = _material_order(db, 1)
        order = db.get(ProductionOrder, oid)
        db.query(ProductionOrderItem).filter_by(production_order_id=oid).delete()
        db.add_all([ProductionOrderItem(production_order_id=oid, model_id=order.model_id,
                                       color="white", size=size, planned_quantity=100) for size in SIZES])
        db.add_all([ModelSize(model_id=order.model_id, size=size) for size in ["46", "48", "50", "52", "54", "56"]])
        values = dict(pieces=600, beka_per_piece_kg=.005, other_beka_per_piece_kg=.001,
                      ribana_per_piece_kg=0, scrap_kg=2, layer_weight_kg=2.4, total_layers=50,
                      fabric_width_m=1.8, lay_length_m=3.37, gramage=.191, planned_kg=200, meter_mode=False)
        passport = CuttingPassport(passport_no="ORDER-SIZES", production_order_id=oid,
                                   date=datetime(2026, 10, 17, tzinfo=timezone.utc), size_range="122-152",
                                   materials=[dict(values, stock_batch_id=batches[0])], **values)
        db.add(passport)
        db.commit()
        pid = passport.id
        defaults = material_defaults(oid, db, _factory_user())
        assert defaults["available_sizes"] == defaults["sizes"] == SIZES
        assert defaults["size_count"] == 6
    expected = round(1.8 * 3.37 * .191 / 6 + .006, 6)
    for url in [f"/api/cutting-passports/{pid}", f"/api/cutting-passports?production_order_id={oid}"]:
        response = client.get(url, headers=auth_headers)
        assert response.status_code == 200, response.text
        row = response.json() if isinstance(response.json(), dict) else response.json()[0]
        assert row["size_count"] == 6
        assert row["per_piece_weight_kg"] == row["materials"][0]["per_piece_weight_kg"] == expected
    with SessionLocal() as db:
        actor = db.query(User).filter_by(email="admin@example.com").one()
        rows = list(_report_passports(db, actor, "ORDER-SIZES", None, None, None))
        assert rows[0][1][0]["size_count"] == 6
        assert rows[0][1][0]["per_piece_weight_kg"] == expected
        assert [row.size for row in db.query(ProductionOrderItem).filter_by(production_order_id=oid).order_by(ProductionOrderItem.id)] == SIZES
