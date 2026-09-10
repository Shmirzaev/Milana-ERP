"""One-off screenshot-scoped cleanup. Default mode only checks and rolls back."""
import hashlib
import json
import sys

from sqlalchemy import text
from app.db.session import SessionLocal
from app.services.audit import log_action, verify_audit_hash_chain

NUMBERS = list(range(3, 14)) + list(range(15, 23)) + list(range(25, 32)) + [33, 34, 35, 40, 47]
NAMES = [f"PUR-{n:04d}" for n in NUMBERS]
EXPECTED_DIGEST = "942add2aad3bf521984f68fbb855c1f8894cf39cc52eeafa7cfc961def6f8fd9"
BACKUP = "/opt/milana-erp/shared/backups/pre_delete_marked_purchases_20260910_113715.dump"
BACKUP_SHA256 = "6dca6888d5f4e99f8e51e25b31836d5867c3c401748806d8c03a785ea7888443"


def digest(value):
    return hashlib.sha256(json.dumps(value, default=str, sort_keys=True).encode()).hexdigest()


def rows(db, sql, params=None):
    return [dict(row) for row in db.execute(text(sql), params or {}).mappings()]


def run(apply=False):
    with SessionLocal() as db:
        db.execute(text("SET LOCAL lock_timeout='5s'"))
        db.execute(text("SET LOCAL statement_timeout='30s'"))
        protected = ["purchase_requests", "purchase_request_lines", "stock_batches", "stock_movements",
                     "material_reservations", "items", "suppliers", "tasks"]
        changed = ["purchase_orders", "purchase_order_lines", "business_order_aliases"]
        db.execute(text("LOCK TABLE " + ", ".join(sorted(protected + changed + ["audit_logs"]))
                        + " IN SHARE ROW EXCLUSIVE MODE"))
        assert db.execute(text("select version_num from alembic_version")).scalar_one() == "0122_cutting_material_details"
        selected = rows(db, """select p.id,p.po_no,p.status,p.purchase_request_id,
            s.name supplier,p.expected_date,l.id line_id,l.item_id,i.name item,
            l.ordered_quantity,l.received_quantity,l.photo_url,r.sales_order_id,r.production_order_id
            from purchase_orders p join purchase_order_lines l on l.purchase_order_id=p.id
            left join suppliers s on s.id=p.supplier_id left join items i on i.id=l.item_id
            left join purchase_requests r on r.id=p.purchase_request_id
            where p.po_no=ANY(:names) order by p.po_no,l.id""", {"names": NAMES})
        assert len(selected) == 31 and digest(selected) == EXPECTED_DIGEST, "Reviewed order snapshot changed"
        assert all(r["status"] == "sent" and r["received_quantity"] == 0
                   and r["sales_order_id"] is None and r["production_order_id"] is None for r in selected)
        ids = [r["id"] for r in selected]
        line_ids = [r["line_id"] for r in selected]
        params = {"ids": ids, "line_ids": line_ids, "all_ids": sorted(set(ids + line_ids)),
                  "names": NAMES + [f"PUR-2026-{n:06d}" for n in NUMBERS]}
        assert not rows(db, """select id from stock_movements where
            reference_type ilike '%purchase%' and reference_id=ANY(:all_ids)""", params), "Linked receipt/movement"
        assert not rows(db, """select id from stock_batches where batch_no=ANY(:names)
            or internal_batch_no=ANY(:names) or order_no=ANY(:names)""", params), "Linked stock batch"
        assert not rows(db, """select id from tasks where entity_type ilike '%purchase%'
            and entity_id=ANY(:all_ids)""", params), "Linked business task"
        fks = rows(db, """select conrelid::regclass::text source,pg_get_constraintdef(oid) definition
            from pg_constraint where contype='f' and confrelid in
            ('purchase_orders'::regclass,'purchase_order_lines'::regclass)""")
        assert fks == [{"source": "purchase_order_lines", "definition": "FOREIGN KEY (purchase_order_id) REFERENCES purchase_orders(id)"}], "Unexpected dependent table"
        snapshots = {
            "purchase_orders": rows(db, "select * from purchase_orders where id=ANY(:ids) order by id", params),
            "purchase_order_lines": rows(db, "select * from purchase_order_lines where id=ANY(:line_ids) order by id", params),
            "business_order_aliases": rows(db, "select * from business_order_aliases where namespace='PUR' and entity_id=ANY(:ids) order by id", params),
        }
        assert len(snapshots["business_order_aliases"]) == 31
        predicates = {"purchase_orders": "not (id=ANY(:ids))",
                      "purchase_order_lines": "not (id=ANY(:line_ids))",
                      "business_order_aliases": "not (namespace='PUR' and entity_id=ANY(:ids))"}

        def retained_fingerprints():
            return {table: rows(db, "select count(*) n, md5(coalesce(string_agg(md5(to_jsonb(t)::text),'' order by id),'')) hash from "
                                + table + " t where " + predicates.get(table, "true"), params)[0]
                    for table in protected + changed}

        before = retained_fingerprints()
        result = {"mode": "apply" if apply else "dry-run", "orders": NAMES,
                  "counts": {k: len(v) for k, v in snapshots.items()},
                  "ordered_kg": str(sum(r["ordered_quantity"] for r in selected)),
                  "snapshot_sha256": digest(selected), "backup": BACKUP,
                  "retained_fingerprints": before}
        if not apply:
            db.rollback()
            print(json.dumps(result, default=str, indent=2))
            return
        for table in ["business_order_aliases", "purchase_order_lines", "purchase_orders"]:
            where = {"business_order_aliases": "namespace='PUR' and entity_id=ANY(:ids)",
                     "purchase_order_lines": "id=ANY(:line_ids)", "purchase_orders": "id=ANY(:ids)"}[table]
            count = db.execute(text("delete from " + table + " where " + where), params).rowcount
            assert count == 31, (table, count)
        assert retained_fingerprints() == before, "Unrelated data changed"
        audit = log_action(db, None, "delete_marked_purchase_orders", "PurchaseOrder", None,
                           old_value=snapshots,
                           new_value={"reason": "User requested removal of fabrics marked in ten screenshots on 2026-09-10",
                                      "orders": NAMES, "backup": BACKUP, "backup_sha256": BACKUP_SHA256,
                                      "snapshot_sha256": EXPECTED_DIGEST, "inventory_preserved": True})
        result["audit_id"] = audit.id
        result["audit_check"] = verify_audit_hash_chain(db, start_id=audit.id)
        assert result["audit_check"]["ok"]
        result["remaining_active"] = rows(db, "select po_no from purchase_orders where status in ('sent','approved','partially_received') order by po_no")
        assert len(result["remaining_active"]) == 13
        db.commit()
        print(json.dumps(result, default=str, indent=2))


if __name__ == "__main__":
    run("--apply" in sys.argv)
