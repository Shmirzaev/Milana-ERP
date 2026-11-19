import gc
import json
import os
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Thread

import pytest

from app.core.shared_store import SQLiteSharedCounterStore


def test_sqlite_shared_counter_store(tmp_path):
    store = SQLiteSharedCounterStore(f"sqlite:///{tmp_path / 'shared-store.db'}", prefix="test")

    assert store.increment("auth:login:alice", 30) == 1
    assert store.increment("auth:login:alice", 30) == 2
    assert store.ttl("auth:login:alice") is not None

    store.set("auth:login-lock:alice", "locked", 30)
    assert store.ttl("auth:login-lock:alice") is not None

    store.delete("auth:login:alice")
    assert store.ttl("auth:login:alice") is None

    store.clear_namespace("auth")
    assert store.ttl("auth:login-lock:alice") is None


def test_sqlite_shared_counter_store_expires(tmp_path):
    store = SQLiteSharedCounterStore(f"sqlite:///{tmp_path / 'shared-store.db'}", prefix="test")

    store.increment("short", 1)
    time.sleep(1.1)

    assert store.ttl("short") is None
    assert store.increment("short", 30) == 1


@pytest.mark.skipif(not os.path.isdir("/proc/self/fd"), reason="Linux descriptor accounting")
def test_sqlite_requests_do_not_accumulate_connections_until_gc(tmp_path):
    store = SQLiteSharedCounterStore(f"sqlite:///{tmp_path / 'bounded.db'}", prefix="test")
    gc.collect()
    enabled = gc.isenabled()
    gc.disable()
    try:
        before = len(os.listdir("/proc/self/fd"))
        for count in range(1, 301):
            assert store.increment("global-rate:actor", 60) == count
            assert store.ttl("global-rate:actor") is not None
        assert len(os.listdir("/proc/self/fd")) <= before + 3
    finally:
        store.close()
        if enabled:
            gc.enable()
        gc.collect()


def test_sqlite_ttl_remains_readable_during_another_writer(tmp_path):
    path = tmp_path / "wal.db"
    store = SQLiteSharedCounterStore(f"sqlite:///{path}", prefix="test")
    store.set("auth:locked", "locked", 60)
    writer = sqlite3.connect(path, isolation_level=None)
    writer.execute("BEGIN IMMEDIATE")
    results = []
    errors = []

    def read():
        try:
            results.append(store.ttl("auth:locked"))
        except Exception as error:
            errors.append(type(error).__name__)

    thread = Thread(target=read)
    try:
        thread.start()
        thread.join(timeout=1)
        blocked = thread.is_alive()
    finally:
        writer.rollback()
        writer.close()
        thread.join(timeout=6)
        store.close()
    assert not blocked, "A WAL reader waited for the unrelated writer"
    assert not errors
    assert len(results) == 1 and 1 <= results[0] <= 60


def test_sqlite_multiple_stores_threads_and_reopen_preserve_exact_counts(tmp_path):
    url = f"sqlite:///{tmp_path / 'shared.db'}"
    stores = [SQLiteSharedCounterStore(url, prefix="test") for _ in range(2)]

    def increment(index):
        return stores[index % 2].increment("global-rate:shared", 60)

    try:
        with ThreadPoolExecutor(max_workers=12) as pool:
            values = list(pool.map(increment, range(600)))
        assert sorted(values) == list(range(1, 601))
    finally:
        for store in stores:
            store.close()
    reopened = SQLiteSharedCounterStore(url, prefix="test")
    try:
        assert reopened.increment("global-rate:shared", 60) == 601
        with sqlite3.connect(tmp_path / "shared.db") as conn:
            assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
            assert conn.execute("PRAGMA synchronous").fetchone()[0] == 2
    finally:
        reopened.close()


def test_sqlite_independent_processes_and_replacement_share_counts(tmp_path):
    url = f"sqlite:///{tmp_path / 'processes.db'}"
    store = SQLiteSharedCounterStore(url, prefix="test")
    code = """
import json, sys
from app.core.shared_store import SQLiteSharedCounterStore
store = SQLiteSharedCounterStore(sys.argv[1], prefix='test')
try:
    print(json.dumps([store.increment('global-rate:shared', 60) for _ in range(int(sys.argv[2]))]))
finally:
    store.close()
"""
    processes = [subprocess.Popen(
        [sys.executable, "-c", code, url, "150"], stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True,
    ) for _ in range(2)]
    try:
        values = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=30)
            assert process.returncode == 0, stderr
            values.extend(json.loads(stdout))
        assert sorted(values) == list(range(1, 301))
        replacement = subprocess.run(
            [sys.executable, "-c", code, url, "1"], capture_output=True,
            text=True, timeout=30, check=True,
        )
        assert json.loads(replacement.stdout) == [301]
        assert store.increment("global-rate:shared", 60) == 302
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
        store.close()


def test_sqlite_failed_increment_rolls_back_and_releases_writer(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'failure.db'}"
    store = SQLiteSharedCounterStore(url, prefix="test")
    other = SQLiteSharedCounterStore(url, prefix="test")
    store.set("sentinel", "locked", 60)
    assert store.increment("counter", 60) == 1

    def fail_after_begin(conn):
        conn.execute("DELETE FROM shared_counters WHERE key = 'test:sentinel'")
        raise RuntimeError("injected transaction failure")

    try:
        with monkeypatch.context() as patch:
            patch.setattr(store, "_purge_expired", fail_after_begin)
            with pytest.raises(RuntimeError, match="injected transaction failure"):
                store.increment("counter", 60)
        assert other.ttl("sentinel") is not None
        assert other.increment("counter", 60) == 2
        assert store.increment("counter", 60) == 3
    finally:
        other.close()
        store.close()


def test_sqlite_expiry_boundary_preserves_fixed_window(tmp_path, monkeypatch):
    from app.core import shared_store

    clock = [1000.0]
    monkeypatch.setattr(shared_store.time, "time", lambda: clock[0])
    store = SQLiteSharedCounterStore(f"sqlite:///{tmp_path / 'expiry.db'}", prefix="test")
    try:
        assert store.increment("counter", 30) == 1
        clock[0] = 1029.99
        assert store.ttl("counter") == 1
        assert store.increment("counter", 30) == 2
        clock[0] = 1030.0
        assert store.ttl("counter") is None
        assert store.increment("counter", 30) == 1
        assert store.ttl("counter") == 30
        clock[0] = 1060.01
        assert store.ttl("counter") is None
    finally:
        store.close()
