from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Lock
from time import monotonic, sleep
from unittest.mock import Mock

import pytest

from app import main


@pytest.fixture(autouse=True)
def isolated_readiness_slot(monkeypatch):
    monkeypatch.setattr(main, "_READINESS_CHECK_SLOT", Lock())
    monkeypatch.setattr(main, "_READINESS_PROBE", None, raising=False)


@pytest.fixture
def store(monkeypatch):
    store = Mock()
    store.ttl.return_value = None
    monkeypatch.setattr(main, "get_shared_counter_store", lambda: store)
    return store


def test_readiness_reports_healthy_dependencies(client, monkeypatch, store):
    monkeypatch.setattr(main, "_probe_postgresql", lambda: None)

    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready", "checks": {"postgresql": "ok", "shared_store": "ok"},
    }
    store.ttl.assert_called_once_with("readiness")
    store.set.assert_not_called()
    store.increment.assert_not_called()


@pytest.mark.parametrize("failure", ["postgresql", "shared_store", "store_initialization"])
def test_readiness_dependency_failure_without_secrets(client, monkeypatch, store, failure):
    def fail_probe(*args):
        raise RuntimeError("connection failed: scheme://user:do-not-leak@private-host/internal")

    monkeypatch.setattr(main, "_probe_postgresql", fail_probe if failure == "postgresql" else lambda: None)
    if failure == "shared_store":
        store.ttl.side_effect = fail_probe
    elif failure == "store_initialization":
        monkeypatch.setattr(main, "get_shared_counter_store", fail_probe)

    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {
            "postgresql": "unavailable" if failure == "postgresql" else "ok",
            "shared_store": "ok" if failure == "postgresql" else "unavailable",
        },
    }
    assert "do-not-leak" not in response.text
    assert "private-host" not in response.text


@pytest.mark.parametrize("blocked", ["postgresql", "shared_store"])
def test_readiness_deadline_is_bounded_and_stuck_probe_is_reused(client, monkeypatch, store, blocked):
    entered, release, finished = Event(), Event(), Event()
    calls = []

    def hang(*args):
        calls.append(1)
        entered.set()
        try:
            release.wait(2)
        finally:
            finished.set()

    monkeypatch.setattr(main, "_READINESS_TIMEOUT_SECONDS", 0.04)
    monkeypatch.setattr(main, "_probe_postgresql", hang if blocked == "postgresql" else lambda: None)
    if blocked == "shared_store":
        store.ttl.side_effect = hang

    try:
        started = monotonic()
        response = client.get("/ready")
        elapsed = monotonic() - started
        assert entered.is_set()
        assert response.status_code == 503
        assert response.json()["checks"][blocked] == "unavailable"
        assert elapsed < 0.3
        assert client.get("/ready").status_code == 503
        assert calls == [1]
    finally:
        release.set()
        assert finished.wait(1)


def test_readiness_dependencies_share_one_deadline(client, monkeypatch, store):
    monkeypatch.setattr(main, "_READINESS_TIMEOUT_SECONDS", 0.15)
    monkeypatch.setattr(main, "_probe_postgresql", lambda: sleep(0.10))
    store.ttl.side_effect = lambda key: sleep(0.10)

    started = monotonic()
    response = client.get("/ready")
    elapsed = monotonic() - started

    assert response.status_code == 503
    assert response.json()["checks"] == {"postgresql": "ok", "shared_store": "unavailable"}
    assert elapsed < 0.24


@pytest.mark.parametrize("fails", [False, True])
def test_concurrent_callers_share_inflight_result_and_next_probe_recovers(monkeypatch, store, fails):
    entered, release = Event(), Event()
    callers = Barrier(5)
    probe = Mock()

    def check_database():
        probe()
        entered.set()
        assert release.wait(2)
        if fails:
            raise RuntimeError("database unavailable")

    monkeypatch.setattr(main, "_READINESS_TIMEOUT_SECONDS", 1.0)
    monkeypatch.setattr(main, "_probe_postgresql", check_database)

    def request_ready():
        callers.wait(timeout=2)
        return main.readiness()

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = [pool.submit(request_ready) for _ in range(4)]
        callers.wait(timeout=2)
        try:
            assert entered.wait(1)
            # Give joined callers time to expose the old busy-lock refusal.
            sleep(0.05)
            assert all(not result.done() for result in results)
        finally:
            release.set()
        responses = [result.result(timeout=1) for result in results]

    probe.assert_called_once()
    store.ttl.assert_called_once()
    if fails:
        assert all(response.status_code == 503 for response in responses)
    else:
        assert responses == [{"status": "ready", "checks": {"postgresql": "ok", "shared_store": "ok"}}] * 4

    monkeypatch.setattr(main, "_probe_postgresql", lambda: None)
    assert main.readiness() == {"status": "ready", "checks": {"postgresql": "ok", "shared_store": "ok"}}
    assert store.ttl.call_count == 2


def test_health_remains_dependency_free(client, monkeypatch):
    def forbidden():
        pytest.fail("liveness must not probe dependencies")

    monkeypatch.setattr(main, "_probe_postgresql", forbidden)
    monkeypatch.setattr(main, "get_shared_counter_store", forbidden)

    health = client.get("/health")

    assert health.status_code == 200
    assert health.json() == {"status": "ok", "app": main.settings.APP_NAME}
