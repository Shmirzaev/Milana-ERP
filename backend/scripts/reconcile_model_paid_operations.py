"""Review variant templates and fill only missing/untouched-default family lists.

No mutation on import. Apply requires the reviewed plan hash and current model
preimages; the caller must verify a fresh PostgreSQL backup before invoking it.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from copy import deepcopy
import hashlib
import json
from pathlib import Path


FACTORIES = ("milana", "besttex", "eco_cotton")
IDENTITY_KEYS = {"id", "legacySourceId", "legacy_source_id"}
DEFAULTS = (
    ("SEW-FRONT", "Front body sewing", "sewing"),
    ("SEW-BACK", "Back body sewing", "sewing"),
    ("SEW-ASM", "Assembly sewing", "sewing"),
    ("PRS-PRESS", "Pressing", "pressing"),
    ("PKG-PACK", "Packaging", "packaging"),
)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True, default=str).encode()).hexdigest()


def semantic(rows):
    # Ignore only storage identity. Rates, codes, stages, order, selection,
    # quantities and every other saved setting must agree exactly.
    return [{k: v for k, v in row.items() if k not in IDENTITY_KEYS} for row in rows]


def factory_rows(model, factory):
    return [row for row in model["operations"] if row.get("sewingFactory") == factory]


def is_default(rows, factory):
    expected = [{"code": code, "name": name, "section": section, "selected": True,
                 "rate": "", "sewingFactory": factory, "quantityMode": "batch",
                 "customQuantity": 0, "copies": 1, "splitMode": "none", "splitQuantities": []}
                for code, name, section in DEFAULTS]
    return semantic(rows) == expected


def make_plan(models, choices=None):
    choices = choices or {}
    families = defaultdict(list)
    for row in models:
        if not row["legacy"]:
            families[(row["scope"], row["family_key"])].append(row)
    groups, conflicts, skipped = [], [], []
    for (scope, key), members in sorted(families.items()):
        members.sort(key=lambda row: row["id"])
        if not any(row["variant_no"] and row["operations"] for row in members):
            continue
        # Legacy/unrecognized factory ownership requires human review. Never
        # infer that an unscoped row may be copied to every factory.
        if any(not isinstance(op, dict) or op.get("sewingFactory") not in FACTORIES
               for row in members for op in row["operations"]):
            skipped.append({"scope": scope, "family": key, "reason": "unrecognized_factory"})
            continue
        fills = []
        for factory in FACTORIES:
            donors, targets = [], []
            for row in members:
                ops = factory_rows(row, factory)
                (targets if not ops or is_default(ops, factory) else donors).append(row)
            if not donors or not targets:
                continue
            versions = defaultdict(list)
            for row in donors:
                versions[digest(semantic(factory_rows(row, factory)))].append(row)
            selected_code = choices.get(f"{scope}|{key}|{factory}")
            selected = next((row for row in donors if row["code"] == selected_code), None)
            if selected_code and not selected:
                raise ValueError(f"Chosen donor is not eligible: {selected_code}")
            if len(versions) != 1 and selected is None:
                conflicts.append({"scope": scope, "family": key, "factory": factory,
                                  "targets": [row["code"] for row in targets],
                                  "versions": [{"codes": [r["code"] for r in version],
                                                "count": len(factory_rows(version[0], factory))}
                                               for version in versions.values()]})
                continue
            donor = selected or donors[0]
            fills.append({"factory": factory, "donor_id": donor["id"], "donor_code": donor["code"],
                          "explicit_choice": bool(selected), "operations": deepcopy(factory_rows(donor, factory)),
                          "targets": [{"id": row["id"], "code": row["code"],
                                       "base": not bool(row["variant_no"]),
                                       "replaces_default": bool(factory_rows(row, factory))} for row in targets]})
        if fills:
            groups.append({"scope": scope, "family": key,
                           "members": [{"id": r["id"], "code": r["code"], "details_hash": r["details_hash"]}
                                       for r in members], "fills": fills})
    result = {"version": 1, "groups": groups, "conflicts": conflicts, "skipped": skipped}
    result["sha256"] = digest(result)
    return result


def summary(plan):
    fills = [fill for group in plan["groups"] for fill in group["fills"]]
    return {"plan_sha256": plan["sha256"], "model_families": len(plan["groups"]),
            "factory_lists": len(fills), "model_rows": len({t["id"] for f in fills for t in f["targets"]}),
            "parent_models": len({t["id"] for f in fills for t in f["targets"] if t["base"]}),
            "operation_assignments": sum(len(f["operations"]) * len(f["targets"]) for f in fills),
            "conflicting_families": len({(r["scope"], r["family"]) for r in plan["conflicts"]}),
            "conflicting_factory_lists": len(plan["conflicts"]), "skipped_families": len(plan["skipped"])}


def apply_plan(db, plan, confirmed_hash):
    from app.api.routes.catalog import _approval_family
    from app.models import Model
    from app.services.audit import log_action
    from app.services.paid_operations import paid_operations_from_details

    unsigned = {k: v for k, v in plan.items() if k != "sha256"}
    if plan["sha256"] != confirmed_hash or digest(unsigned) != confirmed_hash:
        raise ValueError("Reviewed plan hash does not match")
    locked = {}
    # Lock/recheck all sources and targets before the first write. A new variant
    # or changed source/target aborts the entire reviewed batch.
    for group in plan["groups"]:
        first = db.get(Model, group["members"][0]["id"])
        if first is None or first.catalog_scope != group["scope"]:
            raise ValueError("Family source changed")
        members = _approval_family(db, first)
        ids = sorted(row.id for row in members)
        if ids != sorted(row["id"] for row in group["members"]):
            raise ValueError(f"Family membership changed: {group['family']}")
        members = db.query(Model).filter(Model.id.in_(ids)).order_by(Model.id).with_for_update().populate_existing().all()
        expected = {row["id"]: row for row in group["members"]}
        for row in members:
            if row.code != expected[row.id]["code"] or digest(row.details_json or {}) != expected[row.id]["details_hash"]:
                raise ValueError(f"Model changed since review: {row.code}")
            locked[row.id] = row
    changed = {}
    for group in plan["groups"]:
        for fill in group["fills"]:
            factory = fill["factory"]
            source_rows = [r for r in paid_operations_from_details(locked[fill["donor_id"]].details_json)
                           if r.get("sewingFactory") == factory]
            if source_rows != fill["operations"]:
                raise ValueError("Donor operation list changed")
            for target in fill["targets"]:
                row = locked[target["id"]]
                details = deepcopy(row.details_json or {})
                old_rows = paid_operations_from_details(details)
                old_factory = [op for op in old_rows if op.get("sewingFactory") == factory]
                if old_factory and not is_default(old_factory, factory):
                    raise ValueError(f"Refusing to replace configured operations on {row.code}")
                hidden = [op for op in old_rows if op.get("sewingFactory") != factory]
                incoming = deepcopy(source_rows)
                identities = [str(op.get("id", "")) for op in [*hidden, *incoming]]
                if any(not identity for identity in identities) or len(set(identities)) != len(identities):
                    raise ValueError(f"Operation identity collision on {row.code}")
                details["paid_operations"] = hidden + incoming
                details.pop("paidOperations", None)
                row.details_json = details
                log_action(db, None, "reconcile_paid_operations", "Model", row.id,
                           old_value={"factory": factory, "paid_operations": old_factory},
                           new_value={"factory": factory, "paid_operations": incoming,
                                      "source_model_id": fill["donor_id"], "source_model_code": fill["donor_code"],
                                      "plan_sha256": confirmed_hash, "reason": "User-requested variant-to-model reconciliation"})
                changed[row.id] = {"id": row.id, "code": row.code, "details_hash": digest(details)}
    db.flush()
    return {**summary(plan), "changed": list(changed.values())}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--choices", type=Path)
    args = parser.parse_args()
    models = json.loads(args.snapshot.read_text(encoding="utf-8-sig"))
    choices = json.loads(args.choices.read_text()) if args.choices else {}
    plan = make_plan(models, choices)
    args.output.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary(plan)))


if __name__ == "__main__":
    main()
