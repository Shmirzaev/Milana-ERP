"""PERF37: a contended real counter store must not stall unrelated HTTP traffic."""

from concurrent.futures import ThreadPoolExecutor
import json
from math import ceil
import socket
import sqlite3
from threading import Event, Thread
from time import monotonic, sleep

import httpx
import uvicorn

from app import main
from app.core.shared_store import SQLiteSharedCounterStore


# Isolated regression bounds; Mirshoir reviews these, not a factory capacity claim.
LOCK_SECONDS = 2.0
LIMITED_REQUESTS = 8
PROBES_PER_PATH = 10
MAX_BYPASS_SECONDS = 1.0
MAX_P95_INCREASE_SECONDS = 0.250
STOP_SECONDS = 10.0


def _measure(client):
    timings = {"health": [], "options": []}
    for _ in range(PROBES_PER_PATH):
        for kind, method, path, status in (
            ("health", "GET", "/health", 200),
            ("options", "OPTIONS", "/api/auth/me", 405),
        ):
            started = monotonic()
            response = client.request(method, path)
            timings[kind].append(monotonic() - started)
            assert response.status_code == status
            if kind == "health":
                assert response.json()["status"] == "ok"
    return {kind: {"p95": sorted(values)[ceil(.95 * len(values)) - 1], "max": max(values)}
            for kind, values in timings.items()}


def test_perf37_locked_sqlite_store_keeps_health_and_options_responsive(tmp_path, monkeypatch):
    """Real TCP, one event loop, real SQLite contention, recovery and exact budgets."""
    store_path = tmp_path / "rate-limits.db"
    store = SQLiteSharedCounterStore(f"sqlite:///{store_path}", prefix="perf37")
    monkeypatch.setattr(main, "get_shared_counter_store", lambda: store)
    monkeypatch.setattr(main.settings, "GLOBAL_RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(main.settings, "GLOBAL_RATE_LIMIT_PER_MINUTE", 3)
    monkeypatch.setattr(main.settings, "GLOBAL_RATE_LIMIT_WINDOW_SECONDS", 60)
    entered = Event()
    real_increment = store.increment

    def observed_increment(*args):
        entered.set()
        return real_increment(*args)

    monkeypatch.setattr(store, "increment", observed_increment)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(
        main.app, host="127.0.0.1", port=port, loop="asyncio", http="h11",
        lifespan="off", proxy_headers=False, access_log=False, log_level="error",
    ))
    serving = Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    held, release, unlocked = Event(), Event(), Event()
    lock_errors = []

    def hold_store_write_lock():
        try:
            with sqlite3.connect(store_path, isolation_level=None) as connection:
                connection.execute("BEGIN IMMEDIATE")
                held.set()
                release.wait(LOCK_SECONDS)
                connection.rollback()
        except BaseException as error:
            lock_errors.append(error)
        finally:
            unlocked.set()

    holder = Thread(target=hold_store_write_lock, daemon=True)
    serving.start()
    try:
        deadline = monotonic() + STOP_SECONDS
        while not server.started and serving.is_alive() and monotonic() < deadline:
            sleep(.01)
        assert server.started, "Isolated Uvicorn did not start within the stop bound"
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False,
                          timeout=STOP_SECONDS, limits=httpx.Limits(max_connections=16)) as client:
            baseline = _measure(client)
            with sqlite3.connect(store_path) as connection:
                assert connection.execute("SELECT key, value FROM shared_counters").fetchall() == []
            holder.start()
            assert held.wait(1), "Could not establish isolated SQLite write contention"
            with ThreadPoolExecutor(max_workers=LIMITED_REQUESTS) as workers:
                queued = [workers.submit(client.get, "/api/auth/me") for _ in range(LIMITED_REQUESTS)]
                assert entered.wait(1), "Limited HTTP requests did not reach the store"
                assert not any(future.done() for future in queued), "Write lock did not hold limited requests"
                blocked = _measure(client)
                # All observations must actually precede the bounded release.
                observed_while_locked = not unlocked.is_set()
                holder.join(timeout=STOP_SECONDS)
                responses = [future.result(timeout=STOP_SECONDS) for future in queued]
            assert not holder.is_alive() and not lock_errors, lock_errors
            assert [response.status_code for response in responses].count(401) == 3
            rejected = [response for response in responses if response.status_code == 429]
            assert len(rejected) == 5
            assert all(1 <= int(response.headers["retry-after"]) <= 60 for response in rejected)
            with sqlite3.connect(store_path) as connection:
                assert connection.execute("SELECT key, value FROM shared_counters").fetchall() == [
                    ("perf37:global-rate:ip:127.0.0.1", str(LIMITED_REQUESTS))]
            assert client.get("/api/auth/me").status_code == 429
            with sqlite3.connect(store_path) as connection:
                assert connection.execute("SELECT value FROM shared_counters").fetchall() == [
                    (str(LIMITED_REQUESTS + 1),)]
            print(json.dumps({"PERF37": {"baseline_seconds": baseline, "blocked_seconds": blocked,
                  "store_lock_seconds": LOCK_SECONDS, "limited_requests": LIMITED_REQUESTS,
                  "probe_count_per_path": PROBES_PER_PATH, "responses_after_release": {"401": 3, "429": 5}}}))
            for kind in baseline:
                assert blocked[kind]["max"] <= MAX_BYPASS_SECONDS, f"{kind} stalled behind the counter store: {blocked}"
                assert blocked[kind]["p95"] <= baseline[kind]["p95"] + MAX_P95_INCREASE_SECONDS, (
                    f"{kind} p95 regressed under store contention: {baseline} -> {blocked}")
            assert observed_while_locked, "Bypass observations outlived the declared store lock"
    finally:
        release.set()
        if holder.ident is not None:
            holder.join(timeout=STOP_SECONDS)
        server.should_exit = True
        serving.join(timeout=STOP_SECONDS)
        listener.close()
        assert not serving.is_alive(), "Isolated Uvicorn exceeded cleanup stop bound"
