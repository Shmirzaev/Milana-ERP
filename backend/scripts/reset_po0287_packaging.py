"""One-time owner-requested reset; retain immutable labels and return evidence.

Default is read-only inspection. Apply requires the inspected fingerprint and a
verified backup. The owner explicitly authorized a one-time exception to the
printed-package deletion guard. Its function is restored byte-for-byte within
the same transaction, before commit; no serving application or lasting schema
change occurs. Immutable print manifests and return history remain intact.
"""
import argparse
import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import text

IDS = [13230, 13231, 13232, 13233]
PO = 312
DELETE_COUNTS = {"packages": 4, "package_items": 24,
                 "package_batch_allocations": 4, "package_scan_logs": 8,
                 "finished_goods_stock": 24, "packaging_records": 1}
ORIGINAL_FUNCTION = """CREATE OR REPLACE FUNCTION public.protect_printed_package_deletion()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
        BEGIN
          IF EXISTS (SELECT 1 FROM package_print_run_members m JOIN package_print_runs r ON r.id=m.run_id
                     WHERE m.package_id=OLD.id AND (OLD.manual_receipt_id IS NULL OR
                       (r.deleted_at IS NULL AND NOT r.deleted_package_ids::jsonb @> jsonb_build_array(OLD.id))))
          THEN RAISE EXCEPTION 'Printed package must have a deleted manual label'; END IF;
          RETURN OLD;
        END; $function$
"""


def exception_definition(original, backend_pid, transaction_id):
    assert original == ORIGINAL_FUNCTION, "Deletion protection differs from reviewed source"
    assert type(backend_pid) is int and backend_pid > 0
    assert type(transaction_id) is int and transaction_id > 0
    exception = f"""
          IF pg_backend_pid() = {backend_pid} AND txid_current() = {transaction_id}
             AND OLD.id IN (13230,13231,13232,13233)
             AND OLD.package_no = 'PKG-2026-' || lpad((OLD.id-13061)::text,6,'0')
             AND OLD.production_order_id=312 AND OLD.production_batch_id=152
             AND OLD.model_id=8444 AND OLD.packaging_department_code='PKG'
             AND OLD.status='returned_to_packaging' AND OLD.total_quantity=90
             AND OLD.received_at IS NULL AND OLD.shipped_at IS NULL
             AND OLD.sales_order_id IS NULL AND OLD.manual_receipt_id IS NULL
             AND OLD.legacy_receipt_id IS NULL AND OLD.dispatched_quantity=0
             AND OLD.quantity_shortfall=0
             AND EXISTS (SELECT 1 FROM public.package_print_runs r
                 WHERE r.id=14 AND r.run_no='PRN-2026-000014'
                 AND r.returned_at IS NOT NULL AND r.received_at IS NULL
                 AND r.deleted_at IS NOT NULL
                 AND r.deleted_package_ids::jsonb = '[13230,13231,13232,13233]'::jsonb
                 AND r.package_ids::jsonb = '[13230,13231,13232,13233]'::jsonb)
          THEN RETURN OLD; END IF;
"""
    return original.replace("        BEGIN\n", "        BEGIN\n" + exception, 1)


def protection_state(db):
    return {"function": db.execute(text("SELECT pg_get_functiondef('public.protect_printed_package_deletion()'::regprocedure)")).scalar(),
            "triggers": rows(db, "SELECT tgname,tgenabled,pg_get_triggerdef(oid) AS definition FROM pg_trigger WHERE tgrelid='packages'::regclass AND NOT tgisinternal ORDER BY tgname")}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def rows(db, sql, **params):
    return [dict(row) for row in db.execute(text(sql), params).mappings()]


def snapshot(db):
    result = {}
    for table in ("packages", "production_orders", "work_orders", "bundles", "production_batches", "packaging_receipts"):
        where = "id=:po" if table == "production_orders" else "production_order_id=:po"
        result[table] = rows(db, f'SELECT * FROM "{table}" WHERE {where} ORDER BY id', po=PO)
    result["packaging_records"] = rows(db, "SELECT * FROM packaging_records WHERE work_order_id IN (SELECT id FROM work_orders WHERE production_order_id=:po) ORDER BY id", po=PO)
    for col in rows(db, "SELECT table_name FROM information_schema.columns WHERE table_schema='public' AND column_name='package_id' ORDER BY table_name"):
        table = col["table_name"]
        result[table] = rows(db, f'SELECT * FROM "{table}" WHERE package_id=ANY(:ids) ORDER BY id', ids=IDS)
    result["package_print_runs"] = rows(db, "SELECT * FROM package_print_runs WHERE id IN (SELECT run_id FROM package_print_run_members WHERE package_id=ANY(:ids)) ORDER BY id", ids=IDS)
    result["material_movements"] = rows(db, "SELECT * FROM stock_movements WHERE (reference_type='PackagingRecord' AND reference_id=23) OR (reference_type='WorkOrder' AND reference_id IN (1226,1227)) ORDER BY id")
    result["stock_dependencies"] = []
    stock_ids = [r["id"] for r in result["finished_goods_stock"]]
    for col in rows(db, "SELECT table_name,column_name FROM information_schema.columns WHERE table_schema='public' AND column_name='finished_goods_stock_id' ORDER BY table_name"):
        table = col["table_name"]
        result["stock_dependencies"] += rows(db, f'SELECT * FROM "{table}" WHERE finished_goods_stock_id=ANY(:ids) ORDER BY id', ids=stock_ids)
    result["work_dependencies"] = []
    for col in rows(db, "SELECT table_name FROM information_schema.columns WHERE table_schema='public' AND column_name='work_order_id' ORDER BY table_name"):
        table = col["table_name"]
        if table == "packaging_records":
            continue
        found = rows(db, f'SELECT * FROM "{table}" WHERE work_order_id IN (1226,1227)')
        if found:
            result["work_dependencies"].append({"table": table, "rows": found})
    # Reject dependencies unknown to this reviewed operation, including cascades.
    result["foreign_dependencies"] = []
    refs = rows(db, """SELECT c.conrelid::regclass::text AS table_name, a.attname AS column_name,
        c.confrelid::regclass::text AS parent FROM pg_constraint c
        JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=c.conkey[1]
        WHERE c.contype='f' AND c.confrelid IN ('packages'::regclass,'packaging_records'::regclass)
        ORDER BY 1,2""")
    for ref in refs:
        table, col, parent = ref["table_name"], ref["column_name"], ref["parent"]
        if parent == "packages" and table in DELETE_COUNTS and col == "package_id":
            continue
        found = rows(db, f'SELECT * FROM "{table}" WHERE "{col}"=ANY(:ids)', ids=IDS if parent == "packages" else [23])
        if found:
            result["foreign_dependencies"].append({"table": table, "rows": found})
    return result


def validate(s):
    assert [p["id"] for p in s["packages"]] == IDS, "Package selection changed"
    assert s["production_orders"][0]["production_no"] == "PO-0287"
    for i, p in enumerate(s["packages"]):
        assert p["package_no"] == f"PKG-2026-{169+i:06d}"
        assert p["status"] == "returned_to_packaging" and p["total_quantity"] == 90
        assert p["production_batch_id"] == 152 and p["model_id"] == 8444
        assert p["packaging_department_code"] == "PKG"
        assert not any(p[k] for k in ("received_at", "received_by", "shipped_at", "sales_order_id", "quantity_shortfall", "dispatched_quantity", "dispatched_quantities", "manual_receipt_id", "legacy_receipt_id"))
    for table, count in DELETE_COUNTS.items():
        assert len(s[table]) == count, f"Changed count: {table}"
    allowed = set(DELETE_COUNTS) | {"production_orders", "work_orders", "bundles", "production_batches", "package_print_runs", "package_print_run_members"}
    for table, data in s.items():
        assert not data or table in allowed, f"Unexpected dependency: {table}"
    assert len(s["package_print_runs"]) == 1 and len(s["package_print_run_members"]) == 4
    run = s["package_print_runs"][0]
    assert run["id"] == 14 and run["run_no"] == "PRN-2026-000014"
    assert run["package_ids"] == IDS and run["returned_at"] and not run["received_at"]
    assert not run["deleted_at"] and not run["deleted_package_ids"]
    for stock in s["finished_goods_stock"]:
        assert stock["quantity"] == stock["available_qty"] == 15
        assert not stock["sold_qty"] and not stock["reserved_qty"] and not stock["sales_order_id"]
        assert stock["status"] == "available"
    for pid in IDS:
        for table, qty in (("package_items", "quantity"), ("package_batch_allocations", "quantity"), ("finished_goods_stock", "quantity")):
            assert sum(x[qty] for x in s[table] if x["package_id"] == pid) == 90
        assert sorted(x["scan_type"] for x in s["package_scan_logs"] if x["package_id"] == pid) == ["packed", "returned_to_packaging"]
    rec = s["packaging_records"][0]
    assert rec["id"] == 23 and rec["work_order_id"] == 1226 and rec["production_batch_id"] == 152
    assert rec["packed_qty"] == rec["input_qty"] == 360 and rec["damaged_qty"] == 0
    wo = {w["id"]: w for w in s["work_orders"]}
    assert set(wo) == {1224, 1225, 1226, 1227}
    assert wo[1226]["operation"] == "packaging" and wo[1226]["status"] == "completed"
    assert wo[1226]["passed_qty"] == wo[1226]["actual_output_qty"] == 360
    assert wo[1227]["operation"] == "storage_transfer" and wo[1227]["passed_qty"] == 0


def unrelated(db):
    conditions = {"packages": "production_order_id IS DISTINCT FROM 312",
                  "packaging_records": "work_order_id<>1226", "work_orders": "id NOT IN (1226,1227)",
                  "package_print_runs": "id<>14", "package_print_run_members": "true",
                  "production_orders": "true", "bundles": "true", "production_batches": "true"}
    for table in ("package_items", "package_batch_allocations", "package_scan_logs", "finished_goods_stock"):
        conditions[table] = "package_id IS NULL OR package_id NOT IN (13230,13231,13232,13233)"
    return {t: rows(db, f"SELECT count(*) AS n, md5(coalesce(string_agg(row_to_json(x)::text, '' ORDER BY id),'')) AS hash FROM (SELECT * FROM {t} WHERE {c}) x")[0] for t, c in conditions.items()}


def execute(db, before, backup):
    from app.models import PackagePrintRun, WorkOrder
    from app.services.audit import log_action
    from app.services.numbering import retire_label_numbers
    preserved = unrelated(db)
    protection = protection_state(db)
    assert protection["triggers"] and all(t["tgenabled"] == "O" for t in protection["triggers"])
    backend_pid, transaction_id = db.execute(text("SELECT pg_backend_pid(),txid_current()")).one()
    temporary = exception_definition(protection["function"], backend_pid, transaction_id)
    run = db.get(PackagePrintRun, 14)
    run.deleted_package_ids = IDS
    run.deleted_at = datetime.now(timezone.utc)
    retire_label_numbers(db, [p["package_no"] for p in before["packages"]], run.run_no)
    for table in ("finished_goods_stock", "package_scan_logs", "package_batch_allocations", "package_items"):
        res = db.execute(text(f"DELETE FROM {table} WHERE package_id=ANY(:ids)"), {"ids": IDS})
        assert res.rowcount == DELETE_COUNTS[table]
    # Transactional DDL is never committed with the exception installed. Other
    # sessions keep the original protection; this exception additionally requires
    # this exact backend PID/transaction and the reviewed retired four-pack run.
    db.execute(text(temporary))
    assert db.execute(text("DELETE FROM packages WHERE id=ANY(:ids)"), {"ids": IDS}).rowcount == 4
    db.execute(text(protection["function"]))
    assert protection_state(db) == protection, "Deletion protection was not restored"
    assert db.execute(text("DELETE FROM packaging_records WHERE id=23 AND work_order_id=1226")).rowcount == 1
    for wid, status in ((1226, "pending"), (1227, "waiting")):
        wo = db.get(WorkOrder, wid)
        wo.status = status
        for attr in ("actual_input_qty", "actual_output_qty", "passed_qty", "failed_qty", "rework_qty"):
            setattr(wo, attr, 0)
        wo.start_time = wo.end_time = None
    db.flush()
    after = snapshot(db)
    assert not any(after[t] for t in DELETE_COUNTS)
    assert unrelated(db) == preserved, "Unrelated records changed"
    old_run = dict(before["package_print_runs"][0])
    new_run = dict(after["package_print_runs"][0])
    for key in ("deleted_at", "deleted_package_ids"):
        old_run.pop(key); new_run.pop(key)
    assert old_run == new_run, "Historical manifest or return evidence changed"
    log_action(db, None, "owner_reset_po0287_packaging", "ProductionOrder", PO,
               old_value=before, new_value={"deleted": DELETE_COUNTS, "packaging_status": "pending",
               "storage_status": "waiting", "history_retained": True, "backup": backup,
               "protection_restored": True, "protection_sha256": digest(protection),
               "reason": "Owner requested deletion of incorrect packages and reset to Packaging arrival"})
    return {"deleted": DELETE_COUNTS, "packaging_status": "pending", "storage_status": "waiting", "unrelated_preserved": True, "history_preserved": True, "protection_restored": True, "protection_sha256": digest(protection)}


def main():
    from app.db.session import SessionLocal
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["inspect", "rehearse", "apply"])
    parser.add_argument("--expected")
    parser.add_argument("--backup")
    args = parser.parse_args()
    with SessionLocal() as db:
        db.execute(text("SET LOCAL lock_timeout='5s'"))
        db.execute(text("SET LOCAL statement_timeout='30s'"))
        if args.mode == "inspect":
            db.execute(text("SET TRANSACTION READ ONLY"))
        else:
            assert args.expected and args.backup and args.backup.startswith("/opt/milana-erp/shared/backups/")
            for table in sorted(set(DELETE_COUNTS) | {"work_orders", "package_print_runs", "package_print_run_members"}):
                db.execute(text(f"LOCK TABLE {table} IN SHARE ROW EXCLUSIVE MODE"))
        before = snapshot(db)
        validate(before)
        fingerprint = digest(before)
        if args.mode == "inspect":
            print(json.dumps({"fingerprint": fingerprint, "counts": DELETE_COUNTS, "before": before}, default=str))
            return
        assert fingerprint == args.expected, "Target changed after inspection"
        result = execute(db, before, args.backup)
        if args.mode == "apply":
            db.commit()
        else:
            db.rollback()
            assert digest(snapshot(db)) == fingerprint, "Rollback did not restore targets"
            assert protection_state(db)["function"] == ORIGINAL_FUNCTION
        print(json.dumps({"mode": args.mode, "fingerprint": fingerprint, **result}))


if __name__ == "__main__":
    main()
