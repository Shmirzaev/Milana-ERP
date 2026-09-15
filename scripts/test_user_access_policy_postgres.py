"""Exercise the real additive migration using only a disposable PostgreSQL DB."""
import importlib.util
import os
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text

engine = create_engine(os.environ["DATABASE_URL"])
assert os.environ.get("USER_ACCESS_DISPOSABLE") == "1"
assert engine.url.database.startswith("user_access_qa_")
assert engine.url.host.startswith("user-access-qa-")
path = Path(__file__).resolve().parents[1] / "backend/alembic/versions/0129_user_access_policy.py"
spec = importlib.util.spec_from_file_location("policy_migration", path)
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)
with engine.begin() as connection:
    assert connection.execute(text("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")).scalar_one() == 0
    connection.execute(text("CREATE TABLE users (id integer PRIMARY KEY, name text, extra_permissions json)"))
    connection.execute(text("INSERT INTO users VALUES (1, 'Existing user', '[\"finance.view\"]')"))
    migration.op = Operations(MigrationContext.configure(connection))
    migration.upgrade()
    assert connection.execute(text("SELECT access_policy FROM users WHERE id=1")).scalar_one() is None
    assert connection.execute(text("SELECT extra_permissions FROM users WHERE id=1")).scalar_one() == ["finance.view"]
    connection.execute(text("UPDATE users SET access_policy='{}'"))
    migration.downgrade()
    migration.upgrade()
    connection.execute(text("UPDATE users SET access_policy='{" + '"MIL":{"deny":["finance.view"]}' + "}'"))
    try:
        migration.downgrade()
    except RuntimeError as error:
        assert "Restore backed-up access settings" in str(error)
    else:
        raise AssertionError("Unsafe downgrade was allowed")
    # Old application column selections still work with the additive schema.
    assert connection.execute(text("SELECT name, extra_permissions FROM users WHERE id=1")).one() == ("Existing user", ["finance.view"])
    connection.execute(text("UPDATE users SET access_policy=NULL"))
    migration.downgrade()
    migration.upgrade()
print("POSTGRES_USER_ACCESS_PASSED")
