import importlib.util
from decimal import Decimal
from io import StringIO
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def _migration():
    path = Path(__file__).resolve().parents[2] / "alembic/versions/0136_employee_salary_precision.py"
    spec = importlib.util.spec_from_file_location("employee_salary_precision", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def _precision(connection):
    column = next(column for column in sa.inspect(connection).get_columns("employees") if column["name"] == "salary")
    return column["type"].precision, column["type"].scale


def test_salary_migration_preserves_values_and_guards_lossy_downgrade(monkeypatch):
    migration = _migration()
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    employees = sa.Table("employees", metadata, sa.Column("id", sa.Integer, primary_key=True),
                         sa.Column("full_name", sa.String(255), nullable=False),
                         sa.Column("salary", sa.Numeric(12, 2)))
    metadata.create_all(engine)
    try:
        with engine.begin() as connection:
            connection.execute(employees.insert(), [
                {"id": 1, "full_name": "Existing salary", "salary": Decimal("1234.25")},
                {"id": 2, "full_name": "No salary", "salary": None},
            ])
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()
            assert _precision(connection) == (14, 4)
            reflected = sa.Table("employees", sa.MetaData(), autoload_with=connection)
            assert connection.execute(sa.select(reflected)).all() == [
                (1, "Existing salary", Decimal("1234.2500")), (2, "No salary", None),
            ]
            connection.execute(reflected.update().where(reflected.c.id == 1).values(salary=Decimal("1234.5678")))
            with pytest.raises(RuntimeError, match="employee 1.*four decimals"):
                migration.downgrade()
            assert _precision(connection) == (14, 4)
            assert connection.execute(sa.select(reflected.c.salary).where(reflected.c.id == 1)).scalar_one() == Decimal("1234.5678")
            connection.execute(reflected.update().where(reflected.c.id == 1).values(salary=Decimal("1234.56")))
            migration.downgrade()
            assert _precision(connection) == (12, 2)
            downgraded = sa.Table("employees", sa.MetaData(), autoload_with=connection)
            assert connection.execute(sa.select(downgraded)).all() == [
                (1, "Existing salary", Decimal("1234.56")), (2, "No salary", None),
            ]
    finally:
        engine.dispose()


def test_salary_upgrade_emits_postgres_precision_change(monkeypatch):
    migration = _migration()
    sql = StringIO()
    context = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": sql})
    monkeypatch.setattr(migration, "op", Operations(context))
    migration.upgrade()
    assert "ALTER TABLE employees ALTER COLUMN salary TYPE NUMERIC(14, 4)" in sql.getvalue()
