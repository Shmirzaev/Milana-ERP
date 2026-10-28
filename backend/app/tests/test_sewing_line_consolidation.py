import importlib.util
from pathlib import Path

from sqlalchemy import create_engine, text


def _load_migration_module():
    migration_path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "0044_consolidate_sewing_lines.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0044", migration_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_active_sewing_lines_use_consolidated_names(client, auth_headers):
    response = client.get("/api/sewing-flows", headers=auth_headers)
    assert response.status_code == 200, response.text
    by_code = {row["code"]: row for row in response.json()}

    expected_names = {
        "SEW-01": "Bozorova Nargiza",
        "SEW-06": "Botirova Shaxnoza",
        "SEW-07": "Jalolova Nargiza",
        "SEW-09": "Akbarova Dilafruz",
        "SEW-10": "Maxmudova Nargiza - 1",
        "SEW-12": "Botirova Muxlisa",
        "SEW-13": "Maxmudova Nargiza - 2",
    }
    assert {code: by_code[code]["name"] for code in expected_names} == expected_names
    assert not {"SEW-02", "SEW-03", "SEW-04", "SEW-05", "SEW-08", "SEW-11"}.intersection(by_code)


def test_migration_moves_references_without_deleting_assignments(monkeypatch):
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
                "(1, 'SEW-01', 'Line 01', '', 200, true), "
                "(2, 'SEW-02', 'Line 02', '', 250, true), "
                "(8, 'SEW-08', 'Line 08', '', 300, true), "
                "(7, 'SEW-07', 'Line 07', '', 200, true), "
                "(5, 'SEW-05', 'Line 05', '', 200, true), "
                "(4, 'SEW-04', 'Line 04', '', 200, true), "
                "(3, 'SEW-03', 'Line 03', '', 200, true)"
            )
        )
        bind.execute(text("INSERT INTO work_orders VALUES (101, 5), (102, 8)"))
        bind.execute(text("INSERT INTO sewing_assignments VALUES (201, 3, 40), (202, 7, 60)"))
        bind.execute(text("INSERT INTO sewing_daily_reports VALUES (301, 4, 'SEW-04', 'Line 04')"))
        bind.execute(text("INSERT INTO sewing_records VALUES (401, 'SEW-05'), (402, 'Line 02')"))

        monkeypatch.setattr(migration.op, "get_bind", lambda: bind)
        migration.upgrade()

        assert bind.execute(text("SELECT sewing_flow_id FROM work_orders WHERE id = 101")).scalar_one() == 7
        assert bind.execute(text("SELECT sewing_flow_id FROM work_orders WHERE id = 102")).scalar_one() == 1
        assert bind.execute(text("SELECT count(*) FROM sewing_assignments")).scalar_one() == 2
        assert bind.execute(text("SELECT sewing_flow_id FROM sewing_assignments WHERE id = 201")).scalar_one() == 7
        assert bind.execute(text("SELECT line_code || ':' || line_name FROM sewing_daily_reports")).scalar_one() == "SEW-07:Jalilova"
        assert bind.execute(text("SELECT group_concat(line_name, ',') FROM sewing_records ORDER BY id")).scalar_one() == "Jalilova,Bozorova"
        assert bind.execute(text("SELECT capacity_per_day FROM sewing_flows WHERE code = 'SEW-01'")).scalar_one() == 750
        assert bind.execute(text("SELECT capacity_per_day FROM sewing_flows WHERE code = 'SEW-07'")).scalar_one() == 800
        assert bind.execute(text("SELECT count(*) FROM sewing_flows WHERE is_active = false")).scalar_one() == 5
