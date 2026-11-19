"""Reviewed maintenance runner; default commands are read-only.

Run from backend with PYTHONPATH=. python scripts/bst_master_handoff.py --help.
No production identity specification is supplied until the owner confirms it.
"""
import argparse
import json
from pathlib import Path

from sqlalchemy import text

from app.db.session import SessionLocal
from app.models.people.bst_master_handoff_service import (
    HandoffRefused, apply_reviewed_plan, capture_plan, fingerprint, preview_plan,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("capture", "check", "apply"))
    parser.add_argument("input", type=Path, help="Specification JSON for capture; reviewed plan JSON otherwise")
    parser.add_argument("--reviewed-sha256", help="Required exact reviewed plan digest for apply")
    parser.add_argument("--backup-reference", help="Required verified production backup reference for apply")
    args = parser.parse_args()
    value = json.loads(args.input.read_text(encoding="utf-8-sig"))
    if args.command == "apply" and (not args.reviewed_sha256 or not args.backup_reference):
        parser.error("apply requires --reviewed-sha256 and --backup-reference")
    with SessionLocal() as db:
        try:
            if args.command != "apply" and db.get_bind().dialect.name == "postgresql":
                db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            if args.command == "capture":
                plan = capture_plan(db, value)
                print(json.dumps({"reviewed_sha256": fingerprint(plan), "plan": plan,
                                  "proposed_after": preview_plan(plan)}, indent=2, ensure_ascii=False))
            elif args.command == "check":
                if capture_plan(db, value["specifications"]) != value:
                    raise HandoffRefused("Reviewed before-state has drifted")
                print(json.dumps(preview_plan(value), indent=2, ensure_ascii=False))
            else:
                result = apply_reviewed_plan(db, value, reviewed_sha256=args.reviewed_sha256,
                                            backup_reference=args.backup_reference)
                db.commit()
                print(json.dumps(result))
            db.rollback()
        except HandoffRefused as exc:
            db.rollback()
            print(f"REFUSED: {exc}")
            return 2
        except Exception:
            db.rollback()
            print("FAILED OR OUTCOME UNKNOWN: inspect the saved audit receipt and current roster before retrying the same reviewed plan. A lost commit response does not prove rollback.")
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
