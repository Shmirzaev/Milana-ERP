import importlib.util
from pathlib import Path

from sqlalchemy import create_engine, text


def _load_migration_module():
    migration_path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "0049_merge_sew_10_11.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0049", migration_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_merge_moves_sew_11_references_and_preserves_history(monkeypatch):
    migration = _load_migration_module()
    engine = create_engine("sqlite:///:memory:")

    with engine.begin() as bind:
        for statement in (
            "CREATE TABLE sewing_flows (id INTEGER PRIMARY KEY, code TEXT UNIQUE, name TEXT UNIQUE, description TEXT, capacity_per_day INTEGER, is_active BOOLEAN, updated_at DATETIME)",
            "CREATE TABLE work_orders (id INTEGER PRIMARY KEY, sewing_flow_id INTEGER)",
            "CREATE TABLE sewing_assignments (id INTEGER PRIMARY KEY, sewing_flow_id INTEGER, quantity INTEGER)",
            "CREATE TABLE sewing_daily_reports (id INTEGER PRIMARY KEY, sewing_flow_id INTEGER, line_code TEXT, line_name TEXT)",
            "CREATE TABLE sewing_records (id INTEGER PRIMARY KEY, line_name TEXT)",
        ):
            bind.execute(text(statement))

        bind.execute(
            text(
                "INSERT INTO sewing_flows "
                "(id, code, name, description, capacity_per_day, is_active) VALUES "
                "(10, 'SEW-10', 'Nargiza opa', '', 200, true), "
                "(11, 'SEW-11', 'Maxmudova Nargiza', '', 200, true)"
            )
        )
        bind.execute(text("INSERT INTO work_orders VALUES (101, 11)"))
        bind.execute(text("INSERT INTO sewing_assignments VALUES (201, 11, 60)"))
        bind.execute(text("INSERT INTO sewing_daily_reports VALUES (301, 11, 'SEW-11', 'Maxmudova Nargiza')"))
        bind.execute(text("INSERT INTO sewing_records VALUES (401, 'SEW-11'), (402, 'Maxmudova Nargiza')"))

        monkeypatch.setattr(migration.op, "get_bind", lambda: bind)
        migration.upgrade()

        assert bind.execute(text("SELECT sewing_flow_id FROM work_orders WHERE id = 101")).scalar_one() == 10
        assert bind.execute(text("SELECT sewing_flow_id FROM sewing_assignments WHERE id = 201")).scalar_one() == 10
        assert bind.execute(text("SELECT line_code || ':' || line_name FROM sewing_daily_reports")).scalar_one() == "SEW-10:Nargiza opa"
        assert bind.execute(text("SELECT group_concat(line_name, ',') FROM sewing_records ORDER BY id")).scalar_one() == "Nargiza opa,Nargiza opa"
        assert bind.execute(text("SELECT capacity_per_day FROM sewing_flows WHERE code = 'SEW-10'")).scalar_one() == 400
        assert not bind.execute(text("SELECT is_active FROM sewing_flows WHERE code = 'SEW-11'")).scalar_one()
