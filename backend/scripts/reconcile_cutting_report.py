"""Apply a reviewed, hash-pinned cutting-passport data plan; dry-run by default.

The plan preserves blank source cells, existing operational links and explicitly
protected passports. It never creates orders, consumes stock or changes output.
"""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models.cutting_passport import CuttingPassport
from app.services.audit import log_action

PROTECTED = {"9055", "9109"}
EDITABLE = {
    "date", "notes", "materials", "rolls_count", "layer_weight_kg", "total_layers",
    "planned_kg", "pieces", "fabric_width_m", "lay_length_m", "gramage", "waste_pct",
    "beka_per_piece_kg", "other_beka_per_piece_kg", "scrap_kg", "ribana_per_piece_kg",
    "operator_name_manual", "fabric_type", "lot_no", "size_range",
}
PRESERVED_TABLES = (
    "production_orders", "production_order_materials", "work_orders", "cutting_records",
    "cutting_material_usages", "stock_batches", "stock_movements", "material_reservations",
    "bundles", "packages", "shipments",
)


def plain(value):
    return json.loads(json.dumps(value, default=str))


def passports(db):
    return plain([dict(r) for r in db.execute(text("SELECT * FROM cutting_passports ORDER BY id")).mappings()])


def fingerprints(db):
    return {table: db.execute(text(
        f"SELECT count(*)::text || ':' || md5(coalesce(string_agg(md5(row_to_json(t)::text), '' ORDER BY id), '')) FROM {table} t"
    )).scalar_one() for table in PRESERVED_TABLES}


def execute(plan, apply=False):
    assert plan["version"] == 1
    assert set(plan["protected_passports"]) == PROTECTED
    updates, inserts = plan["updates"], plan["inserts"]
    numbers = [u["passport_no"] for u in updates] + [i["values"]["passport_no"] for i in inserts]
    assert len(numbers) == len(set(numbers)) and not PROTECTED.intersection(numbers)
    for u in updates:
        assert set(u["values"]) <= EDITABLE
        assert u["expected"]["id"] == u["id"] and u["expected"]["passport_no"] == u["passport_no"]
        for key, value in u["values"].items():
            assert value is not None and value != "", f"Blank overwrite: {key}"
        if "materials" in u["values"]:
            before = u["expected"].get("materials") or []
            after = u["values"]["materials"]
            assert [r["stock_batch_id"] for r in before] == [r["stock_batch_id"] for r in after]
            for old, new in zip(before, after):
                assert all(new.get(k) is not None for k, v in old.items() if v is not None)
                assert "size_range" not in new, "Size range belongs to the passport, not a material"
    for item in inserts:
        assert set(item["values"]) <= EDITABLE | {"passport_no", "model_code", "variant", "mold_no", "order_no", "has_print"}
        assert "materials" not in item["values"]
    with Session(engine) as db:
        db.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
        db.execute(text("SET LOCAL lock_timeout = '5s'"))
        db.execute(text("SET LOCAL statement_timeout = '60s'"))
        if not apply:
            db.execute(text("SET TRANSACTION READ ONLY"))
        else:
            db.execute(text("LOCK TABLE cutting_passports IN SHARE ROW EXCLUSIVE MODE"))
            db.execute(text("LOCK TABLE audit_logs IN SHARE ROW EXCLUSIVE MODE"))
        before = passports(db)
        assert before == plan["expected_all_passports"], "Live passports changed; rebuild and review the plan"
        result = {"updates": len(updates), "inserts": len(inserts), "held_entries": len(plan["held"]), "applied": False}
        if not apply:
            db.rollback()
            return result
        preserved = fingerprints(db)
        audit_ids, inserted_ids = [], []
        for u in updates:
            p = db.get(CuttingPassport, u["id"])
            assert p.passport_no == u["passport_no"]
            for key, value in u["values"].items():
                setattr(p, key, datetime.fromisoformat(value) if key == "date" else value)
            db.flush()
            audit_ids.append(log_action(db, None, "reconcile_cutting_report", "CuttingPassport", p.id,
                old_value=u["expected"], new_value={"fields": u["values"], "sources": plan["sources"]}).id)
        for item in inserts:
            values = dict(item["values"])
            values["date"] = datetime.fromisoformat(values["date"])
            p = CuttingPassport(**values)
            db.add(p)
            db.flush()
            inserted_ids.append(p.id)
            audit_ids.append(log_action(db, None, "import_cutting_report", "CuttingPassport", p.id,
                new_value={"fields": values, "file": item["file"], "row": item["row"], "sources": plan["sources"]}).id)
        db.flush()
        after = passports(db)
        touched = {u["id"] for u in updates}
        assert [p for p in before if p["id"] not in touched] == [p for p in after if p["id"] not in touched and p["id"] not in inserted_ids]
        assert len(after) == len(before) + len(inserts)
        assert preserved == fingerprints(db), "Operational data changed unexpectedly"
        from app.api.routes.cutting_passports import _serialize
        from app.schemas.cutting_passport import CuttingPassportOut
        for passport_id in touched | set(inserted_ids):
            CuttingPassportOut.model_validate(_serialize(db.get(CuttingPassport, passport_id), db))
        result.update(applied=True, inserted_ids=inserted_ids, audit_ids=audit_ids,
                      preserved_tables=preserved, protected_unchanged=sorted(PROTECTED))
        db.commit()
        return result


def repair_material_shape(plan):
    """Remove only the duplicate passport-size key introduced by this import."""
    from app.api.routes.cutting_passports import _serialize
    from app.schemas.cutting_passport import CuttingPassportOut

    repaired = []
    with Session(engine) as db:
        db.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
        db.execute(text("SET LOCAL lock_timeout = '5s'"))
        db.execute(text("LOCK TABLE cutting_passports IN SHARE ROW EXCLUSIVE MODE"))
        db.execute(text("LOCK TABLE audit_logs IN SHARE ROW EXCLUSIVE MODE"))
        for u in plan["updates"]:
            if "materials" not in u["values"]:
                continue
            assert u["passport_no"] not in PROTECTED
            assert all("size_range" not in row for row in u["expected"]["materials"])
            p = db.get(CuttingPassport, u["id"])
            assert p.materials == u["values"]["materials"], "Material data changed after import"
            before = p.materials
            p.materials = [{k: v for k, v in row.items() if k != "size_range"} for row in before]
            db.flush()
            CuttingPassportOut.model_validate(_serialize(p, db))
            log_action(db, None, "repair_report_material_shape", "CuttingPassport", p.id,
                       old_value={"materials": before}, new_value={"materials": p.materials})
            repaired.append(p.passport_no)
        db.commit()
    return {"repaired_passports": repaired}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("plan")
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    raw = Path(args.plan).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == args.sha256, "Plan hash mismatch"
    print(json.dumps(execute(json.loads(raw), apply=args.apply), default=str))
