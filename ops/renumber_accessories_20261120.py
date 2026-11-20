"""Bounded, audited correction of the 759 imported accessory batch labels.

The reviewed plan fixes IDs, old/new labels and source identities. Quantities,
QC, warehouse, item, references and movements must remain field-identical.
"""
from __future__ import annotations

import hashlib
import json
import os
import re

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.deps import user_permissions
from app.models import inventory_access_service
from app.models.audit_service import _audit_entry_hash, log_action
from app.schemas import AuditLog, StockBatch, User, Warehouse
from app.schemas.inventory.batch_identity_persistence import set_batch_number

OPERATION = "MILANA_ACCESSORIES_BATCH_NUMBERS_20261120"
PREFIX = "MIL-OPEN26-"
EXPECTED_IDS = set(range(2189, 2948))


def check(value, message):
    if not value:
        raise ValueError(message)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     default=str, separators=(",", ":")).encode()).hexdigest()


def validate_plan(plan, expected_sha):
    check(digest(plan) == expected_sha, "Reviewed plan hash differs")
    check(len(plan) == 759 and {r["id"] for r in plan} == EXPECTED_IDS, "Batch coverage differs")
    check(len({r["old"] for r in plan}) == 759, "Duplicate source labels")
    check(len({r["new"] for r in plan}) == 759, "Duplicate target labels")
    check(all(re.fullmatch(r"[1-9][0-9]{3}", r["new"]) for r in plan), "Four-digit number required")
    check(all(re.fullmatch(r"MIL-OPEN26-[A-Z]{3}-[0-9]+-[0-9]+", r["old"]) for r in plan), "Source label differs")
    return {r["id"]: r for r in plan}


def preserved_facts(db):
    """Full stock and linked inventory snapshots except the permitted labels."""
    facts = {}
    for table in ("stock_batches", "items", "stock_movements", "material_reservations",
                  "manual_accessory_issues"):
        rows = [dict(r) for r in db.execute(text("SELECT * FROM " + table + " ORDER BY id")).mappings()]
        if table == "stock_batches":
            for row in rows:
                if row["id"] in EXPECTED_IDS:
                    row.pop("batch_no")
                    row.pop("updated_at", None)
        facts[table] = digest(rows)
    return facts


def verify_rows(db, plan):
    rows = db.query(StockBatch).filter(StockBatch.id.in_(EXPECTED_IDS)).order_by(StockBatch.id).all()
    check(len(rows) == 759, "Missing imported batches")
    by_id = {r["id"]: r for r in plan}
    for batch in rows:
        wanted = by_id[batch.id]
        check(batch.batch_no == wanted["new"], "Saved number differs")
        check(batch.item_id == wanted["item_id"] and batch.old_code == wanted["source_key"], "Source identity changed")
        check(batch.warehouse_id == 2 and batch.item.category in ("accessory", "packaging"), "Scope differs")
        check(batch.item.sku == wanted["sku"], "Product identity differs")
    check(not db.query(StockBatch.id).filter(StockBatch.batch_no.like(PREFIX + "%")).first(), "Old import labels remain")
    # Avoid ambiguity with either kind of existing batch label, including archived rows.
    labels = {r["new"] for r in plan}
    collisions = db.query(StockBatch.id).filter(
        ~StockBatch.id.in_(EXPECTED_IDS),
        (StockBatch.batch_no.in_(labels) | StockBatch.internal_batch_no.in_(labels)),
    ).first()
    check(not collisions, "Target number collision")
    return {"batches": len(rows), "first": min(labels), "last": max(labels)}


def verify_audits(db, plan_sha):
    rows = db.query(AuditLog).filter(
        AuditLog.new_value_json["operation"].as_string() == OPERATION
    ).order_by(AuditLog.id).all()
    check(len(rows) == 760, "Correction audit coverage differs")
    previous = db.query(AuditLog.entry_hash).filter(AuditLog.id < rows[0].id).order_by(AuditLog.id.desc()).first()
    previous_hash = previous[0] if previous else None
    for row in rows:
        check(row.user_id == 1 and row.new_value_json["plan_sha256"] == plan_sha, "Audit attribution differs")
        check(row.prev_hash == previous_hash, "Audit chain differs")
        check(row.entry_hash == _audit_entry_hash(
            prev_hash=row.prev_hash, user_id=row.user_id, action=row.action,
            entity_type=row.entity_type, entity_id=row.entity_id,
            old_value=row.old_value_json, new_value=row.new_value_json), "Audit hash differs")
        previous_hash = row.entry_hash
    return len(rows)


def operation(plan, *, mode, plan_sha, fail_after=None):
    validate_plan(plan, plan_sha)
    check(mode in ("inspect", "rehearse", "apply", "verify"), "Unsupported mode")
    qa_url = os.environ.get("ACCESSORY_RENUMBER_QA_DATABASE_URL")
    url = make_url(qa_url or settings.DATABASE_URL)
    if qa_url:
        check(url.database == "milana_accessories_renumber_20261120" and url.host in ("127.0.0.1", "localhost"), "Invalid private QA database")
    else:
        check(url.host == "172.16.10.3" and url.database == "erp" and mode != "rehearse" and fail_after is None, "Production database/mode guard failed")
    engine = create_engine(url, poolclass=NullPool)
    try:
        with Session(engine) as db:
            if mode in ("inspect", "verify"):
                db.execute(text("SET TRANSACTION READ ONLY"))
            else:
                db.execute(text("SET LOCAL lock_timeout='5s'"))
                db.execute(text("SET LOCAL statement_timeout='60s'"))
                db.execute(text("LOCK TABLE stock_batches IN SHARE ROW EXCLUSIVE MODE"))
            check(db.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0159_ceo_balance_snapshots", "Schema changed")
            actor = db.get(User, 1)
            check(actor is not None and actor.is_active and actor.name == "System Admin" and "*" in user_permissions(actor), "Authorized actor unavailable")
            inventory_access_service.require_accessories(actor)
            warehouse = db.get(Warehouse, 2)
            check(warehouse and warehouse.type == "accessory_storage" and warehouse.department_id == 3, "Warehouse scope changed")
            completed = db.query(AuditLog).filter(
                AuditLog.action == "accessories_batch_numbers_complete",
                AuditLog.new_value_json["operation"].as_string() == OPERATION,
            ).all()
            if completed:
                check(len(completed) == 1, "Duplicate completion record")
                result = verify_rows(db, plan)
                facts = preserved_facts(db)
                check(facts == completed[0].new_value_json["preserved_facts"], "Preserved inventory changed since correction")
                return {"already_applied": True, **result, "audit_rows": verify_audits(db, plan_sha),
                        "preserved_facts": facts, "completion_audit": completed[0].id}
            check(mode != "verify", "Correction has not been applied")
            rows = db.query(StockBatch).filter(StockBatch.id.in_(EXPECTED_IDS)).order_by(StockBatch.id).all()
            check(len(rows) == 759, "Imported batch coverage changed")
            by_id = {r["id"]: r for r in plan}
            for batch in rows:
                row = by_id[batch.id]
                check((batch.batch_no, batch.item_id, batch.old_code, batch.item.sku, batch.warehouse_id) ==
                      (row["old"], row["item_id"], row["source_key"], row["sku"], 2), "Source batch changed")
                inventory_access_service.require_batch(db, actor, batch.id)
            check(db.query(StockBatch).filter(StockBatch.batch_no.like(PREFIX + "%")).count() == 759, "Unexpected imported batch namespace")
            labels = {r["new"] for r in plan}
            check(not db.query(StockBatch.id).filter(
                StockBatch.batch_no.in_(labels) | StockBatch.internal_batch_no.in_(labels)
            ).first(), "Target number already exists")
            before = preserved_facts(db)
            if mode == "inspect":
                return {"ready": True, "batches": len(rows), "first": min(labels), "last": max(labels), "preserved_facts": before}
            for n, batch in enumerate(rows, 1):
                row = by_id[batch.id]
                set_batch_number(db, batch, row["new"])
                log_action(db, actor, "accessories_batch_number", "StockBatch", batch.id,
                           old_value={"batch_no": row["old"]},
                           new_value={"operation": OPERATION, "plan_sha256": plan_sha,
                                      "batch_no": row["new"], "source_key": row["source_key"]})
                if fail_after == n:
                    db.flush()
                    raise ValueError("Deliberate isolated correction fault")
            db.flush()
            result = verify_rows(db, plan)
            check(preserved_facts(db) == before, "Correction changed inventory facts")
            if mode == "rehearse":
                db.rollback()
                check(preserved_facts(db) == before, "Rollback changed facts")
                check(all(db.get(StockBatch, r["id"]).batch_no == r["old"] for r in plan), "Rollback left renamed batches")
                return {"rollback_verified": True, **result, "preserved_facts": before}
            audit = log_action(db, actor, "accessories_batch_numbers_complete", "AccessoryBatchCorrection", None,
                               new_value={"operation": OPERATION, "plan_sha256": plan_sha,
                                          "batches": len(rows), "preserved_facts": before})
            db.commit()
            return {"applied": True, **result, "preserved_facts": before, "completion_audit": audit.id}
    finally:
        engine.dispose()
