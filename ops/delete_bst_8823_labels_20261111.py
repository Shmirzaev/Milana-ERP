"""Owner-authorized, order-only payroll cancellation; never restores old labels.

Run locally: inspect -> backup -> rehearse -> commit source -> apply -> verify.
Evidence is private/ignored under outputs/bst-8823-cancellation. No app deploy.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ORDER = "MAN-8823-01-94WJ3U"
FACTORY = "BST"
MODEL = "BJ5033-V-6741"
OPERATION = "owner-bst-8823-cancellation-20261111"
RELEASE = "20261111_052632"
CONTAINER = "milana-backend-green"


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def operate(mode, expected=None, backup=None):
    from decimal import Decimal
    from sqlalchemy import text
    from app.db.session import SessionLocal
    from app.models.audit_service import log_action
    from app.schemas import PayrollQrLabel, PayrollRecord
    from app.schemas.people.payroll_record_persistence import apply_payroll_record_changes
    from app.schemas.people.payroll_qr_lifecycle_persistence import stage_delete_qr_labels

    with SessionLocal() as db:
        db.execute(text("SET LOCAL lock_timeout = '5s'"))
        db.execute(text("SET LOCAL statement_timeout = '30s'"))
        if mode in ("rehearse", "apply"):
            # Also prevent a concurrent scan/issue/adjustment from creating a
            # new target row between discovery and deletion. Reads stay live.
            db.execute(text("LOCK TABLE payroll_qr_labels, payroll_records, payroll_adjustments IN SHARE ROW EXCLUSIVE MODE"))

        def rows(sql, **params):
            return [dict(r) for r in db.execute(text(sql), params).mappings()]

        def target(table):
            assert table in ("payroll_qr_labels", "payroll_records")
            return rows(f"SELECT * FROM {table} WHERE factory_code=:factory AND production_no=:order ORDER BY id", factory=FACTORY, order=ORDER)

        def outside():
            result = {}
            projections = {
                "payroll_records": "id,factory_code,production_no,model_code,employee_id,payroll_period_id,status,scan_uid,original_scan_uid,dedupe_key,quantity,rate_per_piece,total_amount,currency,updated_at",
                "payroll_qr_labels": "id,factory_code,production_no,model_code,label_uid,payroll_record_id,split_from_label_id,status,quantity,rate_per_piece,currency,return_count,updated_at",
                "payroll_adjustments": "id,factory_code,payroll_period_id,employee_id,source_payroll_record_id,adjustment_type,amount,currency,reason,created_by,created_at",
            }
            for table in ("payroll_qr_labels", "payroll_records", "payroll_adjustments"):
                where = "" if table == "payroll_adjustments" else "WHERE NOT (factory_code=:factory AND production_no IS NOT DISTINCT FROM :order)"
                # Avoid serializing large historical scan/image payloads while
                # blocking writers. All mutation-relevant scalar fields remain
                # covered; full target rows are compared separately below.
                projection = projections[table]
                result[table] = rows(f"SELECT count(*) AS count,sum(('x'||substr(md5(concat_ws('|',{projection})),1,15))::bit(60)::bigint)::text AS hash FROM {table} {where}", factory=FACTORY, order=ORDER)
            return result

        labels, records = target("payroll_qr_labels"), target("payroll_records")
        snapshot = {"labels": labels, "records": records}
        if mode == "verify":
            assert not labels
            assert len(records) == 93 and all(r["status"] == "voided" and r["scan_uid"] is None for r in records)
            assert rows("SELECT count(*) AS count FROM audit_logs WHERE action='owner_cancel_order_labels' AND new_value_json->>'operation'=:operation", operation=OPERATION)[0]["count"] == 1
            return {"verified": True, "remaining_labels": 0, "active_earnings": "0.00", "retained_voided_records": len(records), "snapshot_sha256": digest(snapshot)}

        active = [r for r in records if r["status"] != "voided"]
        assert len(labels) == 138 and len(records) == 93
        assert len(active) == 66 and len({r["employee_id"] for r in active}) == 9
        assert sum(r["total_amount"] for r in active) == Decimal("780960.00")
        assert all(r["status"] == "recorded" and r["payroll_period_id"] is None and r["currency"] == "UZS" for r in active)
        assert all(r["model_code"] == MODEL and r["model_id"] == 8823 for r in labels + records)
        assert all(r["production_order_id"] is None and r["sales_order_id"] is None and r["work_order_id"] is None for r in labels + records)
        record_ids, label_ids = {r["id"] for r in records}, {r["id"] for r in labels}
        assert all(r["payroll_record_id"] is None or r["payroll_record_id"] in record_ids for r in labels)
        assert not rows("SELECT a.id FROM payroll_adjustments a JOIN payroll_records r ON r.id=a.source_payroll_record_id WHERE r.factory_code=:factory AND r.production_no=:order", factory=FACTORY, order=ORDER)
        assert not rows("SELECT l.id FROM payroll_qr_labels l JOIN payroll_records r ON r.id=l.payroll_record_id WHERE r.factory_code=:factory AND r.production_no=:order AND NOT (l.factory_code=:factory AND l.production_no IS NOT DISTINCT FROM :order)", factory=FACTORY, order=ORDER)
        assert not rows("SELECT child.id FROM payroll_qr_labels child JOIN payroll_qr_labels parent ON child.split_from_label_id=parent.id WHERE parent.factory_code=:factory AND parent.production_no=:order AND NOT (child.factory_code=:factory AND child.production_no IS NOT DISTINCT FROM :order)", factory=FACTORY, order=ORDER)
        assert all(r["split_from_label_id"] is None or r["split_from_label_id"] in label_ids for r in labels)
        summary = {"operation": OPERATION, "order": ORDER, "model": MODEL, "labels": len(labels), "active_records": len(active), "historical_voided_records": len(records)-len(active), "employees": 9, "removed_amount_uzs": "780960.00", "snapshot_sha256": digest(snapshot)}
        if mode == "inspect":
            db.rollback()
            return {"summary": summary, "snapshot": snapshot}
        assert expected and expected["summary"] == summary, "Target changed since reviewed inspection"
        assert backup and backup["restore_objects"] > 100 and backup["bytes"] > 0 and backup["mode"] == "0o600"
        conserved = outside()
        record_objects = db.query(PayrollRecord).filter(PayrollRecord.id.in_(sorted(record_ids))).order_by(PayrollRecord.id).with_for_update().all()
        label_objects = db.query(PayrollQrLabel).filter(PayrollQrLabel.id.in_(sorted(label_ids))).order_by(PayrollQrLabel.id).with_for_update().all()
        for record in record_objects:
            # Keep wage amounts/work/employee evidence, but release live scan
            # and retry identities so a same-date reprint is not a duplicate.
            apply_payroll_record_changes(record, {
                "status": "voided", "scan_uid": None,
                "original_scan_uid": record.original_scan_uid or record.scan_uid,
                "dedupe_key": digest([OPERATION, record.id, record.dedupe_key]),
            })
        db.flush()
        # Children precede any parents because split lineage uses RESTRICT.
        pending = {label.id: label for label in label_objects}
        while pending:
            parent_ids = {label.split_from_label_id for label in pending.values()}
            leaves = [label for label in pending.values() if label.id not in parent_ids]
            assert leaves, "Unexpected split cycle"
            stage_delete_qr_labels(db, leaves)
            db.flush()
            for label in leaves:
                pending.pop(label.id)
        assert not target("payroll_qr_labels")
        after_records = target("payroll_records")
        assert len(after_records) == 93 and all(r["status"] == "voided" and r["scan_uid"] is None for r in after_records)
        for before, after in zip(records, after_records):
            for key in before:
                if key not in {"status", "scan_uid", "original_scan_uid", "dedupe_key", "updated_at"}:
                    assert before[key] == after[key], key
        assert outside() == conserved, "Non-target payroll changed"
        if mode == "rehearse":
            db.rollback()
            assert digest({"labels": target("payroll_qr_labels"), "records": target("payroll_records")}) == summary["snapshot_sha256"]
            return {"rollback_verified": True, "conservation_verified": True, "summary": summary}
        assert mode == "apply"
        entry = log_action(db, None, "owner_cancel_order_labels", "PayrollQrLabel", 203248,
            old_value={"label_ids": sorted(label_ids), "records": [{k: r[k] for k in ("id", "employee_id", "status", "total_amount", "scan_uid", "original_scan_uid", "dedupe_key")} for r in records]},
            new_value={**summary, "owner_authorized": True, "restored_labels": 0, "reason": "Owner requested delete all labels and employee earnings for pictured order; staff will reprint", "backup": backup})
        db.commit()
        return {"committed": True, "audit_id": entry.id, "conservation_verified": True, "summary": summary}


def local_main():
    root = Path(__file__).resolve().parents[1]
    out = root / "outputs/bst-8823-cancellation"
    out.mkdir(parents=True, exist_ok=True)
    mode = sys.argv[1]
    assert mode in ("inspect", "rehearse", "apply", "verify", "backup")
    ssh = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "-o", "StrictHostKeyChecking=yes", "-i", str(Path.home()/".ssh/milana_erp_deploy_ed25519"), "admilana@172.16.10.4"]
    source = Path(__file__).read_text(encoding="utf-8")
    expected = json.loads((out/"inspect.json").read_text()) if mode in ("rehearse", "apply") else None
    backup = json.loads((out/"backup.json").read_text()) if mode in ("rehearse", "apply") else None
    if mode == "apply":
        committed = subprocess.check_output(["git", "show", "HEAD:ops/"+Path(__file__).name], cwd=root).decode().replace("\r\n", "\n")
        assert committed == source, "Commit reviewed operation before application"
        rehearsal = json.loads((out/"rehearse.json").read_text())
        assert rehearsal["rollback_verified"] and rehearsal["source_sha256"] == hashlib.sha256(source.encode()).hexdigest()
    if mode == "backup":
        program = (root/"ops/backup_fabric_reconciliation.py").read_text().replace("milana-backend-blue", CONTAINER).replace("milana_erp_pre_fabric_reconcile_", "milana_erp_pre_bst_8823_delete_").replace("ghcr.io/shmirzaev/milana-erp-backend:20261005_070406", RELEASE_IMAGE)
        command = "python3 -"
    else:
        program = "__name__='remote_operation'\n"+source+"\nprint(json.dumps(operate("+repr(mode)+","+repr(expected)+","+repr(backup)+"),default=str,ensure_ascii=False))\n"
        command = "docker exec -i "+CONTAINER+" python -"
    check = subprocess.check_output(ssh+["readlink -f /opt/milana-erp/current"], text=True).strip()
    assert check == "/opt/milana-erp/releases/"+RELEASE
    result = subprocess.run(ssh+[command], input=program.encode(), capture_output=True)
    if result.returncode:
        (out/(mode+"-error.txt")).write_bytes(result.stderr)
        raise RuntimeError("Remote operation failed; inspect private evidence")
    data = json.loads(result.stdout)
    data["source_sha256"] = hashlib.sha256(source.encode()).hexdigest()
    (out/(mode+".json")).write_text(json.dumps(data,indent=2,default=str,ensure_ascii=False),encoding="utf-8")
    print(json.dumps({k:v for k,v in data.items() if k != "snapshot"},ensure_ascii=False))


# A local existing image reference is pinned before running backup below.
RELEASE_IMAGE = "ghcr.io/shmirzaev/milana-erp-backend:20261111_052632"

if __name__ == "__main__":
    local_main()
