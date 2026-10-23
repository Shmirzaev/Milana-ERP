"""One-off owner-requested warehouse reconciliation; never run at startup.

Inspect, back up, rehearse with rollback, review/commit, then apply the exact
fingerprint. Imported receipt evidence and cancelled shipment history survive.
"""
import copy
import hashlib
import json
import time
from types import SimpleNamespace

from sqlalchemy import text

from app.db.session import SessionLocal
from app.schemas.shipment_review import ShipmentReopen
from app.services.audit import _finalize_postgres_audits, log_action, verify_audit_hash_chain
from app.services.shipment_reopen import reopen_shipment


REASON = "Owner-requested warehouse reconciliation: return only Invertar shipments, remove unverified imported stock, clear physical counts"
TABLES = (
    "packages", "package_items", "package_barcode_aliases", "package_batch_allocations",
    "package_scan_logs", "finished_goods_stock", "legacy_stock_receipts",
    "manual_package_receipts", "package_print_runs", "package_print_run_members",
    "package_change_requests", "package_quantity_adjustments", "stock_reservations",
    "warehouse_pack_reservations", "warehouse_stocktakes", "warehouse_stocktake_rows",
    "shipments", "shipment_packages", "shipment_scan_logs", "sales_orders",
    "sales_order_items", "invoices", "payments", "idempotency_records",
)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def rows(db, table, condition="true"):
    return [dict(r) for r in db.execute(text(
        f'SELECT * FROM "{table}" WHERE {condition} ORDER BY id')).mappings()]


def ids_sql(values):
    assert all(isinstance(v, int) for v in values)
    return "(" + ",".join(map(str, values or [-1])) + ")"


def signature(db, table, condition="true"):
    return dict(db.execute(text(
        'SELECT count(*) AS rows, md5(coalesce(string_agg(md5(row_to_json(t)::text), '
        f"'' ORDER BY id),'')) AS hash FROM (SELECT * FROM \"{table}\" WHERE {condition}) t"
    )).mappings().one())


def prepare(db):
    assert db.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0148_second_grade_packages"
    assert rows(db, "customers", "id=28")[0]["name"] == "Invertar"
    stocktakes = rows(db, "warehouse_stocktakes")
    counted = sorted(db.execute(text("SELECT DISTINCT package_id FROM warehouse_stocktake_rows "
                                    "WHERE scanned_at IS NOT NULL AND package_id IS NOT NULL")).scalars())
    # Human receiving/placement/return/dispatch evidence always protects an old
    # pack. Import-generated events alone do not establish physical presence.
    delete = rows(db, "packages", "status='received_in_storage' AND legacy_receipt_id IS NOT NULL "
                  "AND production_order_id IS NULL AND manual_receipt_id IS NULL "
                  "AND NOT EXISTS(SELECT 1 FROM warehouse_stocktake_rows r "
                  "WHERE r.package_id=packages.id AND r.scanned_at IS NOT NULL) "
                  "AND NOT EXISTS(SELECT 1 FROM package_scan_logs s WHERE s.package_id=packages.id "
                  "AND s.scan_type NOT LIKE 'legacy_%')")
    delete_ids = [r["id"] for r in delete]
    assert delete_ids and all(not p["sales_order_id"] and not p["dispatched_quantity"]
                              and not p["dispatched_quantities"] and not p["quantity_shortfall"] for p in delete)
    shipments = rows(db, "shipments", "customer_id=28 AND status IN ('shipped','delivered') AND deleted_at IS NULL")
    assert shipments and all((s["dispatch_snapshot"] or {}).get("manual") for s in shipments)
    shipment_ids = [r["id"] for r in shipments]
    links = rows(db, "shipment_packages", "shipment_id IN " + ids_sql(shipment_ids))
    return_ids = sorted(r["package_id"] for r in links)
    assert len(set(return_ids)) == len(return_ids) and not set(delete_ids) & set(return_ids)
    order_ids = sorted(s["sales_order_id"] for s in shipments if s["sales_order_id"])
    stocks = rows(db, "finished_goods_stock", "package_id IN " + ids_sql(delete_ids))
    assert stocks and sum(r["quantity"] for r in stocks) == sum(p["total_quantity"] for p in delete)
    assert all(r["available_qty"] == r["quantity"] and not r["reserved_qty"] and not r["sold_qty"] for r in stocks)
    stock_ids = [r["id"] for r in stocks]
    # Discover every real FK; unexpected dependencies stop the entire operation.
    foreign_keys = db.execute(text("SELECT tc.table_name,kcu.column_name,ccu.table_name target "
        "FROM information_schema.table_constraints tc JOIN information_schema.key_column_usage kcu "
        "ON tc.constraint_name=kcu.constraint_name AND tc.constraint_schema=kcu.constraint_schema "
        "JOIN information_schema.constraint_column_usage ccu ON ccu.constraint_name=tc.constraint_name "
        "AND ccu.constraint_schema=tc.constraint_schema WHERE tc.constraint_type='FOREIGN KEY' "
        "AND tc.table_schema='public' AND ccu.table_name IN ('packages','finished_goods_stock')")).mappings()
    allowed = {"package_items", "package_scan_logs", "package_barcode_aliases", "finished_goods_stock"}
    for fk in foreign_keys:
        selected = delete_ids if fk["target"] == "packages" else stock_ids
        if fk["table_name"] not in allowed:
            assert not db.execute(text(f'SELECT 1 FROM "{fk["table_name"]}" WHERE '
                f'"{fk["column_name"]}" IN {ids_sql(selected)} LIMIT 1')).first(), dict(fk)
    for table in ("shipment_scan_logs", "package_quantity_adjustments", "package_print_run_members", "package_change_requests"):
        assert not rows(db, table, "package_id IN " + ids_sql(delete_ids)), table
    invoice_ids = [r["id"] for r in rows(db, "invoices", "sales_order_id IN " + ids_sql(order_ids))]
    plan = {"delete_ids": delete_ids, "return_ids": return_ids, "shipment_ids": shipment_ids,
            "order_ids": order_ids, "invoice_ids": invoice_ids,
            "count_ids": [s["id"] for s in stocktakes], "counted_ids": counted}
    summary = {"delete_packs": len(delete), "delete_pieces": sum(p["total_quantity"] for p in delete),
               "return_packs": len(return_ids), "return_pieces": sum(r["quantity"] for r in links),
               "return_shipments": len(shipments), "void_invoices": len(invoice_ids),
               "clear_counts": len(stocktakes),
               "clear_count_rows": signature(db, "warehouse_stocktake_rows")["rows"],
               "keep_existing_storage_packs": db.execute(text("SELECT count(*) FROM packages "
                   "WHERE status='received_in_storage'")).scalar_one() - len(delete)}
    # Bind approval to the affected records. Unrelated live Packaging activity
    # must survive and must not make an otherwise identical reviewed plan stale.
    both = ids_sql(delete_ids + return_ids)
    selected_orders, selected_shipments = ids_sql(order_ids), ids_sql(shipment_ids)
    conditions = {t: "false" for t in TABLES}
    for table in ("package_items", "package_barcode_aliases", "package_batch_allocations", "package_scan_logs",
                  "finished_goods_stock", "package_change_requests", "package_quantity_adjustments",
                  "stock_reservations", "warehouse_pack_reservations", "package_print_run_members"):
        conditions[table] = f"package_id IN {both}"
    conditions.update(packages=f"id IN {both}", shipments=f"id IN {selected_shipments}",
        shipment_packages=f"package_id IN {both} OR shipment_id IN {selected_shipments}",
        shipment_scan_logs=f"package_id IN {both} OR shipment_id IN {selected_shipments}",
        sales_orders=f"id IN {selected_orders}", sales_order_items=f"sales_order_id IN {selected_orders}",
        invoices=f"sales_order_id IN {selected_orders}", payments="invoice_id IN " + ids_sql(invoice_ids),
        warehouse_stocktakes="true", warehouse_stocktake_rows="true",
        legacy_stock_receipts=f"id IN (SELECT legacy_receipt_id FROM packages WHERE id IN {both})",
        idempotency_records="scope LIKE 'shipments.%'")
    fingerprints = {t: signature(db, t, conditions[t]) for t in TABLES}
    return {"plan": plan, "summary": summary, "fingerprints": fingerprints,
            "fingerprint": digest({"plan": plan, "fingerprints": fingerprints})}


def protected_signatures(db, plan, audit_max):
    d, r, s, o, i = (ids_sql(plan[k]) for k in
                    ("delete_ids", "return_ids", "shipment_ids", "order_ids", "invoice_ids"))
    filters = {"packages": f"id NOT IN {d} AND id NOT IN {r}",
               "finished_goods_stock": f"package_id IS NULL OR (package_id NOT IN {d} AND package_id NOT IN {r})",
               "package_items": f"package_id NOT IN {d}",
               "package_barcode_aliases": f"package_id NOT IN {d}",
               "package_scan_logs": f"package_id NOT IN {d}",
               "shipments": f"id NOT IN {s}", "sales_orders": f"id NOT IN {o}",
               "invoices": f"id NOT IN {i}"}
    scan_max = db.execute(text("SELECT coalesce(max(id),0) FROM package_scan_logs")).scalar_one()
    filters["package_scan_logs"] += f" AND id<={scan_max}"
    result = {t: signature(db, t, filters.get(t, "true")) for t in TABLES
              if t not in {"warehouse_stocktakes", "warehouse_stocktake_rows", "idempotency_records"}}
    result["audit_logs"] = signature(db, "audit_logs", f"id<={audit_max}")
    return result, scan_max


def assert_row_changes(before, after, allowed):
    assert [r["id"] for r in before] == [r["id"] for r in after]
    for old, new in zip(before, after):
        assert {k:v for k,v in old.items() if k not in allowed} == {
            k:v for k,v in new.items() if k not in allowed}, (old["id"], allowed)


def execute(db, inspection, backup):
    plan, summary = inspection["plan"], inspection["summary"]
    d, r, s, o, i = (ids_sql(plan[k]) for k in
                    ("delete_ids", "return_ids", "shipment_ids", "order_ids", "invoice_ids"))
    audit_max = db.execute(text("SELECT coalesce(max(id),0) FROM audit_logs")).scalar_one()
    protected, scan_max = protected_signatures(db, plan, audit_max)
    before_packages = rows(db, "packages", f"id IN {r}")
    before_stock = rows(db, "finished_goods_stock", f"package_id IN {r}")
    before_orders = rows(db, "sales_orders", f"id IN {o}")
    before_invoices = rows(db, "invoices", f"id IN {i}")
    before_shipments = rows(db, "shipments", f"id IN {s}")
    before_retries = rows(db, "idempotency_records")
    expected_retries = copy.deepcopy(before_retries)
    links = rows(db, "shipment_packages", f"shipment_id IN {s}")
    actor = SimpleNamespace(id=None)
    for old in before_shipments:
        own_ids = {link["package_id"] for link in links if link["shipment_id"] == old["id"]}
        for retry in expected_retries:
            response = retry["response_json"] or {}
            scope = retry["scope"]
            if scope.startswith("shipments.") and (response.get("shipment_id") == old["id"]
                    or response.get("id") == old["id"] or ((scope == "shipments.scan-package"
                    or scope.startswith("shipments.scan-package:v2:")) and response.get("package_id") in own_ids)):
                retry["request_hash"] = hashlib.sha256(("shipment-reopened:" + retry["request_hash"]).encode()).hexdigest()
        shipment = reopen_shipment(db, old["id"], ShipmentReopen(
            expected_shipped_at=old["shipped_at"], packages_returned=True, reason=REASON), actor)
        # Preserve the original links/scans for history, while releasing every
        # pack from active dispatch claims. Do not create new preparation work.
        assert shipment.sales_order_id is None
        shipment.status = "cancelled"
        log_action(db, None, "cancel_returned_invertar_shipment", "Shipment", shipment.id,
                   old_value={"status": "created"}, new_value={"status": "cancelled", "reason": REASON})
    db.flush()
    after_packages = rows(db, "packages", f"id IN {r}")
    assert_row_changes(before_packages, after_packages,
                       {"status", "shipped_at", "dispatched_quantity", "dispatched_quantities", "updated_at"})
    assert all(p["status"] == "received_in_storage" and p["shipped_at"] is None
               and p["dispatched_quantity"] == 0 and p["dispatched_quantities"] == {} for p in after_packages)
    assert not db.execute(text("SELECT 1 FROM shipment_packages sp JOIN shipments s "
        f"ON s.id=sp.shipment_id WHERE sp.package_id IN {r} AND s.status!='cancelled' "
        "AND s.deleted_at IS NULL LIMIT 1")).first(), "Returned pack remains claimed by a live shipment"
    from app.services.package_identity import resolve_warehouse_package
    sample = after_packages[::max(1, len(after_packages)//20)]
    for package in sample:
        assert resolve_warehouse_package(db, package["barcode"]) == (package["id"], False)
    expected_stock = copy.deepcopy(before_stock)
    for stock in expected_stock:
        stock.update(available_qty=stock["quantity"], sold_qty=0, reserved_qty=0, status="available")
    after_stock = rows(db, "finished_goods_stock", f"package_id IN {r}")
    assert_row_changes(expected_stock, after_stock, {"updated_at"})
    assert sum(x["quantity"] for x in after_stock) == summary["return_pieces"]
    for table, before, condition, allowed in (
        ("shipments", before_shipments, f"id IN {s}",
         {"status", "shipped_at", "delivered_at", "sales_order_id", "dispatch_snapshot", "updated_at"}),
        ("sales_orders", before_orders, f"id IN {o}", {"status", "total_amount", "updated_at"}),
        ("invoices", before_invoices, f"id IN {i}", {"status", "amount", "updated_at"}),
    ):
        after = rows(db, table, condition)
        assert_row_changes(before, after, allowed)
        if table == "shipments":
            assert all(x["status"] == "cancelled" and x["shipped_at"] is None
                       and x["delivered_at"] is None and x["sales_order_id"] is None for x in after)
            for old, new in zip(before, after):
                selection = (old["dispatch_snapshot"] or {}).get("package_quantities", {})
                assert new["dispatch_snapshot"] == ({"manual": True, "package_quantities": selection}
                    if selection else {"manual": True})
        elif table == "sales_orders":
            assert all(x["status"] == "cancelled" and x["total_amount"] == 0 for x in after)
        else:
            assert all(x["status"] == "void" and x["amount"] == 0 for x in after)
    assert_row_changes(expected_retries, rows(db, "idempotency_records"), {"updated_at"})
    # Only never-used imported packs are physically deleted. Receipt source rows
    # remain immutable and prevent silent reimport of the removed balances.
    deleted_rows = {}
    for table in ("finished_goods_stock", "package_scan_logs", "package_items", "package_barcode_aliases"):
        deleted_rows[table] = db.execute(text(f'DELETE FROM "{table}" WHERE package_id IN {d}')).rowcount
    deleted_rows["packages"] = db.execute(text(f"DELETE FROM packages WHERE id IN {d}")).rowcount
    assert deleted_rows["packages"] == summary["delete_packs"]
    # Scan evidence has already determined and fingerprinted the keep list.
    deleted_rows["warehouse_stocktake_rows"] = db.execute(text("DELETE FROM warehouse_stocktake_rows "
        "WHERE stocktake_id IN " + ids_sql(plan["count_ids"]))).rowcount
    deleted_rows["warehouse_stocktakes"] = db.execute(text("DELETE FROM warehouse_stocktakes WHERE id IN "
        + ids_sql(plan["count_ids"]))).rowcount
    assert deleted_rows["warehouse_stocktake_rows"] == summary["clear_count_rows"]
    assert signature(db, "warehouse_stocktakes")["rows"] == signature(db, "warehouse_stocktake_rows")["rows"] == 0
    again, _ = protected_signatures(db, plan, audit_max)
    # New return scan events are appended, never rewritten.
    again["package_scan_logs"] = signature(db, "package_scan_logs", f"package_id NOT IN {d} AND id<={scan_max}")
    assert protected == again, "Protected warehouse/history rows changed"
    new_scans = rows(db, "package_scan_logs", f"id>{scan_max}")
    assert sorted(x["package_id"] for x in new_scans) == plan["return_ids"]
    assert all(x["scan_type"] == "returned" for x in new_scans)
    remaining = db.execute(text("SELECT count(*) packs,sum(total_quantity) pieces FROM packages "
                                "WHERE status='received_in_storage'")).mappings().one()
    assert remaining["packs"] == summary["keep_existing_storage_packs"] + summary["return_packs"]
    entry = log_action(db, None, "warehouse_cleanup_invertar_20261023", "Warehouse", None,
        old_value={"fingerprint": inspection["fingerprint"], "plan": plan, "summary": summary},
        new_value={"reason": REASON, "backup": backup, "deleted_rows": deleted_rows,
                   "remaining_storage": dict(remaining), "receipt_and_shipment_history_preserved": True})
    return {"summary": summary, "deleted_rows": deleted_rows, "remaining_storage": dict(remaining),
            "audit_start": audit_max+1, "protected_fingerprint": digest(protected)}, entry


def run(mode, expected=None, backup=None):
    assert mode in {"inspect", "rehearse", "apply"}
    started = time.monotonic()
    with SessionLocal() as db:
        db.execute(text("SET LOCAL lock_timeout='5s'"))
        db.execute(text("SET LOCAL statement_timeout='90s'"))
        if mode == "inspect":
            db.execute(text("SET TRANSACTION READ ONLY"))
        else:
            db.execute(text("LOCK TABLE " + ",".join(TABLES) + " IN SHARE ROW EXCLUSIVE MODE"))
        inspection = prepare(db)
        if mode == "inspect":
            db.rollback()
            return inspection
        assert expected == inspection["fingerprint"], "Data changed; inspect/rehearse again"
        assert backup and backup["bytes"] > 0 and backup["restore_objects"] > 100
        assert backup["mode"] == "0o600" and len(backup["sha256"]) == 64
        result, entry = execute(db, inspection, backup)
        # Exercise the same before-commit audit finalizer during rehearsal, so
        # audit insertion/hash failures are caught before applying business data.
        _finalize_postgres_audits(db)
        result["audit_id"] = entry.id
        chain = verify_audit_hash_chain(db, start_id=result["audit_start"])
        assert chain["ok"], chain
        result["new_audit_chain"] = chain
        assert time.monotonic() - started < 180, "Maintenance exceeded its time budget"
        if mode == "rehearse":
            db.rollback()
            assert prepare(db)["fingerprint"] == expected, "Rollback fingerprint mismatch"
            db.rollback()
            return {**result, "rollback_verified": True, "fingerprint": expected}
        db.commit()
        result.update(applied=True, new_audit_chain=verify_audit_hash_chain(db, start_id=result["audit_start"]))
        db.rollback()
        return result
