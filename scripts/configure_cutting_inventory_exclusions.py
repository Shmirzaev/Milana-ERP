"""Apply or restore a reviewed Cutting Inventory exclusion manifest."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

from sqlalchemy import select, text

from app.db.session import SessionLocal
from app.models.audit_service import log_action
from app.models.production.cutting_balance_service import CUTTING_INVENTORY_EXCLUSIONS
from app.schemas import Bundle, ProductionOrder, SystemSetting


def read_manifest(source):
    payload = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")
    rows = json.loads(payload)
    fields = {"id", "bundle_no", "order_no", "batch_id"}
    if not isinstance(rows, list) or not rows or any(
        not isinstance(row, dict) or set(row) != fields or type(row["id"]) is not int or row["id"] <= 0
        for row in rows
    ):
        raise ValueError("Expected a nonempty list of exact bundle identities")
    rows_by_id = {row["id"]: row for row in rows}
    if len(rows_by_id) != len(rows):
        raise ValueError("The manifest contains repeated bundle identities")
    canonical = json.dumps(sorted(rows, key=lambda row: row["id"]), sort_keys=True, separators=(",", ":"))
    return rows_by_id, hashlib.sha256(canonical.encode()).hexdigest()


def configure(db, *, manifest, digest, active):
    # A section-specific transaction lock also protects the first insert.
    db.execute(text("SELECT pg_advisory_xact_lock(1297047635, 4)"))
    setting = db.scalar(select(SystemSetting).where(SystemSetting.key == CUTTING_INVENTORY_EXCLUSIONS).with_for_update())
    before = setting.value_json if setting else {}
    if not isinstance(before, dict):
        raise ValueError("Review the existing Cutting Inventory exclusion setting")
    if before and before.get("manifest_sha256") != digest:
        raise ValueError("The existing exclusion applies to a different manifest")
    if not active and not before:
        raise ValueError("No recorded exclusion to restore")
    if before and before.get("active") is active:
        return False
    if active:
        rows = db.execute(select(
            Bundle.id,
            Bundle.bundle_no,
            ProductionOrder.production_no.label("order_no"),
            Bundle.production_batch_id.label("batch_id"),
        ).join(ProductionOrder, Bundle.production_order_id == ProductionOrder.id).where(
            Bundle.id.in_(manifest),
            ProductionOrder.source_type == "standard",
        )).mappings()
        if {row["id"]: dict(row) for row in rows} != manifest:
            raise ValueError("A bundle identity changed, is missing, or belongs to Usluga")
    after = {"active": active, "bundle_ids": sorted(manifest), "manifest_sha256": digest}
    saved = SystemSetting.write_section(
        db, section=CUTTING_INVENTORY_EXCLUSIONS, setting=setting, value_json=after,
    )
    log_action(
        db, None, "exclude_cutting_inventory" if active else "restore_cutting_inventory",
        "SystemSetting", saved.id,
        old_value={"active": bool(before.get("active")), "manifest_sha256": before.get("manifest_sha256")},
        new_value={"active": active, "manifest_sha256": digest, "bundle_count": len(manifest)},
    )
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("apply", "restore"))
    parser.add_argument("manifest", help="Reviewed JSON manifest path, or - for stdin")
    args = parser.parse_args()
    manifest, digest = read_manifest(args.manifest)
    active = args.action == "apply"
    with SessionLocal.begin() as db:
        changed = configure(db, manifest=manifest, digest=digest, active=active)
    print(json.dumps({"active": active, "changed": changed, "bundle_count": len(manifest), "manifest_sha256": digest}))


if __name__ == "__main__":
    main()
