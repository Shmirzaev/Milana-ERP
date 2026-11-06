"""Rehearse the narrow access migration on disposable PostgreSQL only."""
import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.schemas import User
from app.tests.test_password_change_races import password_change_postgres_sessions  # noqa: F401


def test_besttex_grant_postgres_lock_retry_and_persisted_scope(password_change_postgres_sessions):
    sessions, engine = password_change_postgres_sessions
    path = Path(__file__).resolve().parents[2] / "alembic/versions/0149_besttex_cutting_access.py"
    spec = importlib.util.spec_from_file_location("besttex_postgres_grant", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with sessions() as db:
        account = User(name="Besttex migration rehearsal", email="besttex@milanapremium.uz",
                       password_hash="disposable-only", factory_code="BST", extra_permissions=["sewing.records"],
                       access_policy={"BST": {"allow": ["sewing.flows"], "deny": ["besttex.cutting_sheets", "finance.view"]},
                                      "ECO": {"allow": ["payroll.view"], "deny": []}})
        other = User(name="Unrelated rehearsal", email="unrelated-besttex@disposable.invalid",
                     password_hash="disposable-only", factory_code="BST", extra_permissions=["payroll.view"])
        db.add_all([account, other])
        db.commit()
        account_id, other_id = account.id, other.id
    with engine.connect() as blocker, engine.connect() as contender:
        blocker.execute(text("SELECT id FROM users WHERE id=:id FOR UPDATE"), {"id": account_id})
        contender.execute(text("SET LOCAL lock_timeout='250ms'"))
        migration.op = Operations(MigrationContext.configure(contender))
        with pytest.raises(OperationalError) as locked:
            migration.upgrade()
        assert locked.value.orig.pgcode == "55P03"
        contender.rollback()
        blocker.rollback()
    for _ in range(2):
        with engine.begin() as connection:
            migration.op = Operations(MigrationContext.configure(connection))
            migration.upgrade()
    with sessions() as db:
        account = db.get(User, account_id)
        assert account.extra_permissions == ["sewing.records", "besttex.cutting_sheets"]
        assert account.access_policy["BST"] == {"allow": ["sewing.flows", "besttex.cutting_sheets"], "deny": ["finance.view"]}
        assert account.access_policy["ECO"] == {"allow": ["payroll.view"], "deny": []}
        assert (account.name, account.factory_code, account.password_hash, account.is_active) == (
            "Besttex migration rehearsal", "BST", "disposable-only", True)
        assert db.get(User, other_id).extra_permissions == ["payroll.view"]
        account.factory_code = "MIL"
        account.extra_permissions = ["sewing.records"]
        db.commit()
    with engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
    with sessions() as db:
        account = db.get(User, account_id)
        assert account.factory_code == "MIL"
        assert account.extra_permissions == ["sewing.records", "factory:BST:besttex.cutting_sheets"]
        assert db.get(User, other_id).extra_permissions == ["payroll.view"]
