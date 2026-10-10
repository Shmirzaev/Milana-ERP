"""Normalize catalog size labels only; preserve every operational size snapshot.

Dry-run by default. Apply requires the exact dry-run fingerprint and a verified
database backup. Numeric ranges are retained; standalone letter sizes are removed.
No schema, runtime application code, or non-catalog business row is changed.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import re


LETTER = r"(?:[1-9][0-9]*X[SL]|X*[SL]|M)"


def canonical_size(value: str) -> str | None:
    value = value.strip()
    if value.casefold().replace(" ", "") == "freesize":
        return "Free Size"
    if re.fullmatch(LETTER, value, re.I):
        return None
    combined = re.fullmatch(rf"{LETTER}\s*-\s*([0-9]+)", value, re.I)
    if combined:
        return combined.group(1)
    if re.fullmatch(r"[0-9]+(?:-[0-9]+)?", value):
        return value
    raise ValueError(f"Unrecognized catalog size: {value!r}")


def fingerprint(rows: list[dict]) -> str:
    return hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def plan(rows: list[dict]) -> dict:
    groups = defaultdict(list)
    removed = []
    updates = []
    duplicates = 0
    standalone = 0
    for row in rows:
        target = canonical_size(row["size"])
        if target is None:
            if row["measurement_json"]:
                raise ValueError(f"Standalone size {row['id']} has measurements; explicit review required")
            removed.append(row)
            standalone += 1
        else:
            groups[(row["model_id"], target)].append(row)
    for (_, target), members in sorted(groups.items()):
        # Prefer the already-numeric row, then the oldest row. Preserve measurements.
        members.sort(key=lambda row: (row["size"] != target, row["id"]))
        survivor = members[0]
        measurements = {json.dumps(row["measurement_json"], sort_keys=True)
                        for row in members if row["measurement_json"]}
        if len(measurements) > 1:
            raise ValueError(f"Conflicting measurements for model {survivor['model_id']} size {target}")
        measurement = json.loads(next(iter(measurements))) if measurements else survivor["measurement_json"]
        if survivor["size"] != target or survivor["measurement_json"] != measurement:
            updates.append({"before": survivor, "after": dict(survivor, size=target, measurement_json=measurement)})
        removed.extend(members[1:])
        duplicates += len(members) - 1
    return {"fingerprint": fingerprint(rows), "before_rows": len(rows),
            "after_rows": len(rows) - len(removed), "renamed_rows": len(updates),
            "duplicate_rows": duplicates, "standalone_rows": standalone,
            "updates": updates, "removed": removed}


def run(apply: bool = False, expected: str | None = None, backup: str | None = None) -> dict:
    from sqlalchemy import text
    from app.core.deps import is_super_admin
    from app.db.session import SessionLocal
    from app.models import User
    from app.services.audit import log_action

    with SessionLocal() as db:
        if not apply:
            db.execute(text("SET TRANSACTION READ ONLY"))
        db.execute(text("SET LOCAL lock_timeout='5s'"))
        db.execute(text("SET LOCAL statement_timeout='60s'"))
        if apply:
            if not expected or not backup:
                raise ValueError("Apply requires --expected fingerprint and --backup verified dump path")
            db.execute(text("LOCK TABLE model_sizes IN SHARE ROW EXCLUSIVE MODE"))
        if db.execute(text("SELECT count(*) FROM pg_constraint WHERE confrelid='model_sizes'::regclass")).scalar_one():
            raise ValueError("Catalog size foreign keys require explicit review")

        def snapshot():
            return [dict(row) for row in db.execute(text(
                "SELECT id,model_id,size,measurement_json FROM model_sizes ORDER BY id"
            )).mappings()]

        rows = snapshot()
        changes = plan(rows)
        report = {key: value for key, value in changes.items() if key not in ("updates", "removed")}
        report["apply"] = apply
        report["sizes_after"] = sorted({canonical_size(row["size"]) for row in rows} - {None})
        if not apply:
            return report
        if expected != changes["fingerprint"]:
            raise ValueError("Catalog changed since review; run a new dry-run")
        if not changes["updates"] and not changes["removed"]:
            return report
        actor = next(user for user in db.query(User).order_by(User.id) if user.is_active and is_super_admin(user))
        if changes["removed"]:
            db.execute(text("DELETE FROM model_sizes WHERE id=:id"),
                       [{"id": row["id"]} for row in changes["removed"]])
        if changes["updates"]:
            db.execute(text("UPDATE model_sizes SET size=:size, measurement_json=CAST(:measurement AS json) WHERE id=:id"),
                       [{"id": item["after"]["id"], "size": item["after"]["size"],
                         "measurement": json.dumps(item["after"]["measurement_json"])} for item in changes["updates"]])
        expected_rows = {row["id"]: row for row in rows}
        for row in changes["removed"]:
            del expected_rows[row["id"]]
        for item in changes["updates"]:
            expected_rows[item["after"]["id"]] = item["after"]
        after = snapshot()
        if after != sorted(expected_rows.values(), key=lambda row: row["id"]):
            raise ValueError("Post-write rows differ from the reviewed plan")
        remaining = plan(after)
        if remaining["updates"] or remaining["removed"]:
            raise ValueError("Cleanup did not converge")
        audit_rows = ([{"before": row, "after": None} for row in changes["removed"]] + changes["updates"])
        for start in range(0, len(audit_rows), 500):
            log_action(db, actor, "normalize_catalog_sizes", "ModelSize", None,
                       old_value={"rows": [item["before"] for item in audit_rows[start:start + 500]]},
                       new_value={"rows": [item["after"] for item in audit_rows[start:start + 500]],
                                  "reviewed_fingerprint": expected, "backup": backup,
                                  "reason": "Owner-approved numeric/Free Size catalog cleanup 2026-10-10"})
        report["after_fingerprint"] = fingerprint(after)
        report["audit_entries"] = (len(audit_rows) + 499) // 500
        db.commit()
        return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected")
    parser.add_argument("--backup")
    args = parser.parse_args()
    print(json.dumps(run(args.apply, args.expected, args.backup), sort_keys=True))
