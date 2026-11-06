"""Known PostgreSQL commit abort for the manual waste request."""
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import event

from app.core.security import create_access_token
from app.tests.test_waste_create_receive_postgres import _app, _public_snapshot, _seed
from app.tests.test_modelsize_create_postgres import pg_sessions as pg_sessions  # noqa: F401


def test_pg_manual_create_commit_abort_rolls_back_then_retry(pg_sessions):
    actor, _, item_id, batch_id = _seed(pg_sessions)
    marker = f'commit-abort-{uuid4().hex}'
    payload = {'item_id': item_id, 'batch_id': batch_id, 'waste_type': 'cutting', 'quantity': 4,
               'unit': 'kg', 'reason': marker}
    headers = {'Authorization': f'Bearer {create_access_token(actor)}'}
    engine = pg_sessions.kw['bind']
    with pg_sessions() as db:
        before = _public_snapshot(db)
    with engine.begin() as conn:
        conn.exec_driver_sql("""CREATE FUNCTION pr411_reject_commit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
            RAISE EXCEPTION 'fixture commit failure' USING ERRCODE = '23514', CONSTRAINT = 'pr411_commit_guard'; END; $$""")
        conn.exec_driver_sql(f"""CREATE CONSTRAINT TRIGGER pr411_commit_guard AFTER INSERT ON waste_records
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN (NEW.reason = '{marker}')
            EXECUTE FUNCTION pr411_reject_commit()""")
    observed = []
    def capture(context):
        exc = context.original_exception
        if getattr(exc, 'pgcode', None) == '23514':
            observed.append((context.statement, exc.diag.constraint_name))
    event.listen(engine, 'handle_error', capture)
    try:
        with TestClient(_app(pg_sessions), raise_server_exceptions=False) as client:
            failed = client.post('/waste', headers=headers, json=payload)
        assert failed.status_code == 500 and observed == [(None, 'pr411_commit_guard')]
        with pg_sessions() as db:
            assert _public_snapshot(db) == before
    finally:
        event.remove(engine, 'handle_error', capture)
        with engine.begin() as conn:
            conn.exec_driver_sql('DROP TRIGGER pr411_commit_guard ON waste_records')
            conn.exec_driver_sql('DROP FUNCTION pr411_reject_commit()')
    with TestClient(_app(pg_sessions), raise_server_exceptions=False) as client:
        retry = client.post('/waste', headers=headers, json=payload)
    assert retry.status_code == 201
    with pg_sessions() as db:
        from app.schemas import AuditLog, WasteRecord
        record = db.get(WasteRecord, retry.json()['id'])
        assert record.reason == marker and float(record.estimated_value) == 13.0
        assert db.query(AuditLog).filter_by(entity_type='WasteRecord', entity_id=record.id, action='create').count() == 1
