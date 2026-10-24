"""Explicit owner-approved correction; never runs at startup or in migrations.

Only the fifteen photo-identified September 30 receipts are eligible. A fresh
validated backup and reviewed snapshot are required by the production launcher.
No shared material master or historical cutting execution is rewritten.
"""
from decimal import Decimal
import hashlib
import json

from sqlalchemy import text

FACTOR = Decimal("2.6")
OPERATION = "bambuk-15-photo-metres-20261017"
METRE_SKU = "BAMBUK-M-20261017"
# photo number, batch identity, source kg, rolls, exact stored image identity
TARGETS = [
    (1, 1730, "216.8", 13, "dcf68681c5e4382dee92db16"),
    (2, 1731, "360.7", 23, "466e111f1d9abd9a8b711c4e"),
    (3, 1732, "415.1", 25, "ece34819b75bf4c1da561a02"),
    (4, 1733, "384.4", 24, "85bfa75f080da935b7a8067b"),
    (5, 1734, "390.9", 26, "5d9980b3e11e85961012fe6a"),
    (6, 1735, "401.9", 25, "a01555f6c1cf020f938c5e04"),
    (7, 1736, "374.5", 25, "dad1c6de48568465c0c292a7"),
    (8, 1737, "274.8", 18, "8588a8343ee0e1e22fcb8d87"),
    (9, 1738, "387.6", 27, "d1f6e3f1b04d50848064a807"),
    (10, 1739, "424.7", 28, "7c10b060e09447a144f8d524"),
    (11, 1740, "313.3", 21, "6b89f8456ca1acf258a0ca72"),
    (12, 1741, "416.8", 28, "7ab4484da3df4c175df8138d"),
    (13, 1742, "382.6", 24, "58b7af66ae7bbeae8701729d"),
    (14, 1743, "279.3", 17, "9d77ffb222d4956c1e1aefbe"),
    (15, 1744, "303", 19, "23635cbe3f1eec139424940d"),
]
IDS = [row[1] for row in TARGETS]
TABLE_FILTERS = {
    "stock_batches": "id=ANY(:ids)",
    "stock_movements": "batch_id=ANY(:ids)",
    "production_orders": "fabric_batch_id=ANY(:ids)",
    "production_order_materials": "stock_batch_id=ANY(:ids)",
    "material_reservations": "stock_batch_id=ANY(:ids)",
    "cutting_records": "fabric_batch_id=ANY(:ids)",
    "cutting_material_usages": "stock_batch_id=ANY(:ids)",
    "cutting_beika_material_usages": "stock_batch_id=ANY(:ids)",
    "model_bom": "stock_batch_id=ANY(:ids)",
    "waste_records": "batch_id=ANY(:ids)",
    "eco_fabric_rolls": "batch_id=ANY(:ids)",
    "cutting_passports": "production_order_id IN (SELECT id FROM production_orders WHERE fabric_batch_id=ANY(:ids))",
}


def canonical(value):
    return json.loads(json.dumps(value, default=str, sort_keys=True))


def digest(value):
    return hashlib.sha256(json.dumps(canonical(value), sort_keys=True).encode()).hexdigest()


def snapshot(db):
    return canonical({table: [dict(r) for r in db.execute(text(
        f"SELECT * FROM {table} WHERE {where} ORDER BY id"), {"ids": IDS}).mappings()]
        for table, where in TABLE_FILTERS.items()})


def protected(db, new_item_id=None):
    """Exact fingerprints of unrelated rows and downstream execution."""
    filters = {table: f"NOT ({where}) OR ({where}) IS NULL"
               for table, where in TABLE_FILTERS.items()}
    filters.update({table: "true" for table in (
        "items", "work_orders", "production_batches", "bundles", "packages",
        "cutting_records", "cutting_passports", "model_bom", "waste_records",
    )})
    if new_item_id is not None:
        filters["items"] = "id<>:new_item_id"
    return {table: db.execute(text(
        "SELECT md5(COALESCE(string_agg(row_to_json(t)::text, '' ORDER BY id),'')) "
        f"FROM (SELECT * FROM {table} WHERE {where}) t"), {"ids": IDS, "new_item_id": new_item_id}).scalar_one()
        for table, where in filters.items()}


def build_changes(before, new_item_id=None):
    batches = {r["id"]: r for r in before["stock_batches"]}
    assert set(batches) == set(IDS), "Exact fifteen batches required"
    changes = []

    def change(table, row, **values):
        changes.append({"table": table, "id": row["id"], "values": canonical(values)})

    for _, bid, kg, rolls, image in TARGETS:
        row = batches[bid]
        assert row["item_id"] == 4 and row["warehouse_id"] == 1
        assert row["unit"] == "kg" and Decimal(row["quantity"]) == Decimal(kg), "Stock changed; re-review required"
        assert row["piece_count"] == rolls and row["archived_at"] is None
        assert row["image_url"] == f"/storage/model-files/fabric-followup-20260930-{image}.webp"
        assert Decimal(row["cost_per_unit"]) == 0, "Nonzero valuation requires separate review"
        assert not row["roll_weights_kg"] and not row["roll_lengths_m"]
        metres = Decimal(kg) * FACTOR
        values = dict(quantity=metres, unit="m", length_m=metres)
        if new_item_id is not None:
            values["item_id"] = new_item_id
        change("stock_batches", row, **values)

    receipts = before["stock_movements"]
    assert len(receipts) == 15 and {r["batch_id"] for r in receipts} == set(IDS)
    for row in receipts:
        assert row["movement_type"] == "receive" and row["unit"] == "kg"
        assert Decimal(row["quantity"]) == Decimal(batches[row["batch_id"]]["quantity"])
        assert row.get("item_id", 4) == 4
        values = dict(quantity=Decimal(row["quantity"]) * FACTOR, unit="m")
        if new_item_id is not None:
            values["item_id"] = new_item_id
        change("stock_movements", row, **values)

    orders = before["production_orders"]
    materials = before["production_order_materials"]
    assert len(orders) == len(materials) == 24, "Order links changed; re-review required"
    by_order = {r["production_order_id"]: r for r in materials}
    assert set(by_order) == {r["id"] for r in orders}
    assert any(r["production_no"] == "PO-0332" and r["fabric_batch_id"] == 1742 for r in orders)
    for row in orders:
        material = by_order[row["id"]]
        assert material["stock_batch_id"] == row["fabric_batch_id"]
        assert row["estimated_material_unit"] == material["unit"] == "kg"
        assert Decimal(row["estimated_material_amount"]) == Decimal(material["estimated_quantity"])
        quantity = Decimal(row["estimated_material_amount"]) * FACTOR
        values = dict(estimated_material_amount=quantity, estimated_material_unit="m")
        if new_item_id is not None:
            assert row["estimated_material_code"] == "1111"
            values["estimated_material_code"] = METRE_SKU
        change("production_orders", row, **values)
        change("production_order_materials", material, estimated_quantity=quantity, unit="m")

    for table in ("material_reservations", "cutting_material_usages", "cutting_beika_material_usages",
                  "model_bom", "waste_records", "eco_fabric_rolls", "cutting_passports"):
        assert not before[table], f"New dependency in {table}; re-review required"
    assert len(before["cutting_records"]) == 21
    for row in before["cutting_records"]:
        assert all(Decimal(row[field]) == 0 for field in (
            "input_quantity", "waste_quantity", "layer_material_kg", "beika_kg"))
        assert row["cutting_passport_id"] is None
    return changes


def verify_changes(before, after, changes):
    expected = canonical(before)
    for change in changes:
        row = next(r for r in expected[change["table"]] if r["id"] == change["id"])
        row.update(change["values"])
    # PostgreSQL preserves each numeric column's scale; compare numeric fields numerically.
    for table in expected:
        assert len(expected[table]) == len(after[table])
        for old, new in zip(expected[table], after[table]):
            assert old.keys() == new.keys()
            for key in old:
                if key in {"quantity", "length_m", "estimated_quantity", "estimated_material_amount"} and old[key] is not None:
                    assert Decimal(old[key]) == Decimal(new[key]), (table, old["id"], key)
                else:
                    assert old[key] == new[key], (table, old["id"], key)


def execute(db, expected, backup):
    """Caller commits only after verification; no implicit application or commit."""
    from app.models.audit_service import log_action
    from app.models import Item

    assert backup["bytes"] > 0 and backup["restore_objects"] > 100
    assert backup["mode"] == "0o600" and len(backup["sha256"]) == 64
    assert db.bind.dialect.name == "postgresql"
    db.execute(text("SET LOCAL lock_timeout = '5s'"))
    # Short table locks prevent new dependency rows and unit-changing concurrent writes.
    db.execute(text("LOCK TABLE items, " + ", ".join(TABLE_FILTERS) + " IN SHARE ROW EXCLUSIVE MODE"))
    existing = db.execute(text("SELECT id FROM audit_logs WHERE action=:action"), {"action": OPERATION}).first()
    assert existing is None, "Correction already recorded; do not apply twice"
    before = snapshot(db)
    assert digest(before) == expected, "Reviewed snapshot changed; re-review required"
    build_changes(before)
    preserved = protected(db)
    original = db.get(Item, 4)
    assert original.name == "BAMBUK" and original.unit == "kg" and original.sku == "1111"
    assert not db.query(Item.id).filter_by(sku=METRE_SKU).first()
    master = Item(sku=METRE_SKU, name="BAMBUK (m)", category=original.category, unit="m",
                  default_cost=0, reorder_level=0, track_batch=original.track_batch,
                  is_active=True, composition_json=original.composition_json, image_url=original.image_url)
    db.add(master)
    db.flush()
    changes = build_changes(before, master.id)
    for change in changes:
        values = change["values"]
        statement = f"UPDATE {change['table']} SET " + ", ".join(f"{k}=:{k}" for k in values) + " WHERE id=:id"
        assert db.execute(text(statement), dict(values, id=change["id"])).rowcount == 1
    after = snapshot(db)
    verify_changes(before, after, changes)
    assert protected(db, master.id) == preserved, "Unrelated or historical data changed"
    log_action(db, None, OPERATION, "StockBatch", None,
               old_value=before, new_value={"operation": OPERATION, "factor": str(FACTOR),
               "backup": backup, "after": after, "changes": changes,
               "new_material": {"id": master.id, "sku": METRE_SKU, "name": master.name, "unit": "m"}})
    return {"before_hash": digest(before), "after_hash": digest(after), "changes": changes,
            "preserved": preserved, "new_item_id": master.id,
            "orders": [r["production_no"] for r in before["production_orders"]],
            "total_metres": str(sum(Decimal(r["quantity"]) for r in after["stock_batches"]))}
