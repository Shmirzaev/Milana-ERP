"""Read-only preview of the role permission append in Alembic revision 0126."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import sqlalchemy as sa

from app.migrations.preflight import _revision_in_history


REVISION_0126 = "0126_payroll_sewing_access"
PREDECESSOR_0126 = "0125_roll_lengths"
GRANTS_0126 = ("sewing.flows", "sewing.records", "sewing.bundles")


def _snapshot_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def preview_0126_permissions(connection: sa.Connection) -> dict[str, Any]:
    """Predict revision 0126's permission append for every matching role.

    Malformed permission values are reported as blockers instead of emulating
    Python's surprising list(string)/list(dict) conversions in the migration.
    """
    roles = sa.Table("roles", sa.MetaData(), autoload_with=connection)
    matches = connection.execute(
        sa.select(roles.c.id, roles.c.name, roles.c.permissions)
        .where(sa.func.lower(roles.c.name) == "payroll")
        .order_by(roles.c.id)
    ).mappings().all()

    previews = []
    for row in matches:
        before = row["permissions"]
        entry: dict[str, Any] = {
            "role_id": int(row["id"]),
            "role_name": row["name"],
            "before": before,
            "before_sha256": _snapshot_hash({"permissions": before}),
        }
        if before is not None and not isinstance(before, list):
            entry["blocker"] = "Existing permissions are not a JSON array; manual migration review required."
        else:
            normalized = list(before or [])
            after = normalized + [grant for grant in GRANTS_0126 if grant not in normalized]
            entry.update({
                "after": after,
                "changed": before != after,
                "after_sha256": _snapshot_hash({"permissions": after}),
            })
        previews.append(entry)

    return {
        "revision": REVISION_0126,
        "expected_predecessor": PREDECESSOR_0126,
        "grants": list(GRANTS_0126),
        "matching_role_count": len(previews),
        "changed_role_count": sum(item.get("changed") is True for item in previews),
        "blocked_role_count": sum("blocker" in item for item in previews),
        "roles": previews,
        "recovery": (
            "For a pending stage, each before value is the exact current permissions JSON to restore. "
            "At an applied revision these snapshots cannot reconstruct overwritten historical data."
        ),
    }


def read_only_preflight_0126(engine: sa.Engine) -> dict[str, Any]:
    """Inspect only at the exact predecessor, in a read-only snapshot."""
    with engine.connect() as connection:
        with connection.begin():
            if connection.dialect.name == "postgresql":
                connection.execute(sa.text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            elif connection.dialect.name != "sqlite":
                raise RuntimeError(f"Unsupported database dialect for read-only preflight: {connection.dialect.name}")

            current = connection.execute(
                sa.text("SELECT version_num FROM alembic_version")
            ).scalar_one_or_none()
            if current != PREDECESSOR_0126:
                return {
                    "revision": REVISION_0126,
                    "expected_predecessor": PREDECESSOR_0126,
                    "database_revision": current,
                    "migration_pending": False,
                    "applicability": (
                        "migration_already_applied" if _revision_in_history(current, REVISION_0126)
                        else "revision_mismatch_review_required"
                    ),
                    "affected_rows_inspected": False,
                }

            report = preview_0126_permissions(connection)
            report["database_revision"] = current
            report["migration_pending"] = True
            if report["blocked_role_count"]:
                report["applicability"] = "blocked_by_migration_input"
            elif report["matching_role_count"] == 0:
                report["applicability"] = "no_target"
            elif report["matching_role_count"] > 1:
                report["applicability"] = "multiple_matches_review_required"
            else:
                report["applicability"] = "ready_for_operator_review"
            return report
