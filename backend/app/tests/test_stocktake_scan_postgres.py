"""Scan transaction regressions using the approved migrated PostgreSQL fixture."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import event, select, text

from app.api.routes import stocktake
from app.libs.dto.inventory.warehouse_stocktake_input import ScanCount
from app.models import audit_service, stocktake_service
from app.schemas import AuditLog, LegacyStockReceipt, Package, User
from app.schemas.inventory.stocktake import WarehouseStocktake, WarehouseStocktakeRow

pytest_plugins = ("app.tests.test_modelcolor_create_postgres",)


def prepare(sessions, case, app):
    with sessions.begin() as db:
        db.get(User, case["actors"]["standard"]).role.permissions = ["storage.packages"]
        db.get(User, case["actors"]["eco"]).role.permissions = ["storage.packages"]
        count = WarehouseStocktake(request_key=str(uuid4()), title="scan", created_by=case["actors"]["standard"])
        db.add(count)
        db.flush()
        count_id = count.id
    app.include_router(stocktake.router, prefix="/api")
    return count_id


def state(sessions, count_id):
    with sessions() as db:
        rows = db.scalars(select(WarehouseStocktakeRow).where(
            WarehouseStocktakeRow.stocktake_id == count_id).order_by(WarehouseStocktakeRow.id)).all()
        audits = db.scalars(select(AuditLog).where(AuditLog.entity_type == "WarehouseStocktake",
            AuditLog.entity_id == count_id).order_by(AuditLog.id)).all()
        return ([(r.id, r.identity, r.package_id, r.expected, r.category, r.snapshot,
                  r.scan_snapshot, r.scan_code, r.scanned_at, r.scanned_by) for r in rows],
                [(a.action, a.user_id, a.new_value_json) for a in audits])


def test_pg_scan_auth_duplicate_first_evidence_and_completed_refusal(pg_sessions, pg_case, pg_app):
    count_id = prepare(pg_sessions, pg_case, pg_app)
    url = f"/api/warehouse-stocktakes/{count_id}/scan"
    code = f"unknown-{uuid4()}"
    with TestClient(pg_app, raise_server_exceptions=False) as client:
        for actor, status in (("anonymous", 401), ("denied", 403)):
            assert client.post(url, headers={"X-Actor": actor}, json={"code": code}).status_code == status
        assert state(pg_sessions, count_id) == ([], [])
        first = client.post(url, json={"code": code})
        assert first.status_code == 200 and first.json()["duplicate"] is False
        before_rows, before_audits = state(pg_sessions, count_id)
        assert len(before_rows) == 1 and before_rows[0][2:8] == (None, False, "unknown", {}, None, code)
        assert before_rows[0][8] is not None and before_rows[0][9] == pg_case["actors"]["standard"]
        assert len(before_audits) == 1 and before_audits[0][0:2] == ("scan", pg_case["actors"]["standard"])
        duplicate = client.post(url, headers={"X-Actor": "eco"}, json={"code": code})
        assert duplicate.status_code == 200 and duplicate.json()["duplicate"] is True
        rows, audits = state(pg_sessions, count_id)
        assert rows == before_rows
        assert len(audits) == 2 and audits[0] == before_audits[0]
        assert audits[1][0:2] == ("scan_duplicate", pg_case["actors"]["eco"])
        assert audits[1][2]["row_id"] == rows[0][0]
        with pg_sessions.begin() as db:
            db.get(WarehouseStocktake, count_id).completed_at = datetime.now(timezone.utc)
        assert client.post(url, json={"code": "another"}).status_code == 409
        assert state(pg_sessions, count_id) == (rows, audits)


def test_pg_scan_request_audit_finalization_failure_then_retry(pg_sessions, pg_case, pg_app, monkeypatch):
    count_id = prepare(pg_sessions, pg_case, pg_app)
    url = f"/api/warehouse-stocktakes/{count_id}/scan"
    code = f"unknown-{uuid4()}"
    observed = []
    original = audit_service.add_audit_log_rows

    def fail_after_flush(db, entries):
        original(db, entries)
        db.flush()
        observed.extend(entry.action for entry in entries)
        raise RuntimeError("injected audit finalization failure")

    with monkeypatch.context() as patch:
        patch.setattr(audit_service, "add_audit_log_rows", fail_after_flush)
        with TestClient(pg_app, raise_server_exceptions=False) as client:
            assert client.post(url, json={"code": code}).status_code == 500
    assert observed == ["scan"]
    assert state(pg_sessions, count_id) == ([], [])
    with TestClient(pg_app, raise_server_exceptions=False) as client:
        response = client.post(url, json={"code": code})
    assert response.status_code == 200 and response.json()["duplicate"] is False
    rows, audits = state(pg_sessions, count_id)
    assert len(rows) == 1 and rows[0][7] == code and rows[0][9] == pg_case["actors"]["standard"]
    assert len(audits) == 1 and audits[0][0:2] == ("scan", pg_case["actors"]["standard"])
    assert audits[0][2]["row_id"] == rows[0][0]


def seed_packages(sessions, case, count_id):
    """Use the same legacy-receipt-backed package shape as the creation tests."""
    marker = uuid4().hex
    packages = []
    with sessions.begin() as db:
        for status in ("received_in_storage", "packed"):
            receipt = LegacyStockReceipt(source_system="COUNT_TEST", source_warehouse_id="1",
                source_record_id=f"{marker}-{status}", source_checksum="0" * 64, source_payload={})
            db.add(receipt)
            db.flush()
            package = Package(package_no=f"COUNT-{marker}-{status}", barcode=f"QR-{marker}-{status}",
                legacy_receipt_id=receipt.id, model_id=case["models"]["standard"],
                color="BLUE", total_quantity=10, capacity=10, status=status)
            db.add(package)
            db.flush()
            packages.append((package.id, package.package_no, package.barcode))
        expected_id = packages[0][0]
        db.add(WarehouseStocktakeRow(stocktake_id=count_id, identity=f"package:{expected_id}",
            package_id=expected_id, expected=True, category="expected", snapshot={"quantity": 10}))
    return packages


def test_pg_scan_expected_unexpected_package_and_refusals(pg_sessions, pg_case, pg_app):
    count_id = prepare(pg_sessions, pg_case, pg_app)
    expected, unexpected = seed_packages(pg_sessions, pg_case, count_id)
    url = f"/api/warehouse-stocktakes/{count_id}/scan"
    before = state(pg_sessions, count_id)
    with TestClient(pg_app, raise_server_exceptions=False) as client:
        for actor, status in (("anonymous", 401), ("denied", 403)):
            assert client.post(url, headers={"X-Actor": actor}, json={"code": expected[2]}).status_code == status
        assert client.post(url, json={"code": "   "}).status_code == 422
        assert state(pg_sessions, count_id) == before
        first = client.post(url, json={"code": expected[2]})
        assert first.status_code == 200 and first.json()["duplicate"] is False
        assert first.json()["row"]["result"] == "found"
        expected_rows, expected_audits = state(pg_sessions, count_id)
        row = expected_rows[0]
        assert len(expected_rows) == 1 and row[1:4] == (f"package:{expected[0]}", expected[0], True)
        assert row[4:6] == ("expected", {"quantity": 10})
        assert row[6]["quantity"] == 10 and row[6]["status"] == "received_in_storage"
        assert row[7] == expected[2] and row[8] is not None and row[9] == pg_case["actors"]["standard"]
        assert expected_audits == [("scan", pg_case["actors"]["standard"],
            {"row_id": row[0], "code": expected[2], "package_id": expected[0], "category": "expected"})]
        duplicate = client.post(url, headers={"X-Actor": "eco"}, json={"code": expected[1]})
        assert duplicate.status_code == 200 and duplicate.json()["duplicate"] is True
        rows, audits = state(pg_sessions, count_id)
        assert rows == expected_rows
        assert audits == expected_audits + [("scan_duplicate", pg_case["actors"]["eco"],
            {"row_id": row[0], "code": expected[1], "package_id": expected[0], "category": "expected"})]
        other = client.post(url, json={"code": unexpected[2]})
        assert other.status_code == 200 and other.json()["duplicate"] is False
        assert other.json()["row"]["result"] == "unexpected"
        rows, audits = state(pg_sessions, count_id)
        assert len(rows) == 2 and rows[0] == row
        created = rows[1]
        assert created[1:5] == (f"package:{unexpected[0]}", unexpected[0], False, "unexpected")
        assert created[5]["quantity"] == created[6]["quantity"] == 10
        assert created[5]["status"] == created[6]["status"] == "packed"
        assert created[7] == unexpected[2] and created[8] is not None and created[9] == pg_case["actors"]["standard"]
        assert audits[-1] == ("scan", pg_case["actors"]["standard"],
            {"row_id": created[0], "code": unexpected[2], "package_id": unexpected[0], "category": "unexpected"})
        assert len(audits) == 3
        with pg_sessions.begin() as db:
            db.get(WarehouseStocktake, count_id).completed_at = datetime.now(timezone.utc)
        assert client.post(url, json={"code": expected[2]}).status_code == 409
        assert client.post(url, json={"code": unexpected[2]}).status_code == 409
        assert state(pg_sessions, count_id) == (rows, audits)


def test_pg_duplicate_package_scan_waits_on_first_parent_lock(pg_sessions, pg_case, pg_app, monkeypatch):
    count_id = prepare(pg_sessions, pg_case, pg_app)
    expected, _ = seed_packages(pg_sessions, pg_case, count_id)
    before = state(pg_sessions, count_id)
    locked, release, selecting = Event(), Event(), Event()
    pids = {}
    original = stocktake_service.record_first_scan

    def pause_first(db, row, **kwargs):
        original(db, row, **kwargs)
        pids["first"] = db.scalar(text("select pg_backend_pid()"))
        locked.set()
        assert release.wait(20)

    monkeypatch.setattr(stocktake_service, "record_first_scan", pause_first)

    def scan(actor_name, code, observe=False):
        with pg_sessions() as db:
            actor = db.get(User, pg_case["actors"][actor_name])
            if observe:
                pids["second"] = db.scalar(text("select pg_backend_pid()"))
                def before_execute(conn, cursor, statement, parameters, context, executemany):
                    if "for update" in statement.lower() and "warehouse_stocktakes" in statement.lower():
                        selecting.set()
                event.listen(db.connection(), "before_cursor_execute", before_execute)
            return stocktake_service.scan_count(db, count_id, ScanCount(code=code), actor)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(scan, "standard", expected[2])
        second = None
        try:
            assert locked.wait(10)
            second = pool.submit(scan, "eco", expected[1], True)
            assert selecting.wait(10)
            deadline = monotonic() + 10
            blocked = False
            while monotonic() < deadline:
                with pg_sessions() as db:
                    blocked = pids["first"] in db.scalar(
                        text("select pg_blocking_pids(:pid)"), {"pid": pids["second"]})
                if blocked:
                    break
                sleep(.05)
            assert blocked
            assert state(pg_sessions, count_id) == before
        finally:
            release.set()
            try:
                first_result = first.result(timeout=30)
            finally:
                second_result = second.result(timeout=30) if second is not None else None
    assert first_result["duplicate"] is False
    assert second_result is not None and second_result["duplicate"] is True
    rows, audits = state(pg_sessions, count_id)
    assert len(rows) == 1
    row = rows[0]
    assert row[1:5] == (f"package:{expected[0]}", expected[0], True, "expected")
    assert row[6]["quantity"] == 10 and row[6]["status"] == "received_in_storage"
    assert row[7] == expected[2] and row[8] is not None and row[9] == pg_case["actors"]["standard"]
    assert first_result["row"]["scan_snapshot"] == second_result["row"]["scan_snapshot"] == row[6]
    assert first_result["row"]["scanned_at"] == second_result["row"]["scanned_at"]
    assert first_result["row"]["scanned_by"] == second_result["row"]["scanned_by"] == row[9]
    assert audits == [
        ("scan", pg_case["actors"]["standard"],
         {"row_id": row[0], "code": expected[2], "package_id": expected[0], "category": "expected"}),
        ("scan_duplicate", pg_case["actors"]["eco"],
         {"row_id": row[0], "code": expected[1], "package_id": expected[0], "category": "expected"}),
    ]
