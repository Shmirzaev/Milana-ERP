"""Read-only previews for data-affecting Alembic revisions."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import sqlalchemy as sa


REVISION_0130 = "0130_eco_fabric_transfers"
PREDECESSOR_0130 = "0129_user_access_policy"
TARGET_PERMISSION_0130 = "inventory.eco_transfers"
TARGET_EMAIL_0130 = "mubina@milanapremium.uz"


def _snapshot_hash(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def preview_0130_permissions(connection: sa.Connection) -> dict[str, Any]:
    """Return exact current and post-upgrade grants for 0130's target account.

    The result deliberately omits the email address. The ``before`` object is
    sufficient to restore the two fields if an operator approves a correction.
    """
    users = sa.table(
        "users",
        sa.column("id", sa.Integer),
        sa.column("email", sa.String),
        sa.column("extra_permissions", sa.JSON),
        sa.column("access_policy", sa.JSON),
    )
    rows = connection.execute(
        sa.select(users.c.id, users.c.extra_permissions, users.c.access_policy)
        .where(sa.func.lower(users.c.email) == TARGET_EMAIL_0130)
        .order_by(users.c.id)
    ).mappings()

    previews = []
    for row in rows:
        before = {
            "extra_permissions": row["extra_permissions"],
            "access_policy": row["access_policy"],
        }
        try:
            # Keep the conversion semantics aligned with revision 0130. If an
            # existing value is malformed, the migration would fail; report
            # that fact instead of presenting a fabricated successful preview.
            after_grants = list(dict.fromkeys([
                *(list(before["extra_permissions"] or [])),
                TARGET_PERMISSION_0130,
            ]))
            after_policy = dict(before["access_policy"] or {})
            if "MIL" in after_policy:
                mil = dict(after_policy["MIL"])
                mil["allow"] = list(dict.fromkeys([*(mil.get("allow", [])), TARGET_PERMISSION_0130]))
                mil["deny"] = [permission for permission in mil.get("deny", [])
                               if permission != TARGET_PERMISSION_0130]
                after_policy["MIL"] = mil
        except (TypeError, ValueError) as exc:
            previews.append({
                "user_id": int(row["id"]),
                "before": before,
                "changed": None,
                "blocker": f"Revision 0130 would fail converting existing permission data: {type(exc).__name__}",
                "before_sha256": _snapshot_hash(before),
            })
            continue
        after = {
            "extra_permissions": after_grants,
            "access_policy": after_policy or None,
        }
        previews.append({
            "user_id": int(row["id"]),
            "before": before,
            "after": after,
            "changed": before != after,
            "before_sha256": _snapshot_hash(before),
            "after_sha256": _snapshot_hash(after),
        })

    return {
        "revision": REVISION_0130,
        "expected_predecessor": PREDECESSOR_0130,
        "permission": TARGET_PERMISSION_0130,
        "matching_account_count": len(previews),
        "changed_account_count": sum(preview["changed"] is True for preview in previews),
        "blocked_account_count": sum("blocker" in preview for preview in previews),
        "accounts": previews,
        "recovery": "Each before object contains the exact extra_permissions and access_policy values to restore; hashes identify the reviewed snapshots.",
    }


def read_only_preflight_0130(engine: sa.Engine) -> dict[str, Any]:
    """Run the 0130 permission preview inside a read-only transaction."""
    with engine.connect() as connection:
        with connection.begin():
            if connection.dialect.name == "postgresql":
                connection.execute(sa.text("SET TRANSACTION READ ONLY"))
            current = connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
            report = preview_0130_permissions(connection)
            report["database_revision"] = current
            report["migration_pending"] = current == PREDECESSOR_0130
            report["applicability"] = (
                "blocked_by_migration_input" if current == PREDECESSOR_0130 and report["blocked_account_count"]
                else "ready_for_review" if current == PREDECESSOR_0130
                else "migration_already_applied" if current == REVISION_0130
                else "revision_mismatch_review_required"
            )
            return report
