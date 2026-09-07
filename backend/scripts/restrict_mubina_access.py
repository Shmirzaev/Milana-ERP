"""Apply the authorized material-only restriction to exactly Mubina's existing account."""
import argparse
import json

from sqlalchemy import select
from sqlalchemy.orm import lazyload

from app.core.deps import user_permissions
from app.db.session import SessionLocal
from app.models import User
from app.services.audit import log_action
from app.services.inventory_access import MATERIALS_ONLY


def restrict(db, *, apply=False):
    user = db.execute(select(User).options(lazyload("*")).where(User.id == 8).with_for_update(of=User).execution_options(populate_existing=True)).scalar_one()
    if user.email != "mubina@milanapremium.uz" or not user.role or user.role.name != "Storage":
        raise RuntimeError("Target account identity or role changed; review before applying")
    before = list(user.extra_permissions or [])
    after = [permission for permission in before if permission != "price_calculation.accessories"]
    if MATERIALS_ONLY not in after:
        after.append(MATERIALS_ONLY)
    result = {"user_id": user.id, "changed": before != after, "applied": False,
              "before": before, "after": after}
    if apply and before != after:
        user.extra_permissions = after
        entry = log_action(db, None, "restrict_accessories", "User", user.id,
                           old_value={"extra_permissions": before},
                           new_value={"extra_permissions": after, "reason": "User requested removal of all Mubina accessory access"})
        assert MATERIALS_ONLY in user_permissions(user)
        result.update(applied=True, audit_id=entry.id)
        db.commit()
    else:
        db.rollback()
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    with SessionLocal() as session:
        print(json.dumps(restrict(session, apply=args.apply)))
