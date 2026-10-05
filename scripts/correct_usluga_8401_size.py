"""Guarded, owner-requested correction of TB1444-V-5's leading-space size.

Run inside the verified backend with --check, --dry-run, or --apply.
Apply requires a separately verified fresh PostgreSQL backup.
"""
import argparse
import json

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.routes.usluga import UslugaOrderIn, _normalized_plan_lines
from app.db.session import engine
from app.models import Model
from app.services.audit import _audit_entry_hash, log_action


def snapshot(db):
    return [dict(row) for row in db.execute(text(
        "SELECT * FROM model_sizes WHERE model_id IN (8400,8401,8402,8403) ORDER BY id"
    )).mappings()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["--check", "--dry-run", "--apply"])
    # Explicit positional mode is supplied after '--' to argparse.
    args = parser.parse_args()
    with Session(engine, expire_on_commit=False) as db:
        if args.mode == "--check":
            db.execute(text("SET TRANSACTION READ ONLY"))
        else:
            db.execute(text("SET LOCAL lock_timeout = '5s'"))
            db.execute(text("SET LOCAL statement_timeout = '20s'"))
            db.execute(text(
                "SELECT id FROM models WHERE id IN (8400,8401,8402,8403) ORDER BY id FOR UPDATE"
            )).all()
            db.execute(text(
                "SELECT id FROM model_sizes WHERE model_id IN (8400,8401,8402,8403) ORDER BY id FOR UPDATE"
            )).all()
        model = db.get(Model, 8401)
        assert (model.code, model.catalog_scope, model.factory_code, model.status) == (
            "TB1444-5", "usluga", "ECO", "approved"
        ), "Target model identity changed"
        before = snapshot(db)
        target = next(row for row in before if row["id"] == 34833)
        assert target["model_id"] == 8401 and target["size"] == " 98-104", "Unexpected target size"
        assert len(model.sizes) == 11, "Model size count changed"
        assert not any(row.size == "98-104" for row in model.sizes), "Canonical size already exists"
        payload = UslugaOrderIn(customer_name="validation only", model_id=8401,
            lines=[{"color": "validation only", "size": row.size.strip(), "quantity": 1}
                   for row in model.sizes])
        try:
            _normalized_plan_lines(payload, model)
        except HTTPException as exc:
            assert exc.status_code == 400 and exc.detail == "Sizes are not configured on this Usluga model: 98-104"
        else:
            raise AssertionError("Original failure was not reproduced")
        if args.mode == "--check":
            print(json.dumps({"mode": args.mode, "reproduced": True, "target": target}, default=str))
            return
        result = db.execute(text(
            "UPDATE model_sizes SET size='98-104' WHERE id=34833 AND model_id=8401 AND size=' 98-104'"
        ))
        assert result.rowcount == 1
        db.expire(model, ["sizes"])
        assert len(_normalized_plan_lines(payload, model)) == 11
        after = snapshot(db)
        expected = [dict(row, size="98-104") if row["id"] == 34833 else row for row in before]
        assert after == expected, "Unexpected family size change"
        if args.mode == "--dry-run":
            db.rollback()
            assert snapshot(db) == before, "Dry-run rollback failed"
            print(json.dumps({"mode": args.mode, "validation_passed": True, "rollback_verified": True}))
            return
        audit = log_action(db, None, "correct_usluga_model_size_whitespace", "ModelSize", 34833,
            old_value=target,
            new_value={**next(row for row in after if row["id"] == 34833),
                       "reason": "Owner requested fixing ECT order validation for TB1444-V-5; remove one leading space only."})
        db.commit()
        assert audit.entry_hash == _audit_entry_hash(prev_hash=audit.prev_hash, user_id=audit.user_id,
            action=audit.action, entity_type=audit.entity_type, entity_id=audit.entity_id,
            old_value=audit.old_value_json, new_value=audit.new_value_json)
        with Session(engine) as verify:
            verify.execute(text("SET TRANSACTION READ ONLY"))
            assert snapshot(verify) == expected
            assert len(_normalized_plan_lines(payload, verify.get(Model, 8401))) == 11
        print(json.dumps({"mode": args.mode, "audit_id": audit.id, "size_id": 34833,
            "before": " 98-104", "after": "98-104", "all_11_sizes_validated": True,
            "fresh_readback_passed": True, "other_family_sizes_preserved": True}))


if __name__ == "__main__":
    main()
