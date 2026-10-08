"""Owner-authorized one-order reset; defaults to read-only inspection.

The caller must verify the production release and a full database backup.
Rehearsal rolls back all changes. Apply requires the exact inspected snapshot.
"""
import hashlib
import json
from decimal import Decimal

from sqlalchemy import text

from app.db.session import SessionLocal
from app.services.audit import log_action

ORDER = "MAN-8373-8910-1CJYA8J"
RECORD_IDS = [11520, 12054, 12055, 12068, 12069, 12070]
SCOPE = "factory_code='BST' AND production_no=:order"


def rows(db, sql, **params):
    return [dict(row) for row in db.execute(text(sql), params).mappings()]


def snapshot(db):
    return {
        table: [row["data"] for row in rows(
            db, f"SELECT to_jsonb(t) AS data FROM {table} t WHERE {SCOPE} ORDER BY id",
            order=ORDER,
        )]
        for table in ("payroll_qr_labels", "payroll_records")
    }


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def protected(db):
    return {
        table: rows(db, f"SELECT count(*) AS count, md5(coalesce(string_agg(to_jsonb(t)::text, '' ORDER BY id),'')) AS hash FROM {table} t WHERE ({SCOPE}) IS NOT TRUE", order=ORDER)[0]
        for table in ("payroll_qr_labels", "payroll_records")
    }


def validate(db, data):
    labels, records = data["payroll_qr_labels"], data["payroll_records"]
    assert len(labels) == 580, "Label count changed"
    assert [r["id"] for r in records] == RECORD_IDS, "Payroll records changed"
    assert {r["model_id"] for r in labels + records} == {8373}
    assert {r["model_code"] for r in labels + records} == {"PG10522-V-6213"}
    assert {r["batch_no"] for r in labels + records} == {"8910"}
    assert {r["size"] for r in labels} == {"128", "134", "140", "146", "152"}
    assert {r["sewing_line_code"] for r in labels} == {"BST-BAND-01", "BST-BAND-08"}
    assert {r["currency"] for r in records} == {"UZS"}
    assert sum(r["status"] == "recorded" for r in records) == 5
    assert sum(r["status"] == "voided" for r in records) == 1
    assert sum(Decimal(str(r["total_amount"])) for r in records if r["status"] == "recorded") == Decimal("56210")
    assert all(r["payroll_period_id"] is None for r in records), "Period assignment changed"
    assert all(r[k] is None for r in labels + records for k in ("production_order_id", "sales_order_id", "work_order_id", "production_batch_id"))
    uids = [r["label_uid"] for r in labels]
    label_ids = [r["id"] for r in labels]
    linked = rows(db, "SELECT id FROM payroll_records WHERE scan_uid=ANY(:uids) OR original_scan_uid=ANY(:uids) ORDER BY id", uids=uids)
    assert [r["id"] for r in linked] == RECORD_IDS, "Unexpected payroll history"
    assert not rows(db, "SELECT id FROM payroll_adjustments WHERE source_payroll_record_id=ANY(:ids)", ids=RECORD_IDS)
    assert not rows(db, "SELECT id FROM payroll_qr_labels WHERE split_from_label_id=ANY(:ids)", ids=label_ids)
    assert not rows(db, "SELECT id FROM payroll_qr_labels WHERE payroll_record_id=ANY(:ids) AND (" + SCOPE + ") IS NOT TRUE", ids=RECORD_IDS, order=ORDER)


def operation(mode="inspect", expected=None, backup=None):
    assert mode in {"inspect", "rehearse", "apply"}
    with SessionLocal() as db:
        db.execute(text("SET LOCAL lock_timeout='5s'"))
        db.execute(text("SET LOCAL statement_timeout='30s'"))
        if mode == "inspect":
            db.execute(text("SET TRANSACTION READ ONLY"))
            data = snapshot(db)
            validate(db, data)
            return {"snapshot": data, "sha256": digest(data), "labels": 580, "records": 6, "active_payroll_removed_uzs": 56210}
        assert backup and backup["bytes"] > 0 and backup["restore_objects"] > 100 and backup["mode"] == "0o600"
        # Briefly exclude concurrent scans/issuance/adjustments while validating
        # and deleting. This also prevents new references after dependency checks.
        db.execute(text("LOCK TABLE payroll_qr_labels, payroll_records, payroll_adjustments IN SHARE ROW EXCLUSIVE MODE"))
        data = snapshot(db)
        validate(db, data)
        assert digest(data) == expected["sha256"], "Target data changed since review"
        before = protected(db)
        label_ids = [r["id"] for r in data["payroll_qr_labels"]]
        deleted_labels = db.execute(text("DELETE FROM payroll_qr_labels WHERE id=ANY(:ids) AND " + SCOPE), {"ids": label_ids, "order": ORDER}).rowcount
        deleted_records = db.execute(text("DELETE FROM payroll_records WHERE id=ANY(:ids) AND " + SCOPE), {"ids": RECORD_IDS, "order": ORDER}).rowcount
        assert deleted_labels == 580 and deleted_records == 6
        assert snapshot(db) == {"payroll_qr_labels": [], "payroll_records": []}
        assert protected(db) == before, "Unrelated payroll rows changed"
        audit = log_action(
            db, None, "owner_authorized_label_reset", "PayrollQrLabel", min(label_ids),
            old_value=data,
            new_value={"order": ORDER, "factory_code": "BST", "deleted_labels": 580,
                       "deleted_payroll_records": 6, "active_payroll_removed_uzs": "56210.00",
                       "reason": "Owner requested full order label reset for reissue, explicitly including payroll reversal.",
                       "backup": backup, "snapshot_sha256": expected["sha256"]},
        )
        if mode == "rehearse":
            db.rollback()
            assert digest(snapshot(db)) == expected["sha256"]
            assert protected(db) == before
            return {"rollback_verified": True, "would_delete_labels": 580, "would_delete_records": 6, "protected_rows_unchanged": True}
        db.commit()
        return {"deleted_labels": deleted_labels, "deleted_records": deleted_records,
                "audit_id": audit.id, "active_payroll_removed_uzs": "56210.00",
                "protected_rows_unchanged": True, "snapshot_sha256": expected["sha256"]}
