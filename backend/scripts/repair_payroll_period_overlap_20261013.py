"""Owner-approved MIL period cutover; preserve every existing wage and QR.

Dry-run by default. PAY-2026-07 remains locked and retains all assigned records,
including entries already saved on October 13. New work dated October 13 onward
uses PAY-2026-10. This does not reassign old or unassigned wages.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json


CUTOVER = datetime(2026, 10, 12, 19, tzinfo=timezone.utc)  # October 13, Tashkent.
TARGETS = {4: ("PAY-2026-07", "locked"), 5: ("PAY-2026-10", "open")}
ORIGINAL_START = datetime(2026, 7, 31, 19, tzinfo=timezone.utc)
ORIGINAL_END = datetime(2026, 10, 30, 18, 59, 59, tzinfo=timezone.utc)
NEW_ORIGINAL_START = datetime(2026, 10, 5, 19, tzinfo=timezone.utc)
NEW_END = datetime(2026, 10, 31, 18, 59, 59, tzinfo=timezone.utc)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def plan(rows: list[dict], new_period_dependencies: int) -> list[dict]:
    by_id = {row["id"]: row for row in rows}
    for key, (number, status) in TARGETS.items():
        row = by_id.get(key)
        if not row or (row["factory_code"], row["period_no"], row["status"]) != ("MIL", number, status):
            raise ValueError("Payroll period identity/status changed; review again")
    old, new = by_id[4], by_id[5]
    if old["start_date"] != ORIGINAL_START or new["end_date"] != NEW_END:
        raise ValueError("Payroll period outer dates changed; review again")
    if old["end_date"] == CUTOVER - timedelta(microseconds=1) and new["start_date"] == CUTOVER:
        return []
    if old["end_date"] != ORIGINAL_END or new["start_date"] != NEW_ORIGINAL_START:
        raise ValueError("Payroll period dates changed; review again")
    if new_period_dependencies:
        raise ValueError("New period is no longer empty; review before changing its dates")
    for row in rows:
        if row["factory_code"] == "MIL" and row["id"] not in TARGETS:
            if row["start_date"] <= NEW_END and row["end_date"] >= CUTOVER:
                raise ValueError("Another payroll period conflicts with the new period")
    return [
        {"id": 4, "field": "end_date", "before": old["end_date"], "after": CUTOVER - timedelta(microseconds=1)},
        {"id": 5, "field": "start_date", "before": new["start_date"], "after": CUTOVER},
    ]


def run(apply=False, expected=None, backup=None):
    from sqlalchemy import text
    from app.db.session import SessionLocal
    from app.models import PayrollPeriod
    from app.services.audit import log_action

    with SessionLocal() as db:
        if not apply:
            db.execute(text("SET TRANSACTION READ ONLY"))
        db.execute(text("SET LOCAL lock_timeout='5s'"))
        db.execute(text("SET LOCAL statement_timeout='60s'"))
        if apply:
            if not expected or not backup or not backup.startswith("/opt/milana-erp/shared/backups/"):
                raise ValueError("Apply requires the reviewed fingerprint and verified backup path")
            db.execute(text("LOCK TABLE payroll_periods IN EXCLUSIVE MODE"))
            db.execute(text("LOCK TABLE payroll_records, payroll_adjustments, payroll_qr_labels IN SHARE MODE"))

        def periods():
            return [dict(row) for row in db.execute(text(
                "SELECT id,factory_code,period_no,name,start_date,end_date,status,notes "
                "FROM payroll_periods ORDER BY id"
            )).mappings()]

        def preserved():
            result = {}
            for table in ("payroll_records", "payroll_adjustments", "payroll_qr_labels"):
                result[table] = dict(db.execute(text(
                    f"SELECT count(*) AS count, md5(coalesce(string_agg(md5(row_to_json(t)::text), '' ORDER BY id), '')) "
                    f"AS hash FROM {table} t"
                )).mappings().one())
            return result

        before = periods()
        dependencies = db.execute(text(
            "SELECT (SELECT count(*) FROM payroll_records WHERE payroll_period_id=5) + "
            "(SELECT count(*) FROM payroll_adjustments WHERE payroll_period_id=5)"
        )).scalar_one()
        changes = plan(before, dependencies)
        report = {"apply": apply, "fingerprint": fingerprint(before), "changes": changes}
        if not apply or not changes:
            return report
        if expected != report["fingerprint"]:
            raise ValueError("Period configuration changed since review")
        preservation = preserved()
        expected_rows = [dict(row) for row in before]
        audits = []
        for change in changes:
            period = db.get(PayrollPeriod, change["id"])
            setattr(period, change["field"], change["after"])
            next(row for row in expected_rows if row["id"] == period.id)[change["field"]] = change["after"]
            audits.append(log_action(
                db, None, "repair_payroll_period_overlap", "PayrollPeriod", period.id,
                old_value={change["field"]: change["before"]},
                new_value={change["field"]: change["after"], "backup": backup,
                           "reason": "Owner selected locked PAY-2026-07 retention and PAY-2026-10 for new work, 2026-10-13",
                           "existing_wages": "Preserved in their original periods, including October 13 entries"},
            ))
        db.flush()
        after = periods()
        if after != expected_rows or preserved() != preservation or plan(after, dependencies):
            raise ValueError("Post-write preservation check failed")
        report["preserved"] = preservation
        db.commit()
        report["audit_ids"] = [row.id for row in audits]
        report["after_fingerprint"] = fingerprint(after)
        return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected")
    parser.add_argument("--backup")
    args = parser.parse_args()
    print(json.dumps(run(args.apply, args.expected, args.backup), default=str, sort_keys=True))
