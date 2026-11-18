"""Bounded one-time opening-stock operation; no application deployment.

Uses the deployed DTOs, access guards and schema-owned writers. One transaction
creates only new Item/StockBatch/StockMovement rows and append-only audit rows.
An identical retry is read-only; a partial/colliding namespace is refused.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
import hashlib
import json
import os

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.deps import user_permissions
from app.libs.dto.inventory.item_input import ItemIn
from app.libs.dto.inventory.stock_batch_input import StockBatchIn
from app.libs.enums.inventory import StockBatchQcStatus
from app.libs.types.inventory import ItemInsertCommand
from app.models import inventory_access_service
from app.models.audit_service import _audit_entry_hash, log_action
from app.models.inventory.stock_service import _ensure_unique_active_item_name, _validate_receiving_warehouse
from app.schemas import AuditLog, Item, StockBatch, StockMovement, User, Warehouse
from app.schemas.inventory import item_persistence, stock_receipt_persistence

OPERATION = "MILANA_ACCESSORIES_OPENING_20261118"
PREFIX = "MIL-OPEN26-"
REVIEWED_MANIFEST_SHA256 = "5d0d727e6b3032c0d24aa7550e5a3778bc1b7a67e8f5809690c387a86189a30d"
REVIEWED_CANONICAL_SHA256 = "8a74887a8c8449adb72528849b0b9c3ce2350439cb7c858fa8afd3ae2bfbf5d6"


def check(condition, message):
    if not condition:
        raise ValueError(message)


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False).encode()).hexdigest()


def validate_manifest(manifest):
    check(canonical_hash(manifest) == REVIEWED_CANONICAL_SHA256, "Manifest differs from independently reviewed content")
    check(manifest["operation"] == OPERATION and manifest["version"] == 1, "Operation identity mismatch")
    check(manifest["warehouse_id"] == 2 and manifest["warehouse_name"] == "Accessory Storage", "Warehouse mismatch")
    check(manifest["database_revision"] == "0157_package_allocation_items", "Schema guard changed")
    check(len(manifest["sources"]) == 11 and len(manifest["rows"]) == 875, "Source coverage changed")
    check(manifest["summary"]["status_counts"] == {"pending": 45, "ready": 759, "zero_balance": 51, "historical_excluded": 20}, "Reviewed status counts changed")
    check(len(manifest["products"]) == 792, "Reviewed product count changed")
    products = {p["sku"]: p for p in manifest["products"]}
    check(len(products) == 792, "Duplicate SKU")
    check(len({p["name"].strip().lower() for p in products.values()}) == 792, "Duplicate product name")
    for p in products.values():
        check(p["sku"].startswith("MIL-") and len(p["sku"]) <= 64 and 0 < len(p["name"]) <= 255, "Invalid product identity")
        check(p["category"] in {"accessory", "packaging"} and p["unit"] in {"kg", "m", "pcs", "bundle"}, "Invalid product vocabulary")
        check(Decimal(p["default_cost"]) == 0, "Unapproved product valuation")
    batches = [r for r in manifest["rows"] if r["status"] == "ready"]
    check(len({r["batch_no"] for r in batches}) == 759, "Duplicate source batch")
    for row in manifest["rows"]:
        check(Decimal(row["quantity"]).is_finite() and Decimal(row["quantity"]) >= 0, "Invalid source quantity")
        if row["status"] in {"pending", "historical_excluded"}:
            check("sku" not in row, "Pending/historical row unexpectedly has an import target")
        elif row["status"] == "zero_balance":
            check(Decimal(row["quantity"]) == 0 and row["sku"] in products, "Invalid zero balance")
        elif row["status"] == "ready":
            p = products[row["sku"]]
            check(0 < Decimal(row["quantity"]) <= Decimal("9999999999.9999"), "Receipt quantity outside storage bounds")
            check(row["batch_no"].startswith(PREFIX) and len(row["batch_no"]) <= 64, "Invalid batch identity")
            check(p["unit"] == row["unit"] and p["category"] == row["category"], "Product/batch mismatch")
            check(row["source_sheet"].strip() == "КАРТАЛАР 2026" if row["family_code"] == "TAG" else True, "Old cards cannot create stock")
        else:
            raise ValueError("Unexpected source status")
    return products, batches


def existing_accessories(db):
    items = db.execute(text("SELECT id,sku,name,category,unit,default_cost,reorder_level,track_batch,is_active,image_url FROM items WHERE category IN ('accessory','packaging') AND sku NOT LIKE 'MIL-%' ORDER BY id")).mappings().all()
    batches = db.execute(text("SELECT b.* FROM stock_batches b JOIN items i ON i.id=b.item_id WHERE (i.category IN ('accessory','packaging') OR b.warehouse_id=2) AND b.batch_no NOT LIKE :prefix ORDER BY b.id"), {"prefix": PREFIX + "%"}).mappings().all()
    return canonical_hash({"items": [dict(x) for x in items], "batches": [dict(x) for x in batches]})


def verify(db, manifest):
    products, batches = validate_manifest(manifest)
    actual_items = db.query(Item).filter(Item.sku.in_(products)).all()
    actual_batches = db.query(StockBatch).filter(StockBatch.batch_no.like(PREFIX + "%")).all()
    check(len(actual_items) == len(products) and len(actual_batches) == len(batches), "Imported coverage mismatch")
    by_sku = {i.sku: i for i in actual_items}
    expected_batches = {r["batch_no"]: r for r in batches}
    totals = defaultdict(Decimal)
    for sku, item in by_sku.items():
        p = products[sku]
        check((item.name, item.category, item.unit, Decimal(item.default_cost), item.track_batch, item.is_active) == (p["name"], p["category"], p["unit"], Decimal(0), True, True), "Imported item differs: " + sku)
    batch_ids = []
    for batch in actual_batches:
        row = expected_batches[batch.batch_no]
        check(batch.item_id == by_sku[row["sku"]].id and batch.warehouse_id == 2, "Imported batch identity/location differs")
        check(Decimal(batch.quantity) == Decimal(row["quantity"]) and batch.unit == row["unit"] and Decimal(batch.cost_per_unit) == 0, "Imported quantity/valuation differs")
        check(batch.archived_at is None and batch.qc_status == "pending", "Opening batch lifecycle differs")
        check(batch.old_code == row["source_key"] and batch.supplier_id is None and batch.order_no is None, "Source provenance/business links differ")
        check("COST PROVISIONAL ZERO" in (batch.processes or ""), "Missing valuation flag")
        totals[row["family_code"]] += Decimal(batch.quantity)
        batch_ids.append(batch.id)
    moves = db.query(StockMovement).filter(StockMovement.batch_id.in_(batch_ids)).all()
    check(len(moves) == len(batches), "Receipt ledger coverage differs")
    by_id = {b.id: b for b in actual_batches}
    seen = set()
    for move in moves:
        batch = by_id[move.batch_id]
        check(move.batch_id not in seen, "Duplicate receipt movement")
        seen.add(move.batch_id)
        check((move.movement_type, move.item_id, move.to_warehouse_id, move.from_warehouse_id, move.unit, Decimal(move.quantity), move.created_by, move.reference_type, move.reference_id) == ("receive", batch.item_id, 2, None, batch.unit, Decimal(batch.quantity), 1, "StockBatch", batch.id), "Receipt ledger differs")
    expected_totals = {x["family_code"]: Decimal(x["quantity"]) for x in manifest["summary"]["family_units"]}
    check(dict(totals) == expected_totals, "Family quantities differ from reviewed manifest")
    return {"products": len(actual_items), "batches": len(actual_batches), "receipt_movements": len(moves), "family_totals": {k: str(v) for k, v in sorted(totals.items())}, "item_ids": sorted(i.id for i in actual_items), "batch_ids": sorted(batch_ids)}


def verify_audits(db, manifest_sha256):
    rows = db.query(AuditLog).filter(AuditLog.new_value_json["operation"].as_string() == OPERATION).order_by(AuditLog.id).all()
    check(len(rows) == 1552, "Import audit coverage differs")
    previous = db.query(AuditLog.entry_hash).filter(AuditLog.id < rows[0].id).order_by(AuditLog.id.desc()).first()
    previous_hash = previous[0] if previous else None
    for row in rows:
        check(row.user_id == 1 and row.new_value_json["manifest_sha256"] == manifest_sha256, "Import audit identity differs")
        check(row.prev_hash == previous_hash, "Import audit chain link differs")
        actual = _audit_entry_hash(prev_hash=row.prev_hash, user_id=row.user_id, action=row.action, entity_type=row.entity_type, entity_id=row.entity_id, old_value=row.old_value_json, new_value=row.new_value_json)
        check(row.entry_hash == actual, "Import audit hash differs")
        previous_hash = row.entry_hash
    return len(rows)


def operation(manifest, *, mode="inspect", valuation_approved=False, manifest_sha256=None, expected_manifest_sha256=None, fail_after=None):
    products, batches = validate_manifest(manifest)
    check(manifest_sha256 == expected_manifest_sha256 == REVIEWED_MANIFEST_SHA256, "Manifest SHA-256 guard failed")
    check(mode in {"inspect", "rehearse", "apply", "verify"}, "Unknown operation mode")
    qa_url = os.environ.get("ACCESSORY_QA_DATABASE_URL")
    url = make_url(qa_url or settings.DATABASE_URL)
    if qa_url:
        check(url.database == "milana_accessories_20261118" and url.host in {"127.0.0.1", "localhost"}, "QA database is not isolated")
    else:
        check(url.host == "172.16.10.3" and mode != "rehearse" and fail_after is None, "Production database/mode guard failed")
    if mode in {"apply", "rehearse"}:
        check(valuation_approved is True, "Owner approval of provisional zero valuation is required")
    engine = create_engine(url, poolclass=NullPool)
    try:
        with Session(engine) as db:
            if mode in {"inspect", "verify"}:
                db.execute(text("SET TRANSACTION READ ONLY"))
            db.execute(text("SET LOCAL lock_timeout = '5s'"))
            db.execute(text("SET LOCAL statement_timeout = '90s'"))
            check(db.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == manifest["database_revision"], "Live database revision changed")
            warehouse = db.get(Warehouse, 2)
            check(warehouse is not None and (warehouse.name, warehouse.type, warehouse.department_id) == ("Accessory Storage", "accessory_storage", 3), "Milana warehouse scope changed")
            actor = db.get(User, 1)
            check(actor is not None and actor.is_active and actor.name == "System Admin" and "*" in user_permissions(actor), "Observed System Admin context changed")
            inventory_access_service.require_accessories(actor)
            existing = existing_accessories(db)
            collisions = db.query(Item).filter(Item.sku.in_(products)).count()
            namespace_batches = db.query(StockBatch).filter(StockBatch.batch_no.like(PREFIX + "%")).count()
            if collisions or namespace_batches or mode == "verify":
                result = verify(db, manifest)
                result["audit_rows"] = verify_audits(db, manifest_sha256)
                db.rollback()
                return {"already_applied": True, "existing_accessories_fingerprint": existing, **result}
            names = [p["name"].lower() for p in products.values()]
            check(not db.execute(text("SELECT id FROM items WHERE is_active AND lower(trim(name)) = ANY(:names)"), {"names": names}).first(), "Active catalog name collision")
            if mode == "inspect":
                db.rollback()
                return {"ready": True, "existing_accessories_fingerprint": existing, **manifest["summary"]}
            check(db.execute(text("SELECT pg_try_advisory_xact_lock(20261118, 761793)")).scalar_one(), "Another accessories opening import is running")
            # Recheck under the import lock before allocating any business row.
            check(db.query(Item).filter(Item.sku.in_(products)).count() == 0 and db.query(StockBatch).filter(StockBatch.batch_no.like(PREFIX + "%")).count() == 0, "Import namespace changed")
            created = {}
            for sku, p in sorted(products.items()):
                request = ItemIn(sku=sku, name=p["name"], category=p["category"], unit=p["unit"], default_cost=0, reorder_level=0, track_batch=True, is_active=True)
                inventory_access_service.require_category(actor, request.category)
                _ensure_unique_active_item_name(db, request.model_dump())
                command = ItemInsertCommand(sku=sku, name=request.name, category=request.category, unit=request.unit, default_cost=request.default_cost, reorder_level=request.reorder_level, track_batch=True, is_active=True, image_url=None, composition_json=[])
                item = item_persistence.insert_item(db, command)
                created[sku] = item
                log_action(db, actor, "opening_import_item", "Item", item.id, new_value={"operation": OPERATION, "manifest_sha256": manifest_sha256, "sku": sku, "cost_status": "provisional_zero", "source_keys": p["source_keys"]})
            for n, row in enumerate(batches, 1):
                item = created[row["sku"]]
                inventory_access_service.require_item(db, actor, item.id)
                _validate_receiving_warehouse(item, warehouse)
                provenance = f"OPENING 2026-11-18; COST PROVISIONAL ZERO; {row['source_file']}; {row['source_sheet']}; row {row['source_row']}; origin {row['origin'] or 'unknown'}"
                check(len(provenance) <= 255, "Provenance exceeds storage capacity")
                request = StockBatchIn(item_id=item.id, batch_no=row["batch_no"], old_code=row["source_key"], color_code=row["color_code"], quantity=float(Decimal(row["quantity"])), unit=row["unit"], cost_per_unit=0, warehouse_id=2, qc_status=StockBatchQcStatus.PENDING, processes=provenance)
                batch = stock_receipt_persistence.add_stock_batch(db, item_id=item.id, batch_no=request.batch_no, supplier_id=None, color=None, old_code=request.old_code, color_code=request.color_code, color_status=None, order_no=None, width=None, gsm=None, length_m=None, quantity=request.quantity, piece_count=None, roll_weights_kg=[], roll_lengths_m=[], processes=request.processes, unit=request.unit, cost_per_unit=request.cost_per_unit, image_url=None, warehouse_id=2, qc_status=request.qc_status)
                stock_receipt_persistence.add_receive_movement(db, item_id=item.id, batch_id=batch.id, to_warehouse_id=2, quantity=request.quantity, unit=request.unit, reference_type="StockBatch", reference_id=batch.id, created_by=actor.id)
                log_action(db, actor, "opening_import_receive", "StockBatch", batch.id, new_value={"operation": OPERATION, "manifest_sha256": manifest_sha256, "source_key": row["source_key"], "quantity": row["quantity"], "unit": row["unit"], "cost_status": "provisional_zero", "source_received_date": row["source_received_date"]})
                if fail_after == n:
                    raise ValueError("Deliberate isolated rollback fault")
            db.flush()
            result = verify(db, manifest)
            check(existing_accessories(db) == existing, "Pre-existing accessories changed")
            if mode == "rehearse":
                db.rollback()
                check(db.query(Item).filter(Item.sku.in_(products)).count() == 0 and db.query(StockBatch).filter(StockBatch.batch_no.like(PREFIX + "%")).count() == 0, "Rollback left imported records")
                return {"rollback_verified": True, **result}
            audit = log_action(db, actor, "opening_import_complete", "AccessoryOpeningImport", None, new_value={"operation": OPERATION, "manifest_sha256": manifest_sha256, "products": len(products), "batches": len(batches), "pending_rows": 45, "historical_excluded": 20})
            db.commit()
            return {"applied": True, "audit_id": audit.id, "existing_accessories_fingerprint": existing, **result}
    finally:
        engine.dispose()
