"""Guard the exact scoped maintenance plan, including rejection of stale state."""
import importlib.util
from pathlib import Path
from decimal import Decimal

import pytest

spec = importlib.util.spec_from_file_location(
    "bambuk_conversion", Path(__file__).resolve().parents[2] / "scripts/convert_bambuk_15_metres.py")
correction = importlib.util.module_from_spec(spec)
spec.loader.exec_module(correction)


@pytest.fixture
def snapshot():
    result = {key: [] for key in correction.TABLE_FILTERS}
    for _, bid, kg, rolls, image in correction.TARGETS:
        result["stock_batches"].append(dict(id=bid, item_id=4, warehouse_id=1, unit="kg",
            quantity=kg, piece_count=rolls, archived_at=None, cost_per_unit="0",
            image_url=f"/storage/model-files/fabric-followup-20260930-{image}.webp",
            roll_weights_kg=[], roll_lengths_m=[], length_m="400" if bid == 1742 else None))
        result["stock_movements"].append(dict(id=bid, batch_id=bid, quantity=kg, unit="kg", movement_type="receive"))
    for index in range(24):
        bid = 1742 if index == 0 else correction.IDS[index % 15]
        result["production_orders"].append(dict(id=index + 1, production_no="PO-0332" if index == 0 else f"TEST-{index}",
            fabric_batch_id=bid, estimated_material_amount="600", estimated_material_unit="kg", estimated_material_code="1111"))
        result["production_order_materials"].append(dict(id=index + 1, production_order_id=index + 1,
            stock_batch_id=bid, estimated_quantity="600", unit="kg"))
    result["cutting_records"] = [dict(id=index + 1, input_quantity="0", waste_quantity="0",
        layer_material_kg="0", beika_kg="0", cutting_passport_id=None) for index in range(21)]
    return result


def test_exact_fifteen_and_order_units_preserve_master_and_history(snapshot):
    original = correction.canonical(snapshot)
    changes = correction.build_changes(snapshot)
    assert len(changes) == 78
    assert snapshot == original
    assert {r["table"] for r in changes} == {
        "stock_batches", "stock_movements", "production_orders", "production_order_materials"}
    batches = [r for r in changes if r["table"] == "stock_batches"]
    assert {r["id"] for r in batches} == set(correction.IDS)
    assert sum(Decimal(r["values"]["quantity"]) for r in batches) == Decimal("13848.64")
    assert next(r for r in batches if r["id"] == 1742)["values"]["length_m"] == "994.76"
    assert all(r["values"]["estimated_material_amount"] == "1560.0"
               for r in changes if r["table"] == "production_orders")


@pytest.mark.parametrize("mutation", ["photo", "consumed", "already_m", "new_reservation", "new_order", "valuation", "cutting"])
def test_refuses_ambiguous_consumed_or_changed_state(snapshot, mutation):
    row = snapshot["stock_batches"][0]
    if mutation == "photo":
        row["image_url"] = "unrelated.webp"
    elif mutation == "consumed":
        row["quantity"] = "200"
    elif mutation == "already_m":
        row["unit"] = "m"
    elif mutation == "new_reservation":
        snapshot["material_reservations"].append({"id": 999})
    elif mutation == "new_order":
        snapshot["production_orders"].pop()
    elif mutation == "valuation":
        row["cost_per_unit"] = "3"
    elif mutation == "cutting":
        snapshot["cutting_records"][0]["input_quantity"] = "1"
    with pytest.raises(AssertionError):
        correction.build_changes(snapshot)


def test_readback_rejects_unplanned_changes(snapshot):
    changes = correction.build_changes(snapshot)
    after = correction.canonical(snapshot)
    for change in changes:
        next(r for r in after[change["table"]] if r["id"] == change["id"]).update(change["values"])
    correction.verify_changes(snapshot, after, changes)
    after["stock_batches"][0]["piece_count"] = 99
    with pytest.raises(AssertionError):
        correction.verify_changes(snapshot, after, changes)


def test_unit_specific_master_relinks_only_selected_receipts_and_orders(snapshot):
    changes = correction.build_changes(snapshot, new_item_id=9000)
    assert all(r["values"]["item_id"] == 9000 for r in changes
               if r["table"] in {"stock_batches", "stock_movements"})
    assert all(r["values"]["estimated_material_code"] == correction.METRE_SKU for r in changes
               if r["table"] == "production_orders")
    assert not any(r["table"] in {"items", "cutting_records"} for r in changes)
