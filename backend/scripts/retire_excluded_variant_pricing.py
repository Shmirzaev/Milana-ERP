"""Preview exclusions; --apply requires the exact reviewed preview JSON. Never deletes history."""
import argparse
import json
import os
from pathlib import Path

from app.db.session import SessionLocal
from app.libs.dto.planning.price_workflow_input import PriceRetirementTarget
from app.models.planning.variant_pricing_reconciliation_service import reconcile
from app.schemas import User


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--actor-id", type=int, required=True)
    parser.add_argument("--preview", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.apply and args.preview is None:
        parser.error("--apply requires --preview")
    targets = None
    if args.preview:
        preview = json.loads(args.preview.read_text(encoding="utf-8"))
        if preview.get("applied") is not False:
            parser.error("Expected a read-only preview")
        targets = [PriceRetirementTarget.model_validate(row) for row in preview["targets"]]
    # Reserve the private result before any write. Failed/empty evidence is retained.
    with os.fdopen(os.open(args.report, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "w", encoding="utf-8") as stream:
        with SessionLocal() as db:
            actor = db.get(User, args.actor_id)
            if actor is None:
                parser.error("Select an existing active global Finance approver")
            result = reconcile(db, actor, targets, apply=args.apply)
        json.dump(result, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    print(json.dumps({"applied": result["applied"], "requests": len(result["targets"]), "readback_verified": result.get("readback_verified")}))


if __name__ == "__main__":
    main()
