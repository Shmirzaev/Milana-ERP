"""Quantity correction evidence survives migration and cannot be dropped once used."""

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_quantity_evidence_migration_roundtrip_and_retention():
    path = Path(__file__).parents[2] / "alembic/versions/0117_package_quantity_evidence.py"
    spec = importlib.util.spec_from_file_location("quantity_evidence_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            assert {i["name"] for i in sa.inspect(connection).get_indexes("package_quantity_adjustments")} == {
                "ix_package_quantity_adjustments_package_id", "ix_package_quantity_adjustments_shipment_id",
            }
            migration.downgrade()
            migration.upgrade()
            with pytest.raises(sa.exc.IntegrityError):
                connection.execute(sa.text("""INSERT INTO package_quantity_adjustments
                    (package_id,shipment_id,delta,before_json,after_json,reason,created_by,extra_receipt_quantity)
                    VALUES (1,1,1,'{}','{}','Invalid receipt',1,-1)"""))
            connection.execute(sa.text("""INSERT INTO package_quantity_adjustments
                (package_id,shipment_id,delta,before_json,after_json,reason,created_by,extra_receipt_quantity)
                VALUES (1,1,1,:before,:after,'Counted and received one extra piece',1,1)"""),
                {"before": '{"quantity":4}', "after": '{"quantity":5}'})
            with pytest.raises(RuntimeError, match="physical quantity adjustment evidence"):
                migration.downgrade()
            row = connection.execute(sa.text("SELECT delta,extra_receipt_quantity FROM package_quantity_adjustments")).one()
            assert tuple(row) == (1, 1)
    engine.dispose()
