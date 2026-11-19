"""Real PostgreSQL readback, arithmetic and bounded parallel read integrity."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from io import BytesIO
import importlib.util
from pathlib import Path
from time import monotonic

from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import event, select

from app.api.router import api_router
from app.core.security import create_access_token
from app.db.base import Base
from app.db.session import get_db
from app.models.department_dashboards_service import cutting_board
from app.schemas import CuttingPassport, WorkOrder
from app.tests.factory_reports_fixture import build_factory_reports_fixture
from app.tests.test_planning_cutting_factory_postgres import cutting_factory_postgres  # noqa: F401


def test_postgres_reports_saved_readback_parallel_reads_and_integrity(cutting_factory_postgres):
    sessions, engine = cutting_factory_postgres
    # The shared ORM fixture intentionally omits0084's historical generated
    # catalog read columns. Reproduce their real DDL only in its owned schema.
    path = Path(__file__).parents[2] / "alembic/versions/0084_model_group_key.py"
    spec = importlib.util.spec_from_file_location("qa_report_0084", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.begin() as conn:
        conn.exec_driver_sql("ALTER TABLE models ADD COLUMN is_legacy_import boolean GENERATED ALWAYS AS ((coalesce(details_json ->> 'legacy_import', 'false')) = 'true') STORED")
        conn.exec_driver_sql(f"ALTER TABLE models ADD COLUMN model_group_key text GENERATED ALWAYS AS ({migration.GROUP_KEY_SQL}) STORED")
    with sessions() as db:
        facts = build_factory_reports_fixture(db)
        db.commit()
    app = FastAPI()
    app.include_router(api_router)

    def db_context():
        with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = db_context

    def fingerprint():
        with sessions() as db:
            return {table.name: sorted(repr(tuple(row)) for row in db.execute(select(table)))
                    for table in Base.metadata.sorted_tables}

    before = fingerprint()
    writes = []

    def track(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().split(None, 1)[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            writes.append(statement.split(None, 1)[0])

    event.listen(engine, "before_cursor_execute", track)
    try:
        with TestClient(app) as client:
            for factory, department in (("MIL", "CUT"), ("ECO", "ECT")):
                expected = facts["factories"][factory]
                headers = {"Authorization": "Bearer " + create_access_token(expected["user_id"], {"factory_code": factory})}
                pid, wid = expected["passport_id"], expected["work_order_id"]
                passport = client.get(f"/api/cutting-passports/{pid}", headers=headers)
                assert passport.status_code == 200, passport.text
                assert passport.json()["cutting_work_order_id"] == wid
                listing = client.get("/api/cutting-passports", headers=headers)
                assert listing.status_code == 200, listing.text
                assert next(row for row in listing.json() if row["id"] == pid)["cutting_work_order_id"] == wid
                report = client.get(f"/api/cutting-passports/dashboard?date_from={facts['day']}&date_to={facts['day']}", headers=headers)
                assert report.status_code == 200, report.text
                assert report.json()["totals"] == expected["expected_passports"]
                assert report.json()["daily"] == [{"date": facts["day"], **expected["expected_passports"]}]
                board_url = f"/api/dashboard/cutting?start={facts['day']}&end={facts['day']}&cutting_department_code={department}"
                board = client.get(board_url, headers=headers)
                assert board.status_code == 200, board.text
                assert board.json()["totals"] == expected["expected_board"]
                assert sum(row["created_pieces"] for row in board.json()["factories"]) == (27 if factory == "MIL" else 30)
                assert sum(row["transferred_pieces"] for row in board.json()["factories"]) == (7 if factory == "MIL" else 0)
                if factory == "MIL":
                    assert {row["unit"]: row["quantity"] for row in board.json()["waste"]} == {"kg": 2.5, "m": 3}
                other = facts["factories"]["ECO" if factory == "MIL" else "MIL"]["passport_id"]
                assert client.get(f"/api/cutting-passports/{other}", headers=headers).status_code == 403
                started = monotonic()
                with ThreadPoolExecutor(max_workers=4) as workers:
                    results = list(workers.map(lambda _: client.get(board_url, headers=headers), range(20)))
                assert monotonic() - started < 30
                assert all(row.status_code == 200 and row.json()["totals"] == expected["expected_board"] for row in results)
            response = client.get(f"/api/shipments/{facts['shipment_id']}/invoice.xlsx", headers=headers)
            assert response.status_code == 200, response.text
            sheet = load_workbook(BytesIO(response.content)).active
            assert sheet.row_dimensions[10].height == sheet.row_dimensions[11].height > 100
            assert sheet["D10"].font.sz == sheet["D11"].font.sz == 10
            assert sheet["G12"].value == 7 and sheet["I12"].value == 2.75 and sheet["K12"].value == 17.5
    finally:
        event.remove(engine, "before_cursor_execute", track)
    assert not writes
    assert fingerprint() == before
    with sessions() as db:
        assert db.query(CuttingPassport).count() == 2
        assert all(work.actual_output_qty == 0 for work in db.query(WorkOrder))
        assert cutting_board(db, "CUT", date.fromisoformat(facts["day"]),
                             date.fromisoformat(facts["day"]))["totals"]["pieces"] == 20
