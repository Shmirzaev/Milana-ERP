from threading import Event, Lock
from time import monotonic, sleep
from unittest.mock import Mock

import pytest

from app import main


@pytest.fixture(autouse=True)
def isolated_readiness_slots(monkeypatch):
    monkeypatch.setattr(main, "_READINESS_CHECK_SLOT", Lock())
    monkeypatch.setattr(main, "_SHARED_STORE_READINESS_CHECK_SLOT", Lock())


def test_readiness_reports_healthy_required_dependencies(client, monkeypatch):
    monkeypatch.setattr(main, "_probe_postgresql", lambda: None)
    store = Mock()
    monkeypatch.setattr(main, "get_shared_counter_store", lambda: store)

    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {"postgresql": "ok", "shared_store": "ok"},
    }
    store.ping.assert_called_once_with()


def test_readiness_returns_503_for_database_failure_without_secrets(client, monkeypatch):
    leaked_url = "postgresql://erp:do-not-leak@private-db.internal:5432/erp"

    def fail_probe():
        raise RuntimeError(f"connection failed for {leaked_url}\nprivate stack details")

    monkeypatch.setattr(main, "_probe_postgresql", fail_probe)
    monkeypatch.setattr(main, "_probe_shared_store", lambda: None)

    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {"postgresql": "unavailable", "shared_store": "ok"},
    }
    assert "do-not-leak" not in response.text
    assert "private-db.internal" not in response.text
    assert "private stack details" not in response.text


def test_readiness_returns_503_for_shared_store_failure_without_secrets(client, monkeypatch):
    leaked_url = "redis://:do-not-leak@private-redis.internal:6379/0"

    def fail_probe():
        raise RuntimeError(f"connection failed for {leaked_url}\nprivate stack details")

    monkeypatch.setattr(main, "_probe_postgresql", lambda: None)
    monkeypatch.setattr(main, "_probe_shared_store", fail_probe)

    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {"postgresql": "ok", "shared_store": "unavailable"},
    }
    assert "do-not-leak" not in response.text
    assert "private-redis.internal" not in response.text
    assert "private stack details" not in response.text


def test_readiness_dependency_timeout_is_one_shared_budget(client, monkeypatch):
    monkeypatch.setattr(main, "_READINESS_TIMEOUT_SECONDS", 0.02)
    monkeypatch.setattr(main, "_probe_postgresql", lambda: sleep(0.5))
    monkeypatch.setattr(main, "_probe_shared_store", lambda: sleep(0.5))

    started = monotonic()
    response = client.get("/ready")
    elapsed = monotonic() - started

    assert response.status_code == 503
    # Leave room for heavily loaded Windows test hosts while remaining well
    # below the 1s serial delay from two 0.5s probes.
    assert elapsed < 0.8
    assert response.json() == {
        "status": "not_ready",
        "checks": {"postgresql": "unavailable", "shared_store": "unavailable"},
    }


@pytest.mark.parametrize("blocked_dependency", ["postgresql", "shared_store"])
def test_readiness_does_not_spawn_duplicate_probe_after_timeout(client, monkeypatch, blocked_dependency):
    monkeypatch.setattr(main, "_READINESS_TIMEOUT_SECONDS", 0.02)
    probe_started = Event()
    release_probe = Event()
    probe_calls = 0

    def blocked_probe():
        nonlocal probe_calls
        probe_calls += 1
        probe_started.set()
        release_probe.wait(timeout=1)

    monkeypatch.setattr(main, "_probe_shared_store", lambda: None)
    monkeypatch.setattr(main, "_probe_postgresql", lambda: None)
    monkeypatch.setattr(main, f"_probe_{blocked_dependency}", blocked_probe)

    try:
        assert client.get("/ready").status_code == 503
        assert probe_started.is_set()
        response = client.get("/ready")
    finally:
        release_probe.set()

    assert response.status_code == 503
    expected_checks = {"postgresql": "ok", "shared_store": "ok"}
    expected_checks[blocked_dependency] = "unavailable"
    assert response.json()["checks"] == expected_checks
    assert probe_calls == 1


def test_health_remains_liveness_when_database_is_unavailable(client, monkeypatch):
    monkeypatch.setattr(main, "_probe_postgresql", lambda: (_ for _ in ()).throw(RuntimeError("database down")))
    monkeypatch.setattr(main, "_probe_shared_store", lambda: None)

    assert client.get("/ready").status_code == 503
    health = client.get("/health")

    assert health.status_code == 200
    assert health.json() == {"status": "ok", "app": main.settings.APP_NAME}
