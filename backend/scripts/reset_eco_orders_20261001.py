"""One-time reviewed Eco Cotton reset. Dry-run by default; never resets sequences.

Only the six reviewed Usluga orders and their exclusively owned operational rows
are eligible. Warehouse, finance, payroll, inventory and unexpected links block
the transaction. Historical audit and pre-existing orphan movement evidence stay.
"""
import argparse
import hashlib
import json
import re

from sqlalchemy import Table, inspect, select, text

from app.db.base import Base
from app.db.session import SessionLocal
import app.models  # noqa: F401
from app.services.audit import log_action


ORDER_NUMBERS = [f"USL-{n:04}" for n in range(1, 7)]
ALLOWED = {
    "production_orders", "production_order_items", "production_batches", "work_orders",
    "bundles", "bundle_scan_logs", "cutting_records", "sewing_records",
    "sewing_assignments", "packaging_records", "packages", "package_items",
    "package_batch_allocations", "package_scan_logs",
}
ENTITY_TABLES = {
    "ProductionOrder": "production_orders", "WorkOrder": "work_orders",
    "CuttingRecord": "cutting_records", "PackagingRecord": "packaging_records",
    "Bundle": "bundles", "Package": "packages",
}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()


def read_rows(db, table, condition=None):
    query = select(table).order_by(table.c.id)
    if condition is not None:
        query = query.where(condition)
    return [dict(row) for row in db.execute(query).mappings()]


def prepare(db):
    tables = Base.metadata.tables
    po = tables["production_orders"]
    orders = read_rows(db, po, po.c.production_no.in_(ORDER_NUMBERS))
    if sorted(r["production_no"] for r in orders) != ORDER_NUMBERS:
        raise ValueError("Reviewed order selection changed")
    if any(r["source_type"] != "usluga" or r["sales_order_id"] or r["planning_order_id"] or r["fabric_batch_id"] for r in orders):
        raise ValueError("Only independent Eco Cotton Usluga orders are supported")
    selected = {"production_orders": {r["id"] for r in orders}}
    work = tables["work_orders"]
    departments_table = tables["departments"]
    flows_table = tables["sewing_flows"]
    bundles = tables["bundles"]
    eco_work = select(work.c.production_order_id).where(
        work.c.department_id.in_(select(departments_table.c.id).where(departments_table.c.code.in_(["ECT", "ECO", "ECP"])))
        | work.c.sewing_flow_id.in_(select(flows_table.c.id).where(flows_table.c.factory_code == "ECO"))
    )
    all_eco = set(db.execute(select(po.c.id).where(
        (po.c.source_type == "usluga") | po.c.id.in_(eco_work)
        | po.c.id.in_(select(bundles.c.production_order_id).where(bundles.c.sewing_factory_code == "ECO"))
    )).scalars())
    if all_eco != selected["production_orders"]:
        raise ValueError("Eco Cotton order selection changed")
    # Discover actual database references, including any future/unmapped tables.
    inspector = inspect(db.connection())
    links = []
    for name in inspector.get_table_names():
        for fk in inspector.get_foreign_keys(name):
            links.append((name, fk["constrained_columns"], fk["referred_table"], fk["referred_columns"]))
    changed = True
    while changed:
        changed = False
        for child, columns, parent, parent_columns in links:
            if parent not in selected:
                continue
            if len(columns) != 1 or parent_columns != ["id"]:
                raise ValueError(f"Unsupported dependency: {child}")
            if child not in tables:
                Table(child, Base.metadata, autoload_with=db.connection())
            table = tables[child]
            rows = db.execute(select(table.c.id).where(table.c[columns[0]].in_(selected[parent]))).scalars().all()
            if not rows:
                continue
            if child not in ALLOWED:
                raise ValueError(f"Protected dependency: {child}")
            before = selected.setdefault(child, set()).copy()
            selected[child].update(rows)
            changed |= selected[child] != before
    snapshot = {name: read_rows(db, tables[name], tables[name].c.id.in_(ids)) for name, ids in sorted(selected.items())}
    departments = {r["id"]: r["code"] for r in read_rows(db, tables["departments"])}
    flows = {r["id"]: r["factory_code"] for r in read_rows(db, tables["sewing_flows"])}
    for row in snapshot.get("work_orders", []):
        if departments.get(row["department_id"]) not in {"ECT", "ECO", "ECP"}:
            raise ValueError("Cross-factory work order")
    for name, rows in snapshot.items():
        for row in rows:
            if row.get("sewing_flow_id") and flows.get(row["sewing_flow_id"]) != "ECO":
                raise ValueError("Cross-factory sewing flow")
            for child, columns, parent, _ in links:
                if child == name and parent in selected and row.get(columns[0]) is not None and row[columns[0]] not in selected[parent]:
                    raise ValueError("Dependency shared with another order")
    for row in snapshot.get("bundles", []):
        if row["sewing_factory_code"] != "ECO":
            raise ValueError("Cross-factory bundle")
    for row in snapshot.get("packages", []):
        if row["packaging_department_code"] != "ECP" or row["status"] != "packed" or any(row.get(k) for k in ["warehouse_id", "received_at", "shipped_at", "sales_order_id", "legacy_receipt_id", "manual_receipt_id"]):
            raise ValueError("Package has warehouse or external evidence")
    for row in snapshot.get("cutting_records", []):
        if row["fabric_batch_id"] or row.get("cutting_passport_id"):
            raise ValueError("Cutting is linked to inventory or a passport")
    # Polymorphic references are not represented by database foreign keys.
    for name, type_key, id_key in [("tasks", "entity_type", "entity_id"), ("stock_movements", "reference_type", "reference_id")]:
        for row in read_rows(db, tables[name]):
            target = ENTITY_TABLES.get(row[type_key])
            if not target or row[id_key] not in selected.get(target, set()):
                continue
            original = next(r for r in snapshot[target] if r["id"] == row[id_key])
            if name == "stock_movements" and str(row["created_at"]) < str(original["created_at"]):
                continue  # Old orphan IDs predate these orders; never reverse or delete them.
            raise ValueError(f"Protected soft dependency: {name}")
    for name in ["payroll_records", "payroll_qr_labels", "sewing_daily_reports", "cutting_passports"]:
        table = tables[name]
        for column in ["production_no", "order_no"]:
            if column in table.c and db.execute(select(table.c.id).where(table.c[column].in_(ORDER_NUMBERS))).first():
                raise ValueError(f"Protected order-number dependency: {name}")
    patterns = [rf"/{path}/(?:{'|'.join(map(str, sorted(selected.get(name, []))))})(?:/|\?|$)"
                for path, name in [("production-orders", "production_orders"), ("work-orders", "work_orders"), ("packages", "packages"), ("bundles", "bundles")] if selected.get(name)]
    for row in read_rows(db, tables["notifications"]):
        if any(re.search(pattern, row["link"] or "") for pattern in patterns):
            raise ValueError("Linked notification requires review")
    def references(value, scope):
        if isinstance(value, list):
            return any(references(v, scope) for v in value)
        if not isinstance(value, dict):
            return value in ORDER_NUMBERS if isinstance(value, str) else False
        targets = {"production_order_id": "production_orders", "work_order_id": "work_orders", "cutting_record_id": "cutting_records", "package_id": "packages", "production_batch_id": "production_batches"}
        if scope == "cutting.records.create":
            targets["id"] = "cutting_records"
        return any((key in targets and isinstance(v, int) and v in selected.get(targets[key], set())) or references(v, scope) for key, v in value.items())
    for row in read_rows(db, tables["idempotency_records"]):
        if references(row["response_json"], row["scope"]):
            raise ValueError("Linked idempotency response requires review")
    # Delete leaves first; refuse cycles instead of disabling integrity checks.
    remaining = set(selected)
    deletion_order = []
    while remaining:
        leaves = sorted(name for name in remaining if not any(parent == name and child in remaining and child != name for child, _, parent, _ in links))
        if not leaves:
            raise ValueError("Cyclic deletion graph")
        deletion_order.extend(leaves)
        remaining.difference_update(leaves)
    return snapshot, digest(snapshot), deletion_order


def apply_reviewed(db, expected):
    snapshot, fingerprint, deletion_order = prepare(db)
    if fingerprint != expected:
        raise ValueError("Reviewed fingerprint changed")
    tables = Base.metadata.tables
    # Check full-row preservation of every untargeted row in affected tables,
    # plus inventory/payroll/catalog/employee/flow data through the transaction.
    protected = set(snapshot) | {"models", "employees", "sewing_flows", "stock_batches", "stock_movements", "finished_goods_stock", "payroll_records", "payroll_qr_labels", "payroll_periods", "payroll_adjustments"}
    before = {}
    for name in protected:
        ids = [r["id"] for r in snapshot.get(name, [])]
        before[name] = digest(read_rows(db, tables[name], ~tables[name].c.id.in_(ids)))
    for name in deletion_order:
        ids = [r["id"] for r in snapshot[name]]
        result = db.execute(tables[name].delete().where(tables[name].c.id.in_(ids)))
        if result.rowcount != len(ids):
            raise ValueError("Deletion count changed")
    for name in protected:
        if digest(read_rows(db, tables[name])) != before[name]:
            raise ValueError(f"Unrelated rows changed: {name}")
    summary = {"factory": "ECO", "orders": ORDER_NUMBERS, "deleted": {name: len(rows) for name, rows in snapshot.items()}, "fingerprint": fingerprint, "protected_fingerprints": before}
    entry = log_action(db, None, "eco_order_reset_20261001", "ProductionOrder", old_value=snapshot, new_value=summary)
    summary["audit_id"] = entry.id
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--fingerprint")
    args = parser.parse_args()
    if args.apply and not args.fingerprint:
        parser.error("--apply requires a reviewed fingerprint and a verified external backup")
    with SessionLocal() as db:
        if db.bind.dialect.name == "postgresql":
            db.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            db.execute(text("SET LOCAL lock_timeout = '5s'"))
            db.execute(text("SET LOCAL statement_timeout = '60s'"))
            if args.apply:
                db.execute(text('LOCK TABLE ' + ','.join(sorted(ALLOWED | {"audit_logs"})) + ' IN SHARE ROW EXCLUSIVE MODE'))
            else:
                db.execute(text("SET TRANSACTION READ ONLY"))
        if args.apply:
            result = apply_reviewed(db, args.fingerprint)
            db.commit()
        else:
            snapshot, fingerprint, _ = prepare(db)
            result = {"fingerprint": fingerprint, "orders": ORDER_NUMBERS, "counts": {name: len(rows) for name, rows in snapshot.items()}}
            db.rollback()
        print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
