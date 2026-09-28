"""Dry-run by default; --apply requires the exact reviewed plan digest."""

import argparse
import json

from app.db.session import SessionLocal
from app.models import User
from app.services.legacy_package_identity import apply_plan, build_plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-sha256")
    parser.add_argument("--actor-id", type=int)
    args = parser.parse_args()
    with SessionLocal() as db:
        if args.apply:
            actor = db.get(User, args.actor_id) if args.actor_id else None
            if not actor or not args.expected_sha256:
                raise SystemExit("Apply requires an existing actor and reviewed --expected-sha256")
            result = apply_plan(db, args.expected_sha256, actor)
            db.commit()
        else:
            result = build_plan(db)
            db.rollback()
        print(json.dumps(result, default=str, sort_keys=True))


if __name__ == "__main__":
    main()
