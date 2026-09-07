"""Guarded, idempotent import of the user's 2026-09-07 XJ3183 workbook."""
from __future__ import annotations

import argparse
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from pathlib import Path

MANIFEST_SHA256 = "1e97061867479739837d21d0c3ee7a6ce1835dd0155ebba631c7b56d76d91403"
MODEL_CODES = ("XJ3183-5966", "XJ3183-5967")
FACTORIES = ("milana", "besttex", "eco_cotton")
STAGES = {"Tikuv": "sewing", "Чистка": "pressing", "Контроль": "sewing", "Упаковка": "packaging", "Склад": "packaging"}


def load_operations(manifest_path: Path) -> tuple[dict, list[dict]]:
    raw = manifest_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != MANIFEST_SHA256:
        raise ValueError("Workbook manifest does not match the reviewed SHA-256")
    manifest = json.loads(raw)
    if tuple(manifest["model_codes"]) != MODEL_CODES or tuple(manifest["factories"]) != FACTORIES:
        raise ValueError("Unexpected model or factory scope")
    rows = manifest["operations"]
    if [row["source_order"] for row in rows] != list(range(1, 37)):
        raise ValueError("Expected exactly 36 sequential workbook operations")
    if sum(Decimal(row["rate"]) for row in rows) != Decimal("8680"):
        raise ValueError("Unexpected workbook rate total")
    operations = []
    for factory in FACTORIES:
        for row in rows:
            order = row["source_order"]
            operations.append({
                "id": f"xj3183-{order:03d}-{factory}",
                "selected": True,
                "section": STAGES[row["stage"]],
                "code": f"XJ3183-{order:03d}",
                "name": row["name"],
                "rate": row["rate"],
                "sourceOrder": order,
                "duration": row["duration"],
                "sourceStage": row["stage"],
                "sewingFactory": factory,
                "quantityMode": "batch",
                "customQuantity": 0,
                "copies": 1,
                "splitMode": "none",
                "splitQuantities": [],
            })
    return manifest, operations


def next_details(existing: dict | None, operations: list[dict]) -> dict:
    details = deepcopy(existing) if isinstance(existing, dict) else {}
    for key in ("paid_operations", "paidOperations"):
        rows = details.get(key)
        if rows not in (None, []) and rows != operations:
            raise ValueError("Existing paid operations changed; refusing to overwrite them")
    details["paid_operations"] = deepcopy(operations)
    details.pop("paidOperations", None)
    return details


def run(manifest_path: Path, apply: bool = False) -> dict:
    from sqlalchemy import text
    from app.db.session import SessionLocal
    from app.models import Model
    from app.services.audit import log_action
    from app.services.paid_operations import filter_paid_operations_for_factory

    manifest, operations = load_operations(manifest_path)
    with SessionLocal() as db:
        if not apply:
            db.execute(text("SET TRANSACTION READ ONLY"))
        db.execute(text("SET LOCAL lock_timeout = '5s'"))
        db.execute(text("SET LOCAL statement_timeout = '30s'"))
        query = db.query(Model).filter(Model.code.in_(MODEL_CODES)).order_by(Model.code)
        if apply:
            query = query.with_for_update(of=Model)
        models = query.all()
        if tuple(model.code for model in models) != MODEL_CODES:
            raise ValueError("Expected both exact XJ3183 variants")
        plans = []
        for model in models:
            if model.catalog_scope != "standard" or model.details_json.get("general", {}).get("model_no") != "XJ3183":
                raise ValueError("Unexpected model identity")
            updated = next_details(model.details_json, operations)
            plans.append((model, updated, deepcopy(model.details_json)))
        changes = []
        for model, updated, previous in plans:
            changed = updated != previous
            entry = None
            if apply and changed:
                model.details_json = updated
                entry = log_action(
                    db, None, "import_paid_operations", "Model", model.id,
                    old_value={"paid_operations": previous.get("paid_operations"), "paidOperations": previous.get("paidOperations")},
                    new_value={
                        "model_code": model.code, "paid_operations": operations,
                        "source_file": manifest["source_file"], "source_sha256": manifest["source_sha256"],
                        "manifest_sha256": MANIFEST_SHA256,
                        "authorization": "User requested workbook operations for XJ3183 in all factories on 2026-09-07",
                    },
                )
            changes.append({"code": model.code, "changed": changed, "operations": len(operations), "audit_id": entry.id if entry else None})
        if apply:
            db.flush()
            for model, updated, previous in plans:
                db.refresh(model)
                if model.details_json != updated:
                    raise ValueError("Persisted operation readback differs")
                untouched = {k: v for k, v in previous.items() if k not in {"paid_operations", "paidOperations"}}
                if {k: v for k, v in model.details_json.items() if k not in {"paid_operations", "paidOperations"}} != untouched:
                    raise ValueError("An unrelated model detail changed")
                for factory in FACTORIES:
                    scoped = filter_paid_operations_for_factory(model.details_json, factory)["paid_operations"]
                    if scoped != [op for op in operations if op["sewingFactory"] == factory]:
                        raise ValueError("Factory readback differs")
            db.commit()
        else:
            db.rollback()
    return {"applied": apply, "models": changes, "per_factory_count": 36, "per_factory_rate_total": "8680", "manifest_sha256": MANIFEST_SHA256}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args.manifest, args.apply), ensure_ascii=False))
