from concurrent.futures import ThreadPoolExecutor
import json
import os
from queue import Queue
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.core.integration_auth import (
    OneCIntegrationIdentity,
    authenticate_onec_integration,
    parse_onec_client_credentials,
)
from app.core.config import settings
from app.db.base import Base
from app.models import IdempotencyRecord
from app.services.integration_idempotency import replay_integration_response, store_integration_response
from app.tests.conftest import TestSessionLocal


CLIENTS = json.dumps({
    "accounting-primary": {
        "current": "a" * 48,
        "previous": "b" * 48,
    },
    "accounting-reporting": {
        "current": "c" * 48,
    },
})


@pytest.mark.parametrize(
    ("client_id", "token", "credential_id"),
    [
        ("accounting-primary", "a" * 48, "current"),
        ("accounting-primary", "b" * 48, "previous"),
        ("accounting-reporting", "c" * 48, "current"),
    ],
)
def test_named_1c_clients_support_explicit_rotation_slots(client_id, token, credential_id):
    identity = authenticate_onec_integration(
        supplied_client_id=client_id,
        supplied_token=token,
        clients_json=CLIENTS,
        legacy_shared_token="old-shared-token",
        strict_security_required=True,
    )
    assert identity == OneCIntegrationIdentity(client_id, credential_id)
    assert token not in json.dumps(identity.audit_metadata())


@pytest.mark.parametrize(
    ("client_id", "token"),
    [
        (None, "a" * 48),
        ("unknown", "a" * 48),
        ("accounting-primary", "wrong"),
        ("accounting-reporting", "a" * 48),
    ],
)
def test_named_1c_clients_reject_missing_wrong_or_cross_client_credentials(client_id, token):
    with pytest.raises(HTTPException) as caught:
        authenticate_onec_integration(
            supplied_client_id=client_id,
            supplied_token=token,
            clients_json=CLIENTS,
            legacy_shared_token="old-shared-token",
            strict_security_required=True,
        )
    assert caught.value.status_code == 401
    assert caught.value.detail == "Invalid 1C token"


def test_shared_1c_token_is_development_compatibility_only():
    identity = authenticate_onec_integration(
        supplied_client_id=None,
        supplied_token="local-token",
        clients_json="",
        legacy_shared_token="local-token",
        strict_security_required=False,
    )
    assert identity.legacy_shared is True

    with pytest.raises(HTTPException) as caught:
        authenticate_onec_integration(
            supplied_client_id=None,
            supplied_token="local-token",
            clients_json="",
            legacy_shared_token="local-token",
            strict_security_required=True,
        )
    assert caught.value.status_code == 503
    assert "per-client" in caught.value.detail


@pytest.mark.parametrize(
    "raw",
    [
        "not-json",
        "[]",
        json.dumps({"bad client": {"current": "a" * 48}}),
        json.dumps({"client": {"bad credential": "a" * 48}}),
        json.dumps({"client": {"current": "short"}}),
        json.dumps({"one": {"current": "a" * 48}, "two": {"current": "a" * 48}}),
    ],
)
def test_1c_client_configuration_fails_closed_without_exposing_secrets(raw):
    with pytest.raises(ValueError) as caught:
        parse_onec_client_credentials(raw, minimum_secret_length=32)
    assert "a" * 48 not in str(caught.value)


def test_integration_replay_is_scoped_to_client_and_never_persists_credentials():
    primary = OneCIntegrationIdentity("accounting-primary", "current")
    reporting = OneCIntegrationIdentity("accounting-reporting", "current")
    payload = {"invoices": [{"external_id": "invoice-1"}], "payments": []}
    response = {"invoices_created": 1, "errors": []}

    with TestSessionLocal() as db:
        assert replay_integration_response(
            db, identity=primary, key="request-1", payload=payload, required=True,
        ) is None
        store_integration_response(
            db, identity=primary, key="request-1", payload=payload, response=response,
        )
        db.commit()

    with TestSessionLocal() as db:
        assert replay_integration_response(
            db, identity=primary, key="request-1", payload=payload, required=True,
        ) == response
        assert replay_integration_response(
            db, identity=reporting, key="request-1", payload=payload, required=True,
        ) is None
        row = db.query(IdempotencyRecord).filter(IdempotencyRecord.scope.like("integrations.1c:%")).one()
        serialized = json.dumps(row.response_json)
        assert row.user_id is None
        assert "credential" not in serialized
        assert "token" not in serialized

        with pytest.raises(HTTPException) as caught:
            replay_integration_response(
                db,
                identity=primary,
                key="request-1",
                payload={"invoices": [], "payments": []},
                required=True,
            )
        assert caught.value.status_code == 409


def test_integration_replay_policy_can_require_request_identity():
    with TestSessionLocal() as db:
        with pytest.raises(HTTPException) as caught:
            replay_integration_response(
                db,
                identity=OneCIntegrationIdentity("accounting-primary", "current"),
                key=None,
                payload={},
                required=True,
            )
    assert caught.value.status_code == 400


def test_1c_route_rejects_invalid_named_client_before_sync_or_idempotency_write(client, monkeypatch):
    import app.api.routes.finance as finance_route

    secret = "route-secret-" + "x" * 40
    monkeypatch.setattr(settings, "INTEGRATION_1C_CLIENTS_JSON", json.dumps({"accounting": {"current": secret}}))
    monkeypatch.setattr(settings, "INTEGRATION_1C_TOKEN", "legacy-token")
    monkeypatch.setattr(settings, "ENV", "production")
    sync_calls = []
    monkeypatch.setattr(finance_route, "sync_from_1c", lambda *_args: sync_calls.append(True))

    with TestSessionLocal() as db:
        before = db.query(IdempotencyRecord).filter(
            IdempotencyRecord.scope.like("integrations.1c:%")
        ).count()
    response = client.post(
        "/api/finance/integrations/1c/sync",
        headers={"X-1C-Client": "accounting", "X-1C-Token": "wrong", "Idempotency-Key": "route-invalid"},
        json={"invoices": [], "payments": []},
    )
    with TestSessionLocal() as db:
        after = db.query(IdempotencyRecord).filter(
            IdempotencyRecord.scope.like("integrations.1c:%")
        ).count()

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid 1C token"}
    assert sync_calls == []
    assert after == before
    assert secret not in response.text


def test_1c_route_uses_client_identity_and_replays_without_persisting_credentials(client, monkeypatch):
    import app.api.routes.finance as finance_route

    secret = "route-secret-" + "y" * 40
    monkeypatch.setattr(settings, "INTEGRATION_1C_CLIENTS_JSON", json.dumps({"accounting": {"current": secret}}))
    monkeypatch.setattr(settings, "INTEGRATION_1C_TOKEN", "legacy-token")
    monkeypatch.setattr(settings, "ENV", "production")
    calls = []

    def fake_sync(_db, _payload):
        calls.append(True)
        return {"invoices_created": 1, "payments_created": 0, "errors": []}

    monkeypatch.setattr(finance_route, "sync_from_1c", fake_sync)
    headers = {
        "X-1C-Client": "accounting",
        "X-1C-Token": secret,
        "Idempotency-Key": "route-replay",
    }
    body = {"invoices": [], "payments": []}
    first = client.post("/api/finance/integrations/1c/sync", headers=headers, json=body)
    second = client.post("/api/finance/integrations/1c/sync", headers=headers, json=body)

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json() == {"invoices_created": 1, "payments_created": 0, "errors": []}
    assert len(calls) == 1
    with TestSessionLocal() as db:
        rows = db.query(IdempotencyRecord).filter_by(
            scope="integrations.1c:accounting", key="route-replay",
        ).all()
        assert len(rows) == 1
        serialized = json.dumps(rows[0].response_json)
        assert secret not in serialized
        assert "legacy-token" not in serialized


def test_1c_route_fails_closed_when_named_clients_are_unconfigured_in_production(client, monkeypatch):
    import app.api.routes.finance as finance_route

    monkeypatch.setattr(settings, "INTEGRATION_1C_CLIENTS_JSON", "")
    monkeypatch.setattr(settings, "INTEGRATION_1C_TOKEN", "legacy-token")
    monkeypatch.setattr(settings, "ENV", "production")
    sync_calls = []
    monkeypatch.setattr(finance_route, "sync_from_1c", lambda *_args: sync_calls.append(True))

    response = client.post(
        "/api/finance/integrations/1c/sync",
        headers={"X-1C-Token": "legacy-token", "Idempotency-Key": "route-no-clients"},
        json={"invoices": [], "payments": []},
    )
    assert response.status_code == 503
    assert "per-client" in response.json()["detail"]
    assert sync_calls == []


def test_1c_route_requires_replay_key_in_production(client, monkeypatch):
    import app.api.routes.finance as finance_route

    secret = "route-secret-" + "z" * 40
    monkeypatch.setattr(settings, "INTEGRATION_1C_CLIENTS_JSON", json.dumps({"accounting": {"current": secret}}))
    monkeypatch.setattr(settings, "ENV", "production")
    sync_calls = []
    monkeypatch.setattr(finance_route, "sync_from_1c", lambda *_args: sync_calls.append(True))

    response = client.post(
        "/api/finance/integrations/1c/sync",
        headers={"X-1C-Client": "accounting", "X-1C-Token": secret},
        json={"invoices": [], "payments": []},
    )
    assert response.status_code == 400
    assert response.json() == {"detail": "Idempotency-Key is required for 1C synchronization"}
    assert sync_calls == []


@pytest.fixture(scope="module")
def integration_replay_postgres_sessions():
    raw = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw:
        pytest.skip("Requires disposable PostgreSQL")
    url = make_url(raw)
    if url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"} or url.query:
        pytest.fail("Only loopback PostgreSQL without connection overrides is supported")
    schema = f"ops09_integration_{uuid4().hex}"
    engine = create_engine(
        url,
        pool_size=4,
        max_overflow=0,
        isolation_level="READ COMMITTED",
        connect_args={"options": f"-csearch_path={schema} -clock_timeout=15000 -cstatement_timeout=20000"},
    )
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        Base.metadata.create_all(engine)
        yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()


def test_postgres_same_client_replay_serializes_and_returns_one_result(integration_replay_postgres_sessions):
    sessions = integration_replay_postgres_sessions
    identity = OneCIntegrationIdentity("accounting-primary", "current")
    key = f"ops09-{uuid4().hex}"
    payload = {"invoices": [{"external_id": "invoice-1"}], "payments": []}
    first_has_lock = Event()
    release_first = Event()
    second_pid = Queue()

    def submit(index: int):
        with sessions() as db:
            pid = db.execute(text("SELECT pg_backend_pid()")).scalar_one()
            if index:
                second_pid.put(pid)
            replay = replay_integration_response(
                db, identity=identity, key=key, payload=payload, required=True,
            )
            if replay is not None:
                db.commit()
                return replay
            result = {"request_owner": index, "invoices_created": 1}
            if index == 0:
                first_has_lock.set()
                assert release_first.wait(15), "First integration request was not released"
            store_integration_response(db, identity=identity, key=key, payload=payload, response=result)
            db.commit()
            return result

    with ThreadPoolExecutor(max_workers=2) as workers:
        first = workers.submit(submit, 0)
        assert first_has_lock.wait(10), "First integration request did not acquire its replay lock"
        second = workers.submit(submit, 1)
        pid = second_pid.get(timeout=10)
        try:
            with sessions() as observer:
                deadline = monotonic() + 10
                while monotonic() < deadline:
                    if observer.execute(text("SELECT cardinality(pg_blocking_pids(:pid))"), {"pid": pid}).scalar_one() > 0:
                        break
                    sleep(0.02)
                else:
                    pytest.fail("Repeated integration request must wait for the original replay lock")
        finally:
            release_first.set()
        assert first.result(timeout=20) == second.result(timeout=20) == {
            "request_owner": 0,
            "invoices_created": 1,
        }

    with sessions() as db:
        assert db.query(IdempotencyRecord).filter_by(
            scope="integrations.1c:accounting-primary", key=key,
        ).count() == 1
