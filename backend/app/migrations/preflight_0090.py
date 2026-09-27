"""Read-only preview for the user-factory assignment in revision 0090."""

from __future__ import annotations

import hashlib
import json
import sqlalchemy as sa


REVISION_0090 = "0090_user_factory_access"
PREDECESSOR_0090 = "0089_packaging_departments"


def _hash(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def preview_0090_factory_assignments(connection: sa.Connection) -> dict:
    """Preview every user row changed by 0090 and identify implicit MIL fallback."""
    users = sa.Table("users", sa.MetaData(), autoload_with=connection)
    departments = sa.Table("departments", sa.MetaData(), autoload_with=connection)
    rows = connection.execute(
        sa.select(users.c.id, users.c.department_id, departments.c.code.label("department_code"))
        .select_from(users.outerjoin(departments, users.c.department_id == departments.c.id))
        .order_by(users.c.id)
    ).mappings().all()
    accounts = []
    for row in rows:
        code = row["department_code"]
        if code in ("BST", "BPK"):
            factory = "BST"
        elif code in ("ECT", "ECO", "ECP"):
            factory = "ECO"
        else:
            factory = "MIL"
        before = {"factory_code": None}
        after = {"factory_code": factory}
        accounts.append({
            "user_id": int(row["id"]),
            "department_id": row["department_id"],
            "department_code": code,
            "before": before,
            "after": after,
            "changed": before != after,
            "implicit_mil_fallback": code not in ("BST", "BPK", "ECT", "ECO", "ECP"),
            "before_sha256": _hash(before),
            "after_sha256": _hash(after),
        })
    fallback_count = sum(account["implicit_mil_fallback"] for account in accounts)
    return {
        "revision": REVISION_0090,
        "expected_predecessor": PREDECESSOR_0090,
        "matching_user_count": len(accounts),
        "changed_user_count": sum(account["changed"] for account in accounts),
        "implicit_mil_fallback_count": fallback_count,
        "users": accounts,
        "recovery": "The migration adds factory_code; downgrade drops it and cannot restore the reviewed assignments. Retain this preview with the backup before approval.",
    }


def read_only_preflight_0090(engine: sa.Engine) -> dict:
    """Read the preview only when the database is exactly at 0090's parent."""
    with engine.connect() as connection:
        with connection.begin():
            if connection.dialect.name == "postgresql":
                connection.execute(sa.text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            current = connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
            if current != PREDECESSOR_0090:
                return {
                    "revision": REVISION_0090,
                    "expected_predecessor": PREDECESSOR_0090,
                    "database_revision": current,
                    "migration_pending": False,
                    "applicability": "migration_already_applied" if current == REVISION_0090 else "revision_mismatch_review_required",
                    "affected_rows_inspected": False,
                }
            report = preview_0090_factory_assignments(connection)
            report.update({
                "database_revision": current,
                "migration_pending": True,
                "applicability": "review_implicit_mil_fallback" if report["implicit_mil_fallback_count"] else "ready_for_review",
            })
            return report
