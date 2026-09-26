from __future__ import annotations

import sqlalchemy as sa

from app.migrations.preflight_0090 import PREDECESSOR_0090, read_only_preflight_0090


def _engine(revision: str = PREDECESSOR_0090) -> sa.Engine:
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    version = sa.Table("alembic_version", metadata, sa.Column("version_num", sa.String, primary_key=True))
    departments = sa.Table("departments", metadata,
                           sa.Column("id", sa.Integer, primary_key=True), sa.Column("code", sa.String))
    users = sa.Table("users", metadata,
                     sa.Column("id", sa.Integer, primary_key=True), sa.Column("department_id", sa.Integer))
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(version.insert(), {"version_num": revision})
        connection.execute(departments.insert(), [
            {"id": 1, "code": "BST"}, {"id": 2, "code": "ECT"}, {"id": 3, "code": "OTHER"},
        ])
        connection.execute(users.insert(), [
            {"id": 1, "department_id": 1}, {"id": 2, "department_id": 2},
            {"id": 3, "department_id": 3}, {"id": 4, "department_id": None},
        ])
    return engine


def test_0090_preflight_predecessor_preview_shows_exact_assignments_and_fallbacks():
    engine = _engine()
    try:
        report = read_only_preflight_0090(engine)
        assert report["migration_pending"] is True
        assert report["applicability"] == "review_implicit_mil_fallback"
        assert report["implicit_mil_fallback_count"] == 2
        assert [(row["user_id"], row["after"]["factory_code"]) for row in report["users"]] == [
            (1, "BST"), (2, "ECO"), (3, "MIL"), (4, "MIL"),
        ]
        with engine.connect() as connection:
            assert "factory_code" not in {c["name"] for c in sa.inspect(connection).get_columns("users")}
    finally:
        engine.dispose()


def test_0090_preflight_stops_on_revision_mismatch_before_table_inspection():
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    version = sa.Table("alembic_version", metadata, sa.Column("version_num", sa.String, primary_key=True))
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(version.insert(), {"version_num": "0090_user_factory_access"})
    try:
        report = read_only_preflight_0090(engine)
        assert report["affected_rows_inspected"] is False
        assert report["applicability"] == "migration_already_applied"
    finally:
        engine.dispose()
