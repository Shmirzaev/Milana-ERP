from threading import Lock
from time import monotonic, sleep

import pytest

from app import main


@pytest.fixture(autouse=True)
def isolated_readiness_slot(monkeypatch):
    monkeypatch.setattr(main, "_READINESS_CHECK_SLOT", Lock())


def test_readiness_reports_healthy_postgresql_without_shared_store(client, monkeypatch):
    monkeypatch.setattr(main, "_probe_postgresql", lambda: None)

    def forbidden_shared_store():
        pytest.fail("PostgreSQL readiness must not depend on Redis/shared-store policy")

    monkeypatch.setattr(main, "get_shared_counter_store", forbidden_shared_store)

    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {"postgresql": "ok"}}


def test_readiness_returns_503_for_database_failure_without_secrets(client, monkeypatch):
    leaked_url = "postgresql://erp:do-not-leak@private-db.internal:5432/erp"

    def fail_probe():
        raise RuntimeError(f"connection failed for {leaked_url}\nprivate stack details")

    monkeypatch.setattr(main, "_probe_postgresql", fail_probe)

    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {"postgresql": "unavailable"},
    }
    assert "do-not-leak" not in response.text
    assert "private-db.internal" not in response.text
    assert "private stack details" not in response.text


def test_readiness_database_timeout_is_bounded(client, monkeypatch):
    monkeypatch.setattr(main, "_READINESS_TIMEOUT_SECONDS", 0.02)
    monkeypatch.setattr(main, "_probe_postgresql", lambda: sleep(0.5))

    started = monotonic()
    response = client.get("/ready")
    elapsed = monotonic() - started

    assert response.status_code == 503
    assert elapsed < 0.3


def test_health_remains_liveness_when_database_is_unavailable(client, monkeypatch):
    monkeypatch.setattr(main, "_probe_postgresql", lambda: (_ for _ in ()).throw(RuntimeError("database down")))

    assert client.get("/ready").status_code == 503
    health = client.get("/health")

    assert health.status_code == 200
    assert health.json() == {"status": "ok", "app": main.settings.APP_NAME}
