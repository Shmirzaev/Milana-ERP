"""PostgreSQL list contract: remaining quantities and read-only GET."""
from contextlib import contextmanager
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import event, text

from app.core.security import create_access_token
from app.models.inventory.waste_service import list_waste
from app.schemas import WasteRecord, WasteSale
from app.tests.test_modelsize_create_postgres import pg_sessions as pg_sessions  # noqa: F401
from app.tests.test_waste_race_rollback_postgres import _app, _public_snapshot, _setup


@contextmanager
def observe(engine):
    statements, commits = [], []
    def before(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)
    def commit(conn):
        commits.append(True)
    event.listen(engine, 'before_cursor_execute', before)
    event.listen(engine, 'commit', commit)
    try:
        yield statements, commits
    finally:
        event.remove(engine, 'before_cursor_execute', before)
        event.remove(engine, 'commit', commit)


def assert_read_only(statements, commits):
    assert not commits
    assert not [s for s in statements if s.lstrip().upper().startswith(('INSERT ', 'UPDATE ', 'DELETE ', 'MERGE ', 'TRUNCATE ', 'COMMIT'))]


def history_count(statements):
    return sum('FROM waste_sales' in s and s.lstrip().upper().startswith('SELECT') for s in statements)


def test_pg_empty_filtered_list_has_no_sale_query(pg_sessions):  # noqa: F811
    actor, _, _ = _setup(pg_sessions)
    headers = {'Authorization': f'Bearer {create_access_token(actor)}'}
    # Isolate the empty case without deleting or changing any shared fixture rows.
    with pg_sessions() as db:
        assert not db.query(WasteRecord).filter_by(status='disposed', sellable=False).count()
    with TestClient(_app(pg_sessions)) as client, observe(pg_sessions.kw['bind']) as (sql, commits):
        response = client.get('/waste?status=disposed&sellable=false', headers=headers)
    assert response.status_code == 200 and response.json() == []
    assert history_count(sql) == 0
    assert_read_only(sql, commits)


def test_pg_list_batch_history_filters_auth_and_no_writes(pg_sessions):  # noqa: F811
    actor, _, _ = _setup(pg_sessions)
    headers = {'Authorization': f'Bearer {create_access_token(actor)}'}
    cases = {
        'none': (10, [], 10), 'partial': (10, [4], 6), 'exhausted': (10, [4, 6], 0),
        'oversold': (10, [11], None), 'zero_sale': (10, [0], None),
        'negative_sale': (10, [-1], None), 'nan_sale': (10, [Decimal('NaN')], None),
        'mixed_invalid': (10, [-1, 3], None), 'zero_original': (0, [], None),
        'negative_original': (-1, [], None),
    }
    ids = {}
    with pg_sessions.begin() as db:
        for label, (original, sales, _) in cases.items():
            row = WasteRecord(waste_type=label, quantity=original, unit='kg', sellable=True, status='received_by_waste_department')
            db.add(row)
            db.flush()
            ids[label] = row.id
            for quantity in sales:
                db.add(WasteSale(waste_record_id=row.id, buyer_name='history', quantity=quantity, unit_price=1, total_amount=0))
    with pg_sessions() as db:
        before = _public_snapshot(db)
    with TestClient(_app(pg_sessions)) as client:
        assert client.get('/waste').status_code in (401, 403)
        with observe(pg_sessions.kw['bind']) as (sql, commits):
            response = client.get('/waste?status=received_by_waste_department&sellable=true', headers=headers)
        assert response.status_code == 200, response.text
        rows = {r['id']: r for r in response.json()}
        for label, (original, _, expected) in cases.items():
            assert rows[ids[label]]['quantity'] == original
            assert rows[ids[label]]['remaining_quantity'] == expected
        assert history_count(sql) == 1
        assert_read_only(sql, commits)
        filtered = client.get('/waste?status=recorded&sellable=true', headers=headers)
        assert filtered.status_code == 200
        assert not set(ids.values()) & {r['id'] for r in filtered.json()}
        filtered = client.get('/waste?status=received_by_waste_department&sellable=false', headers=headers)
        assert filtered.status_code == 200
        assert not set(ids.values()) & {r['id'] for r in filtered.json()}
    with pg_sessions() as db:
        assert _public_snapshot(db) == before


def test_pg_partial_sale_remaining_stale_and_exhaustion(pg_sessions):  # noqa: F811
    actor, wid, _ = _setup(pg_sessions)
    headers = {'Authorization': f'Bearer {create_access_token(actor)}'}
    with TestClient(_app(pg_sessions)) as client:
        def current():
            response = client.get('/waste', headers=headers)
            assert response.status_code == 200, response.text
            return next(row for row in response.json() if row['id'] == wid)
        def sell(quantity):
            return client.post(f'/waste/{wid}/sell', headers=headers, json={'buyer_name': 'Buyer', 'quantity': quantity, 'unit_price': 2})
        first = current()
        assert (first['quantity'], first['remaining_quantity']) == (10, 10)
        assert sell(4).status_code == 200
        partial = current()
        assert (partial['quantity'], partial['remaining_quantity']) == (10, 6)
        assert sell(first['remaining_quantity']).status_code == 400
        assert sell(partial['remaining_quantity']).status_code == 200
        final = current()
        assert (final['quantity'], final['remaining_quantity'], final['status']) == (10, 0, 'sold')


def test_pg_nan_original_service_diagnostic(pg_sessions):  # noqa: F811
    # The pre-existing original quantity and estimated_value still carry NaN;
    # this service assertion is not an HTTP serialization acceptance claim.
    with pg_sessions.begin() as db:
        row = WasteRecord(waste_type='nan-original', quantity=Decimal('NaN'), unit='kg', sellable=True, status='recorded')
        db.add(row)
        db.flush()
        wid = row.id
    with pg_sessions() as db:
        result = next(row for row in list_waste(db) if row.id == wid)
        assert result.remaining_quantity is None
    with pg_sessions.begin() as db:
        db.execute(text('DELETE FROM waste_records WHERE id=:id'), {'id': wid})
