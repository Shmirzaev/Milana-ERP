from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory


BACKEND = Path(__file__).resolve().parents[2]


def _migration():
    config = Config(str(BACKEND / "alembic.ini"))
    return ScriptDirectory.from_config(config).get_revision("0099_payroll_qr_edit_split").module


@pytest.mark.parametrize("evidence", [
    {"status": "superseded", "superseded_at": None, "superseded_by": None, "split_from_label_id": None},
    {"status": "available", "superseded_at": None, "superseded_by": None, "split_from_label_id": 4},
    {"status": "scanned", "superseded_at": "2026-09-01", "superseded_by": 7, "split_from_label_id": None},
])
def test_0099_downgrade_blocks_before_deleting_or_clearing_lineage(evidence):
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    labels = sa.Table(
        "payroll_qr_labels", metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("status", sa.String, nullable=False),
        sa.Column("superseded_at", sa.String),
        sa.Column("superseded_by", sa.Integer),
        sa.Column("split_from_label_id", sa.Integer),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(labels.insert(), {"id": 1, **evidence})
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            with pytest.raises(RuntimeError, match="Refusing to downgrade 0099"):
                _migration().downgrade()
        assert connection.execute(sa.select(labels)).mappings().one()["id"] == 1
        assert {column["name"] for column in sa.inspect(connection).get_columns("payroll_qr_labels")} == {
            "id", "status", "superseded_at", "superseded_by", "split_from_label_id",
        }
    engine.dispose()
