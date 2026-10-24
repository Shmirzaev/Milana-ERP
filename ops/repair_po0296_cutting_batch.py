"""Owner-authorized PO-0296 batch-link correction; default is a rollback rehearsal.

Run inside the verified production application only after a fresh verified backup.
Pass APPLY=True for rehearsal and COMMIT=True only for the authorized final run.
Never changes a piece count, barcode, scan, material usage or existing audit row.
"""
import hashlib
import json

from sqlalchemy import func, select, text

from app.core.deps import user_permissions
from app.db.base import Base
from app.db.session import SessionLocal
from app.models import AuditLog, Bundle, CuttingRecord, ProductionBatch, ProductionOrder, User, WorkOrder
from app.models.audit_service import _finalize_postgres_audits, log_action, verify_audit_hash_chain
from app.models.factory_scope_service import require_work_order_factory_access

APPLY = globals().get("APPLY", False)
COMMIT = globals().get("COMMIT", False)
BUNDLE_IDS = list(range(9418, 9424))


def rows(db, name, condition):
    table = Base.metadata.tables[name]
    return [dict(r._mapping) for r in db.execute(select(table).where(condition).order_by(*table.primary_key.columns))]


def fingerprint(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return {"count": len(value), "sha256": hashlib.sha256(raw).hexdigest()}


def audit_prefix(db, cutoff):
    return tuple(db.execute(text("SELECT count(*),md5(coalesce(string_agg(md5(row_to_json(a)::text),'' ORDER BY a.id),'')) FROM audit_logs a WHERE id<=:cutoff"), {"cutoff": cutoff}).one())


def snapshot(db):
    """Protect all order/work-order rows, exact bundles and their dependent evidence."""
    tables = Base.metadata.tables
    conditions = {}
    for name, table in tables.items():
        if name == "audit_logs":
            continue
        clauses = []
        if name == "production_orders":
            clauses.append(table.c.id == 321)
        if "production_order_id" in table.c:
            clauses.append(table.c.production_order_id == 321)
        if "work_order_id" in table.c:
            clauses.append(table.c.work_order_id.in_([1260, 1261, 1262, 1263]))
        for fk in table.foreign_keys:
            if fk.column.table.name == "bundles":
                clauses.append(fk.parent.in_(BUNDLE_IDS))
            if fk.column.table.name == "cutting_records":
                clauses.append(fk.parent == 319)
            if fk.column.table.name == "production_batches":
                clauses.append(fk.parent.in_([180, 186]))
        if name == "stock_movements":
            clauses.append((table.c.reference_type == "CuttingRecord") & (table.c.reference_id == 319))
        if clauses:
            from sqlalchemy import or_
            conditions[name] = or_(*clauses)
    data = {name: rows(db, name, condition) for name, condition in conditions.items()}
    stock_ids = {r["fabric_batch_id"] for r in data["cutting_records"] if r.get("fabric_batch_id")}
    for name in ("cutting_material_usages", "cutting_beika_material_usages", "material_reservations"):
        stock_ids.update(r["stock_batch_id"] for r in data.get(name, []) if r.get("stock_batch_id"))
    data["stock_batches"] = rows(db, "stock_batches", tables["stock_batches"].c.id.in_(stock_ids))
    return data


def normalized(data):
    data = {name: [dict(row) for row in values] for name, values in data.items()}
    for name in ("cutting_records", "bundles"):
        for row in data[name]:
            assert (name == "cutting_records" and row["id"] == 319) or (name == "bundles" and row["id"] in BUNDLE_IDS)
            assert row["production_batch_id"] in (180, 186)
            row["production_batch_id"] = 180
            row.pop("updated_at", None)
    return {name: fingerprint(values) for name, values in data.items()}


with SessionLocal() as db:
    if APPLY:
        db.execute(text("SET LOCAL lock_timeout='5s'"))
        db.execute(text("SET LOCAL statement_timeout='60s'"))
    else:
        db.execute(text("SET TRANSACTION READ ONLY"))
    def locked(query, model):
        return query.with_for_update(of=model, nowait=True) if APPLY else query
    order = locked(db.query(ProductionOrder).filter_by(id=321), ProductionOrder).one()
    assert order.production_no == "PO-0296" and order.status == "sewing"
    works = locked(db.query(WorkOrder).filter_by(production_order_id=321).order_by(WorkOrder.id), WorkOrder).all()
    assert {w.id for w in works} == {1260, 1261, 1262, 1263}
    cutting = next(w for w in works if w.id == 1260)
    assert cutting.operation == "cutting" and cutting.passed_qty == cutting.actual_output_qty == 486
    assert all(w.actual_output_qty == w.passed_qty == 0 for w in works if w.operation != "cutting")
    batches = locked(db.query(ProductionBatch).filter(ProductionBatch.id.in_([180, 186])).order_by(ProductionBatch.id), ProductionBatch).all()
    assert [(b.id, b.production_order_id, b.batch_no, b.planned_quantity) for b in batches] == [(180, 321, "0321-01", 486), (186, 321, "0321-02", 0)]
    record = locked(db.query(CuttingRecord).filter_by(work_order_id=1260), CuttingRecord).one()
    assert record.id == 319 and record.production_batch_id == 186
    assert record.cut_pieces == record.passed_pieces == 486 and record.defective_pieces == 0
    bundles = locked(db.query(Bundle).filter_by(production_order_id=321).order_by(Bundle.id), Bundle).all()
    assert [b.id for b in bundles] == BUNDLE_IDS
    assert all(b.production_batch_id == 186 and b.cutting_record_id == 319 and b.quantity == 81 for b in bundles)
    # Stop if either batch gains any additional scoped/downstream activity.
    for table in Base.metadata.tables.values():
        if table.name in ("bundles", "cutting_records"):
            continue
        for fk in table.foreign_keys:
            if fk.column.table.name == "production_batches":
                assert not db.execute(select(fk.parent).where(fk.parent.in_([180, 186])).limit(1)).first(), table.name
    actor = next(u for u in db.query(User).filter_by(is_active=True) if "*" in user_permissions(u))
    require_work_order_factory_access(actor, db, cutting)
    before = snapshot(db)
    cutoff = db.query(func.max(AuditLog.id)).scalar()
    prefix = audit_prefix(db, cutoff)
    result = {"order": "PO-0296", "apply": APPLY, "committed": bool(APPLY and COMMIT), "from_batch": "0321-02", "to_batch": "0321-01", "pieces": 486, "bundles": 6, "audit_cutoff": cutoff, "audit_prefix_count": prefix[0], "audit_prefix_hash": prefix[1], "preserved": normalized(before)}
    if APPLY:
        record.production_batch_id = 180
        for bundle in bundles:
            bundle.production_batch_id = 180
        db.flush()
        after = snapshot(db)
        assert normalized(after) == normalized(before), "An unrelated row, quantity or identifier changed"
        log_action(db, actor, "repair_cutting_batch_link", "ProductionOrder", 321,
                   old_value={"cutting_records": before["cutting_records"], "bundles": before["bundles"]},
                   new_value={"cutting_records": after["cutting_records"], "bundles": after["bundles"], "reason": "Owner-authorized correction: the existing 486 cut pieces and six bundles belong to Nastil 1 / 0321-01. Corrective maintenance attribution; original Cutting actor and history retained."})
        _finalize_postgres_audits(db)
        assert audit_prefix(db, cutoff) == prefix, "Existing audit history changed"
        audit = db.query(AuditLog).filter_by(action="repair_cutting_batch_link", entity_type="ProductionOrder", entity_id=321).one()
        assert audit.id > cutoff and audit.old_value_json["cutting_records"][0]["production_batch_id"] == 186
        assert audit.new_value_json["cutting_records"][0]["production_batch_id"] == 180
        assert verify_audit_hash_chain(db, start_id=audit.id, limit=1)["ok"]
        from app.api.routes.production import _revised_sewing_input_limit
        sewing = next(w for w in works if w.id == 1261)
        assert _revised_sewing_input_limit(db, sewing, 180, record.passed_pieces) == 486
        assert db.query(func.sum(CuttingRecord.passed_pieces)).filter_by(work_order_id=1260, production_batch_id=180).scalar() == 486
        assert db.query(func.count(CuttingRecord.id)).filter_by(work_order_id=1260, production_batch_id=186).scalar() == 0
        result.update(audit_id=audit.id, audit_history_preserved=True, production_preserved=True, sewing_available=486)
        if COMMIT:
            db.commit()
            assert normalized(snapshot(db)) == normalized(before)
            assert audit_prefix(db, cutoff) == prefix
            assert db.get(CuttingRecord, 319).production_batch_id == 180
            assert all(db.get(Bundle, bundle_id).production_batch_id == 180 for bundle_id in BUNDLE_IDS)
            result["commit_readback_verified"] = True
        else:
            db.rollback()
            assert snapshot(db) == before
            assert audit_prefix(db, cutoff) == prefix
            result["rollback_verified"] = True
    print(json.dumps(result, default=str))
