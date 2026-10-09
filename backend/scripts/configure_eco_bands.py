"""Provision only after a verified database backup. Password stays off argv/logs."""
import argparse
import getpass
import json

from app.core.deps import is_super_admin
from app.db.session import SessionLocal
from app.models import User
from app.services.sewing_band_setup import configure_eco_bands


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--actor-id", type=int, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    with SessionLocal() as db:
        actor = db.get(User, args.actor_id)
        if not actor or not actor.is_active or not is_super_admin(actor):
            raise RuntimeError("An active super-admin actor is required")
        password = getpass.getpass("Band account password: ") if args.apply else None
        result = configure_eco_bands(db, actor, password, apply=args.apply)
        if args.apply:
            db.commit()
        else:
            db.rollback()
        print(json.dumps(result))


if __name__ == "__main__":
    main()
