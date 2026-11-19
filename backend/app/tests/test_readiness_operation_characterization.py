"""Normal /ready HTTP probes execute SELECT 1 on SQLite and approved PostgreSQL."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Lock
from time import monotonic, sleep

import pytest
from sqlalchemy import create_engine, event

from app import main
from app.core.shared_store import InMemorySharedCounterStore
from app.tests.pg_approved_instance import (
    create_target_database, finalize_target, load_approved_instance, target_engine,
)


@pytest.fixture(params=['sqlite', 'postgres'])
def readiness_engine(request, tmp_path):
    if request.param == 'sqlite':
        engine = create_engine(f'sqlite:///{tmp_path / "readiness.db"}')
        try:
            yield engine
        finally:
            engine.dispose()
        return
    target = create_target_database(load_approved_instance())
    engine = None
    try:
        engine = target_engine(target)
        yield engine
    finally:
        finalize_target(target, engine)


@pytest.fixture
def readiness_case(readiness_engine, monkeypatch):
    owner = getattr(main, 'readiness_checks', main)
    monkeypatch.setattr(owner, '_READINESS_CHECK_SLOT', Lock())
    monkeypatch.setattr(owner, '_READINESS_PROBE', None)
    monkeypatch.setattr(owner, 'engine', readiness_engine)
    store = InMemorySharedCounterStore()
    monkeypatch.setattr(owner, 'get_shared_counter_store', lambda: store)
    statements = []
    def record_sql(connection, cursor, statement, parameters, context, executemany):
        if statement.strip() == 'SELECT 1':
            statements.append(statement)
    event.listen(readiness_engine, 'before_cursor_execute', record_sql)
    yield owner, store, statements
    probe = owner._READINESS_PROBE
    if probe is not None:
        assert probe[0].wait(2), 'readiness characterization left a live probe'
    event.remove(readiness_engine, 'before_cursor_execute', record_sql)


def test_real_database_ready_http_and_dependency_free_health(client, readiness_case):
    owner, store, statements = readiness_case
    response = client.get('/ready')
    assert response.status_code == 200, response.text
    assert response.json() == {'status': 'ready', 'checks': {'postgresql': 'ok', 'shared_store': 'ok'}, 'release': main.settings.RELEASE_ID}
    assert statements == ['SELECT 1']
    assert store.ttl('readiness') is None
    assert client.get('/health').status_code == 200
    assert statements == ['SELECT 1']


@pytest.mark.parametrize('failure', ['database', 'store'])
def test_dependency_failure_http_redacts_details_then_recovers(client, readiness_case, readiness_engine, monkeypatch, failure):
    owner, store, statements = readiness_case
    def unavailable(*args, **kwargs):
        raise RuntimeError('private://user:do-not-leak@private-host/internal')
    def fail_sql(connection, cursor, statement, parameters, context, executemany):
        if statement.strip() == 'SELECT 1':
            unavailable()
    original_ttl = store.ttl
    if failure == 'database':
        event.listen(readiness_engine, 'before_cursor_execute', fail_sql)
    else:
        monkeypatch.setattr(store, 'ttl', unavailable)
    response = client.get('/ready')
    assert response.status_code == 503
    assert response.json()['checks'] == {'postgresql': 'unavailable' if failure == 'database' else 'ok', 'shared_store': 'unavailable' if failure == 'store' else 'ok'}
    assert 'private-host' not in response.text and 'do-not-leak' not in response.text
    assert statements == ['SELECT 1']
    if failure == 'database':
        event.remove(readiness_engine, 'before_cursor_execute', fail_sql)
    else:
        monkeypatch.setattr(store, 'ttl', original_ttl)
    assert client.get('/ready').status_code == 200
    assert statements == ['SELECT 1', 'SELECT 1']


def test_http_deadline_reuses_stuck_real_probe_and_recovers(client, readiness_case, monkeypatch):
    owner, store, statements = readiness_case
    entered, release = Event(), Event()
    original = owner._probe_postgresql
    def blocked():
        original()
        entered.set()
        assert release.wait(2)
    monkeypatch.setattr(owner, '_probe_postgresql', blocked)
    monkeypatch.setattr(main, '_READINESS_TIMEOUT_SECONDS', 0.04)
    try:
        started = monotonic()
        response = client.get('/ready')
        assert entered.is_set()
        assert response.status_code == 503
        assert response.json()['checks'] == {'postgresql': 'unavailable', 'shared_store': 'unavailable'}
        assert monotonic() - started < 0.35
        assert client.get('/ready').status_code == 503
        assert statements == ['SELECT 1']
    finally:
        release.set()
        assert owner._READINESS_PROBE[0].wait(2)
    monkeypatch.setattr(owner, '_probe_postgresql', original)
    assert client.get('/ready').status_code == 200
    assert statements == ['SELECT 1', 'SELECT 1']


def test_concurrent_http_callers_share_one_real_probe(client, readiness_case, monkeypatch):
    owner, store, statements = readiness_case
    entered, release = Event(), Event()
    callers = Barrier(5)
    original = owner._probe_postgresql
    def blocked():
        original()
        entered.set()
        assert release.wait(2)
    monkeypatch.setattr(owner, '_probe_postgresql', blocked)
    def request_ready():
        callers.wait(timeout=2)
        return client.get('/ready')
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = [pool.submit(request_ready) for _ in range(4)]
        callers.wait(timeout=2)
        try:
            assert entered.wait(1)
            sleep(0.05)
            assert all(not result.done() for result in results)
        finally:
            release.set()
        responses = [result.result(timeout=2) for result in results]
    assert all(response.status_code == 200 for response in responses)
    assert statements == ['SELECT 1']
