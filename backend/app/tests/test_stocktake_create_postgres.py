"""Creation regressions using the approved migrated PostgreSQL fixture."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import event, select

from app.api.routes import stocktake
from app.libs.dto.inventory.warehouse_stocktake_input import CreateCount
from app.models import audit_service, stocktake_service
from app.schemas import AuditLog, LegacyStockReceipt, Package, User
from app.schemas.inventory.stocktake import WarehouseStocktake, WarehouseStocktakeRow

pytest_plugins = ("app.tests.test_modelcolor_create_postgres",)
URL = "/api/warehouse-stocktakes"


def prepare(sessions, case, app):
    marker = uuid4().hex
    with sessions.begin() as db:
        db.get(User, case["actors"]["standard"]).role.permissions = ["storage.packages"]
        ids = []
        for status in ("received_in_storage", "packed"):
            receipt = LegacyStockReceipt(source_system="COUNT_TEST", source_warehouse_id="1",
                                         source_record_id=f"{marker}-{status}", source_checksum="0" * 64,
                                         source_payload={})
            db.add(receipt)
            db.flush()
            package = Package(package_no=f"COUNT-{marker}-{status}", barcode=f"QR-{marker}-{status}",
                              legacy_receipt_id=receipt.id, model_id=case["models"]["standard"],
                              color="BLUE", total_quantity=10, capacity=10, status=status)
            db.add(package)
            db.flush()
            ids.append(package.id)
        expected = set(db.scalars(select(Package.id).where(
            Package.status.in_(("received_in_storage", "reserved", "damaged")))).all())
    app.include_router(stocktake.router, prefix="/api")
    return ids, expected


def state(sessions, key, failed_id=None):
    with sessions() as db:
        counts = db.scalars(select(WarehouseStocktake).where(WarehouseStocktake.request_key == str(key))).all()
        ids = [count.id for count in counts]
        observed_ids = ids + ([failed_id] if failed_id is not None else [])
        rows = db.scalars(select(WarehouseStocktakeRow).where(WarehouseStocktakeRow.stocktake_id.in_(observed_ids))).all()
        audits = db.scalars(select(AuditLog).where(AuditLog.entity_type == "WarehouseStocktake",
            AuditLog.action == "start", AuditLog.entity_id.in_(observed_ids))).all()
        return [(c.id, c.title, c.created_by) for c in counts], [(r.stocktake_id, r.package_id, r.expected, r.category, r.snapshot) for r in rows], [(a.entity_id, a.user_id, a.new_value_json) for a in audits]


def assert_created(sessions, key, actor, package_ids, expected, count_id):
    counts, rows, audits = state(sessions, key)
    assert counts == [(count_id, "Count", actor)]
    assert len(rows) == len(expected)
    assert {r[1] for r in rows} == expected
    assert all(r[0] == count_id and r[2:4] == (True, "expected") for r in rows)
    snapshot = next(r[4] for r in rows if r[1] == package_ids[0])
    assert snapshot["quantity"] == 10 and snapshot["status"] == "received_in_storage"
    assert package_ids[1] not in {r[1] for r in rows}
    assert audits == [(count_id, actor, {"title": "Count"})]


def test_pg_http_create_auth_and_request_key_replay(pg_sessions, pg_case, pg_app):
    package_ids, expected = prepare(pg_sessions, pg_case, pg_app)
    key = uuid4()
    body = {"request_key": str(key), "title": "  Count  "}
    with TestClient(pg_app, raise_server_exceptions=False) as client:
        for actor, status in (("anonymous", 401), ("denied", 403)):
            response = client.post(URL, headers={"X-Actor": actor}, json=body)
            assert response.status_code == status
        assert state(pg_sessions, key) == ([], [], [])
        created = client.post(URL, json=body)
        replay = client.post(URL, json={**body, "title": "Different"})
    assert created.status_code == replay.status_code == 200
    assert replay.json() == created.json()
    assert_created(pg_sessions, key, pg_case["actors"]["standard"], package_ids, expected, created.json()["id"])


def test_pg_same_key_concurrent_create_replays_unique_winner(pg_sessions, pg_case, pg_app, monkeypatch):
    package_ids, expected = prepare(pg_sessions, pg_case, pg_app)
    key = uuid4()
    barrier, guard = Barrier(2), Lock()
    rollbacks = []
    original = stocktake_service.add_stocktake
    def synchronized_add(db, **kwargs):
        barrier.wait(timeout=15)  # Both initial key lookups have returned no row.
        return original(db, **kwargs)
    monkeypatch.setattr(stocktake_service, "add_stocktake", synchronized_add)
    def create():
        with pg_sessions() as db:
            def rolled_back(session):
                with guard:
                    rollbacks.append(True)
            event.listen(db, "after_rollback", rolled_back)
            actor = db.get(User, pg_case["actors"]["standard"])
            return stocktake_service.create_count(db, CreateCount(request_key=key, title=" Count "), actor)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(create) for _ in range(2)]
        results = [future.result(timeout=45) for future in futures]
    assert results[0] == results[1]
    assert len(rollbacks) == 1
    assert_created(pg_sessions, key, pg_case["actors"]["standard"], package_ids, expected, results[0]["id"])


def test_pg_request_audit_finalization_failure_rolls_back_then_retry(pg_sessions, pg_case, pg_app, monkeypatch):
    package_ids, expected = prepare(pg_sessions, pg_case, pg_app)
    key = uuid4()
    body = {"request_key": str(key), "title": "Count"}
    failed_ids = []
    original = audit_service.add_audit_log_rows
    def fail_after_audit_flush(db, entries):
        failed_ids.extend(entry.entity_id for entry in entries if entry.entity_type == "WarehouseStocktake")
        original(db, entries)
        db.flush()
        raise RuntimeError("injected audit finalization failure")
    with monkeypatch.context() as patch:
        patch.setattr(audit_service, "add_audit_log_rows", fail_after_audit_flush)
        with TestClient(pg_app, raise_server_exceptions=False) as client:
            failed = client.post(URL, json=body)
    assert failed.status_code == 500 and len(failed_ids) == 1
    assert state(pg_sessions, key, failed_ids[0]) == ([], [], [])
    with TestClient(pg_app, raise_server_exceptions=False) as client:
        retry = client.post(URL, json=body)
    assert retry.status_code == 200
    assert_created(pg_sessions, key, pg_case["actors"]["standard"], package_ids, expected, retry.json()["id"])


def test_pg_deferred_create_commit_abort_rolls_back_then_retry(pg_sessions, pg_case, pg_app):
    package_ids, expected = prepare(pg_sessions, pg_case, pg_app)
    key = uuid4()
    body = {"request_key": str(key), "title": "Count"}
    engine = pg_sessions.kw["bind"]
    observed = []
    failed_ids = []
    with engine.begin() as conn:
        conn.exec_driver_sql("""CREATE FUNCTION pr415_create_commit_abort() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
            RAISE EXCEPTION 'fixture commit failure' USING ERRCODE = '23514', CONSTRAINT = 'pr415_create_commit_guard'; END; $$""")
        conn.exec_driver_sql(f"""CREATE CONSTRAINT TRIGGER pr415_create_commit_guard AFTER INSERT ON warehouse_stocktakes
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN (NEW.request_key = '{key}')
            EXECUTE FUNCTION pr415_create_commit_abort()""")
    def capture(context):
        exc = context.original_exception
        if getattr(exc, "pgcode", None) == "23514":
            observed.append((context.statement, exc.diag.constraint_name))
    def capture_id(session, flush_context):
        failed_ids.extend(row.id for row in session.identity_map.values() if isinstance(row, WarehouseStocktake) and row.request_key == str(key) and row.id not in failed_ids)
    event.listen(engine, "handle_error", capture)
    from sqlalchemy.orm import Session
    event.listen(Session, "after_flush_postexec", capture_id)
    try:
        with TestClient(pg_app, raise_server_exceptions=False) as client:
            failed = client.post(URL, json=body)
        assert failed.status_code == 500 and observed == [(None, "pr415_create_commit_guard")]
        assert len(failed_ids) == 1
        assert state(pg_sessions, key, failed_ids[0]) == ([], [], [])
    finally:
        event.remove(Session, "after_flush_postexec", capture_id)
        event.remove(engine, "handle_error", capture)
        with engine.begin() as conn:
            conn.exec_driver_sql("DROP TRIGGER pr415_create_commit_guard ON warehouse_stocktakes")
            conn.exec_driver_sql("DROP FUNCTION pr415_create_commit_abort()")
    with TestClient(pg_app, raise_server_exceptions=False) as client:
        retry = client.post(URL, json=body)
    assert retry.status_code == 200
    assert_created(pg_sessions, key, pg_case["actors"]["standard"], package_ids, expected, retry.json()["id"])
