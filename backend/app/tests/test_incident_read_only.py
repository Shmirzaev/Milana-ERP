"""Old recovery application must not execute newer-fact mutation paths."""
import pytest
import json
from pathlib import Path
from app.core.config import Settings, settings
from app.db.session import _engine_options
from app.schemas import User
from app.tests.conftest import TestSessionLocal
from sqlalchemy.exc import DBAPIError
from uuid import uuid4


@pytest.mark.parametrize(('enabled', 'sqlstate'), [
    (False, '25006'), (False, '23505'), (True, '23505'),
])
def test_database_errors_preserve_original_server_error(client, monkeypatch, enabled, sqlstate):
    from app.main import app
    monkeypatch.setattr(settings, 'INCIDENT_READ_ONLY', enabled)
    original = ValueError('synthetic database error')
    original.pgcode = sqlstate
    failure = DBAPIError('synthetic database failure', {}, original)
    path = '/api/incident-error-probe-' + uuid4().hex
    def fail():
        raise failure
    app.add_api_route(path, fail, methods=['GET'])
    try:
        with pytest.raises(DBAPIError) as raised:
            client.get(path)
        assert raised.value is failure
    finally:
        app.router.routes[:] = [route for route in app.router.routes if getattr(route, 'path', None) != path]


def test_readonly_database_error_is_service_unavailable(client, monkeypatch):
    from app.main import app
    monkeypatch.setattr(settings, 'INCIDENT_READ_ONLY', True)
    original = ValueError('synthetic read-only database error')
    original.pgcode = '25006'
    path = '/api/incident-error-probe-' + uuid4().hex
    def fail():
        raise DBAPIError('synthetic read-only failure', {}, original)
    app.add_api_route(path, fail, methods=['GET'])
    try:
        response = client.get(path)
        assert response.status_code == 503
        assert response.headers['x-erp-read-only'] == 'true'
    finally:
        app.router.routes[:] = [route for route in app.router.routes if getattr(route, 'path', None) != path]


def test_recovery_container_starts_uvicorn_without_migrations():
    dockerfile=(Path(__file__).resolve().parents[2]/'Dockerfile').read_text()
    command=json.loads(next(line[4:] for line in dockerfile.splitlines() if line.startswith('CMD ')))
    assert command[:2]==['sh','-c']
    assert command[2].startswith('exec env PYTHONPATH=/app:/app/backend uvicorn app.main:app ')
    assert 'alembic' not in command[2] and '&&' not in command[2]
    assert '--workers ${WEB_CONCURRENCY:-2}' in command[2]


def test_mode_defaults_off_and_requires_postgresql():
    assert Settings(_env_file=None).INCIDENT_READ_ONLY is False
    assert _engine_options('postgresql://qa@localhost/qa', None, None, True)['connect_args'] == {
        'options': '-c default_transaction_read_only=on'}
    with pytest.raises(RuntimeError, match='requires PostgreSQL'):
        _engine_options('sqlite://', None, None, True)


@pytest.mark.parametrize(('method','path'), [
    ('POST','/api/cutting/records'), ('PATCH','/api/cutting-passports/1'),
    ('DELETE','/api/work-orders/1/batches/1'), ('POST','/api/work-orders/1/start'),
    ('PATCH','/api/work-orders/1'), ('POST','/api/eco-inventory/consume'),
    ('POST','/api/auth/reset-password'), ('POST','/api/session/switch-factory'),
    ('GET','/api/packages'), ('GET','/api/packages/'), ('HEAD','/api/packages'),
    ('TRACE','/api/cutting-passports'), ('POST','/api/auth/login-json/extra'),
])
def test_incident_mode_refuses_before_business_routes(client, monkeypatch, method, path):
    monkeypatch.setattr(settings,'INCIDENT_READ_ONLY',True)
    response=client.request(method,path,json={})
    assert response.status_code==503,response.text
    assert response.headers['x-erp-read-only']=='true'


@pytest.mark.parametrize('prefix',['auth','session'])
def test_login_me_logout_work_without_timestamp_writes(client,monkeypatch,prefix):
    with TestSessionLocal() as db:
        user=db.query(User).filter_by(email='admin@example.com').one()
        before=(user.last_login_at,user.last_seen_at)
    monkeypatch.setattr(settings,'INCIDENT_READ_ONLY',True)
    response=client.post(f'/api/{prefix}/login-json',json={
        'email':'admin@example.com','password':'test-admin-password-123!','factory_code':'MIL'})
    assert response.status_code==200,response.text
    assert client.get(f'/api/{prefix}/me').status_code==200
    assert client.get('/health').status_code==200
    assert client.post(f'/api/{prefix}/logout').status_code==200
    with TestSessionLocal() as db:
        user=db.query(User).filter_by(email='admin@example.com').one()
        assert (user.last_login_at,user.last_seen_at)==before


@pytest.mark.parametrize('startup', ['seed','schema'])
def test_incident_startup_refuses_writers(monkeypatch,startup):
    from app import main
    monkeypatch.setattr(settings,'INCIDENT_READ_ONLY',True)
    monkeypatch.setattr(settings,'STARTUP_SCHEMA_SYNC',startup=='schema')
    monkeypatch.setenv('RUN_SEED_ON_STARTUP','true' if startup=='seed' else 'false')
    with pytest.raises(RuntimeError,match='forbids startup'):
        main._run_startup()


def test_normal_mode_keeps_login_timestamp_updates(client,monkeypatch):
    monkeypatch.setattr(settings,'INCIDENT_READ_ONLY',False)
    response=client.post('/api/auth/login-json',json={
        'email':'admin@example.com','password':'test-admin-password-123!','factory_code':'MIL'})
    assert response.status_code==200
    with TestSessionLocal() as db:
        user=db.query(User).filter_by(email='admin@example.com').one()
        assert user.last_login_at is not None and user.last_seen_at is not None
